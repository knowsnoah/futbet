from flask import Flask, jsonify, render_template, request

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


@app.route("/search")
def search_team():
    name = request.args.get("name", "")
    result = []
    for team in teams:
        if team["name"].lower() == name.lower():
            result.append(team)
            
    return jsonify(result)



if __name__ == "__main__":
    app.run(host ="0.0.0.0", port=5005, debug=True)