
def youth_or_non_target_fixture(event):
    """
    Keep the main scanner focused on senior men's football.
    This prevents expensive API calls on U20/U21/U19/W/youth fixtures.
    """
    texts = []

    for key in (
        "home",
        "away",
        "home_name",
        "away_name",
        "home_team",
        "away_team",
        "league_name",
    ):
        value = event.get(key)

        if isinstance(value, dict):
            value = value.get("name")

        if value:
            texts.append(str(value).lower())

    text = " ".join(texts)

    youth_name_block = (
        "u20", "u21", "u19", "u18", "u17", "u16",
        "u15", "u14",
        "youth", "junior", "women", "woman",
        "feminino", "femenino", "female",
        "girls", "girl"
    )

    # Common API-Football team-name convention:
    # "Team W" / "Team Women" for women's sides.
    name_tokens = set(text.replace("-", " ").split())

    if "w" in name_tokens:
        return True

    return any(term in text for term in youth_name_block)


import os
from pathlib import Path
import json
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

def load_env_file():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

load_env_file()

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

# API-Football response cache for the current scanner run.
# Prevents duplicate calls for the same endpoint.
API_RESPONSE_CACHE = {}
API_RATE_LIMITED = False

LEAGUE_CACHE = {}
API_CACHE = {}
PREDICTION_CACHE = {}
STATS_CACHE = {}
LINEUP_CACHE = {}

SQUAD_CACHE = {}
INJURY_CACHE = {}

def league_allowed(event):
    # API-Football fixture
    if event.get("_source") == "api-football":
        league_type = str(event.get("league_type") or "").strip().lower()
        league_name = str(event.get("league_name") or "").strip().lower()
        stage = str(event.get("stage") or "").strip().lower()
        stage_name = str(event.get("stage_name") or "").strip().lower()

        # If API-Football explicitly identifies a non-league competition, reject it.
        if league_type and league_type != "league":
            return False

        # Obvious cup/friendly competitions.
        blocked_names = (
            "cup",
            "trophy",
            "taça",
            "taca",
            "copa",
            "coupe",
            "friendly",
            "friendlies",
            "super cup",
            "league cup",
        )

        if any(x in league_name for x in blocked_names):
            return False

        # Knockout / qualification / playoff stages.
        # Normal rounds such as "Apertura - 9" remain allowed.
        blocked_stage_terms = (
            "qualification",
            "qualifying",
            "quarter-final",
            "quarter final",
            "semi-final",
            "semi final",
            "playoff",
            "play-offs",
            "play off",
            "knockout",
        )

        if any(x in stage or x in stage_name for x in blocked_stage_terms):
            return False

        return bool(league_name)

    # Existing BSD league filter
    league_id = event.get("league_id")

    if not league_id:
        return False

    stage = str(event.get("stage", "")).lower()
    stage_name = str(event.get("stage_name", "")).lower()

    blocked_stages = (
        "qualification",
        "qualifying",
        "quarter",
        "semi-final",
        "semifinal",
        "final",
        "playoff",
        "knockout",
    )

    if any(x in stage or x in stage_name for x in blocked_stages):
        return False

    if league_id not in LEAGUE_CACHE:
        data = api_get(f"{BSD_BASE}/leagues/{league_id}")
        if not data:
            return False
        LEAGUE_CACHE[league_id] = data

    league = LEAGUE_CACHE[league_id]
    name = str(league.get("name", "")).lower()

    blocked_names = (
        "cup",
        "trophy",
        "taça",
        "taca",
        "copa",
        "coupe",
        "friendly",
        "friendlies",
        "super cup",
        "league cup",
    )

    if any(x in name for x in blocked_names):
        return False

    return True

def api_get(url):
    if url in API_CACHE:
        return API_CACHE[url]

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {BSD_API_KEY}",
            "User-Agent": "FootballTips/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
            API_CACHE[url] = data
            return data

    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"⛔ API 429 RATE LIMIT — stopping this request:")
            print(f"   {url}")
            return None

        print(f"API ERROR: {url}")
        print(e)
        return None

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
                "User-Agent": "FootballTips/1.0",
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



# ============================================================
# API-FOOTBALL
# ============================================================

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_KEY = str(os.getenv("API_FOOTBALL_KEY", "")).strip()

API_FOOTBALL_CACHE = {}


def api_football_get(path):
    """
    API-Football request wrapper with:
    - per-run response cache
    - 429 circuit breaker
    - no repeated request for identical endpoint
    """
    global API_RATE_LIMITED

    if not path:
        return None

    # Once the API says 429, do NOT hammer it with hundreds more requests.
    if API_RATE_LIMITED:
        return None

    cache_key = str(path)

    if cache_key in API_RESPONSE_CACHE:
        return API_RESPONSE_CACHE[cache_key]

    url = API_FOOTBALL_BASE + path

    try:
        req = urllib.request.Request(
            url,
            headers={
                "x-apisports-key": API_FOOTBALL_KEY
            }
        )

        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)

        API_RESPONSE_CACHE[cache_key] = data
        return data

    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry_after = e.headers.get("Retry-After") if e.headers else None

            print("⛔ API-FOOTBALL 429 RATE LIMIT")
            if retry_after:
                print(f"   Retry-After: {retry_after}s")
            print(f"   Limited endpoint: {url}")

            # Do not permanently kill the whole scan.
            # Keep the existing cache intact and let the caller
            # decide whether this item can be skipped.
            return None

        print(f"API-FOOTBALL ERROR {e.code}: {url}")
        return None

    except Exception as e:
        print(f"API-FOOTBALL ERROR: {e}")
        return None

