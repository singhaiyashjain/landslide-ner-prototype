"""
GeoSentinel NER — SMS alert sender
-----------------------------------
Sends a landslide-risk SMS alert via Twilio.

SETUP:
  1. pip install -r requirements.txt
  2. Create a .env file in this folder (copy .env.example) and fill in:
       TWILIO_ACCOUNT_SID=xxxx
       TWILIO_AUTH_TOKEN=xxxx
       TWILIO_FROM_NUMBER=+1xxxxxxxxxx   (your Twilio number)
  3. Run:  python alerts.py
     (edit the __main__ block below to change the test zone/number)

To wire this to the frontend "Simulate Alert" button, wrap send_alert()
in a small Flask/FastAPI endpoint (see run_server() below) and call it
from map.js via fetch().
"""

import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")


def send_alert(to_number: str, zone_name: str, risk_label: str, score: int) -> str:
    """Sends a landslide risk SMS alert. Returns the Twilio message SID."""
    if not (ACCOUNT_SID and AUTH_TOKEN and FROM_NUMBER):
        raise RuntimeError(
            "Twilio credentials missing. Fill in .env (see .env.example)."
        )

    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    body = (
        f"\U0001F6A8 LANDSLIDE RISK ALERT\n"
        f"Zone: {zone_name}\n"
        f"Risk level: {risk_label} (score {score}/100)\n"
        f"Please follow local evacuation guidance and avoid the flagged slope area."
    )

    message = client.messages.create(body=body, from_=FROM_NUMBER, to=to_number)
    return message.sid


# ---------------------------------------------------------------------
# Optional: tiny Flask server so the frontend can trigger a real SMS.
# Uncomment and run `python alerts.py --server` to use it.
# ---------------------------------------------------------------------
def run_server():
    from flask import Flask, request, jsonify
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)  # allow requests from the frontend during local dev

    @app.route("/send-alert", methods=["POST"])
    def send_alert_endpoint():
        data = request.get_json()
        to_number = data.get("to_number")  # e.g. hardcode a test number for demo
        zone_name = data.get("zone", "Unknown zone")
        risk_label = data.get("risk", "High")
        score = data.get("score", 0)

        try:
            sid = send_alert(to_number, zone_name, risk_label, score)
            return jsonify({"status": "sent", "sid": sid})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    app.run(port=5000, debug=True)


if __name__ == "__main__":
    import sys

    if "--server" in sys.argv:
        run_server()
    else:
        # Quick manual test — edit these before running
        TEST_NUMBER = "+91XXXXXXXXXX"  # must be a Twilio-verified number on trial accounts
        sid = send_alert(TEST_NUMBER, "Sohra Ridge", "High", 78)
        print("Sent! Message SID:", sid)
