"""
GeoSentinel NER — Alerts Engine
--------------------------------
Multi-channel landslide risk alert dispatcher: real SMS via Twilio when
credentials are configured, with an automatic SIMULATION fallback so the
demo never breaks — no funded Twilio account or working internet needed
at the venue.

Why this matters for Saturday:
  Judges will click "Simulate Alert" live. If Twilio isn't set up, or the
  venue wifi drops, the old code would either do nothing (still fake) or
  crash (worse). This version always returns a real, structured result —
  "sent" if Twilio is live, "simulated" otherwise — and logs every alert
  so the frontend can show a live "Recent Alerts" feed either way.

SETUP (only needed if you want a REAL SMS to go out):
  1. pip install -r requirements.txt
  2. Copy .env.example -> .env and fill in TWILIO_ACCOUNT_SID / AUTH_TOKEN / FROM_NUMBER
  3. Start the server:  python alerts.py --server      (Flask, port 5000)
     Or send one manually from the CLI:  python alerts.py

If .env is missing, incomplete, or still has placeholder values, every
alert automatically runs in SIMULATION_MODE. Nothing crashes, nothing is
actually sent, but the response shape is identical and every alert is
appended to alert_log.json.

Endpoints (python alerts.py --server):
  GET  /health                                     -> {status, mode}
  POST /send-alert  { to_number, zone, risk, score } -> dispatch one alert
  GET  /alerts                                     -> last 50 alerts (for a live feed)
"""

import os
import re
import json
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

# ---------------------------------------------------------------------
# Decide once at startup whether we're in SIMULATION_MODE. We treat
# missing values *and* obvious placeholder values (from .env.example)
# as "not configured", so a half-filled-in .env doesn't crash the demo.
# ---------------------------------------------------------------------
_PLACEHOLDER_MARKERS = ("your_", "xxxx", "XXXXXXXXXX")


def _looks_like_placeholder(value):
    if not value:
        return True
    return any(marker in value for marker in _PLACEHOLDER_MARKERS)


SIMULATION_MODE = any(
    _looks_like_placeholder(v) for v in (ACCOUNT_SID, AUTH_TOKEN, FROM_NUMBER)
)

_twilio_client = None
if not SIMULATION_MODE:
    try:
        from twilio.rest import Client

        _twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)
    except Exception as exc:  # pragma: no cover - defensive, keeps demo alive
        print(f"[alerts] Twilio client init failed, falling back to simulation mode: {exc}")
        SIMULATION_MODE = True

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_log.json")
PHONE_RE = re.compile(r"^\+\d{8,15}$")  # basic E.164 check


def _load_log():
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(entry):
    log = _load_log()
    log.insert(0, entry)  # newest first
    log = log[:50]  # plenty for a live demo feed
    try:
        with open(LOG_PATH, "w") as f:
            json.dump(log, f, indent=2)
    except OSError as exc:
        print(f"[alerts] Warning: could not write alert log: {exc}")
    return log


def build_message(zone_name: str, risk_label: str, score: int) -> str:
    return (
        f"\U0001F6A8 LANDSLIDE RISK ALERT\n"
        f"Zone: {zone_name}\n"
        f"Risk level: {risk_label} (score {score}/100)\n"
        f"Please follow local evacuation guidance and avoid the flagged slope area."
    )


def send_alert(to_number: str, zone_name: str, risk_label: str, score: int) -> dict:
    """
    Dispatches a landslide risk alert and returns a structured result.
    The shape is identical whether the SMS was real, simulated, or a
    live Twilio call failed mid-demo — callers never need to special-case it.
    """
    body = build_message(zone_name, risk_label, score)
    valid_number = bool(to_number) and bool(PHONE_RE.match(to_number))

    if SIMULATION_MODE or not valid_number:
        # Demo-safe path. Also doubles as a stand-in for the "IVR
        # fallback for low-connectivity areas" story from the one-pager:
        # if there's no real number/credentials, we simulate SMS + IVR.
        reason = "no Twilio credentials configured" if SIMULATION_MODE else "invalid/missing phone number"
        result = {
            "id": str(uuid.uuid4())[:8],
            "channel": "simulated-sms+ivr",
            "status": "simulated",
            "note": f"Simulated ({reason}). Would dispatch real SMS + IVR fallback in production.",
            "to_number": to_number or "N/A",
            "zone": zone_name,
            "risk": risk_label,
            "score": score,
            "message": body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    else:
        try:
            message = _twilio_client.messages.create(body=body, from_=FROM_NUMBER, to=to_number)
            result = {
                "id": message.sid,
                "channel": "sms",
                "status": "sent",
                "note": "Sent via Twilio.",
                "to_number": to_number,
                "zone": zone_name,
                "risk": risk_label,
                "score": score,
                "message": body,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            # A live Twilio failure mid-demo (bad trial-account number,
            # no signal, etc.) should degrade gracefully, not crash.
            result = {
                "id": str(uuid.uuid4())[:8],
                "channel": "simulated-sms+ivr",
                "status": "error-fallback",
                "note": f"Twilio send failed ({exc}); simulated instead.",
                "to_number": to_number,
                "zone": zone_name,
                "risk": risk_label,
                "score": score,
                "message": body,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    _append_log(result)
    return result


# ---------------------------------------------------------------------
# Flask server so the frontend "Simulate Alert" button calls this for
# real instead of just showing a static banner. Run: python alerts.py --server
# ---------------------------------------------------------------------
def run_server():
    from flask import Flask, request, jsonify
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)  # allow requests from the frontend during local dev

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "mode": "simulation" if SIMULATION_MODE else "live"})

    @app.route("/send-alert", methods=["POST"])
    def send_alert_endpoint():
        data = request.get_json(silent=True) or {}
        to_number = data.get("to_number")
        zone_name = data.get("zone", "Unknown zone")
        risk_label = data.get("risk", "High")
        try:
            score = int(data.get("score", 0))
        except (TypeError, ValueError):
            score = 0

        result = send_alert(to_number, zone_name, risk_label, score)
        return jsonify(result)

    @app.route("/alerts", methods=["GET"])
    def alert_history():
        return jsonify(_load_log())

    mode = "SIMULATION" if SIMULATION_MODE else "LIVE"
    print(f"[alerts] Starting server on http://localhost:5000  (mode: {mode})")
    app.run(port=5000, debug=True)


if __name__ == "__main__":
    import sys

    if "--server" in sys.argv:
        run_server()
    else:
        # Quick manual CLI test. Set TEST_PHONE_NUMBER in your .env to
        # avoid editing this file, or just let it run in simulation mode.
        TEST_NUMBER = os.getenv("TEST_PHONE_NUMBER", "+91XXXXXXXXXX")
        result = send_alert(TEST_NUMBER, "Sohra Ridge", "High", 78)
        print(json.dumps(result, indent=2))
