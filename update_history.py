import json
import os
import urllib.request
from pathlib import Path

BASE = "https://sports.bzzoiro.com/api/v2"
KEY = os.getenv("BSD_API_KEY", "").strip()
PATH = Path("docs/history.json")


def get_event(event_id):
    url = f"{BASE}/events/{event_id}/"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {KEY}",
            "User-Agent": "FootballTips/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"API ERROR {event_id}: {e}")
        return None


def check_market(market, home_score, away_score):
    total = home_score + away_score

    if market == "OVER 2.5":
        return total >= 3

    if market == "OVER 3.5":
        return total >= 4

    if market == "GG":
        return home_score >= 1 and away_score >= 1

    if market == "OVER 2.5 + GG":
        return total >= 3 and home_score >= 1 and away_score >= 1

    if market == "OVER 3.5 + GG":
        return total >= 4 and home_score >= 1 and away_score >= 1

    return None


if not KEY:
    raise SystemExit("BSD_API_KEY is missing")

if not PATH.exists():
    raise SystemExit("docs/history.json not found")

history = json.loads(PATH.read_text(encoding="utf-8"))

if not isinstance(history, list):
    raise SystemExit("history.json must contain a list")

changed = False

for item in history:

    status = str(item.get("status", "")).upper()

    if status != "PENDING":
        continue

    event_id = item.get("event_id")

    if not event_id:
        print("SKIP: missing event_id")
        continue

    data = get_event(event_id)

    if not isinstance(data, dict):
        continue

    event_status = str(data.get("status", "")).lower()

    if event_status not in ("finished", "completed"):
        continue

    try:
        home_score = float(data.get("home_score"))
        away_score = float(data.get("away_score"))
    except (TypeError, ValueError):
        print(f"SKIP {event_id}: score unavailable")
        continue

    market = str(item.get("market", "")).strip()

    result = check_market(
        market,
        home_score,
        away_score,
    )

    if result is None:
        print(f"SKIP {event_id}: unknown market {market}")
        continue

    item["home_score"] = home_score
    item["away_score"] = away_score
    item["status"] = "WIN" if result else "LOSS"

    changed = True

    print(
        f"{event_id} | {market} | "
        f"{home_score:g}-{away_score:g} | {item['status']}"
    )


if changed:
    PATH.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("✅ History updated")
else:
    print("ℹ️ No finished PENDING picks to update")
