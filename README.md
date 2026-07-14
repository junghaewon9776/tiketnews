# tiketnews

티켓링크에서 지정한 공연장/키워드의 신규 공연을 매일 확인해 텔레그램으로 알림을 보냅니다.

## 감시 항목 추가하기

`venues.json`에 문자열을 추가하면 됩니다.

```json
[
  "영광문화예술의전당",
  "다른 공연장 이름"
]
```

커밋 후 push하면 다음 실행부터 자동으로 반영됩니다.

## 필요한 GitHub Secrets

저장소 Settings → Secrets and variables → Actions 에서 등록:

- `TELEGRAM_BOT_TOKEN`: @BotFather에서 발급받은 봇 토큰
- `TELEGRAM_CHAT_ID`: 알림을 받을 텔레그램 채팅 ID

## 수동 실행

Actions 탭 → "Ticketlink watch" → "Run workflow" 로 즉시 테스트 가능합니다.

## 동작 방식

- 매일 09:00 KST에 GitHub Actions가 실행됩니다 (PC/앱이 꺼져 있어도 동작).
- 각 키워드로 티켓링크를 검색해, 이전에 못 본 공연(product id 기준)이 있으면 텔레그램으로 전송합니다.
- 확인한 목록은 `state/` 폴더에 저장되어 다음 실행 때 비교 기준으로 사용됩니다.
- 예매/결제는 자동화하지 않으며, 사용자가 알림의 링크를 눌러 직접 진행해야 합니다.