def get_api_football_today():
    """
    Get all today's fixtures from API-Football.
    Only League competitions are returned.
    """
    from datetime import timedelta

    now_cyprus = datetime.now()
    today = now_cyprus.strftime("%Y-%m-%d")
    tomorrow = (now_cyprus + timedelta(days=1)).strftime("%Y-%m-%d")

    # Scan window:
    # - today's fixtures
    # - tomorrow's early-morning fixtures (00:00-08:59 Cyprus)
    #
    # This allows the 09:00 scan to catch matches such as 03:00
    # that belong to the previous day's coupon.
    fixtures = []

    for fixture_date in (today, tomorrow):
        data = api_football_get(
            f"/fixtures?date={fixture_date}&timezone=Europe/Nicosia"
        )

        if not data or not isinstance(data, dict):
            continue

        response = data.get("response", [])
        if isinstance(response, list):
            fixtures.extend(response)

    result = []

    for item in fixtures:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        teams = item.get("teams") or {}

        # League only — no cups / friendlies / knockout competitions.
        # API-Football can return league.type as None on the fixtures endpoint,
        # so a missing type must NOT remove a valid league.
        league_type = str(league.get("type", "") or "").lower()
        league_name = str(league.get("name", "") or "").lower()
        league_round = str(league.get("round", "") or "").lower()

        # Reject youth/women competitions before adding fixtures
        # to the scanner queue. This prevents unnecessary processing.
        home = teams.get("home") or {}
        away = teams.get("away") or {}

        teams_text = " ".join([
            str(home.get("name", "") or "").lower(),
            str(away.get("name", "") or "").lower(),
            league_name,
        ])

        youth_women_terms = (
            "u20", "u21", "u19", "u18", "u17", "u16",
            "u15", "u14",
            "youth", "junior", "women", "woman",
            "feminino", "femenino", "female",
            "girls", "girl",
        )

        # API-Football commonly labels women's teams with a
        # standalone "W" suffix, e.g. "Atlante W".
        team_tokens = set(
            teams_text.replace("-", " ").split()
        )

        if "w" in team_tokens:
            continue

        if any(term in teams_text for term in youth_women_terms):
            continue

        blocked_names = (
            "cup",
            "trophy",
            "taça",
            "taca",
            "copa",
            "coupe",
            "friendly",
            "friendlies",
            "super cup",
            "league cup",
            "knockout",
        )

        blocked_rounds = (
            "qualification",
            "qualifying",
            "quarter-final",
            "quarter final",
            "semi-final",
            "semi final",
            "final",
            "playoff",
            "play-offs",
            "play off",
            "knockout",
        )

        if any(x in league_name for x in blocked_names):
            continue

        if any(x in league_round for x in blocked_rounds):
            continue

        # Reject an explicitly non-league type.
        # Empty/None type is allowed.
        if league_type and league_type != "league":
            continue

        home = teams.get("home") or {}
        away = teams.get("away") or {}

        if not home.get("id") or not away.get("id"):
            continue

        result.append({
            "id": fixture.get("id"),
            "event_date": fixture.get("date"),
            "start_time": fixture.get("date"),

            "league_id": league.get("id"),
            "league_name": league.get("name"),
            "league_type": league.get("type"),
            "stage": league.get("round") or "",
            "stage_name": league.get("round") or "",

            "home_team": {
                "id": home.get("id"),
                "name": home.get("name"),
            },

            "away_team": {
                "id": away.get("id"),
                "name": away.get("name"),
            },

            "_source": "api-football",
            "_api_football_fixture_id": fixture.get("id"),
        })

    return result


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


def get_fixture_unavailable(fixture_id, home_id=None, away_id=None):
    key = f"af_injuries_{fixture_id}"

    if key in INJURY_CACHE:
        return INJURY_CACHE[key]

    data = api_football_get(f"/injuries?fixture={fixture_id}")

    home_count = 0
    away_count = 0

    if data and isinstance(data, dict):
        rows = data.get("response") or []

        for row in rows:
            if not isinstance(row, dict):
                continue

            team = row.get("team") or {}
            team_id = team.get("id")

            if not team_id:
                continue

            if home_id and team_id == home_id:
                home_count += 1
            elif away_id and team_id == away_id:
                away_count += 1

    result = {
        "home": home_count,
        "away": away_count,
        "total": home_count + away_count,
    }

    INJURY_CACHE[key] = result
    return result


def get_lineups(event_id):
    key = f"af_lineups_{event_id}"

    if key in LINEUP_CACHE:
        return LINEUP_CACHE[key]

    data = api_football_get(f"/fixtures/lineups?fixture={event_id}")

    if not data or not isinstance(data, dict):
        result = {"lineup_status": "unknown"}
        LINEUP_CACHE[key] = result
        return result

    rows = data.get("response") or []

    if not rows:
        result = {"lineup_status": "unknown"}
        LINEUP_CACHE[key] = result
        return result

    # API-Football lineups are normally published shortly before kickoff.
    result = {
        "lineup_status": "confirmed",
        "response": rows,
    }

    LINEUP_CACHE[key] = result
    return result


def get_event_stats(event_id):
    key = f"af_stats_{event_id}"

    if key in STATS_CACHE:
        return STATS_CACHE[key]

    data = api_football_get(f"/fixtures/statistics?fixture={event_id}")

    if not data or not isinstance(data, dict):
        STATS_CACHE[key] = None
        return None

    rows = data.get("response") or []

    result = {
        "response": rows,
        "_api_football": True,
    }

    # Extract expected goals when available.
    xg_values = []

    for team_block in rows:
        for stat in team_block.get("statistics") or []:
            name = str(stat.get("type", "")).lower()

            if name in (
                "expected goals",
                "expected_goals",
                "xg",
            ):
                value = safe_float(stat.get("value"))

                if value is not None:
                    xg_values.append(value)

    if xg_values:
        result["xg"] = sum(xg_values)

    STATS_CACHE[key] = result
    return result


def prediction_value(prediction, market):
    if not prediction:
        return None

    value = prediction.get(market)

    if value is None:
        aliases = {
            "OVER 2.5": ("over25", "over_25"),
            "OVER 3.5": ("over35", "over_35"),
            "GG": ("btts", "BTTS"),
        }

        for alias in aliases.get(market, ()):
            value = prediction.get(alias)
            if value is not None:
                break

    return safe_float(value)


