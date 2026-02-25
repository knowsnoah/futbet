from flask import Flask, jsonify, render_template, request
import os
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv
import certifi


app = Flask(__name__)

# loading enviornment variables from .env file
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
API_KEY = os.getenv("FOOTBALL_DATA_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = client["futbet"]
teams_col = db["teams"]
matches_col = db["matches"]
odds_col = db["odds"]

# NEW: meta collection for refresh timestamps
meta_col = db["meta"]

# NEW: how often to refresh automatically (every few hours)
AUTO_REFRESH_HOURS = 12


# -------------------------
# Helpers
# -------------------------

# function for simplifying the team names
def norm_team(name: str) -> str:
    if not name:
        return ""
    return (name.lower()
            .replace(" fc", "")
            .replace(" afc", "")
            .replace("&", "and")
            .strip())


# NEW: stale-check helpers
def is_stale(key: str, hours: int = AUTO_REFRESH_HOURS) -> bool:
    doc = meta_col.find_one({"key": key}, {"_id": 0, "lastRefresh": 1})
    if not doc or not doc.get("lastRefresh"):
        return True
    return (datetime.utcnow() - doc["lastRefresh"]) > timedelta(hours=hours)


def set_refreshed(key: str):
    meta_col.update_one(
        {"key": key},
        {"$set": {"lastRefresh": datetime.utcnow()}},
        upsert=True
    )


# function for calculating the form score of a team based on the last 5 matches
def team_form_score(team_id):
    last5 = list(matches_col.find(
        {
            "$and": [
                {"$or": [{"homeTeam.id": team_id}, {"awayTeam.id": team_id}]},
                {"status": "FINISHED"}
            ]
        },
        {"_id": 0}
    ).sort("utcDate", -1).limit(5))

    points = 0

    for m in last5:
        ft = m.get("score", {}).get("fullTime", {})
        hg = ft.get("home")
        ag = ft.get("away")

        if hg is None or ag is None:
            continue

        is_home = m["homeTeam"]["id"] == team_id
        team_goals = hg if is_home else ag
        opp_goals = ag if is_home else hg

        # Points: win +3, draw +1, loss 0
        if team_goals > opp_goals:
            points += 3
        elif team_goals == opp_goals:
            points += 1

    return points


# -------------------------
# NEW: refresh logic as callable functions
# -------------------------

def do_refresh_epl():
    if not API_KEY:
        raise RuntimeError("Missing FOOTBALL_DATA_KEY in .env")
    if not MONGO_URI:
        raise RuntimeError("Missing MONGO_URI in .env")

    headers = {"X-Auth-Token": API_KEY}
    url = "https://api.football-data.org/v4/competitions/PL/matches"
    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        raise RuntimeError(f"football-data API request failed ({r.status_code}): {r.text}")

    data = r.json()
    matches = data.get("matches", [])
    season = data.get("filters", {}).get("season")

    team_ops = []
    match_ops = []

    for m in matches:
        home = m["homeTeam"]
        away = m["awayTeam"]

        # upsert teams
        for t in (home, away):
            team_ops.append(
                UpdateOne(
                    {"id": t["id"]},
                    {"$set": {
                        "id": t["id"],
                        "name": t["name"],
                        "shortName": t.get("shortName"),
                        "tla": t.get("tla"),
                        "crest": t.get("crest")
                    }},
                    upsert=True
                )
            )

        # upsert match
        match_doc = {
            "id": m["id"],
            "utcDate": m.get("utcDate"),
            "status": m.get("status"),
            "matchday": m.get("matchday"),
            "season": season,
            "homeTeam": {"id": home["id"], "name": home["name"]},
            "awayTeam": {"id": away["id"], "name": away["name"]},
            "score": m.get("score", {})
        }

        match_ops.append(
            UpdateOne({"id": m["id"]}, {"$set": match_doc}, upsert=True)
        )

    if team_ops:
        teams_col.bulk_write(team_ops, ordered=False)
    if match_ops:
        matches_col.bulk_write(match_ops, ordered=False)

    set_refreshed("matches")

    return {
        "ok": True,
        "teams_upserted": len(team_ops),
        "matches_upserted": len(match_ops)
    }


def do_refresh_odds():
    if not ODDS_API_KEY:
        raise RuntimeError("Missing ODDS_API_KEY in .env")

    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    }

    r = requests.get(url, params=params)

    if r.status_code != 200:
        raise RuntimeError(f"Odds API failed ({r.status_code}): {r.text}")

    events = r.json()

    ops = []
    pulled_at = datetime.utcnow().isoformat() + "Z"

    for e in events:
        doc = {
            "eventId": e.get("id"),
            "commenceTime": e.get("commence_time"),
            "homeTeam": e.get("home_team"),
            "awayTeam": e.get("away_team"),
            "homeTeamNorm": norm_team(e.get("home_team")),
            "awayTeamNorm": norm_team(e.get("away_team")),
            "bookmakers": [],
            "pulledAt": pulled_at
        }

        for b in e.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") == "h2h":
                    outcomes = {o["name"]: o["price"] for o in m.get("outcomes", [])}
                    doc["bookmakers"].append({
                        "key": b.get("key"),
                        "title": b.get("title"),
                        "lastUpdate": b.get("last_update"),
                        "h2h": {
                            "home": outcomes.get(doc["homeTeam"]),
                            "draw": outcomes.get("Draw"),
                            "away": outcomes.get(doc["awayTeam"])
                        }
                    })

        if doc["eventId"]:
            ops.append(
                UpdateOne({"eventId": doc["eventId"]}, {"$set": doc}, upsert=True)
            )

    if ops:
        odds_col.bulk_write(ops, ordered=False)

    set_refreshed("odds")

    return {
        "ok": True,
        "eventsStored": len(ops)
    }


