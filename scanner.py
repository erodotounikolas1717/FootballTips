import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ============================================================
# FOOTBALL TIPS SCANNER
# ============================================================

BSD_BASE = "https://sports.bzzoiro.com/api/v2"
TELEGRAM_BASE = "https://api.telegram.org"

BSD_API_KEY = os.getenv("BSD_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not BSD_API_KEY:
    print("❌ Δεν βρέθηκε BSD_API_KEY στο .env")
    raise SystemExit(1)

# ------------------------------------------------------------
# API
# ------------------------------------------------------------

def api_get(url):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {BSD_API_KEY}",
            "User-Agent": "FootballTips/1.0"
        }
    )

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

    encoded = urllib.parse.urlencode(data).encode()

    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print("Telegram POST error:", e)
        return None


# ------------------------------------------------------------
# TELEGRAM CHAT
# ------------------------------------------------------------

def get_chat_id():
    global TELEGRAM_CHAT_ID

    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN:
        return None

    data = telegram_get(
        f"{TELEGRAM_BASE}/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    )

    if not data or not data.get("ok"):
        return None

    results = data.get("result", [])

    for item in reversed(results):
        message = item.get("message", {})
        chat = message.get("chat", {})

        if chat.get("id"):
            return str(chat["id"])

    return None


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ Δεν υπάρχει TELEGRAM_BOT_TOKEN")
        return False

    chat_id = get_chat_id()

    if not chat_id:
        print("⚠️ Δεν βρέθηκε Telegram chat ID")
        return False

    result = telegram_post(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true"
        }
    )

    return bool(result and result.get("ok"))


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

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

    return (
        obj.get("name")
        or obj.get("team_name")
        or obj.get("short_name")
        or "Unknown"
    )


def get_team_id(obj):
    if not isinstance(obj, dict):
        return None

    return (
        obj.get("id")
        or obj.get("team_id")
        or obj.get("home_team_id")
        or obj.get("away_team_id")
    )


# ------------------------------------------------------------
# EVENTS
# ------------------------------------------------------------

def get_today_events():

    today = datetime.now().strftime("%Y-%m-%d")

    url = (
        f"{BSD_BASE}/events/"
        f"?date_from={today}"
        f"&date_to={today}"
        f"&status=upcoming"
        f"&limit=200"
    )

    data = api_get(url)

    if not data:
        return []

    return data.get("results", [])


# ------------------------------------------------------------
# PREDICTION
# ------------------------------------------------------------

def get_prediction(event_id):

    url = f"{BSD_BASE}/events/{event_id}/prediction/"

    return api_get(url)


def prediction_value(prediction, market):

    if not prediction:
        return None

    markets = prediction.get("markets", {})

    over_under = markets.get("over_under", {})
    btts = markets.get("btts", {})

    if market == "OVER 2.5":
        return safe_float(over_under.get("prob_over_25"))

    if market == "OVER 3.5":
        return safe_float(over_under.get("prob_over_35"))

    if market == "GG":
        return safe_float(btts.get("prob_yes"))

    return None


# ------------------------------------------------------------
# ODDS
# ------------------------------------------------------------

def get_odds(event_id, market):

    api_market = {
        "OVER 2.5": "over_under_25",
        "OVER 3.5": "over_under_35",
        "GG": "btts"
    }.get(market)

    if not api_market:
        return None

    url = (
        f"{BSD_BASE}/odds/"
        f"?event_id={event_id}"
        f"&market={api_market}"
        f"&limit=20"
    )

    data = api_get(url)

    if not data:
        return None

    rows = data.get("results", [])

    if not rows:
        return None

    # Prefer consensus
    consensus = None

    for row in rows:
        if row.get("bookmaker_slug") == "consensus":
            consensus = row
            break

    if consensus:
        row = consensus
    else:
        row = rows[0]

    odds = safe_float(
        row.get("decimal_odds")
        or row.get("odds")
        or row.get("price")
    )

    previous = safe_float(
        row.get("previous_decimal_odds")
        or row.get("previous_odds")
    )

    opening = safe_float(
        row.get("opening_decimal_odds")
        or row.get("opening_odds")
    )

    movement = row.get("movement")

    return {
        "odds": odds,
        "previous": previous,
        "opening": opening,
        "movement": movement
    }


