from flask import Flask, render_template, request, jsonify
import requests
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
import mongoDB

app = Flask(__name__)
load_dotenv()

FOOTBALL_API_BASE = "https://api.football-data.org/v4"
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID")

football_headers = {
    "X-Auth-Token": FOOTBALL_DATA_KEY
}

# MongoDB setup
if mongoDB.client:
    db = mongoDB.client.futbet
    teams_collection = db.teams
    matches_collection = db.matches
    odds_collection = db.odds
    mongodb_available = True
else:
    db = None
    teams_collection = None
    matches_collection = None
    odds_collection = None
    mongodb_available = False


@app.context_processor
def inject_ga_measurement_id():
    return {"ga_measurement_id": GA_MEASUREMENT_ID}


# -------------------------
# Basic helpers
# -------------------------
def safe_get_json(url, headers=None, params=None):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"Request failed for {url}: {e}")
        return {}


def is_data_stale(cached_doc, max_age_hours=1):
    if not cached_doc or 'cached_at' not in cached_doc:
        return True

    cached_time = cached_doc['cached_at']

    if isinstance(cached_time, str):
        cached_time = datetime.fromisoformat(cached_time.replace('Z', '+00:00'))

    if cached_time.tzinfo is None:
        cached_time = cached_time.replace(tzinfo=timezone.utc)
    else:
        cached_time = cached_time.astimezone(timezone.utc)

    age = datetime.now(timezone.utc) - cached_time
    return age.total_seconds() > (max_age_hours * 3600)


def cache_data(collection, key, data, max_age_hours=1):
    """Cache data with timestamp"""
    if not mongodb_available or not collection:
        return data  # Just return data without caching
        
    doc = {
        '_id': key,
        'data': data,
        'cached_at': datetime.now(timezone.utc)
    }
    collection.replace_one({'_id': key}, doc, upsert=True)
    return data


def get_cached_data(collection, key, fetch_func, max_age_hours=1, force_refresh=False):
    """Get data from cache or fetch and cache"""
    if not mongodb_available or not collection:
        # Fall back to direct API calls if MongoDB is unavailable
        return fetch_func()
        
    if force_refresh:
        # Only fetch fresh data when explicitly requested
        data = fetch_func()
        if data:
            cache_data(collection, key, data, max_age_hours)
        return data
    
    # Always use cached data if available, regardless of age
    cached = collection.find_one({'_id': key})
    if cached:
        return cached['data']
    
    # No cached data, fetch and cache
    data = fetch_func()
    if data:
        cache_data(collection, key, data, max_age_hours)
    return data


