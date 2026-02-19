from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

APP_ID  = os.environ.get("ADZUNA_APP_ID",  "")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Jira-Domain"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

def _parse(r):
    """Safely parse Jira response – falls back to text if body isn't JSON."""
    try:
        return jsonify(r.json()), r.status_code
    except ValueError:
        print(f"[jira] Non-JSON response HTTP {r.status_code}: {r.text[:300]}")
        return jsonify({
            "errorMessages": [f"Unerwartete Antwort vom Server (HTTP {r.status_code})"],
            "detail": r.text[:300]
        }), r.status_code

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


@app.route("/jira/test", methods=["GET", "OPTIONS"])
def jira_test():
    if request.method == "OPTIONS":
        return "", 204

    domain = request.headers.get("X-Jira-Domain", "").strip()
    auth   = request.headers.get("Authorization", "")

    print(f"[jira/test] domain={domain!r} auth_present={bool(auth)}")

    if not domain or not auth:
        return jsonify({"errorMessages": ["Fehlende Header: X-Jira-Domain oder Authorization"]}), 400

    url = f"https://{domain}/rest/api/3/myself"
    try:
        r = requests.get(
            url,
            headers={"Authorization": auth, "Accept": "application/json"},
            timeout=10,
        )
        print(f"[jira/test] HTTP {r.status_code}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/test] Exception: {e}")
        return jsonify({"errorMessages": [str(e)]}), 500


@app.route("/jira/fields", methods=["GET", "OPTIONS"])
def jira_fields():
    if request.method == "OPTIONS":
        return "", 204

    domain  = request.headers.get("X-Jira-Domain", "").strip()
    auth    = request.headers.get("Authorization", "")
    project   = request.args.get("project", "")
    issuetype = request.args.get("issuetype", "")

    print(f"[jira/fields] domain={domain!r} project={project!r} issuetype={issuetype!r}")

    if not domain or not auth or not project:
        return jsonify({"error": "Fehlende Parameter"}), 400

    if issuetype:
        url = f"https://{domain}/rest/api/3/issue/createmeta/{project}/issuetypes/{issuetype}"
    else:
        url = f"https://{domain}/rest/api/3/issue/createmeta/{project}/issuetypes"
    try:
        r = requests.get(
            url,
            headers={"Authorization": auth, "Accept": "application/json"},
            timeout=10,
        )
        print(f"[jira/fields] HTTP {r.status_code}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/fields] Exception: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/jira/issue", methods=["POST", "OPTIONS"])
def jira_issue():
    if request.method == "OPTIONS":
        return "", 204

    domain = request.headers.get("X-Jira-Domain", "").strip()
    auth   = request.headers.get("Authorization", "")

    print(f"[jira/issue] domain={domain!r} auth_present={bool(auth)}")

    if not domain or not auth:
        return jsonify({"errorMessages": ["Fehlende Header: X-Jira-Domain oder Authorization"]}), 400

    url = f"https://{domain}/rest/api/3/issue"
    try:
        r = requests.post(
            url,
            json=request.get_json(force=True),
            headers={
                "Authorization": auth,
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            },
            timeout=15,
        )
        print(f"[jira/issue] HTTP {r.status_code}")
        if r.status_code >= 400:
            print(f"[jira/issue] Error body: {r.text[:500]}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/issue] Exception: {e}")
        return jsonify({"errorMessages": [str(e)]}), 500


if __name__ == "__main__":
    print("✅ JobPipeline Server läuft auf http://localhost:5500")
    app.run(host="0.0.0.0", port=5500, debug=False)
