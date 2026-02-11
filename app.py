from flask import Flask, render_template

app = Flask(__name__)


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

@app.route("/search/<name>")
def search_team(name):
    result = []
    for team in teams:
        if team["name"].lower() == name.lower():
            result.append(team)
            
    return result

app.run(host ="0.0.0.0", port=5005)