def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_team_name(name):
    if not name:
        return ""

    name = name.lower().strip()

    replacements = {
        "fc": "",
        "afc": "",
        "cf": "",
        "ac": "",
        "ssc": "",
        "the ": "",
        "manchester united": "man united",
        "manchester city": "man city",
        "tottenham hotspur": "tottenham",
        "wolverhampton wanderers": "wolves",
        "nottingham forest": "nottingham forest",
        "brighton & hove albion": "brighton",
        "newcastle united": "newcastle",
        "west ham united": "west ham",
        "leicester city": "leicester",
        "ipswich town": "ipswich",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = " ".join(name.split())
    return name


# -------------------------
# football-data.org
# -------------------------
def get_pl_teams(force_refresh=False):
    def fetch_teams():
        url = f"{FOOTBALL_API_BASE}/competitions/PL/teams"
        data = safe_get_json(url, headers=football_headers)
        return data.get("teams", [])
    
    return get_cached_data(teams_collection, 'pl_teams', fetch_teams, max_age_hours=24, force_refresh=force_refresh)


def search_teams_by_name(name):
    teams = get_pl_teams()
    name = name.lower()
    return [team for team in teams if name in team["name"].lower()]


def is_premier_league_match(match):
    competition = match.get("competition", {})
    code = competition.get("code")
    comp_id = competition.get("id")
    return code == "PL" or comp_id == 2021


def get_upcoming_league_matches(force_refresh=False):
    def fetch_matches():
        url = f"{FOOTBALL_API_BASE}/competitions/PL/matches"
        params = {"status": "SCHEDULED"}
        data = safe_get_json(url, headers=football_headers, params=params)
        return data.get("matches", [])[:20]
    
    return get_cached_data(matches_collection, 'upcoming_matches', fetch_matches, max_age_hours=24, force_refresh=force_refresh)


def get_last5(team_id, force_refresh=False):
    def fetch_last5():
        url = f"{FOOTBALL_API_BASE}/teams/{team_id}/matches"
        params = {"status": "FINISHED", "limit": 20}
        data = safe_get_json(url, headers=football_headers, params=params)
        matches = [m for m in data.get("matches", []) if is_premier_league_match(m)]
        return matches[-5:] if len(matches) > 5 else matches
    
    return get_cached_data(matches_collection, f'last5_{team_id}', fetch_last5, max_age_hours=24, force_refresh=force_refresh)


def get_next5(team_id, force_refresh=False):
    def fetch_next5():
        url = f"{FOOTBALL_API_BASE}/teams/{team_id}/matches"
        params = {"status": "SCHEDULED", "limit": 20}
        data = safe_get_json(url, headers=football_headers, params=params)
        matches = [m for m in data.get("matches", []) if is_premier_league_match(m)]
        return matches[:5]
    
    return get_cached_data(matches_collection, f'next5_{team_id}', fetch_next5, max_age_hours=24, force_refresh=force_refresh)


def get_form_results(team_id, limit=5, force_refresh=False):
    matches = get_last5(team_id, force_refresh=force_refresh)
    results = []

    for match in matches:
        ft = match.get("score", {}).get("fullTime", {})
        home_goals = ft.get("home")
        away_goals = ft.get("away")
        if home_goals is None or away_goals is None:
            continue

        is_home = match.get("homeTeam", {}).get("id") == team_id
        if is_home:
            gf, ga = home_goals, away_goals
        else:
            gf, ga = away_goals, home_goals

        if gf > ga:
            results.append("W")
        elif gf == ga:
            results.append("D")
        else:
            results.append("L")

    return list(reversed(results))


def get_team_name(team_id):
    teams = get_pl_teams()
    for team in teams:
        if team["id"] == team_id:
            return team["name"]
    return "Team"


def get_standings(force_refresh=False):
    def fetch_standings():
        url = f"{FOOTBALL_API_BASE}/competitions/PL/standings"
        data = safe_get_json(url, headers=football_headers)
        standings = []

        for table in data.get("standings", []):
            if table.get("type") == "TOTAL":
                for row in table.get("table", []):
                    team = row.get("team", {})
                    team_id = team.get("id")
                    standings.append({
                        "position": row.get("position"),
                        "team_id": team_id,
                        "team_name": team.get("name"),
                        "crest": team.get("crest") or "",
                        "playedGames": row.get("playedGames"),
                        "won": row.get("won"),
                        "draw": row.get("draw"),
                        "lost": row.get("lost"),
                        "points": row.get("points"),
                        "goalsFor": row.get("goalsFor"),
                        "goalsAgainst": row.get("goalsAgainst"),
                        "goalDifference": row.get("goalDifference"),
                        "form": get_form_results(team_id, force_refresh=force_refresh)
                    })
                break

        return standings
    
    return get_cached_data(teams_collection, 'standings', fetch_standings, max_age_hours=168, force_refresh=force_refresh)  # Cache for 1 week


# -------------------------
# Simple model from recent form
# -------------------------
def get_recent_form_points(team_id, limit=5):
    def fetch_recent_form():
        url = f"{FOOTBALL_API_BASE}/teams/{team_id}/matches"
        params = {"status": "FINISHED", "limit": 20}
        data = safe_get_json(url, headers=football_headers, params=params)
        matches = [m for m in data.get("matches", []) if is_premier_league_match(m)]

        points = 0
        goal_diff = 0
        count = 0

        for m in matches[:limit]:
            ft = m.get("score", {}).get("fullTime", {})
            home_goals = ft.get("home")
            away_goals = ft.get("away")

            if home_goals is None or away_goals is None:
                continue

            is_home = m.get("homeTeam", {}).get("id") == team_id

            if is_home:
                gf, ga = home_goals, away_goals
            else:
                gf, ga = away_goals, home_goals

            goal_diff += (gf - ga)

            if gf > ga:
                points += 3
            elif gf == ga:
                points += 1

            count += 1

        if count == 0:
            return {
                "ppg": 1.0,
                "gd_per_match": 0.0
            }

        return {
            "ppg": round(points / count, 3),
            "gd_per_match": round(goal_diff / count, 3)
        }
    
    return get_cached_data(matches_collection, f'recent_form_{team_id}_{limit}', fetch_recent_form, max_age_hours=24, force_refresh=False)  # Cache for 24 hours, don't auto-refresh


def estimate_match_probabilities(home_team_id, away_team_id):
    home_form = get_recent_form_points(home_team_id)
    away_form = get_recent_form_points(away_team_id)

    home_strength = home_form["ppg"] + (0.25 * home_form["gd_per_match"]) + 0.30
    away_strength = away_form["ppg"] + (0.25 * away_form["gd_per_match"])

    home_strength = max(home_strength, 0.2)
    away_strength = max(away_strength, 0.2)

    draw_base = 0.26
    gap = abs(home_strength - away_strength)
    draw_prob = max(0.16, draw_base - 0.04 * gap)

    remaining = max(0.05, 1.0 - draw_prob)
    home_prob_raw = home_strength / (home_strength + away_strength)
    away_prob_raw = away_strength / (home_strength + away_strength)

    home_prob = remaining * home_prob_raw
    away_prob = remaining * away_prob_raw

    total = home_prob + draw_prob + away_prob
    home_prob /= total
    draw_prob /= total
    away_prob /= total

    return {
        "home": round(home_prob, 3),
        "draw": round(draw_prob, 3),
        "away": round(away_prob, 3)
    }


# -------------------------
# The Odds API
# -------------------------
def get_epl_odds(force_refresh=False):
    def fetch_odds():
        if not ODDS_API_KEY:
            print("ODDS_API_KEY not set. Odds will be unavailable.")
            return []

        url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "uk,eu",
            "markets": "h2h",
            "oddsFormat": "decimal"
        }

        data = safe_get_json(url, params=params)
        if isinstance(data, list):
            return data
        return []
    
    return get_cached_data(odds_collection, 'epl_odds', fetch_odds, max_age_hours=6, force_refresh=force_refresh)