# ------------------------------------------------------------
# STATS
# ------------------------------------------------------------

def get_event_stats(event_id):

    url = f"{BSD_BASE}/events/{event_id}/stats/"

    return api_get(url)


# ------------------------------------------------------------
# LINEUPS
# ------------------------------------------------------------

def get_lineups(event_id):

    url = f"{BSD_BASE}/events/{event_id}/lineups/"

    return api_get(url)


# ------------------------------------------------------------
# SQUADS / AVAILABILITY
# ------------------------------------------------------------

def get_squad(team_id):

    if not team_id:
        return None

    url = f"{BSD_BASE}/teams/{team_id}/squad/"

    return api_get(url)


def unavailable_players(squad):

    if not squad:
        return 0

    players = squad.get("players", [])

    count = 0

    for player in players:

        availability = str(
            player.get("availability", "")
        ).lower()

        if availability in (
            "injured",
            "suspended",
            "doubtful"
        ):
            count += 1

    return count


# ------------------------------------------------------------
# SCORE
# ------------------------------------------------------------

def score_market(
    market,
    probability,
    odds,
    movement,
    xg,
    confidence,
    unavailable
):

    if probability is None:
        return 0

    score = 0

    # --------------------------------------------------------
    # PROBABILITY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # xG
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MOVEMENT
    # --------------------------------------------------------

    if movement == "SHORTENING":
        score += 15

    elif movement == "DRIFTING":
        score -= 5

    # --------------------------------------------------------
    # MODEL CONFIDENCE
    # --------------------------------------------------------

    if confidence is not None:

        if confidence >= 0.70:
            score += 15
        elif confidence >= 0.60:
            score += 10
        elif confidence >= 0.50:
            score += 5

    # --------------------------------------------------------
    # ABSENCES
    # --------------------------------------------------------

    if unavailable:

        # For goal markets, missing defenders / players
        # can sometimes increase volatility.
        if unavailable >= 4:
            score += 3

    return max(0, min(100, score))


# ------------------------------------------------------------
# BET BUILDER
# ------------------------------------------------------------

def make_bet_builder(markets):

    over25 = markets.get("OVER 2.5")
    gg = markets.get("GG")

    if not over25 or not gg:
        return None

    # We want both markets to be reasonably strong.
    if over25["score"] >= 55 and gg["score"] >= 50:

        return {
            "text": "Over 2.5 + GG",
            "score": int(
                (over25["score"] + gg["score"]) / 2
            )
        }

    return None


# ------------------------------------------------------------
# EVENT PROCESSING
# ------------------------------------------------------------

