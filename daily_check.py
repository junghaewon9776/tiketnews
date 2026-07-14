from ticketlink import load_seen, save_seen, load_venues, search_ticketlink, send_telegram


def main():
    keywords = load_venues()
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