def get_odds(event_id, market):
    data = api_football_get(f"/odds?fixture={event_id}")

    if not data:
        return None

    response = data.get("response") or []

    if not response:
        return None

    target_market = str(market or "").upper()

    # API-Football structure:
    # response[]
    #   -> bookmakers[]
    #       -> bookmaker
    #       -> bets[]
    for fixture_data in response:
        bookmakers = fixture_data.get("bookmakers") or []

        if not bookmakers:
            continue

        # Prefer Bet365, then fall back to the first bookmaker.
        ordered_bookmakers = sorted(
            bookmakers,
            key=lambda b: (
                0 if str(b.get("name", "")).strip().lower() == "bet365" else 1
            )
        )

        for bookmaker in ordered_bookmakers:
            bookmaker_name = str(bookmaker.get("name", "")).strip()
            bets = bookmaker.get("bets") or []

            for bet in bets:
                bet_name = str(bet.get("name", "")).strip().lower()
                values = bet.get("values") or []

                # OVER 2.5
                if target_market == "OVER 2.5":
                    market_match = (
                        "over/under" in bet_name
                        or "goals over/under" in bet_name
                        or "total goals" in bet_name
                    )

                    if not market_match:
                        continue

                    for value in values:
                        value_name = str(value.get("value", "")).strip().lower()

                        if value_name in ("over 2.5", "o 2.5", "over2.5"):
                            odd = safe_float(value.get("odd"))
                            if odd is not None:
                                return {
                                    "odds": odd,
                                    "movement": None,
                                    "bookmaker": bookmaker_name,
                                }

                # OVER 3.5
                elif target_market == "OVER 3.5":
                    market_match = (
                        "over/under" in bet_name
                        or "goals over/under" in bet_name
                        or "total goals" in bet_name
                    )

                    if not market_match:
                        continue

                    for value in values:
                        value_name = str(value.get("value", "")).strip().lower()

                        if value_name in ("over 3.5", "o 3.5", "over3.5"):
                            odd = safe_float(value.get("odd"))
                            if odd is not None:
                                return {
                                    "odds": odd,
                                    "movement": None,
                                    "bookmaker": bookmaker_name,
                                }

                # GG / BTTS
                elif target_market == "GG":
                    if (
                        "both teams to score" not in bet_name
                        and "both teams score" not in bet_name
                        and "btts" not in bet_name
                    ):
                        continue

                    for value in values:
                        value_name = str(value.get("value", "")).strip().lower()

                        if value_name in ("yes", "gg"):
                            odd = safe_float(value.get("odd"))
                            if odd is not None:
                                return {
                                    "odds": odd,
                                    "movement": None,
                                    "bookmaker": bookmaker_name,
                                }

    return None


def recent_six_signal(market, home_form, away_form):
    """
    Last-6 form signal:
    4/6 = base signal
    5/6 = strong signal
    6/6 = maximum signal
    """

    if not home_form or not away_form:
        return 0

    hs = home_form.get("home_split") or home_form
    aws = away_form.get("away_split") or away_form

    if market == "OVER 2.5":
        h_count = int(hs.get("over25_count", 0) or 0)
        a_count = int(aws.get("over25_count", 0) or 0)

    elif market == "OVER 3.5":
        h_count = int(hs.get("over35_count", 0) or 0)
        a_count = int(aws.get("over35_count", 0) or 0)

    elif market == "GG":
        h_count = int(round((hs.get("btts_rate", 0) or 0) * 6 / 100))
        a_count = int(round((aws.get("btts_rate", 0) or 0) * 6 / 100))

    else:
        return 0

    def level(n):
        if n >= 6:
            return 3
        if n >= 5:
            return 2
        if n >= 4:
            return 1
        return 0

    h_level = level(h_count)
    a_level = level(a_count)

    # Both teams confirm the signal
    if h_level and a_level:
        return (h_level + a_level) * 4

    # One team confirms it
    return max(h_level, a_level) * 2


def attack_defense_score(market, home_form, away_form):
    if not home_form or not away_form:
        return 0

    h_attack = safe_float(home_form.get("avg_goals_for")) or 0
    h_defense = safe_float(home_form.get("avg_goals_against")) or 0

    a_attack = safe_float(away_form.get("avg_goals_for")) or 0
    a_defense = safe_float(away_form.get("avg_goals_against")) or 0

    home_signal = 0
    away_signal = 0

    # Strong home attack vs weak away defense
    if h_attack >= 1.60 and a_defense >= 1.40:
        home_signal += 1
    if h_attack >= 1.80 and a_defense >= 1.60:
        home_signal += 1

    # Strong away attack vs weak home defense
    if a_attack >= 1.60 and h_defense >= 1.40:
        away_signal += 1
    if a_attack >= 1.80 and h_defense >= 1.60:
        away_signal += 1

    if market == "OVER 2.5":
        return (home_signal + away_signal) * 6

    if market == "OVER 3.5":
        return (home_signal + away_signal) * 7

    if market == "GG":
        if home_signal >= 1 and away_signal >= 1:
            return 14
        if home_signal >= 1 or away_signal >= 1:
            return 5

    return 0


