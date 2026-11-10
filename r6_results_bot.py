#!/usr/bin/env python3
"""PandaScore R6 finished-match results -> Discord webhook.

Requires Python 3.9+; no third-party dependencies.

Run:
    python r6_results_bot.py --test   # Send a sample from the latest completed match
    python r6_results_bot.py          # Monitor completed matches every five minutes

On the first launch, API token and webhook URL are requested locally, then stored
in config.json next to this script. Never share this file.
"""

import argparse
import getpass
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "r6_seen.sqlite3"
API_URL = "https://api.pandascore.co/r6siege/matches/past"
POLL_SECONDS = 300  # 5 minutes
PAGE_SIZE = 100
MAX_PAGES = 3  # Check up to 300 most recently completed matches
USER_AGENT = "PersonalR6MatchResultsWebhook/1.0"


def clean_text(value, default="Unknown"):
    if value is None or str(value).strip() == "":
        return default
    return str(value).replace("@", "@\u200b").replace("`", "ˋ")[:180]


def request_json(url, data=None, headers=None, timeout=25):
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        merged.update(headers)
    method = "POST" if data is not None else "GET"
    if data is not None:
        merged["Content-Type"] = "application/json"
        data = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=merged, method=method)
    try:
        with urlopen(req, timeout=timeout) as res:
            body = res.read()
            if not body:
                return None
            return json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        # Intentionally never include URLs in error messages: API URLs contain a token.
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After", "unknown")
            raise RuntimeError("요청 제한(429). 잠시 후 다시 시도하세요. Retry-After: " + str(retry_after)) from None
        raise RuntimeError("HTTP 오류: " + str(exc.code) + " (인증·권한·URL을 확인하세요)") from None
    except URLError:
        raise RuntimeError("네트워크에 연결할 수 없습니다.") from None


def valid_webhook(url):
    p = urlsplit(url)
    parts = p.path.strip("/").split("/")
    return (p.scheme == "https"
            and p.hostname in {"discord.com", "discordapp.com"}
            and len(parts) == 4
            and parts[0] == "api" and parts[1] == "webhooks"
            and parts[2].isdigit() and bool(parts[3]))