def get_best_h2h_odds_for_match(match, odds_events):
    match_home = normalize_team_name(match.get("homeTeam", {}).get("name", ""))
    match_away = normalize_team_name(match.get("awayTeam", {}).get("name", ""))
    match_time = parse_iso_datetime(match.get("utcDate"))

    best = {
        "home": None,
        "draw": None,
        "away": None
    }

    found = False

    for event in odds_events:
        event_home = normalize_team_name(event.get("home_team", ""))
        event_away = normalize_team_name(event.get("away_team", ""))
        event_time = parse_iso_datetime(event.get("commence_time"))

        if not event_time or not match_time:
            continue

        time_diff = abs((event_time - match_time).total_seconds())
        names_match = (
            event_home == match_home and event_away == match_away
        ) or (
            event_home == match_away and event_away == match_home
        )

        if not names_match or time_diff > 18 * 3600:
            continue

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                for outcome in market.get("outcomes", []):
                    outcome_name = normalize_team_name(outcome.get("name", ""))
                    price = outcome.get("price")

                    if price is None:
                        continue

                    if outcome_name == match_home:
                        best["home"] = max(best["home"], price) if best["home"] else price
                        found = True
                    elif outcome_name == match_away:
                        best["away"] = max(best["away"], price) if best["away"] else price
                        found = True
                    elif outcome_name == "draw":
                        best["draw"] = max(best["draw"], price) if best["draw"] else price
                        found = True

    return found, best


# -------------------------
# Value bets
# -------------------------
def calc_value(prob, odds):
    if prob is None or odds is None:
        return None
    return round((prob * odds) - 1, 3)


