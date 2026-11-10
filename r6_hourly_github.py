#!/usr/bin/env python3
"""Run one R6 esports match-results poll (designed for hourly GitHub Actions).

Set PANDASCORE_API_TOKEN and DISCORD_WEBHOOK_URL as environment variables.
Persists already-delivered PandaScore match IDs in state/seen.json.
No third-party Python packages required.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from r6_results_bot import extract_result, fetch_recent_matches, post_result, valid_webhook

STATE_FILE = Path(__file__).resolve().parent / "state" / "seen.json"
SEND_DELAY_SECONDS = 2.1


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state(path=STATE_FILE):
    if not path.is_file():
        return {"initialized": False, "seen": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise RuntimeError("상태 파일 읽기 실패: state/seen.json 확인 필요") from None
    if not isinstance(state, dict) or not isinstance(state.get("seen"), dict):
        raise RuntimeError("상태 파일 형식이 올바르지 않습니다: state/seen.json")
    return {"initialized": bool(state.get("initialized", False)), "seen": state["seen"]}


def save_state(state, path=STATE_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def chronological(pairs):
    return sorted(pairs, key=lambda item: ((item[0].get("end_at") or ""), str(item[1]["id"])))


def poll(fetch, send, path=STATE_FILE, delay=SEND_DELAY_SECONDS):
    """First execution seeds existing results; subsequent executions send newly finished results.

    State is saved after each successful Discord delivery to reduce duplicate risks
    if a run fails partway through. A failed GitHub git-push can still cause repeats.
    """
    state = load_state(path)
    matches = fetch()
    if not isinstance(matches, list):
        raise RuntimeError("경기 목록 응답 형식이 올바르지 않습니다.")

    results = []
    for match in matches:
        result = extract_result(match)
        if result is not None:
            results.append((match, result))

    if not state["initialized"]:
        for _, result in results:
            state["seen"][result["id"]] = utc_now()
        state["initialized"] = True
        save_state(state, path)
        print(f"첫 실행: 완료 경기 {len(results)}건을 기준 데이터로 저장했어요. 과거 경기는 전송하지 않습니다.")
        return 0

    sent = 0
    skipped = 0
    for match, result in chronological(results):
        mid = result["id"]
        if mid in state["seen"]:
            skipped += 1
            continue
        send(result)
        state["seen"][mid] = utc_now()
        save_state(state, path)
        sent += 1
        a, b = result["teams"]
        print(f"전송 {sent}건: {a['name']} {a['score']}:{b['score']} {b['name']} / #{mid}")
        if delay:
            time.sleep(delay)
    print(f"이번 실행 완료: 새 경기 {sent}건 전송, 기존 {skipped}건 건너뜀")
    return sent


def main():
    token = os.environ.get("PANDASCORE_API_TOKEN", "").strip()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not token or not valid_webhook(webhook):
        raise RuntimeError("GitHub Secrets에 PANDASCORE_API_TOKEN과 DISCORD_WEBHOOK_URL을 설정하세요.")
    poll(lambda: fetch_recent_matches(token), lambda result: post_result(webhook, result))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as exc:
        # Never print API token or Discord webhook URL.
        print("실행 실패:", str(exc), file=sys.stderr)
        sys.exit(1)
