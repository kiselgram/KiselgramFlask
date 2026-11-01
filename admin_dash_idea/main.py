from flask import Flask, render_template, jsonify, request
import random
import time

app = Flask(__name__)

# ---------------------------------------------------------------
# Serve the dashboard
# ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------
# Stub API — replace with real data sources
# ---------------------------------------------------------------
@app.route("/api/stats")
def api_stats():
    return jsonify({
        "active_users":   random.randint(120_000, 135_000),
        "messages_min":   random.randint(23_000, 27_000),
        "delivery_rate":  round(random.uniform(99.9, 100.0), 2),
        "avg_latency_ms": random.randint(35, 55),
    })


@app.route("/api/nodes")
def api_nodes():
    nodes = [
        {"name": "EU · Frankfurt", "region": "PRIMARY", "load": random.randint(50, 90), "ping": random.randint(30, 60)},
        {"name": "US · Ashburn",   "region": "REPLICA", "load": random.randint(40, 80), "ping": random.randint(50, 90)},
        {"name": "AS · Singapore", "region": "REPLICA", "load": random.randint(60, 95), "ping": random.randint(70, 120)},
        {"name": "SA · São Paulo", "region": "EDGE",    "load": random.randint(20, 60), "ping": random.randint(90, 130)},
    ]
    return jsonify(nodes)


@app.route("/api/feed")
def api_feed():
    users = ["Nova_Rider", "Kisel", "ZeroCool", "Mira_X", "ByteLord", "Aurora"]
    texts = [
        "Deploying new edge node in Frankfurt 🚀",
        "Voice call quality is unreal now",
        "E2E encrypted 1:1 chats shipped ✅",
        "Latency down to 42ms across EU 🔥",
        "New dark theme looks sick",
    ]
    return jsonify([
        {"user": random.choice(users), "text": random.choice(texts), "ts": int(time.time())}
        for _ in range(5)
    ])


@app.route("/api/chats")
def api_chats():
    return jsonify([
        {"name": "# general",  "members": 12400, "activity": 84},
        {"name": "# dev-talk", "members": 3100,  "activity": 71},
        {"name": "# memes",    "members": 48900, "activity": 66},
        {"name": "# support",  "members": 920,   "activity": 52},
        {"name": "# crypto",   "members": 7800,  "activity": 44},
    ])


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "kiselgram-dashboard"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)