def score_market(
    market,
    probability,
    odds,
    movement,
    xg,
    confidence,
    unavailable,
    home_form,
    away_form,
    lineup_status
):
    # ============================================================
    # NORMALIZED MARKET SCORE — 0..100
    # ============================================================

    score = 50.0

    forms = [
        f for f in (home_form, away_form)
        if f and f.get("games", 0) >= 3
    ]

    if not forms:
        return 0

    def rate(f, key):
        return float(f.get(key, 0) or 0)

    def gf(f):
        return float(f.get("avg_goals_for", 0) or 0)

    def ga(f):
        return float(f.get("avg_goals_against", 0) or 0)

    avg_total = sum(
        float(f.get("avg_total_goals", 0) or 0)
        for f in forms
    ) / len(forms)

    avg_o25 = sum(
        rate(f, "over25_rate")
        for f in forms
    ) / len(forms)

    avg_o35 = sum(
        rate(f, "over35_rate")
        for f in forms
    ) / len(forms)

    avg_btts = sum(
        rate(f, "btts_rate")
        for f in forms
    ) / len(forms)

    min_o25 = min(rate(f, "over25_rate") for f in forms)
    min_o35 = min(rate(f, "over35_rate") for f in forms)
    min_btts = min(rate(f, "btts_rate") for f in forms)

    avg_gf = sum(gf(f) for f in forms) / len(forms)
    avg_ga = sum(ga(f) for f in forms) / len(forms)

    # ------------------------------------------------------------
    # 1. MARKET-SPECIFIC RECENT FORM — biggest component
    # ------------------------------------------------------------

    if market == "OVER 2.5":
        form_strength = (
            min_o25 * 0.28
            + avg_o25 * 0.12
            + min(avg_total / 3.50, 1.0) * 15
        )

    elif market == "OVER 3.5":
        form_strength = (
            min_o35 * 0.30
            + avg_o35 * 0.15
            + min(avg_total / 4.20, 1.0) * 12
        )

    else:  # GG
        form_strength = (
            min_btts * 0.25
            + avg_btts * 0.15
            + min(avg_gf / 2.00, 1.0) * 12
        )

    score += min(form_strength, 45)

    # ------------------------------------------------------------
    # 2. ATTACK / DEFENCE PROFILE
    # ------------------------------------------------------------

    if market in ("OVER 2.5", "OVER 3.5"):
        attack_signal = min((avg_gf + avg_ga) / 3.50, 1.0) * 10

        if market == "OVER 3.5":
            attack_signal = min((avg_gf + avg_ga) / 4.00, 1.0) * 10

        score += attack_signal

    else:
        gg_attack = min(avg_gf / 1.50, 1.0) * 8
        gg_defence = min(avg_ga / 1.30, 1.0) * 6
        score += gg_attack + gg_defence

    # Existing attack/defence model remains part of the score.
    try:
        ad_signal = attack_defense_score(
            market,
            home_form,
            away_form
        )
        score += max(-5, min(8, float(ad_signal)))
    except Exception:
        pass

    # ------------------------------------------------------------
    # 3. xG — strong confirmation when available
    # ------------------------------------------------------------

    if xg is not None:
        try:
            xg = float(xg)

            if market == "OVER 2.5":
                if xg >= 3.40:
                    score += 15
                elif xg >= 3.10:
                    score += 12
                elif xg >= 2.90:
                    score += 9
                elif xg >= 2.70:
                    score += 5
                elif xg < 2.40:
                    score -= 5

            elif market == "OVER 3.5":
                if xg >= 4.00:
                    score += 15
                elif xg >= 3.60:
                    score += 12
                elif xg >= 3.30:
                    score += 9
                elif xg >= 3.00:
                    score += 5
                elif xg < 2.70:
                    score -= 6

            else:
                if xg >= 3.20:
                    score += 14
                elif xg >= 2.90:
                    score += 11
                elif xg >= 2.60:
                    score += 8
                elif xg >= 2.30:
                    score += 4
                elif xg < 2.10:
                    score -= 5

        except Exception:
            pass

    # ------------------------------------------------------------
    # 4. MODEL PROBABILITY
    # ------------------------------------------------------------

    if probability is not None:
        try:
            prob = float(probability)

            if prob >= 75:
                score += 8
            elif prob >= 68:
                score += 6
            elif prob >= 62:
                score += 4
            elif prob >= 57:
                score += 2
            elif prob < 50:
                score -= 4

        except Exception:
            pass

    # ------------------------------------------------------------
    # 5. ODDS MOVEMENT / VALUE SIGNAL
    # ------------------------------------------------------------

    if movement == "SHORTENING":
        score += 4
    elif movement == "DRIFTING":
        score -= 3

    # ------------------------------------------------------------
    # 6. MODEL CONFIDENCE
    # ------------------------------------------------------------

    if confidence is not None:
        try:
            conf = float(confidence)

            if conf >= 0.75:
                score += 5
            elif conf >= 0.68:
                score += 4
            elif conf >= 0.60:
                score += 2
            elif conf < 0.50:
                score -= 3

        except Exception:
            pass

    # ------------------------------------------------------------
    # 7. ABSENCES / LINEUPS
    # ------------------------------------------------------------

    try:
        if unavailable >= 4:
            if market in ("OVER 2.5", "OVER 3.5"):
                score += 2
            else:
                score -= 2
        elif unavailable >= 2:
            score += 1
    except Exception:
        pass

    if str(lineup_status).lower() == "confirmed":
        score += 2

    # ------------------------------------------------------------
    # 8. EXISTING 4/6 → 5/6 → 6/6 SIGNAL
    # ------------------------------------------------------------

    try:
        recent_signal = float(
            recent_six_signal(
                market,
                home_form,
                away_form
            )
        )

        # Keep the existing signal, but prevent it from dominating.
        score += max(-5, min(10, recent_signal))

    except Exception:
        pass

    # ------------------------------------------------------------
    # FINAL NORMALIZATION
    # ------------------------------------------------------------

    # Convert the raw score to a realistic 0-100 range
    # without saturating strong candidates at 100.
    try:
        raw_score = float(score)

        # Raw scoring is normally centered around ~70-90.
        # Keep meaningful separation between candidates.
        normalized = 50.0 + (raw_score - 70.0) * 0.75

    except Exception:
        normalized = 0.0

    return max(0, min(100, round(normalized)))



def make_bet_builder(markets):
    over25 = markets.get("OVER 2.5")
    gg = markets.get("GG")
    if not over25 or not gg:
        return None
    if over25["score"] >= 55 and gg["score"] >= 50:
        return {"text": "Over 2.5 + GG", "score": int((over25["score"] + gg["score"]) / 2)}
    return None


