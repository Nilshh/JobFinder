from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

APP_ID  = "a353f160"
APP_KEY = "195c838b71947625e6c13ed1a329c629"

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response

@app.route("/jobs")
def jobs():
    title   = request.args.get("what", "")
    location= request.args.get("where", "")
    radius  = request.args.get("distance", "50")
    country = request.args.get("country", "de")

    params = {
        "app_id":           APP_ID,
        "app_key":          APP_KEY,
        "results_per_page": 20,
        "what":             title,
        "distance":         radius,
        "content-type":     "application/json",
    }
    if location:
        params["where"] = location

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    try:
        r = requests.get(url, params=params, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("✅ JobFinder Server läuft auf http://localhost:5500")
    app.run(host="0.0.0.0", port=5500, debug=False)