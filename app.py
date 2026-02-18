from flask import Flask, jsonify, render_template, request
import os
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

#API KEY for footbal data API
API_KEY = os.getenv("FOOTBALL_DATA_KEY", "4680440494784f4393b42099061700fd")


teams = [
    {
        "name": "Manchester City"
    },
    {
        "name": "Liverpool"
    },
     {
        "name": "Manchester United"
    },
     {
        "name": "Chelsea"
    },
     {
        "name": "Arsenal"
    },
]

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/search")
def search_team():
    name = request.args.get("name", "")
    result = []
    for team in teams:
        if team["name"].lower() == name.lower():
            result.append(team)
            
    return jsonify(result)


@app.route("/epl/matches")
def get_matches():
    headers = {"X-Auth-Token": API_KEY}
    url = "https://api.football-data.org/v4/competitions/PL/matches"
    response = requests.get(url, headers=headers)

    # ✅ If API error, return useful info to your browser
    if response.status_code != 200:
        return jsonify({
            "error": "Football-data API request failed",
            "status_code": response.status_code,
            "details": response.text
        }), response.status_code

    # ✅ Return the JSON so the browser / frontend can use it
    return jsonify(response.json())



if __name__ == "__main__":
    app.run(host ="0.0.0.0", port=5005, debug=True)