def get_recent_form(team_id):
    # One in-memory result per team for the entire scan.
    # This is intentionally kept simple: no changes to the
    # 4/6 calculation or to the API endpoint.
    key = f"af_form_{team_id}"

    if key in FORM_CACHE:
        return FORM_CACHE[key]

    data = api_football_get(
        f"/fixtures?team={team_id}&last=6"
    )

    if not data or not isinstance(data, dict):
        FORM_CACHE[key] = None
        return None

    rows = data.get("response") or []

    completed = []

    for item in rows:
        fixture = item.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short")

        if status not in (
            "FT",
            "AET",
            "PEN",
        ):
            continue

        completed.append(item)

    completed = completed[:6]

    if len(completed) < 6:
        FORM_CACHE[key] = None
        return None

    def calc(matches, team_id_value, home_only=False, away_only=False):
        gf = ga = o25 = o35 = btts = 0
        games = 0

        for item in matches:
            teams = item.get("teams") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}

            if home_only and home.get("id") != team_id_value:
                continue

            if away_only and away.get("id") != team_id_value:
                continue

            if home.get("id") != team_id_value and away.get("id") != team_id_value:
                continue

            goals = item.get("goals") or {}
            hg = goals.get("home")
            ag = goals.get("away")

            if hg is None or ag is None:
                continue

            hg = int(hg)
            ag = int(ag)

            if home.get("id") == team_id_value:
                team_for = hg
                team_against = ag
            else:
                team_for = ag
                team_against = hg

            total = hg + ag

            gf += team_for
            ga += team_against
            o25 += total >= 3
            o35 += total >= 4
            btts += hg >= 1 and ag >= 1
            games += 1

        if games == 0:
            return None

        return {
            "games": games,
            "avg_goals_for": gf / games,
            "avg_goals_against": ga / games,
            "avg_total_goals": (gf + ga) / games,
            "over25_rate": (o25 / games) * 100,
            "over25_count": o25,
            "over35_rate": (o35 / games) * 100,
            "over35_count": o35,
            "btts_rate": (btts / games) * 100,
        }

    # Use ONLY the team's six most recent completed matches,
    # regardless of whether they were home or away.
    overall = calc(completed, team_id)

    if not overall or overall.get("games") < 6:
        FORM_CACHE[key] = None
        return None

    # Keep compatibility with the existing scoring code.
    # Both references intentionally point to the same overall last-6 sample.
    overall["home_split"] = overall
    overall["away_split"] = overall

    FORM_CACHE[key] = overall
    return overall


def process_event(event):
    # Reject youth/women/non-target fixtures BEFORE any expensive API-Football calls.
    if youth_or_non_target_fixture(event):
        return None

    if not league_allowed(event):
        return None

    event_id = event.get("id")

    home_obj = event.get("home_team")
    away_obj = event.get("away_team")

    home = get_name(home_obj)
    away = get_name(away_obj)

    home_id = (
        home_obj.get("id")
        if isinstance(home_obj, dict)
        else event.get("home_team_id")
    )

    away_id = (
        away_obj.get("id")
        if isinstance(away_obj, dict)
        else event.get("away_team_id")
    )

    home_id = home_id or event.get("home_team_id")
    away_id = away_id or event.get("away_team_id")

    event_date = event.get("event_date") or event.get("start_time")

    # API-Football fixture
    # API-Football /predictions disabled: it does not provide
    # market probabilities for O2.5/O3.5/GG and causes 429 rate limits.
    prediction = {}
    # API-Football predictions are optional.
    # Market probabilities are not required for scoring.
    if not prediction:
        prediction = {}

    confidence = safe_float(
        prediction.get("model", {}).get("confidence")
    )

    # ---------------------------------------------------------
    # STAGE 1: Recent form first
    # ---------------------------------------------------------
    home_form = get_recent_form(home_id)
    away_form = get_recent_form(away_id)

    if not home_form or not away_form:
        print(f"   ↳ FILTER: insufficient recent form")
        return None

    # ---------------------------------------------------------
    # STAGE 2: Odds + cheap form screening
    # ---------------------------------------------------------
    markets = {}

    # First evaluate ONLY the Over markets.
    # GG is secondary and must never consume an API request
    # before an Over market has independently qualified.
    for market in ("OVER 2.5", "OVER 3.5"):
        probability = prediction_value(prediction, market)

        odds_data = get_odds(event_id, market)

        if not odds_data or odds_data.get("odds") is None:
            continue

        markets[market] = {
            "probability": probability,
            "odds": odds_data["odds"],
            "movement": odds_data.get("movement"),
        }

    # Do NOT return here.
    # GG is evaluated independently after the cheap form screen.
    # A market may be added later.

    # Keep the existing strict filters, but avoid expensive API calls
    # when the recent-form profile is clearly unsuitable.
    h_total = safe_float(home_form.get("avg_total_goals")) or 0
    a_total = safe_float(away_form.get("avg_total_goals")) or 0

    h_o25 = int(home_form.get("over25_count", 0) or 0)
    a_o25 = int(away_form.get("over25_count", 0) or 0)

    h_o35 = int(home_form.get("over35_count", 0) or 0)
    a_o35 = int(away_form.get("over35_count", 0) or 0)

    h_btts = safe_float(home_form.get("btts_rate")) or 0
    a_btts = safe_float(away_form.get("btts_rate")) or 0

    h_gf = safe_float(home_form.get("avg_goals_for")) or 0
    a_gf = safe_float(away_form.get("avg_goals_for")) or 0

    basic_candidate = (
        (
            "OVER 2.5" in markets
            and h_o25 >= 4
            and a_o25 >= 4
        )
        or
        (
            "OVER 3.5" in markets
            and h_o35 >= 4
            and a_o35 >= 4
        )
    )

    # GG is an INDEPENDENT market.
    gg_candidate = (
        h_btts >= 55
        and a_btts >= 55
        and h_gf >= 1.10
        and a_gf >= 1.10
    )

    # Relaxed Builder candidate.
    # This lets additional matches reach select_picks(),
    # where the separate Builder sensor decides whether they
    # qualify for OVER + GG.
    builder_candidate = (
        (
            h_o25 >= 3
            and a_o25 >= 3
        )
        or
        (
            h_o35 >= 3
            and a_o35 >= 3
        )
    ) and (
        h_btts >= 50
        and a_btts >= 50
        and h_gf >= 1.00
        and a_gf >= 1.00
    )

    if not basic_candidate and not gg_candidate and not builder_candidate:
        print(
            f"   ↳ FILTER: no strict Main or relaxed Builder candidate"
        )
        return None

    # GG odds are requested only after the historical-form
    # filters have produced a genuine candidate.
    if gg_candidate:
        probability = prediction_value(prediction, "GG")
        odds_data = get_odds(event_id, "GG")

        if odds_data and odds_data.get("odds") is not None:
            markets["GG"] = {
                "probability": probability,
                "odds": odds_data["odds"],
                "movement": odds_data.get("movement"),
            }

    # ---------------------------------------------------------
    # STAGE 3: Expensive statistics / xG only for candidates
    # ---------------------------------------------------------
    stats = get_event_stats(event_id)
    xg = extract_xg(stats, prediction)

    # xG is optional because API-Football statistics do not provide
    # xG for every fixture. Other strict filters remain mandatory.
    if xg is None:
        xg = None

    # ---------------------------------------------------------
    # STAGE 4: Injuries only for candidates
    # ---------------------------------------------------------
    fixture_unavailable = get_fixture_unavailable(
        event_id,
        home_id,
        away_id,
    )

    home_unavailable = fixture_unavailable["home"]
    away_unavailable = fixture_unavailable["away"]
    unavailable_total = fixture_unavailable["total"]

    # ---------------------------------------------------------
    # STAGE 5: Lineups only for candidates
    # ---------------------------------------------------------
    lineup = get_lineups(event_id)

    if isinstance(lineup, dict):
        lineup_status = (
            lineup.get("lineup_status")
            or lineup.get("status")
            or "unknown"
        )
    else:
        lineup_status = "unknown"

    # Calculate final scores using the existing scoring engine.
    for market in list(markets):
        probability = prediction_value(prediction, market)

        odds_data = markets[market]

        score = score_market(
            market,
            probability,
            odds_data["odds"],
            odds_data.get("movement"),
            xg,
            confidence,
            unavailable_total,
            home_form,
            away_form,
            lineup_status,
        )

        markets[market]["score"] = score

    if not markets:
        return None

    return {
        "event_id": event_id,
        "home": home,
        "away": away,
        "home_team": home,
        "away_team": away,
        "time": event_date,
        "xg": xg,
        "confidence": confidence,
        "home_unavailable": home_unavailable,
        "away_unavailable": away_unavailable,
        "lineup_status": lineup_status,
        "home_form": home_form,
        "away_form": away_form,
        "markets": markets,
        "league_name": event.get("league_name"),
        "_source": event.get("_source", "api-football"),
    }




