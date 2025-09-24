DNSC2 - Research C2 Demo

This repository contains a minimal C2 server (Flask) and a sample agent (Go) used to demonstrate attacker tradecraft for research. The admin portal provides a simple web UI to queue commands and view agent responses, with live updates via Server-Sent Events.

Features
- Web admin portal at `/admin` to queue tasks and view responses
- Agents fetch tasks via HTML comment channel (`/about?id=<agent_id>`) and post responses to `/contact`
- Live updates using SSE (`/admin/stream`) + JSON snapshot (`/admin/data`)
- Active agent tracking by last-seen timestamp

Requirements
- Python 3.9+
- Go 1.20+
- OpenSSL (available in Git Bash on Windows, or install separately)

Setup (Server)
1) Create and activate a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate   # Git Bash/Linux/macOS
# On Windows PowerShell: .venv\Scripts\Activate.ps1
```

2) Install dependencies
```bash
pip install flask
```

3) Generate a self-signed certificate (cert.pem/key.pem)
- Using OpenSSL (works in Git Bash/WSL/macOS/Linux):
```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```
This creates `cert.pem` and `key.pem` in the repository root. The server is configured to use these files.

4) Run the C2 server (HTTPS)
```bash
python c2_server.py
```
The server listens by default on `https://0.0.0.0:4443`. Open the admin portal:
- `https://<server-ip>:4443/admin`

Note: If your browser warns about the self-signed certificate, proceed/allow for testing only.

Setup (Agent)
1) Configure the agent server URL and ID in `agent_https.go` (top of file):
```go
const (
    server     = "https://<server-ip>:4443"
    agentID    = "agent01"
    beaconFreq = 20 * time.Second
)
```

2) Build and run the agent
```bash
go build -o agent.exe agent_https.go   # on Windows
./agent.exe
# or on macOS/Linux:
# go build -o agent agent_https.go && ./agent
```
The agent will:
- Beacon to `/about?id=<agentID>` and parse `<!--cmd:...-->` from HTML
- Execute the command, then POST the result to `/contact`

Note: TLS verification is disabled in the sample agent for research (`InsecureSkipVerify: true`). Do not use this in production.

Using the Admin Portal
- Open `https://<server-ip>:4443/admin`
- Use the form to queue a command for an agent (e.g., `whoami`)
- Active agents (seen ≤60s) are listed; click “send task” to target that agent quickly
- Responses appear live in the “Latest Responses” panel

Configuration Notes
- Active window is currently fixed at 60s on the server to approximate the beacon frequency; adjust in `c2_server.py` if needed
- To expose other routes or add authentication, extend the Flask app

Troubleshooting
- If the admin page doesn’t live-update, ensure your browser allows the `EventSource` connection to `/admin/stream`
- If HTTPS fails to start, verify `cert.pem` and `key.pem` exist and are readable
- If the agent cannot connect, confirm firewall rules allow TCP 4443 and the `server` URL/IP is correct

Disclaimer
This code is for internal research and blue-team training only. Do not deploy in production environments.