# -------------------------
# Routes
# -------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/search")
def search_team():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify([])

    teams = list(teams_col.find(
        {"name": {"$regex": name, "$options": "i"}},
        {"_id": 0}
    ).limit(10))

    return jsonify(teams)


@app.route("/team/<int:team_id>/matches")
def team_matches(team_id):
    matches = list(matches_col.find(
        {"$or": [{"homeTeam.id": team_id}, {"awayTeam.id": team_id}]},
        {"_id": 0}
    ).sort("utcDate", -1).limit(5))

    return jsonify(matches)


# To display the last 5 matches of a team, we need to filter by status "FINISHED" and sort by date descending.
@app.route("/team/<int:team_id>/last5")
def team_last5(team_id):
    matches = list(matches_col.find(
        {
            "$and": [
                {"$or": [{"homeTeam.id": team_id}, {"awayTeam.id": team_id}]},
                {"status": "FINISHED"}
            ]
        },
        {"_id": 0}
    ).sort("utcDate", -1).limit(5))

    return jsonify(matches)


# To display the next 5 matches, we filter by status "SCHEDULED" or "TIMED" and sort by date ascending
@app.route("/team/<int:team_id>/next5")
def team_next5(team_id):
    # NEW: auto-refresh matches occasionally (so schedules update after a search/team click)
    try:
        if is_stale("matches", hours=AUTO_REFRESH_HOURS):
            do_refresh_epl()
    except Exception:
        # If refresh fails, still return whatever is in MongoDB (don’t break the page)
        pass

    matches = list(matches_col.find(
        {
            "$and": [
                {"$or": [{"homeTeam.id": team_id}, {"awayTeam.id": team_id}]},
                {"status": {"$in": ["SCHEDULED", "TIMED"]}}
            ]
        },
        {"_id": 0}
    ).sort("utcDate", 1).limit(5))

    return jsonify(matches)


# This route combines the next 5 matches with the best odds and implied probabilities for the team.
@app.route("/team/<int:team_id>/value_simple")
def team_value_simple(team_id):

    # auto-refresh matches + odds occasionally (best place to keep things fresh)
    try:
        if is_stale("matches", hours=AUTO_REFRESH_HOURS):
            do_refresh_epl()
        if is_stale("odds", hours=AUTO_REFRESH_HOURS):
            do_refresh_odds()
    except Exception:
        # If refresh fails, continue using existing DB data
        pass

    # Get next 5 upcoming matches from your matches collection
    next5 = list(matches_col.find(
        {
            "$and": [
                {"$or": [{"homeTeam.id": team_id}, {"awayTeam.id": team_id}]},
                {"status": {"$in": ["SCHEDULED", "TIMED"]}}
            ]
        },
        {"_id": 0}
    ).sort("utcDate", 1).limit(5))

    results = []

    for m in next5:

        home_id = m["homeTeam"]["id"]
        away_id = m["awayTeam"]["id"]

        home_strength = team_form_score(home_id)
        away_strength = team_form_score(away_id)

        # converting difference into a probability
        diff = home_strength - away_strength

        model_home_prob = 1 / (1 + 2.718 ** (-diff / 5))
        model_away_prob = 1 - model_home_prob

        home_name = norm_team(m["homeTeam"]["name"])
        away_name = norm_team(m["awayTeam"]["name"])

        odds_doc = odds_col.find_one({
            "homeTeamNorm": home_name,
            "awayTeamNorm": away_name
        }, {"_id": 0})

        if not odds_doc:
            results.append({
                "match": m,
                "oddsFound": False
            })
            continue

        # Find best (highest) odds across bookmakers
        best_home = None
        best_draw = None
        best_away = None

        for b in odds_doc.get("bookmakers", []):
            h2h = b.get("h2h", {})

            home = h2h.get("home")
            draw = h2h.get("draw")
            away = h2h.get("away")

            if home and (best_home is None or home > best_home):
                best_home = home
            if draw and (best_draw is None or draw > best_draw):
                best_draw = draw
            if away and (best_away is None or away > best_away):
                best_away = away

        # Calculate implied probabilities
        implied = {
            "home": round(1 / best_home, 3) if best_home else None,
            "draw": round(1 / best_draw, 3) if best_draw else None,
            "away": round(1 / best_away, 3) if best_away else None
        }

        value = {
            "home": round(model_home_prob - implied["home"], 3) if implied["home"] else None,
            "away": round(model_away_prob - implied["away"], 3) if implied["away"] else None
        }

        results.append({
            "match": m,
            "oddsFound": True,
            "bestOdds": {
                "home": best_home,
                "draw": best_draw,
                "away": best_away
            },
            "impliedProb": implied,
            "modelProb": {
                "home": round(model_home_prob, 3),
                "away": round(model_away_prob, 3)
            },
            "value": value
        })

    return jsonify(results)


# Admin route to refresh EPL matches and teams data from football-data API
@app.route("/admin/refresh")
def refresh_epl():
    try:
        out = do_refresh_epl()
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/refresh_odds")
def refresh_odds():
    try:
        out = do_refresh_odds()
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/debug/odds")
def debug_odds():
    sample = odds_col.find_one({}, {"_id": 0})
    return jsonify(sample)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)