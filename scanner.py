import os
import json
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

BSD_BASE = "https://sports.bzzoiro.com/api/v2"
TELEGRAM_BASE = "https://api.telegram.org"
BSD_API_KEY = os.getenv("BSD_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ACCESS_WORKER_URL = os.getenv("ACCESS_WORKER_URL", "")
BROADCAST_SECRET = os.getenv("BROADCAST_SECRET", "")
if not BSD_API_KEY:
    print("❌ Δεν βρέθηκε BSD_API_KEY στο .env")
    raise SystemExit(1)

FORM_CACHE = {}


def api_get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Token {BSD_API_KEY}", "User-Agent": "FootballTips/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"API ERROR: {url}")
        print(e)
        return None


def telegram_get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print("Telegram GET error:", e)
        return None


def telegram_post(method, data):
    url = f"{TELEGRAM_BASE}/bot{TELEGRAM_BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print("Telegram POST error:", e)
        return None


def get_chat_id():
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN:
        return None
    data = telegram_get(f"{TELEGRAM_BASE}/bot{TELEGRAM_BOT_TOKEN}/getUpdates")
    if not data or not data.get("ok"):
        return None
    for item in reversed(data.get("result", [])):
        chat = item.get("message", {}).get("chat", {})
        if chat.get("id"):
            return str(chat["id"])
    return None


