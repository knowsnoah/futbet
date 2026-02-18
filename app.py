from flask import Flask, jsonify, render_template, request
import os
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv
from pymongo import UpdateOne



app = Flask(__name__)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
API_KEY = os.getenv("FOOTBALL_DATA_KEY")

client = MongoClient(MONGO_URI)
db = client["futbet"]
teams_col = db["teams"]
matches_col = db["matches"]


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

#To display the last 5 matches of a team, we need to filter by status "FINISHED" and sort by date descending. 
#For the next 5 matches, we filter by status "SCHEDULED" or "TIMED" and sort by date ascending
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

#To display the last 5 matches of a team, we need to filter by status "FINISHED" and sort by date descending.
@app.route("/team/<int:team_id>/next5") 
def team_next5(team_id):
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


@app.route("/admin/refresh")
def refresh_epl():
    if not API_KEY:
        return jsonify({"error": "Missing FOOTBALL_DATA_KEY in .env"}), 500
    if not MONGO_URI:
        return jsonify({"error": "Missing MONGO_URI in .env"}), 500

    headers = {"X-Auth-Token": API_KEY}
    url = "https://api.football-data.org/v4/competitions/PL/matches"
    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return jsonify({
            "error": "football-data API request failed",
            "status_code": r.status_code,
            "details": r.text
        }), r.status_code

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

    return jsonify({
        "ok": True,
        "teams_upserted": len(team_ops),
        "matches_upserted": len(match_ops)
    })



if __name__ == "__main__":
    app.run(host ="0.0.0.0", port=5005, debug=True)