def process_event(event):

    event_id = event.get("id")

    home = (
        get_name(event.get("home_team"))
        if isinstance(event.get("home_team"), dict)
        else event.get("home_team", "Unknown")
    )

    away = (
        get_name(event.get("away_team"))
        if isinstance(event.get("away_team"), dict)
        else event.get("away_team", "Unknown")
    )

    home_id = None
    away_id = None

    if isinstance(event.get("home_team"), dict):
        home_id = event["home_team"].get("id")

    if isinstance(event.get("away_team"), dict):
        away_id = event["away_team"].get("id")

    home_id = home_id or event.get("home_team_id")
    away_id = away_id or event.get("away_team_id")

    event_date = event.get("event_date") or event.get("start_time")

    prediction = get_prediction(event_id)

    if not prediction:
        return None

    model = prediction.get("model", {})
    confidence = safe_float(model.get("confidence"))

    if confidence is not None and confidence <= 1:
        confidence_percent = confidence * 100
    else:
        confidence_percent = confidence

    markets = {}

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    stats = get_event_stats(event_id)

    xg = None

    if stats:

        # Different possible API structures
        if isinstance(stats, dict):

            xg_data = stats.get("xg")

            if isinstance(xg_data, dict):

                hxg = safe_float(
                    xg_data.get("home")
                    or xg_data.get("home_xg")
                )

                axg = safe_float(
                    xg_data.get("away")
                    or xg_data.get("away_xg")
                )

                if hxg is not None and axg is not None:
                    xg = hxg + axg

            if xg is None:

                home_stats = stats.get("home", {})
                away_stats = stats.get("away", {})

                if isinstance(home_stats, dict) and isinstance(away_stats, dict):

                    hxg = safe_float(
                        home_stats.get("xg")
                        or home_stats.get("expected_goals")
                    )

                    axg = safe_float(
                        away_stats.get("xg")
                        or away_stats.get("expected_goals")
                    )

                    if hxg is not None and axg is not None:
                        xg = hxg + axg

    # Prediction xG fallback
    if xg is None:

        prediction_xg = prediction.get(
            "markets", {}
        ).get("expected_goals", {})

        if isinstance(prediction_xg, dict):

            hxg = safe_float(
                prediction_xg.get("home")
            )

            axg = safe_float(
                prediction_xg.get("away")
            )

            if hxg is not None and axg is not None:
                xg = hxg + axg

    # --------------------------------------------------------
    # SQUADS
    # --------------------------------------------------------

    home_unavailable = 0
    away_unavailable = 0

    # We use squads, but failure here should not kill the scan.
    home_squad = get_squad(home_id)
    away_squad = get_squad(away_id)

    home_unavailable = unavailable_players(home_squad)
    away_unavailable = unavailable_players(away_squad)

    unavailable_total = (
        home_unavailable + away_unavailable
    )

    # --------------------------------------------------------
    # LINEUPS
    # --------------------------------------------------------

    lineup = get_lineups(event_id)

    lineup_status = "unknown"

    if isinstance(lineup, dict):
        lineup_status = (
            lineup.get("lineup_status")
            or lineup.get("status")
            or "unknown"
        )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    for market in (
        "OVER 2.5",
        "OVER 3.5",
        "GG"
    ):

        probability = prediction_value(
            prediction,
            market
        )

        if probability is None:
            continue

        odds_data = get_odds(
            event_id,
            market
        )

        if not odds_data:
            continue

        odds = odds_data.get("odds")

        if odds is None:
            continue

        score = score_market(
            market,
            probability,
            odds,
            odds_data.get("movement"),
            xg,
            confidence,
            unavailable_total
        )

        markets[market] = {
            "probability": probability,
            "odds": odds,
            "movement": odds_data.get("movement"),
            "score": score
        }

    if not markets:
        return None

    return {
        "event_id": event_id,
        "home": home,
        "away": away,
        "time": event_date,
        "xg": xg,
        "confidence": confidence_percent,
        "home_unavailable": home_unavailable,
        "away_unavailable": away_unavailable,
        "lineup_status": lineup_status,
        "markets": markets
    }


# ------------------------------------------------------------
# FINAL SELECTION
# ------------------------------------------------------------

def select_picks(results):

    candidates = []

    for result in results:

        for market, data in result["markets"].items():

            score = data["score"]

            # RELAXED FILTER
            if market == "OVER 2.5":
                minimum = 48

            elif market == "OVER 3.5":
                minimum = 52

            elif market == "GG":
                minimum = 48

            else:
                minimum = 50

            if score < minimum:
                continue

            item = {
                **result,
                "market": market,
                "odds": data["odds"],
                "movement": data["movement"],
                "score": score
            }

            candidates.append(item)

    # Highest first
    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # --------------------------------------------------------
    # AVOID TOO MANY MARKETS FROM SAME MATCH
    # --------------------------------------------------------

    final = []

    used_events = set()

    for item in candidates:

        event_id = item["event_id"]

        if event_id in used_events:
            continue

        final.append(item)
        used_events.add(event_id)

    return final


# ------------------------------------------------------------
# FORMAT
# ------------------------------------------------------------

def clean_time(value):

    if not value:
        return "Ώρα TBD"

    text = str(value)

    try:
        if "T" in text:

            dt = datetime.fromisoformat(
                text.replace("Z", "+00:00")
            )

            # API time -> Cyprus local time
            from datetime import timedelta

            dt = dt.astimezone()

            return dt.strftime("%H:%M")

    except Exception:
        pass

    # fallback
    if len(text) >= 16 and "T" in text:
        return text[11:16]

    return text