def send_telegram(message):
    chat_id = get_chat_id()
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    result = telegram_post("sendMessage", {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    return bool(result and result.get("ok"))
def broadcast_telegram(message):
    if not ACCESS_WORKER_URL or not BROADCAST_SECRET:
        return False

    try:
        payload = json.dumps({"message": message}).encode("utf-8")
        req = urllib.request.Request(
            f"{ACCESS_WORKER_URL}/broadcast",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Broadcast-Secret": BROADCAST_SECRET,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        return bool(data.get("ok"))

    except Exception as e:
        print(f"BROADCAST ERROR: {e}")
        return False

def safe_float(value):
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.replace(",", ".")
        return float(value)
    except Exception:
        return None


def get_name(obj):
    if not obj:
        return "Unknown"
    if isinstance(obj, str):
        return obj
    return obj.get("name") or obj.get("team_name") or obj.get("short_name") or "Unknown"


def get_today_events():
    today = datetime.now().strftime("%Y-%m-%d")
    data = api_get(f"{BSD_BASE}/events/?date_from={today}&date_to={today}&status=upcoming&limit=200")
    return data.get("results", []) if data else []


def get_prediction(event_id):
    return api_get(f"{BSD_BASE}/events/{event_id}/prediction/")


def prediction_value(prediction, market):
    if not prediction:
        return None
    markets = prediction.get("markets", {})
    ou = markets.get("over_under", {})
    btts = markets.get("btts", {})
    if market == "OVER 2.5":
        return safe_float(ou.get("prob_over_25"))
    if market == "OVER 3.5":
        return safe_float(ou.get("prob_over_35"))
    if market == "GG":
        return safe_float(btts.get("prob_yes"))
    return None


def get_odds(event_id, market):
    api_market = {"OVER 2.5": "over_under_25", "OVER 3.5": "over_under_35", "GG": "btts"}.get(market)
    if not api_market:
        return None
    data = api_get(f"{BSD_BASE}/odds/?event_id={event_id}&market={api_market}&limit=20")
    if not data:
        return None
    rows = data.get("results", [])
    row = next((r for r in rows if r.get("bookmaker_slug") == "consensus"), rows[0] if rows else None)
    if not row:
        return None
    return {
        "odds": safe_float(row.get("decimal_odds") or row.get("odds") or row.get("price")),
        "movement": row.get("movement"),
        "previous": safe_float(row.get("previous_decimal_odds") or row.get("previous_odds")),
        "opening": safe_float(row.get("opening_decimal_odds") or row.get("opening_odds")),
    }


def get_event_stats(event_id):
    return api_get(f"{BSD_BASE}/events/{event_id}/stats/")


def get_lineups(event_id):
    return api_get(f"{BSD_BASE}/events/{event_id}/lineups/")


def get_squad(team_id):
    return api_get(f"{BSD_BASE}/teams/{team_id}/squad/") if team_id else None


def unavailable_players(squad):
    if not squad:
        return 0
    return sum(1 for p in squad.get("players", []) if str(p.get("availability", "")).lower() in {"injured", "suspended", "doubtful"})


def _score_value(obj, *keys):
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, dict):
                value = value.get("current") or value.get("display") or value.get("goals")
            value = safe_float(value)
            if value is not None:
                return int(value)
    return None


def get_recent_form(team_id):
    """Last 5 completed matches plus home/away split metrics."""
    if not team_id:
        return None
    key = str(team_id)
    if key in FORM_CACHE:
        return FORM_CACHE[key]
    try:
        data = api_get(f"{BSD_BASE}/events/?team_id={team_id}&status=finished&limit=20")
        rows = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        matches = []
        for match in rows:
            if not isinstance(match, dict):
                continue
            home = match.get("home_team") if isinstance(match.get("home_team"), dict) else {}
            away = match.get("away_team") if isinstance(match.get("away_team"), dict) else {}
            home_id = home.get("id") or match.get("home_team_id")
            away_id = away.get("id") or match.get("away_team_id")
            if str(home_id) != key and str(away_id) != key:
                continue
            hs = _score_value(match, "home_score", "home_goals", "home_score_current")
            aws = _score_value(match, "away_score", "away_goals", "away_score_current")
            if hs is None or aws is None:
                score = match.get("score")
                if isinstance(score, dict):
                    hs = _score_value(score, "home", "home_score")
                    aws = _score_value(score, "away", "away_score")
            if hs is None or aws is None:
                continue
            date = str(match.get("event_date") or match.get("start_time") or match.get("date") or "")
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                if dt > now:
                    continue
            except Exception:
                pass
            matches.append((date, home_id, away_id, hs, aws))
        matches.sort(key=lambda x: x[0], reverse=True)
        matches = matches[:5]
        if not matches:
            FORM_CACHE[key] = None
            return None

        def calc(subset):
            if not subset:
                return None
            gf = ga = o25 = o35 = btts = 0
            for _, home_id, away_id, hs, aws in subset:
                if str(home_id) == key:
                    team_for, team_against = hs, aws
                else:
                    team_for, team_against = aws, hs
                total = hs + aws
                gf += team_for
                ga += team_against
                o25 += total >= 3
                o35 += total >= 4
                btts += hs >= 1 and aws >= 1
            n = len(subset)
            return {
                "games": n,
                "avg_goals_for": round(gf / n, 2),
                "avg_goals_against": round(ga / n, 2),
                "avg_total_goals": round((gf + ga) / n, 2),
                "over25_rate": round(o25 / n * 100, 1),
                "over35_rate": round(o35 / n * 100, 1),
                "btts_rate": round(btts / n * 100, 1),
            }

        all_form = calc(matches)
        home_form = calc([m for m in matches if str(m[1]) == key])
        away_form = calc([m for m in matches if str(m[2]) == key])
        form = {
            **all_form,
            "home_games": home_form["games"] if home_form else 0,
            "away_games": away_form["games"] if away_form else 0,
            "home_split": home_form,
            "away_split": away_form,
        }
        FORM_CACHE[key] = form
        return form
    except Exception as e:
        print(f"Recent form error for team {team_id}: {e}")
        FORM_CACHE[key] = None
        return None

def score_market(
    market,
    probability,
    odds,
    movement,
    xg,
    confidence,
    unavailable,
    home_form=None,
    away_form=None,
    lineup_status="unknown"
):
    if probability is None:
        return 0

    score = 0

    # Prediction
    if market == "OVER 2.5":
        if probability >= 62:
            score += 30
        elif probability >= 57:
            score += 24
        elif probability >= 53:
            score += 18
        elif probability >= 50:
            score += 12

    elif market == "OVER 3.5":
        if probability >= 48:
            score += 30
        elif probability >= 42:
            score += 24
        elif probability >= 37:
            score += 18
        elif probability >= 33:
            score += 12

    elif market == "GG":
        if probability >= 60:
            score += 30
        elif probability >= 56:
            score += 25
        elif probability >= 52:
            score += 20
        elif probability >= 49:
            score += 12

    # xG
    if xg is not None:
        if market == "OVER 2.5":
            if xg >= 3.10:
                score += 25
            elif xg >= 2.80:
                score += 20
            elif xg >= 2.55:
                score += 15
            elif xg >= 2.30:
                score += 8

        elif market == "OVER 3.5":
            if xg >= 3.50:
                score += 25
            elif xg >= 3.20:
                score += 20
            elif xg >= 2.90:
                score += 14
            elif xg >= 2.70:
                score += 8

        elif market == "GG":
            if xg >= 3.00:
                score += 25
            elif xg >= 2.70:
                score += 20
            elif xg >= 2.40:
                score += 14
            elif xg >= 2.20:
                score += 8

    # Odds movement
    if movement == "SHORTENING":
        score += 15
    elif movement == "DRIFTING":
        score -= 5

    # Model confidence
    if confidence is not None:
        if confidence >= 0.70:
            score += 15
        elif confidence >= 0.60:
            score += 10
        elif confidence >= 0.50:
            score += 5

    # Absences
    if unavailable >= 4:
        score += 3

    # Strict recent-form layer
    forms = [
        f for f in (home_form, away_form)
        if f and f.get("games", 0) >= 3
    ]

    if forms:
        avg_total = sum(f.get("avg_total_goals", 0) for f in forms) / len(forms)
        avg_o25 = sum(f.get("over25_rate", 0) for f in forms) / len(forms)
        avg_o35 = sum(f.get("over35_rate", 0) for f in forms) / len(forms)
        avg_btts = sum(f.get("btts_rate", 0) for f in forms) / len(forms)

        if market == "OVER 2.5":
            if avg_total >= 3.20 and avg_o25 >= 60:
                score += 12
            elif avg_total >= 2.90 and avg_o25 >= 55:
                score += 8
            elif avg_total >= 2.70 and avg_o25 >= 50:
                score += 4

            if avg_total < 2.40 and avg_o25 < 40:
                score -= 8

            if probability >= 57 and avg_total >= 2.80 and avg_o25 >= 50:
                score += 4

        elif market == "OVER 3.5":
            if avg_total >= 3.60 and avg_o35 >= 50:
                score += 12
            elif avg_total >= 3.30 and avg_o35 >= 40:
                score += 8
            elif avg_total >= 3.00 and avg_o35 >= 35:
                score += 4

            if avg_total < 2.80 and avg_o35 < 25:
                score -= 8

            if probability >= 42 and avg_total >= 3.20 and avg_o35 >= 35:
                score += 4

        elif market == "GG":
            if avg_btts >= 70:
                score += 12
            elif avg_btts >= 62:
                score += 8
            elif avg_btts >= 55:
                score += 4

            if avg_btts < 45:
                score -= 8

            if probability >= 56 and avg_btts >= 60:
                score += 4

    # Confirmed lineups
    if str(lineup_status).lower() == "confirmed":
        score += 2

    return max(0, min(100, score))

def make_bet_builder(markets):
    over25 = markets.get("OVER 2.5")
    gg = markets.get("GG")
    if not over25 or not gg:
        return None
    if over25["score"] >= 55 and gg["score"] >= 50:
        return {"text": "Over 2.5 + GG", "score": int((over25["score"] + gg["score"]) / 2)}
    return None


def extract_xg(stats, prediction):
    if isinstance(stats, dict):
        xg = stats.get("xg")
        if isinstance(xg, dict):
            h = safe_float(xg.get("home") or xg.get("home_xg"))
            a = safe_float(xg.get("away") or xg.get("away_xg"))
            if h is not None and a is not None:
                return h + a
        hs, aws = stats.get("home", {}), stats.get("away", {})
        if isinstance(hs, dict) and isinstance(aws, dict):
            h = safe_float(hs.get("xg") or hs.get("expected_goals"))
            a = safe_float(aws.get("xg") or aws.get("expected_goals"))
            if h is not None and a is not None:
                return h + a
    pxg = prediction.get("markets", {}).get("expected_goals", {})
    if isinstance(pxg, dict):
        h, a = safe_float(pxg.get("home")), safe_float(pxg.get("away"))
        if h is not None and a is not None:
            return h + a
    return None


def process_event(event):
    event_id = event.get("id")
    home_obj, away_obj = event.get("home_team"), event.get("away_team")
    home = get_name(home_obj)
    away = get_name(away_obj)
    home_id = home_obj.get("id") if isinstance(home_obj, dict) else event.get("home_team_id")
    away_id = away_obj.get("id") if isinstance(away_obj, dict) else event.get("away_team_id")
    home_id = home_id or event.get("home_team_id")
    away_id = away_id or event.get("away_team_id")
    event_date = event.get("event_date") or event.get("start_time")

    prediction = get_prediction(event_id)
    if not prediction:
        return None
    confidence = safe_float(prediction.get("model", {}).get("confidence"))
    stats = get_event_stats(event_id)
    xg = extract_xg(stats, prediction)

    home_squad, away_squad = get_squad(home_id), get_squad(away_id)
    home_unavailable = unavailable_players(home_squad)
    away_unavailable = unavailable_players(away_squad)
    unavailable_total = home_unavailable + away_unavailable

    lineup = get_lineups(event_id)
    lineup_status = lineup.get("lineup_status") or lineup.get("status") or "unknown" if isinstance(lineup, dict) else "unknown"

    home_form = get_recent_form(home_id)
    away_form = get_recent_form(away_id)

    markets = {}
    for market in ("OVER 2.5", "OVER 3.5", "GG"):
        probability = prediction_value(prediction, market)
        if probability is None:
            continue
        odds_data = get_odds(event_id, market)
        if not odds_data or odds_data.get("odds") is None:
            continue
        score = score_market(market, probability, odds_data["odds"], odds_data.get("movement"), xg, confidence, unavailable_total, home_form, away_form, lineup_status)
        markets[market] = {"probability": probability, "odds": odds_data["odds"], "movement": odds_data.get("movement"), "score": score}
    if not markets:
        return None
    return {
        "event_id": event_id,
        "home": home,
        "away": away,
        "time": event_date,
        "xg": xg,
        "confidence": confidence,
        "home_unavailable": home_unavailable,
        "away_unavailable": away_unavailable,
        "lineup_status": lineup_status,
        "home_form": home_form,
        "away_form": away_form,
        "markets": markets
    }



def select_picks(results):
    candidates = []

    def strict_qualifies(result, market, data):
        if not data:
            return False
        score = data.get("score", 0)
        probability = data.get("probability")
        xg = result.get("xg")
        if probability is None:
            return False

        minimum = {"OVER 2.5": 66, "OVER 3.5": 72, "GG": 66}.get(market, 50)
        if score < minimum:
            return False

        home = result.get("home_form") or {}
        away = result.get("away_form") or {}
        hs = home.get("home_split") or home
        aws = away.get("away_split") or away
        evidence = 0

        if market == "OVER 2.5":
            if probability >= 58: evidence += 1
            if xg is not None and xg >= 2.90: evidence += 1
            if hs.get("avg_total_goals", 0) >= 2.80 and hs.get("over25_rate", 0) >= 50: evidence += 1
            if aws.get("avg_total_goals", 0) >= 2.80 and aws.get("over25_rate", 0) >= 50: evidence += 1
            if hs.get("over25_rate", 0) < 40 or aws.get("over25_rate", 0) < 40: return False
            return evidence >= 3

        if market == "OVER 3.5":
            if probability >= 44: evidence += 1
            if xg is not None and xg >= 3.30: evidence += 1
            if hs.get("avg_total_goals", 0) >= 3.20 and hs.get("over35_rate", 0) >= 35: evidence += 1
            if aws.get("avg_total_goals", 0) >= 3.20 and aws.get("over35_rate", 0) >= 35: evidence += 1
            if hs.get("over35_rate", 0) < 25 or aws.get("over35_rate", 0) < 25: return False
            return evidence >= 3

        if market == "GG":
            if probability >= 58: evidence += 1
            if xg is not None and xg >= 2.80: evidence += 1
            if hs.get("avg_goals_for", 0) >= 1.20 and hs.get("btts_rate", 0) >= 55: evidence += 1
            if aws.get("avg_goals_for", 0) >= 1.20 and aws.get("btts_rate", 0) >= 55: evidence += 1
            if hs.get("btts_rate", 0) < 45 or aws.get("btts_rate", 0) < 45: return False
            return evidence >= 3

        return False

    for result in results:
        markets = result.get("markets", {})
        builder = make_bet_builder(markets)
        over_ok = strict_qualifies(result, "OVER 2.5", markets.get("OVER 2.5"))
        gg_ok = strict_qualifies(result, "GG", markets.get("GG"))

        if builder and builder.get("score", 0) >= 68 and over_ok and gg_ok:
            candidates.append({**result, "market": builder["text"], "odds": None, "movement": None, "score": builder["score"]})
            continue

        best = []
        for market, data in markets.items():
            if strict_qualifies(result, market, data):
                best.append({**result, "market": market, "odds": data.get("odds"), "movement": data.get("movement"), "score": data.get("score", 0)})
        if best:
            best.sort(key=lambda x: x["score"], reverse=True)
            candidates.append(best[0])

    candidates.sort(key=lambda x: (sort_key(x), -x["score"]))
    return candidates

CYPRUS_TZ = ZoneInfo("Europe/Nicosia")


def parse_event_datetime(value):
    if not value:
        return None

    text = str(value).strip()

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        dt = datetime.fromisoformat(text)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        return dt.astimezone(CYPRUS_TZ)

    except Exception:
        return None


def clean_time(value):
    dt = parse_event_datetime(value)

    if dt is not None:
        return dt.strftime("%H:%M")

    if not value:
        return "Ώρα TBD"

    text = str(value)

    if len(text) >= 16 and "T" in text:
        return text[11:16]

    return text


def sort_key(item):
    dt = parse_event_datetime(item.get("time"))

    if dt is not None:
        return (0, dt)

    return (1, datetime.max.replace(tzinfo=CYPRUS_TZ))


def format_pick(item):
    xg = item.get("xg")
    xg_text = f"{xg:.2f}" if xg is not None else "—"
    return (
        f"⚽ <b>{item['home']} 🆚 {item['away']}</b>\n"
        f"🕘 {clean_time(item['time'])}\n"
        f"🎯 <b>{item['market']}</b>\n"
        f"📊 Score: {item.get('score', 0)}/100\n"
        f"🧠 xG: {xg_text}"
    )

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "docs", "history.json")


def append_history(picks):
    """Persist picks for the public dashboard. Technical scoring fields stay private."""
    import pathlib
    pathlib.Path(os.path.dirname(HISTORY_PATH)).mkdir(parents=True, exist_ok=True)
    try:
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        else:
            history = []
    except Exception:
        history = []

    existing = {str(x.get("event_id")) for x in history if isinstance(x, dict)}
    for item in picks:
        key = f"{item.get('event_id')}"
        if key in existing:
            continue
        history.append({
            "key": key,
            "event_id": item.get("event_id"),
            "date": clean_time(item.get("time")),
            "kickoff": item.get("time"),
            "home": item.get("home"),
            "away": item.get("away"),
            "market": item.get("market"),
            "odds": item.get("odds"),
            "status": "PENDING"
        })
        existing.add(key)

    history.sort(key=lambda x: str(x.get("kickoff", "")), reverse=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def main():
    print("=" * 72)
    print("⚽ FOOTBALL TIPS SCANNER V9.2 STRICT + HISTORY")
    print("=" * 72)
    events = get_today_events()
    print(f"\nΑΓΩΝΕΣ ΣΗΜΕΡΑ: {len(events)}")
    if not events:
        print("❌ Δεν βρέθηκαν αγώνες.")
        return
    results = []
    for i, event in enumerate(events, 1):
        home, away = get_name(event.get("home_team")), get_name(event.get("away_team"))
        print(f"[{i}/{len(events)}] {home} - {away}")
        try:
            result = process_event(event)
            if result:
                results.append(result)
        except Exception as e:
            print(f"⚠️ Error στο {home} - {away}: {e}")
    picks = select_picks(results)
    parts = ["🔥 <b>FOOTBALL TIPS</b>", "📅 Σημερινές επιλογές — ώρα Κύπρου", ""]

    if not picks:
        parts.append("❌ Σήμερα δεν βρέθηκαν επιλογές που να περνούν τα φίλτρα.")
    else:
        normal_picks = [item for item in picks if item.get("market") != "Over 2.5 + GG"]
        builder_picks = [item for item in picks if item.get("market") == "Over 2.5 + GG"]
    
        for item in normal_picks:
            parts += [format_pick(item), ""]
    
        if builder_picks:
            parts += [
                "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦",
                "🔥 <b>BET BUILDER</b>",
                "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦",
                ""
            ]
    
            for item in builder_picks:
                parts += [format_pick(item), ""]
    message = "\n".join(parts).rstrip()
    print("\n" + message.replace("<b>", "").replace("</b>", ""))
    if picks:
        append_history(picks)
        print("\n📲 ΑΠΟΣΤΟΛΗ TELEGRAM...")
        print("✅ Στάλθηκε επιτυχώς στο Telegram." if send_telegram(message) else "❌ Δεν στάλθηκε στο Telegram.")
        print("✅ Broadcast στάλθηκε στους FREE users." if broadcast_telegram(message) else "❌ Το broadcast δεν στάλθηκε.")    print(f"SUMMARY | Events: {len(events)} | Analysed: {len(results)} | Picks: {len(picks)}")


if __name__ == "__main__":
    main()