def get_value_simple(team_id, force_refresh=False):
    next5 = get_next5(team_id, force_refresh=force_refresh)
    odds_events = get_epl_odds(force_refresh=force_refresh)
    results = []

    for match in next5:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})

        probs = estimate_match_probabilities(home_team.get("id"), away_team.get("id"))
        odds_found, best_odds = get_best_h2h_odds_for_match(match, odds_events)

        value = {
            "home": calc_value(probs["home"], best_odds["home"]) if odds_found else None,
            "draw": calc_value(probs["draw"], best_odds["draw"]) if odds_found else None,
            "away": calc_value(probs["away"], best_odds["away"]) if odds_found else None
        }

        results.append({
            "match": match,
            "oddsFound": odds_found,
            "bestOdds": best_odds,
            "modelProb": probs,
            "value": value
        })

    return results


def get_global_value_picks(limit=5, force_refresh=False):
    upcoming_matches = get_upcoming_league_matches(force_refresh=force_refresh)
    odds_events = get_epl_odds(force_refresh=force_refresh)
    all_values = []

    for match in upcoming_matches:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})

        probs = estimate_match_probabilities(home_team.get("id"), away_team.get("id"))
        odds_found, best_odds = get_best_h2h_odds_for_match(match, odds_events)

        if not odds_found:
            continue

        value_home = calc_value(probs["home"], best_odds["home"])
        value_draw = calc_value(probs["draw"], best_odds["draw"])
        value_away = calc_value(probs["away"], best_odds["away"])

        # Collect positive values
        if value_home and value_home > 0:
            all_values.append({
                "match": match,
                "bet": "home",
                "value": value_home,
                "odds": best_odds["home"],
                "prob": probs["home"]
            })
        if value_draw and value_draw > 0:
            all_values.append({
                "match": match,
                "bet": "draw",
                "value": value_draw,
                "odds": best_odds["draw"],
                "prob": probs["draw"]
            })
        if value_away and value_away > 0:
            all_values.append({
                "match": match,
                "bet": "away",
                "value": value_away,
                "odds": best_odds["away"],
                "prob": probs["away"]
            })

    # Sort by value descending and take top limit
    all_values.sort(key=lambda x: x["value"], reverse=True)
    return all_values[:limit]


# -------------------------
# Routes
# -------------------------
@app.route("/", methods=["GET"])
def home():
    query = request.args.get("q", "").strip()
    refresh = request.args.get("refresh", "").lower() in ['true', '1', 'yes']
    
    search_results = search_teams_by_name(query) if query else []
    upcoming_matches = get_upcoming_league_matches(force_refresh=refresh)
    value_picks = get_global_value_picks(force_refresh=refresh) if ODDS_API_KEY else []

    return render_template(
        "home.html",
        query=query,
        search_results=search_results,
        upcoming_matches=upcoming_matches,
        value_picks=value_picks
    )


@app.route("/team/<int:team_id>")
def team_page(team_id):
    refresh = request.args.get("refresh", "").lower() in ['true', '1', 'yes']
    
    team_name = get_team_name(team_id)
    last5 = get_last5(team_id, force_refresh=refresh)
    next5 = get_next5(team_id, force_refresh=refresh)
    value_bets = get_value_simple(team_id, force_refresh=refresh)
    odds_enabled = bool(ODDS_API_KEY)

    return render_template(
        "team.html",
        team_name=team_name,
        team_id=team_id,
        last5=last5,
        next5=next5,
        value_bets=value_bets,
        odds_enabled=odds_enabled
    )


@app.route("/table")
def table_page():
    refresh = request.args.get("refresh", "").lower() in ['true', '1', 'yes']
    standings = get_standings(force_refresh=refresh)
    return render_template("table.html", standings=standings)


@app.route("/combos")
def combos_page():
    refresh = request.args.get("refresh", "").lower() in ['true', '1', 'yes']
    value_picks = get_global_value_picks(force_refresh=refresh) if ODDS_API_KEY else []
    return render_template("combos.html", value_picks=value_picks, odds_enabled=bool(ODDS_API_KEY))


@app.route("/team/<int:team_id>/value_simple")
def team_value_simple(team_id):
    return jsonify(get_value_simple(team_id))


if __name__ == "__main__":
    if not FOOTBALL_DATA_KEY:
        print("Missing FOOTBALL_DATA_KEY in .env")
    if not ODDS_API_KEY:
        print("Missing ODDS_API_KEY in .env (odds/value bets will be empty)")

    app.run(host="0.0.0.0", port=5005, debug=True)