def format_pick(item):
    home = item["home"]
    away = item["away"]
    time = clean_time(item["time"])
    market = item["market"]

    return (
        f"⚽ <b>{home} 🆚 {away}</b>\n"
        f"🕘 {time}\n"
        f"🎯 <b>{market}</b>"
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print("=" * 72)
    print("⚽ FOOTBALL TIPS SCANNER")
    print("=" * 72)

    events = get_today_events()

    print(f"\nΑΓΩΝΕΣ ΣΗΜΕΡΑ: {len(events)}")

    if not events:
        print("❌ Δεν βρέθηκαν αγώνες.")
        return

    results = []

    for i, event in enumerate(events, 1):

        home = get_name(event.get("home_team"))
        away = get_name(event.get("away_team"))

        if home == "Unknown":
            home = event.get("home_team", "Unknown")

        if away == "Unknown":
            away = event.get("away_team", "Unknown")

        print(
            f"[{i}/{len(events)}] "
            f"{home} - {away}"
        )

        try:

            result = process_event(event)

            if result:
                results.append(result)

        except Exception as e:

            print(
                f"⚠️ Error στο "
                f"{home} - {away}: {e}"
            )

    print()
    print("=" * 72)
    print("🔥 ΤΕΛΙΚΕΣ ΕΠΙΛΟΓΕΣ")
    print("=" * 72)

    final_picks = select_picks(results)

    # --------------------------------------------------------
    # BET BUILDER
    # --------------------------------------------------------

    builders = []

    for result in results:

        builder = make_bet_builder(
            result["markets"]
        )

        if builder:

            builders.append({
                **result,
                "builder": builder["text"],
                "score": builder["score"]
            })

    builders.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message_parts = []

    message_parts.append(
        "🔥 <b>FOOTBALL TIPS</b>"
    )

    message_parts.append(
        "📅 Σημερινές επιλογές"
    )

    message_parts.append("")

    if not final_picks:

        message_parts.append(
            "❌ Σήμερα δεν βρέθηκαν "
            "επιλογές που να περνούν τα φίλτρα."
        )

    else:

        for item in final_picks:

            message_parts.append(
                format_pick(item)
            )

            message_parts.append("")

    # --------------------------------------------------------
    # BET BUILDERS
    # --------------------------------------------------------

    if builders:

        message_parts.append(
            "━━━━━━━━━━━━━━━━━━━━"
        )

        message_parts.append(
            "🔗 <b>BET BUILDER</b>"
        )

        message_parts.append("")

        for builder in builders[:5]:

            time = clean_time(
                builder["time"]
            )

            message_parts.append(
                f"⚽ <b>{builder['home']} - "
                f"{builder['away']}</b>\n"
                f"🕐 {time}\n"
                f"🎯 <b>{builder['builder']}</b>"
            )

            message_parts.append("")

    message_parts.append(
        "━━━━━━━━━━━━━━━━━━━━"
    )

    message_parts.append(
        f"📊 Επιλογές: {len(final_picks)}"
    )

    message = "\n".join(message_parts)

    print()
    print(message.replace("<b>", "").replace("</b>", ""))

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if final_picks or builders:

        print()
        print("📲 ΑΠΟΣΤΟΛΗ TELEGRAM...")

        if send_telegram(message):

            print(
                "✅ Στάλθηκε επιτυχώς στο Telegram."
            )

        else:

            print(
                "❌ Δεν στάλθηκε στο Telegram."
            )

    else:

        print(
            "ℹ️ Δεν υπάρχει επιλογή για αποστολή."
        )

    print()
    print("=" * 72)
    print(
        f"SUMMARY | Events: {len(events)} | "
        f"Analysed: {len(results)} | "
        f"Picks: {len(final_picks)} | "
        f"Builders: {len(builders)}"
    )
    print("=" * 72)


if __name__ == "__main__":
    main()
