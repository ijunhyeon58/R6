# R6 Esports 매시간 경기 결과 알림 (GitHub Actions)

PandaScore에 등록된 레식 프로 경기 중 새로 종료된 경기를 승패·최종 스코어와 함께 Discord Webhook으로 보냅니다.
매시간 **10분(한국시간)** 예약 실행. GitHub 서버에서 실행하므로 집 PC가 꺼져 있어도 작동합니다.

## 준비

- GitHub 계정
- 이미 동작을 확인한 PandaScore API 토큰
- 이미 만들어둔 Discord 웹후크 URL

**주의:** 예전에 채팅/스크린샷에 노출된 토큰이라면 반드시 폐기하고 새로 발급해 사용하세요.

## 설정

1. GitHub에서 **Private** 저장소를 하나 새로 만드세요. (예: `r6-results`)
2. 이 ZIP의 파일/폴더를 **구조 그대로** 저장소에 업로드하세요.
   - `r6_hourly_github.py`
   - `r6_results_bot.py`
   - `.github/workflows/r6-hourly.yml` (**`.github`부터 정확한 경로 유지**)
   - `README_KO.md`
3. 저장소의 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`에서 다음 2개를 만드세요.
   - 이름: `PANDASCORE_API_TOKEN` / 값: PandaScore에서 발급받은 **새 토큰**
   - 이름: `DISCORD_WEBHOOK_URL` / 값: Discord 웹후크 전체 주소
   토큰과 웹후크 주소를 **코드 파일, README, GitHub 커밋에 절대 직접 쓰지 마세요.**
4. 저장소 `Actions` 탭 → `R6 Esports - Hourly Results` → `Run workflow` 실행.
   - 처음 실행은 최근 종료된 경기들을 기록만 합니다. 과거 경기 알림은 보내지 않습니다.
   - 로그에 `첫 실행: 완료 경기 ...`가 나오면 성공입니다.
5. 이제 GitHub가 자동으로 매시간 10분에 실행합니다. 경기 종료 시각에 따라 다음 실행에서 알림이 옵니다.
6. **PC에서 실행하던 `start_windows.bat`은 종료**하세요. 함께 돌리면 중복 전송될 수 있습니다.

## 중요

- GitHub 예약 실행은 정시에 보장되지 않습니다. 가끔 실행이 지연되거나 건너뛸 수 있습니다.
- 각 실행 시 최근 완료 경기 최대 300개를 다시 조회하며, 기존에 보낸 경기 ID는 `state/seen.json`에 기록합니다.
- 전송 기록은 GitHub Actions가 자동으로 저장소에 커밋합니다. 저장소에 `state/seen.json` 파일이 생성되면 정상입니다.
- 저장소가 보호된 브랜치라서 Actions가 커밋할 수 없거나 `GITHUB_TOKEN`에 쓰기 권한이 없는 경우 기록 저장에 실패합니다.
- 과거 오사카 메이저 경기 일괄 전송은 **기존 Windows 파일(`send_osaka_major_history.bat`)**을 계속 이용하세요. GitHub 첫 실행에서 과거 경기들을 자동 재전송하지는 않습니다.
- 데이터 원본 PandaScore에 없는 경기까지 전송하지는 않습니다.

## 변경하기

- `10 * * * *` = 매시간 **10분**에 실행
- `30 * * * *` = 매시간 **30분**에 실행
- 1시간 간격으로 맞추고 싶다면 분 숫자만 바꾸세요.

## 보안

API 토큰과 Discord Webhook은 GitHub `Secrets`에만 저장합니다. 저장소가 공개되어 있더라도 코드에 토큰을 직접 적으면 안 됩니다. **Private** 권장.
