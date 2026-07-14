"""Poll Telegram for a message from the user; if one arrives, reply with
the current list of open (reservable) shows for every watched venue right away,
instead of waiting for the daily schedule."""

import re

import requests

from ticketlink import (
    ROOT,
    STATE_DIR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    load_seen,
    load_venues,
    save_seen,
    search_ticketlink,
    send_telegram,
)

OFFSET_FILE = STATE_DIR / "tg_offset.txt"
DAILY_WORKFLOW_FILE = ROOT / ".github" / "workflows" / "daily.yml"


def load_offset() -> int:
    if not OFFSET_FILE.exists():
        return 0
    return int(OFFSET_FILE.read_text(encoding="utf-8").strip() or 0)


def save_offset(offset: int):
    STATE_DIR.mkdir(exist_ok=True)
    OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def fetch_updates(offset: int):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=20)
    resp.raise_for_status()
    return resp.json().get("result", [])


SNAPSHOT_WORDS = {"현황", "최신", "확인", "status"}
SEARCH_COMMANDS = {"지역", "검색", "search", "region"}
TIME_COMMANDS = {"알림시간", "시간변경", "time", "schedule"}

BOT_COMMANDS = [
    {"command": "search", "description": "이름으로 티켓링크 검색 (예: /search 영광)"},
    {"command": "status", "description": "감시 중인 공연장 전체 현황 보기"},
    {"command": "schedule", "description": "알림 시간 변경 (예: /schedule 9, 21)"},
    {"command": "help", "description": "사용 가능한 명령어 안내"},
]

HELP_WORDS = {"help", "도움말", "명령어"}

HELP_TEXT = """[사용 가능한 명령어]

/search <이름> — 티켓링크에서 이름으로 검색 (예: /search 영광문화예술의전당)
그냥 이름만 보내도 동일하게 검색됩니다.

/status — 감시 중인 공연장 전체 현황 보기

/schedule <시간, 시간...> — 매일 알림 시간 변경 (예: /schedule 9, 21)

/help — 이 안내 메시지 보기"""


def register_commands():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    try:
        requests.post(url, json={"commands": BOT_COMMANDS}, timeout=10)
    except requests.RequestException as exc:
        print("setMyCommands failed:", exc)


def is_snapshot_request(text: str) -> bool:
    if text in ("", "/start"):
        return True
    return text.lstrip("/").strip() in SNAPSHOT_WORDS


def parse_keyword(text: str) -> str:
    """'/지역 영광', '/search 영광', '영광' -> '영광'."""
    if text.startswith("/"):
        parts = text[1:].split(maxsplit=1)
        if not parts:
            return ""
        if parts[0] in SEARCH_COMMANDS:
            return parts[1].strip() if len(parts) > 1 else ""
        # unknown slash command with no recognized verb — treat the rest as the keyword
        return " ".join(parts).strip()
    return text.strip()

DAILY_WORKFLOW_TEMPLATE = """name: Ticketlink daily check

on:
  schedule:
{cron_lines}
  workflow_dispatch: {{}}

permissions:
  contents: write

concurrency:
  group: tiketnews-state
  cancel-in-progress: false

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run daily check
        env:
          TELEGRAM_BOT_TOKEN: ${{{{ secrets.TELEGRAM_BOT_TOKEN }}}}
          TELEGRAM_CHAT_ID: ${{{{ secrets.TELEGRAM_CHAT_ID }}}}
        run: python daily_check.py

      - name: Commit updated state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add state/
          git diff --cached --quiet || (git commit -m "Update seen state (daily)" && git pull --rebase && git push)
"""


def parse_time_command(text: str):
    """'/알림시간 9시, 21시' -> [9, 21] (KST hours), or None if not a time command."""
    body = text.lstrip("/").strip()
    parts = body.split(maxsplit=1)
    if not parts or parts[0] not in TIME_COMMANDS:
        return None
    rest = parts[1] if len(parts) > 1 else ""
    hours = sorted({int(n) % 24 for n in re.findall(r"\d{1,2}", rest)})
    return hours


def update_daily_schedule(hours_kst):
    cron_lines = "\n".join(
        f'    - cron: "0 {(h - 9) % 24} * * *"  # {h:02d}:00 KST' for h in hours_kst
    )
    content = DAILY_WORKFLOW_TEMPLATE.format(cron_lines=cron_lines)
    DAILY_WORKFLOW_FILE.write_text(content, encoding="utf-8")


def build_snapshot() -> str:
    keywords = load_venues()
    lines = ["[티켓링크 현황]"]
    for keyword in keywords:
        current = search_ticketlink(keyword)
        lines.append(f"\n{keyword} — 예매 가능 {len(current)}건")
        for r in current:
            lines.append(f"- {r['title']}\n  {r['url']}")
        # mark these as seen so the daily check doesn't re-alert on them
        save_seen(keyword, {r["id"] for r in current} | load_seen(keyword))
    if len(lines) == 1:
        lines.append("\n감시 중인 항목이 없습니다.")
    return "\n".join(lines)


def build_search_reply(keyword: str) -> str:
    current = search_ticketlink(keyword)
    lines = [f"[티켓링크 검색] {keyword} — 예매 가능 {len(current)}건"]
    for r in current:
        lines.append(f"- {r['title']}\n  {r['venue']}\n  {r['url']}")
    if not current:
        lines.append("현재 예매 가능한 공연이 없습니다.")
    return "\n".join(lines)


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing; nothing to do.")
        return

    register_commands()

    offset = load_offset()
    updates = fetch_updates(offset)

    if not updates:
        print("새 메시지 없음")
        return

    texts = []
    max_update_id = offset - 1
    for update in updates:
        max_update_id = max(max_update_id, update["update_id"])
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if str(chat.get("id")) == str(TELEGRAM_CHAT_ID) and "text" in message:
            texts.append(message["text"].strip())

    save_offset(max_update_id + 1)

    if not texts:
        print("해당 채팅의 메시지 없음")
        return

    for text in texts:
        if text.lstrip("/").strip() in HELP_WORDS:
            send_telegram(HELP_TEXT)
            print("도움말 요청 감지, 안내 전송함")
            continue

        hours = parse_time_command(text)
        if hours is not None:
            if hours:
                update_daily_schedule(hours)
                times_str = ", ".join(f"{h:02d}:00" for h in hours)
                send_telegram(f"알림 시간을 매일 {times_str} (KST)로 변경했습니다.")
                print(f"알림 시간 변경: {hours}")
            else:
                send_telegram("시간을 인식하지 못했어요. 예: '알림시간 9시, 21시'")
            continue

        if is_snapshot_request(text):
            send_telegram(build_snapshot())
            print("현황 요청 감지, 감시 목록 전체 현황 전송함")
        else:
            keyword = parse_keyword(text)
            if not keyword:
                continue
            send_telegram(build_search_reply(keyword))
            print(f"'{keyword}' 검색 요청 감지, 결과 전송함")


if __name__ == "__main__":
    main()