def load_config():
    if CONFIG_PATH.exists():
        try:
            conf = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("config.json 파일이 손상됐습니다. 수정하거나 삭제하세요.")
        token = str(conf.get("pandascore_token", "")).strip()
        webhook = str(conf.get("discord_webhook_url", "")).strip()
        if not token or not valid_webhook(webhook):
            raise RuntimeError("config.json의 토큰 또는 Discord 웹후크 주소가 올바르지 않습니다.")
        return token, webhook

    print("처음 실행하는군요! 두 가지 비밀키를 이 PC에서만 입력해 주세요.")
    print("입력 중에는 화면에 글자가 보이지 않습니다. 정상입니다.")
    token = getpass.getpass("PandaScore API Token: ").strip()
    webhook = getpass.getpass("Discord Webhook URL: ").strip()
    if not token or not valid_webhook(webhook):
        raise RuntimeError("API 토큰 또는 디스코드 웹후크 URL이 유효하지 않습니다.")
    with CONFIG_PATH.open("x", encoding="utf-8") as stream:
        json.dump({"pandascore_token": token, "discord_webhook_url": webhook}, stream, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    print("설정 저장 완료! config.json은 다른 사람에게 보내거나 업로드하지 마세요.")
    return token, webhook


def fetch_recent_matches(token):
    matches = []
    for page in range(1, MAX_PAGES + 1):
        params = urlencode({
            "token": token, "sort": "-end_at", "per_page": PAGE_SIZE, "page": page
        })
        data = request_json(API_URL + "?" + params)
        if not isinstance(data, list):
            raise RuntimeError("PandaScore에서 경기 목록 대신 다른 형식의 응답을 받았습니다.")
        matches.extend(data)
        if len(data) < PAGE_SIZE:
            break
    return matches


def extract_result(match):
    """Return a cleaned result dict, or None if final score not available."""
    if not isinstance(match, dict) or match.get("status") != "finished":
        return None
    mid = match.get("id")
    opponents = match.get("opponents") or []
    results = match.get("results") or []
    if mid is None or len(opponents) != 2:
        return None
    scores = {}
    for item in results:
        if isinstance(item, dict) and item.get("team_id") is not None and item.get("score") is not None:
            try:
                scores[str(item["team_id"])] = int(item["score"])
            except (ValueError, TypeError):
                continue
    teams = []
    for item in opponents:
        team = (item or {}).get("opponent") or {}
        tid = team.get("id")
        if tid is None or str(tid) not in scores:
            return None
        teams.append({"id": str(tid), "name": clean_text(team.get("name")), "score": scores[str(tid)]})
    if teams[0]["id"] == teams[1]["id"]:
        return None
    win_id = str(match.get("winner_id")) if match.get("winner_id") is not None else None
    winner = next((team["name"] for team in teams if team["id"] == win_id), None)
    if not winner and teams[0]["score"] != teams[1]["score"]:
        winner = (teams[0] if teams[0]["score"] > teams[1]["score"] else teams[1])["name"]
    if not winner and teams[0]["score"] == teams[1]["score"]:
        winner = "무승부"
    if not winner:
        return None
    league = (match.get("league") or {}).get("name") or "R6 Esports"
    serie = (match.get("serie") or {}).get("full_name") or (match.get("serie") or {}).get("name")
    tournament = (match.get("tournament") or {}).get("name")
    event_parts = [clean_text(x) for x in [league, serie, tournament] if x]
    event = " · ".join(event_parts)[:350]
    return {
        "id": str(mid), "teams": teams, "winner": winner, "event": event,
        "bo": match.get("number_of_games"), "end_at": match.get("end_at")
    }


def build_embed(result, test=False):
    t1, t2 = result["teams"]
    match_desc = f"**{t1['name']}**  **{t1['score']} : {t2['score']}**  **{t2['name']}**"
    fields = [
        {"name": "🏆 승리팀", "value": result["winner"], "inline": True},
        {"name": "🏟️ 대회", "value": result["event"][:1024], "inline": False},
    ]
    bo = result.get("bo")
    if isinstance(bo, int) and bo > 0:
        fields.append({"name": "경기 방식", "value": "BO" + str(bo), "inline": True})
    embed = {
        "title": "🧪 연결 테스트 — 과거 경기" if test else "🏁 Rainbow Six Siege 경기 종료",
        "description": match_desc,
        "color": 0x5865F2 if test else 0x34A853,
        "fields": fields,
        "footer": {"text": "경기 데이터: PandaScore · Match #" + result["id"]},
    }
    ended_at = result.get("end_at")
    if isinstance(ended_at, str) and ended_at:
        embed["timestamp"] = ended_at
    return {"username": "R6 Esports Results", "allowed_mentions": {"parse": []}, "embeds": [embed]}


def post_result(webhook, result, test=False):
    # wait=true asks Discord to confirm that it really saved the message.
    joiner = "&" if "?" in webhook else "?"
    request_json(webhook + joiner + "wait=true", data=build_embed(result, test=test))


def state_db():
    db = sqlite3.connect(STATE_PATH)
    db.execute("CREATE TABLE IF NOT EXISTS seen_matches (id TEXT PRIMARY KEY, marked_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, val TEXT NOT NULL)")
    db.commit()
    return db


def has_initialized(db):
    return db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone() is not None


def already_seen(db, mid):
    return db.execute("SELECT 1 FROM seen_matches WHERE id=?", (mid,)).fetchone() is not None


def mark_seen(db, mid):
    db.execute("INSERT OR IGNORE INTO seen_matches(id,marked_at) VALUES (?,?)",
               (mid, datetime.now(timezone.utc).isoformat()))
    db.commit()


def initialize(db, matches):
    # Deliberately do NOT send old matches on first launch.
    for match in matches:
        mid = match.get("id") if isinstance(match, dict) else None
        if mid is not None:
            db.execute("INSERT OR IGNORE INTO seen_matches(id,marked_at) VALUES (?,?)",
                       (str(mid), datetime.now(timezone.utc).isoformat()))
    db.execute("INSERT OR REPLACE INTO meta(key,val) VALUES ('initialized','yes')")
    db.commit()
    print("첫 실행: 기존 경기 " + str(len(matches)) + "개를 읽고 지나갔습니다. 다음 신규 경기부터 알림이 옵니다.")


def run_test(token, webhook):
    print("PandaScore에서 최근 완료 경기를 찾는 중...")
    matches = fetch_recent_matches(token)
    result = next((extract_result(m) for m in matches if extract_result(m) is not None), None)
    if not result:
        raise RuntimeError("조회된 경기 중 최종 스코어가 있는 경기를 찾지 못했습니다.")
    post_result(webhook, result, test=True)
    print("성공! Discord 채널에 '연결 테스트 — 과거 경기' 메시지를 전송했습니다.")


def run_monitor(token, webhook, once=False):
    with state_db() as db:
        print("R6 경기 결과 자동 알림 시작. 종료: Ctrl + C")
        print("5분마다 확인합니다. 과거 경기 재전송은 하지 않습니다.")
        while True:
            try:
                matches = fetch_recent_matches(token)
                if not has_initialized(db):
                    initialize(db, matches)
                else:
                    # Oldest first to avoid reverse-order alerts if multiple matches end.
                    matches.sort(key=lambda m: (m.get("end_at") or "", str(m.get("id") or "")))
                    sent = 0
                    for match in matches:
                        mid = str(match.get("id"))
                        if already_seen(db, mid):
                            continue
                        result = extract_result(match)
                        if result is None:
                            continue  # No final score yet: retry on next poll
                        post_result(webhook, result)
                        mark_seen(db, mid)  # Save ONLY after Discord confirms send
                        sent += 1
                        print("전송 완료:", result["teams"][0]["name"],
                              result["teams"][0]["score"], ":",
                              result["teams"][1]["score"], result["teams"][1]["name"])
                        time.sleep(2)  # Avoid webhook bursts
                    now = datetime.now().strftime("%H:%M:%S")
                    print("[" + now + "] 확인 완료. 조회 " + str(len(matches)) + "경기, 새 알림 " + str(sent) + "건")
            except KeyboardInterrupt:
                print("종료합니다.")
                return
            except Exception as exc:
                print("오류:", str(exc), "— 다음 주기에 재시도")
            if once:
                return
            try:
                time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                print("종료합니다.")
                return


def main():
    parser = argparse.ArgumentParser(description="R6 PandaScore -> Discord 결과 알림")
    parser.add_argument("--test", action="store_true", help="최근 완료 경기 1건을 테스트로 Discord에 전송")
    parser.add_argument("--once", action="store_true", help="한 번만 조회하고 종료 (점검용)")
    args = parser.parse_args()
    try:
        token, webhook = load_config()
        if args.test:
            run_test(token, webhook)
        else:
            run_monitor(token, webhook, once=args.once)
    except KeyboardInterrupt:
        print("\n취소했습니다.")
    except Exception as exc:
        print("실패:", str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