def save_picks_to_history(selection):
    """Save the exact Main + Builder picks as PENDING history entries."""
    from pathlib import Path
    import json

    path = Path("docs/history.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        history = []

    if not isinstance(history, list):
        history = []

    existing_keys = {
        str(item.get("key"))
        for item in history
        if isinstance(item, dict)
    }

    def add_item(result, market):
        if not isinstance(result, dict):
            return

        event_id = (
            result.get("event_id")
            or result.get("id")
            or result.get("fixture_id")
        )

        if event_id is None:
            return

        home = result.get("home", "")
        away = result.get("away", "")
        kickoff = result.get("time", "")

        # Keep the existing History date/time structure.
        display_date = ""
        display_time = ""

        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            dt = datetime.fromisoformat(
                str(kickoff).replace("Z", "+00:00")
            )

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))

            local_dt = dt.astimezone(ZoneInfo("Europe/Nicosia"))
            display_date = local_dt.strftime("%Y-%m-%d")
            display_time = local_dt.strftime("%H:%M")
        except Exception:
            raw = str(kickoff)
            if len(raw) >= 5 and raw[2] == ":":
                display_time = raw[:5]
            display_date = raw[:10] if len(raw) >= 10 else ""

        key = f"{event_id}|{market}|{kickoff}"

        if key in existing_keys:
            return

        odds = None

        markets = result.get("markets") or {}
        market_data = markets.get(market) or {}

        if isinstance(market_data, dict):
            odds = (
                market_data.get("odds")
                or market_data.get("odd")
            )

        if odds is None:
            odds = result.get("odds")

        history.append({
            "key": key,
            "event_id": event_id,
            "date": display_time,
            "kickoff": kickoff,
            "home": home,
            "away": away,
            "market": market,
            "odds": odds,
            "status": "PENDING",
        })

        existing_keys.add(key)

    # MAIN picks
    for item in selection.get("main") or []:
        result = item.get("result") or item
        market = item.get("main_market") or item.get("market")

        if market in ("OVER 2.5", "OVER 3.5", "GG"):
            add_item(result, market)

    # BET BUILDER picks
    for item in selection.get("builders") or []:
        result = item.get("result") or item
        builder_markets = item.get("builder_markets") or []

        if "GG" not in builder_markets:
            continue

        if "OVER 3.5" in builder_markets:
            market = "OVER 3.5 + GG"
        elif "OVER 2.5" in builder_markets:
            market = "OVER 2.5 + GG"
        else:
            continue

        add_item(result, market)

    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def select_picks(results):
    """
    MAIN:
      - All strict qualified matches.
      - One market only per match.

    BET BUILDER:
      - Separate relaxed sensor.
      - Uses only matches NOT in MAIN.
      - Each match gets exactly:
          OVER 2.5 + GG
          OR
          OVER 3.5 + GG
      - No artificial limit on number of Builder matches.
    """

    qualified = []

    priority = {
        "OVER 3.5": 3,
        "OVER 2.5": 2,
        "GG": 1,
    }

    # =====================================================
    # MAIN — STRICT QUALIFICATION
    # =====================================================

    for result in results:
        hf = result.get("home_form") or {}
        af = result.get("away_form") or {}

        if hf.get("games", 0) < 6 or af.get("games", 0) < 6:
            continue

        h_o25 = hf.get("over25_count", 0)
        a_o25 = af.get("over25_count", 0)

        h_o35 = hf.get("over35_count", 0)
        a_o35 = af.get("over35_count", 0)

        h_btts = hf.get("btts_rate", 0)
        a_btts = af.get("btts_rate", 0)

        h_gf = hf.get("avg_goals_for", 0)
        a_gf = af.get("avg_goals_for", 0)

        qualified_markets = {}

        # OVER 2.5 — both teams 4/6
        if h_o25 >= 4 and a_o25 >= 4:
            try:
                score = float(
                    (result.get("markets") or {})
                    .get("OVER 2.5", {})
                    .get("score", 0)
                )
            except Exception:
                score = 0

            qualified_markets["OVER 2.5"] = score

        # OVER 3.5 — both teams 4/6
        if h_o35 >= 4 and a_o35 >= 4:
            try:
                score = float(
                    (result.get("markets") or {})
                    .get("OVER 3.5", {})
                    .get("score", 0)
                )
            except Exception:
                score = 0

            qualified_markets["OVER 3.5"] = score

        # GG — independent qualification
        if (
            h_btts >= 55
            and a_btts >= 55
            and h_gf >= 1.10
            and a_gf >= 1.10
        ):
            try:
                score = float(
                    (result.get("markets") or {})
                    .get("GG", {})
                    .get("score", 0)
                )
            except Exception:
                score = 0

            qualified_markets["GG"] = score

        if not qualified_markets:
            continue

        # One market only for Main.
        best_market = max(
            qualified_markets,
            key=lambda m: (
                float(qualified_markets.get(m, 0)),
                priority.get(m, 0),
            )
        )

        item = dict(result)
        item["market"] = best_market
        item["score"] = qualified_markets[best_market]
        item["qualified_markets"] = qualified_markets

        qualified.append(item)

    # Highest quality first.
    qualified.sort(
        key=lambda x: float(x.get("score", 0)),
        reverse=True
    )

    # =====================================================
    # MAIN — ALL QUALIFIED, NO LIMIT
    # =====================================================

    main_matches = []

    for q in qualified:
        main_matches.append({
            "result": q,
            "main_market": q.get("market", ""),
            "main_data": {
                "score": q.get("score", 0),
            },
            "score": q.get("score", 0),
            "time": q.get("time", ""),
        })

    # Main fixture IDs.
    reserved = {
        str(
            x.get("event_id")
            or x.get("id")
            or x.get("fixture_id")
        )
        for x in qualified
    }

    # =====================================================
    # BET BUILDER — RELAXED SENSOR
    #
    # IMPORTANT:
    # Main is strict. Builder is separate so that it can
    # find additional games without duplicating Main.
    # =====================================================

    builder_candidates = []

    for result in results:
        fixture_id = str(
            result.get("event_id")
            or result.get("id")
            or result.get("fixture_id")
        )

        if fixture_id in reserved:
            continue

        hf = result.get("home_form") or {}
        af = result.get("away_form") or {}

        if hf.get("games", 0) < 6 or af.get("games", 0) < 6:
            continue

        h_o25 = hf.get("over25_count", 0)
        a_o25 = af.get("over25_count", 0)

        h_o35 = hf.get("over35_count", 0)
        a_o35 = af.get("over35_count", 0)

        h_btts = hf.get("btts_rate", 0)
        a_btts = af.get("btts_rate", 0)

        h_gf = hf.get("avg_goals_for", 0)
        a_gf = af.get("avg_goals_for", 0)

        # Relaxed Builder requirements.
        over_market = None

        if h_o35 >= 3 and a_o35 >= 3:
            over_market = "OVER 3.5"
        elif h_o25 >= 3 and a_o25 >= 3:
            over_market = "OVER 2.5"

        if not over_market:
            continue

        # GG must also have supporting evidence.
        if not (
            h_btts >= 50
            and a_btts >= 50
            and h_gf >= 1.00
            and a_gf >= 1.00
        ):
            continue

        markets = result.get("markets") or {}

        try:
            over_score = float(
                (markets.get(over_market) or {}).get("score", 0)
            )
        except Exception:
            over_score = 0

        try:
            gg_score = float(
                (markets.get("GG") or {}).get("score", 0)
            )
        except Exception:
            gg_score = 0

        builder_item = dict(result)

        builder_item["builder_markets"] = [
            over_market,
            "GG",
        ]

        builder_item["builder_score"] = (
            over_score + gg_score
        ) / 2.0

        builder_candidates.append(builder_item)

    # Best Builder games first, with NO LIMIT.
    builder_candidates.sort(
        key=lambda x: float(x.get("builder_score", 0)),
        reverse=True
    )

    return {
        "main": main_matches,
        "builders": builder_candidates,
    }


