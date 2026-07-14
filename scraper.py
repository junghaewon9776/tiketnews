import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
STATE_DIR = ROOT / "state"
VENUES_FILE = ROOT / "venues.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


def slugify(keyword: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "_", keyword).strip("_")


def state_path(keyword: str) -> Path:
    return STATE_DIR / f"{slugify(keyword)}.json"


def load_seen(keyword: str) -> set:
    path = state_path(keyword)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def save_seen(keyword: str, ids: set):
    STATE_DIR.mkdir(exist_ok=True)
    path = state_path(keyword)
    path.write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def search_ticketlink(keyword: str):
    url = "https://www.ticketlink.co.kr/search?query=" + urllib.parse.quote(keyword)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for a in soup.select('a.result_info[href^="/product/"]'):
        href = a.get("href", "")
        m = re.search(r"/product/(\d+)", href)
        if not m:
            continue
        product_id = m.group(1)

        title_el = a.select_one("strong.tit")
        title = title_el.get_text(strip=True) if title_el else "(제목 없음)"

        venue_el = a.select_one("dd")
        venue = venue_el.get_text(strip=True) if venue_el else ""

        if keyword not in venue and keyword not in title:
            continue

        results.append(
            {
                "id": product_id,
                "title": title,
                "venue": venue,
                "url": "https://www.ticketlink.co.kr/product/" + product_id,
            }
        )

    # de-dup by id, keep first occurrence
    dedup = {}
    for r in results:
        dedup.setdefault(r["id"], r)
    return list(dedup.values())


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing; skipping send. Message was:\n" + text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if not resp.ok:
        print("Telegram send failed:", resp.status_code, resp.text, file=sys.stderr)


def main():
    keywords = json.loads(VENUES_FILE.read_text(encoding="utf-8"))
    any_new = False

    for keyword in keywords:
        seen = load_seen(keyword)
        current = search_ticketlink(keyword)
        current_ids = {r["id"] for r in current}

        new_items = [r for r in current if r["id"] not in seen]

        if new_items:
            any_new = True
            lines = [f"[티켓링크 신규 알림] {keyword}", ""]
            for r in new_items:
                lines.append(f"- {r['title']}\n  {r['venue']}\n  {r['url']}")
            send_telegram("\n\n".join(lines))
            print(f"{keyword}: {len(new_items)}건 신규 발견, 알림 전송")
        else:
            print(f"{keyword}: 신규 없음 ({len(current_ids)}건 확인)")

        save_seen(keyword, current_ids | seen)

    if not any_new:
        print("모든 감시 항목에서 신규 항목 없음")


if __name__ == "__main__":
    main()
