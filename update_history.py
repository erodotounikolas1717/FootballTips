import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "https://v3.football.api-sports.io"
KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
PATH = Path("docs/history.json")

if not KEY:
    raise SystemExit("API_FOOTBALL_KEY is missing")

if not PATH.exists():
    raise SystemExit("docs/history.json not found")


def api_get(url):
    req = urllib.request.Request(
        url,
        headers={
            "x-apisports-key": KEY,
            "User-Agent": "FootballTips/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"API ERROR {e.code}: {url}")
        return None
    except Exception as e:
        print(f"API ERROR: {e}")
        return None


def get_fixture(fixture_id):
    data = api_get(f"{BASE}/fixtures?id={fixture_id}")

    if not isinstance(data, dict):
        return None

    response = data.get("response") or []

    if not response:
        return None

    return response[0]


def check_market(market, home_score, away_score):
    total = home_score + away_score

    market = str(market or "").strip().upper()

    if market == "OVER 2.5":
        return total >= 3

    if market == "OVER 3.5":
        return total >= 4

    if market == "GG":
        return home_score >= 1 and away_score >= 1

    if market in ("OVER 2.5 + GG", "OVER 2.5+GG"):
        return total >= 3 and home_score >= 1 and away_score >= 1

    if market in ("OVER 3.5 + GG", "OVER 3.5+GG"):
        return total >= 4 and home_score >= 1 and away_score >= 1

    return None


history = json.loads(PATH.read_text(encoding="utf-8"))

changed = False
checked = 0
updated = 0

for item in history:
    status = str(item.get("status", "")).upper()

    if status != "PENDING":
        continue

    event_id = item.get("event_id")

    if not event_id:
        print("SKIP: missing event_id")
        continue

    checked += 1

    print(
        f"CHECK {event_id} | "
        f"{item.get('home')} vs {item.get('away')} | "
        f"{item.get('market')}"
    )

    fixture = get_fixture(event_id)

    if not fixture:
        print(f"SKIP {event_id}: fixture not found")
        continue

    fixture_data = fixture.get("fixture") or {}
    teams = fixture.get("teams") or {}
    goals = fixture.get("goals") or {}

    fixture_status = (
        fixture_data.get("status") or {}
    ).get("short", "")

    fixture_status = str(fixture_status).upper()

    finished_statuses = {
        "FT",
        "AET",
        "PEN",
    }

    if fixture_status not in finished_statuses:
        print(
            f"SKIP {event_id}: status={fixture_status}"
        )
        continue

    home_score = goals.get("home")
    away_score = goals.get("away")

    if home_score is None or away_score is None:
        print(f"SKIP {event_id}: score unavailable")
        continue

    try:
        home_score = float(home_score)
        away_score = float(away_score)
    except (TypeError, ValueError):
        print(f"SKIP {event_id}: invalid score")
        continue

    market = str(item.get("market", "")).strip()

    result = check_market(
        market,
        home_score,
        away_score,
    )

    if result is None:
        print(
            f"SKIP {event_id}: unknown market {market}"
        )
        continue

    item["home_score"] = home_score
    item["away_score"] = away_score
    item["status"] = "WIN" if result else "LOSS"

    # Keep the actual fixture names when API-Football provides them.
    api_home = (teams.get("home") or {}).get("name")
    api_away = (teams.get("away") or {}).get("name")

    if api_home:
        item["home"] = api_home

    if api_away:
        item["away"] = api_away

    changed = True
    updated += 1

    print(
        f"RESULT {event_id} | "
        f"{item.get('home')} vs {item.get('away')} | "
        f"{market} | "
        f"{home_score:g}-{away_score:g} | "
        f"{item['status']}"
    )

    # Be gentle with the API.
    time.sleep(0.25)


if changed:
    PATH.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("================================")
    print("✅ HISTORY UPDATED")
    print(f"Checked: {checked}")
    print(f"Updated: {updated}")
    print("================================")
else:
    print()
    print("================================")
    print("ℹ️ NO HISTORY CHANGES")
    print(f"Pending checked: {checked}")
    print("================================")