def main():
    print("=" * 72)
    print("⚽ FOOTBALL TIPS SCANNER V9.3")
    print("=" * 72)

    events = get_api_football_today()
    print(f"\nAPI-FOOTBALL ΑΓΩΝΕΣ ΣΗΜΕΡΑ: {len(events)}")

    if not events:
        print("❌ Δεν βρέθηκαν αγώνες.")
        return

    # =====================================================
    # SCAN TIME WINDOW — CYPRUS TIME
    #
    # 09:00 scan -> today 09:00 through tomorrow 08:59
    # 17:00 scan -> today 17:00 through tomorrow 08:59
    #
    # Never process a fixture that has already started.
    # =====================================================
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    cyprus_tz = ZoneInfo("Europe/Nicosia")
    now_cyprus = datetime.now(cyprus_tz)

    # Scheduled scan anchor:
    # before 17:00 => morning window starts at 09:00
    # 17:00+     => evening window starts at 17:00
    if now_cyprus.hour < 17:
        window_start = now_cyprus.replace(
            hour=9, minute=0, second=0, microsecond=0
        )
    else:
        window_start = now_cyprus.replace(
            hour=17, minute=0, second=0, microsecond=0
        )

    # Both daily scans include fixtures until 05:00 Cyprus
    # of the following day.
    next_day = window_start.date() + timedelta(days=1)
    window_end = datetime.combine(
        next_day,
        datetime.min.time(),
        tzinfo=cyprus_tz
    ).replace(hour=5)

    filtered_events = []

    for event in events:
        event_date = event.get("event_date") or event.get("start_time")

        try:
            fixture_dt = datetime.fromisoformat(
                str(event_date).replace("Z", "+00:00")
            )

            if fixture_dt.tzinfo is None:
                fixture_dt = fixture_dt.replace(tzinfo=cyprus_tz)

            fixture_dt = fixture_dt.astimezone(cyprus_tz)

        except Exception:
            continue

        # Must be inside the current scan window.
        if fixture_dt < window_start or fixture_dt >= window_end:
            continue

        # Never show a match that has already started.
        if fixture_dt <= now_cyprus:
            continue

        filtered_events.append(event)

    events = filtered_events

    print(
        f"🕘 SCAN WINDOW: "
        f"{window_start.strftime('%d/%m %H:%M')} → "
        f"{window_end.strftime('%d/%m %H:%M')} Cyprus"
    )
    print(f"📦 FIXTURES AFTER DATE WINDOW: {len(events)}")
    print(f"⏭️ UPCOMING FIXTURES: {len(events)}")

    results = []

    for i, event in enumerate(events, 1):
        home = get_name(event.get("home_team"))
        away = get_name(event.get("away_team"))

        print(f"[{i}/{len(events)}] {home} - {away}")

        try:
            result = process_event(event)
            if result:
                results.append(result)
        except Exception as e:
            print(f"⚠️ Error στο {home} - {away}: {e}")

    selection = select_picks(results)
    save_picks_to_history(selection)

    picks = selection.get("main") or []

    # Chronological order — Cyprus time
    def _pick_time(x):
        t = str(x.get("time", "23:59"))
        try:
            h, m = t[:5].split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return 1439

    picks = sorted(picks, key=_pick_time)

    builders = selection.get("builders") or []

    parts = [
        "🔥 <b>FOOTBALL TIPS</b>",
        "📅 Σημερινές επιλογές — ώρα Κύπρου",
        ""
    ]

    if not picks:
        parts.append(
            "❌ Σήμερα δεν βρέθηκαν επιλογές που να περνούν τα φίλτρα."
        )

    else:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        cyprus_tz = ZoneInfo("Europe/Nicosia")

        # =====================================================
        # MAIN COUPON
        # ONE MATCH = ONE MARKET ONLY
        # =====================================================

        for item in picks:
            result = item.get("result") or {}

            home = result.get("home", "")
            away = result.get("away", "")
            event_time = result.get("time", "")
            xg = result.get("xg")

            market = item.get("main_market", "")
            data = item.get("main_data") or {}

            try:
                score = int(float(data.get("score", 0) or 0))
            except Exception:
                score = int(item.get("score", 0) or 0)

            display_time = event_time

            try:
                dt = datetime.fromisoformat(
                    str(event_time).replace("Z", "+00:00")
                )

                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                display_time = dt.astimezone(
                    cyprus_tz
                ).strftime("%H:%M")
            except Exception:
                pass

            parts.append(f"⚽ {home} 🆚 {away}")
            parts.append(f"🕘 {display_time}")
            parts.append(f"🎯 {market}")
            parts.append(f"📊 Score: {score}/100")

            if xg is not None:
                try:
                    parts.append(f"🧠 xG: {float(xg):.2f}")
                except Exception:
                    parts.append(f"🧠 xG: {xg}")

            parts.append("")

        # =====================================================
        # SEPARATE BET BUILDER
        # 2+ DIFFERENT MATCHES
        # Each match = OVER 2.5 + GG OR OVER 3.5 + GG
        # Main coupon matches are excluded.
        # =====================================================

        if builders:
            parts += [
                "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦",
                "🔥 <b>BET BUILDER</b>",
                "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦",
                ""
            ]

            main_fixture_ids = set()

            for main_item in picks:
                main_result = main_item.get("result") or {}
                fid = (
                    main_result.get("id")
                    or main_result.get("fixture_id")
                )
                if fid is not None:
                    main_fixture_ids.add(str(fid))

            builder_count = 0
            builder_fixture_ids = set()

            for builder in builders:
                builder_result = builder.get("result") or builder

                fid = (
                    builder_result.get("event_id")
                    or builder_result.get("id")
                    or builder_result.get("fixture_id")
                )

                if fid is not None:
                    fid_str = str(fid)

                    # Never use a Main coupon match in Builder.
                    if fid_str in main_fixture_ids:
                        continue

                    # Never repeat the same Builder match.
                    if fid_str in builder_fixture_ids:
                        continue

                    builder_fixture_ids.add(fid_str)

                builder_markets = builder.get("builder_markets") or []

                if "GG" not in builder_markets:
                    continue

                if "OVER 3.5" in builder_markets:
                    over_market = "OVER 3.5"
                elif "OVER 2.5" in builder_markets:
                    over_market = "OVER 2.5"
                else:
                    continue

                home = builder_result.get("home", "")
                away = builder_result.get("away", "")

                # Convert fixture timestamp to Cyprus local time.
                event_time = ""
                raw_time = builder_result.get("time", "")
                try:
                    from datetime import datetime
                    from zoneinfo import ZoneInfo

                    dt = datetime.fromisoformat(
                        str(raw_time).replace("Z", "+00:00")
                    )

                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

                    event_time = dt.astimezone(
                        ZoneInfo("Europe/Nicosia")
                    ).strftime("%H:%M")
                except Exception:
                    # Fallback if the value is already HH:MM.
                    raw_text = str(raw_time)
                    if len(raw_text) >= 5 and raw_text[2] == ":":
                        event_time = raw_text[:5]

                parts.append(
                    f"⚽ {home} 🆚 {away}"
                )

                if event_time:
                    parts.append(
                        f"🕘 {event_time}"
                    )

                parts.append(
                    f"🎯 {over_market} + GG"
                )
                parts.append("")

                builder_count += 1

            if builder_count == 0:
                # Remove the Builder section if no valid games remain.
                while parts and parts[-1] == "":
                    parts.pop()

                if parts and parts[-1] == "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦":
                    parts.pop()

                if parts and parts[-1] == "🔥 <b>BET BUILDER</b>":
                    parts.pop()

                if parts and parts[-1] == "🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦":
                    parts.pop()

    message = "\n".join(parts).rstrip()

    print(
        "\n" +
        message.replace("<b>", "").replace("</b>", "")
    )

    if picks:
        print("\n📲 ΑΠΟΣΤΟΛΗ TELEGRAM...")

        print(
            "✅ Στάλθηκε επιτυχώς στο Telegram."
            if send_telegram(message)
            else
            "❌ Δεν στάλθηκε στο Telegram."
        )

        print(
            "✅ Broadcast στάλθηκε στους FREE users."
            if broadcast_telegram(message)
            else
            "❌ Το broadcast δεν στάλθηκε."
        )

    if 'save_api_football_persistent_cache' in globals():
        save_api_football_persistent_cache()

    print(
        f"SUMMARY | Events: {len(events)} | "
        f"Analysed: {len(results)} | Picks: {len(picks)}"
    )

    print(
        f"API CACHE | in-memory: {len(API_RESPONSE_CACHE)} | "
        f'persistent: {len(globals().get("API_FOOTBALL_PERSISTENT_CACHE", {}))} | '
        f"rate_limited: {API_RATE_LIMITED}"
    )


if __name__ == "__main__":
    main()