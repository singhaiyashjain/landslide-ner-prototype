"""
server.py — GeoSentinel NER backend.

Serves:
  GET  /api/zones?rainfall=<mm>   -> all pilot zones with live ML risk score,
                                      label, and a short "why" explanation
  POST /api/predict               -> single zone / custom feature what-if
  POST /api/send-alert            -> triggers backend/alerts.send_alert();
                                      if Twilio creds are missing it returns
                                      a SIMULATED response instead of
                                      crashing, so no real Twilio account is
                                      needed to demo the flow end-to-end

Run:
  cd backend
  pip install -r requirements.txt
  python risk_model/train_model.py   # only needed once, or after data_gen changes
  python server.py                   # starts on http://localhost:5000

The frontend (frontend/map.js) calls this instead of computing risk in the
browser. If this server isn't running, the frontend falls back to its own
local formula automatically — see calculateRiskFallback() in map.js.
"""

import json
import os
import sys

import joblib
from flask import Flask, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_model"))
from features import FEATURES, score_to_label, compute_contributions  # noqa: E402

import alerts  # backend/alerts.py — Tech 3's file, used as-is

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(HERE, "risk_model", "artifacts")
DATA_PATH = os.path.join(HERE, "..", "data", "risk_data.json")

MODEL_PATH = os.path.join(ARTIFACTS_DIR, "risk_model.joblib")
META_PATH = os.path.join(ARTIFACTS_DIR, "model_meta.json")

app = Flask(__name__)

_model = None
_meta = None
_zones_raw = None


def load_artifacts():
    global _model, _meta, _zones_raw
    if not os.path.exists(MODEL_PATH):
        raise RuntimeError(
            "No trained model found. Run `python risk_model/train_model.py` first."
        )
    _model = joblib.load(MODEL_PATH)
    with open(META_PATH) as f:
        _meta = json.load(f)
    with open(DATA_PATH) as f:
        _zones_raw = json.load(f)


# --- manual CORS (avoids depending on the flask-cors package) ---
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def zone_to_features(zone: dict, rainfall_override=None) -> dict:
    """Maps a data/risk_data.json zone entry onto the model's FEATURES."""
    return {
        "slope_deg": zone.get("slope_deg", 0),
        "rainfall_mm": rainfall_override if rainfall_override is not None else zone.get("base_rainfall_mm", 0),
        "soil_moisture_pct": zone.get("soil_moisture_pct", 0),
        "seismic_activity": zone.get("seismic_activity", 4.0),
        "vegetation_cover_pct": zone.get("vegetation_cover_pct", 40.0),
        "human_activity_index": zone.get("human_activity_index", 30.0),
        "insar_deformation_mm_yr": zone.get("insar_deformation_mm_yr", 5.0),
    }


def score_zone(feature_row: dict):
    X = [[feature_row[f] for f in FEATURES]]
    proba = float(_model.predict_proba(X)[0][1])
    score = round(proba * 100)
    label = score_to_label(score)
    factors = compute_contributions(
        _model, feature_row, _meta["feature_means"], _meta["feature_stds"]
    )
    return score, label, factors


@app.route("/api/zones", methods=["GET"])
def get_zones():
    rainfall_override = request.args.get("rainfall", type=float)
    results = []
    for zone in _zones_raw["zones"]:
        features = zone_to_features(zone, rainfall_override)
        score, label, factors = score_zone(features)
        results.append({
            **zone,
            "rainfall_used_mm": features["rainfall_mm"],
            "score": score,
            "label": label,
            "factors": factors,
        })
    return jsonify({
        "district": _zones_raw["district"],
        "center": _zones_raw["center"],
        "model_backend": "sklearn-gradient-boosting",
        "model_test_auc": _meta["test_auc"],
        "zones": results,
    })


@app.route("/api/predict", methods=["POST"])
def predict():
    body = request.get_json(force=True) or {}
    zone_id = body.get("zone_id")
    zone = next((z for z in _zones_raw["zones"] if z["id"] == zone_id), None)
    if zone is None:
        return jsonify({"error": f"unknown zone_id '{zone_id}'"}), 404

    rainfall_override = body.get("rainfall_mm")
    features = zone_to_features(zone, rainfall_override)
    # allow overriding any other feature too, for a fuller what-if later
    for f in FEATURES:
        if f in body and f != "rainfall_mm":
            features[f] = body[f]

    score, label, factors = score_zone(features)
    return jsonify({
        "zone_id": zone_id,
        "zone_name": zone["name"],
        "score": score,
        "label": label,
        "factors": factors,
        "features_used": features,
    })


@app.route("/api/send-alert", methods=["POST"])
def send_alert_endpoint():
    body = request.get_json(force=True) or {}
    zone_name = body.get("zone", "Unknown zone")
    risk_label = body.get("risk", "High")
    score = body.get("score", 0)
    to_number = body.get("to_number") or os.getenv("DEMO_ALERT_NUMBER", "+91XXXXXXXXXX")

    try:
        sid = alerts.send_alert(to_number, zone_name, risk_label, score)
        return jsonify({"status": "sent", "sid": sid})
    except RuntimeError:
        # No Twilio credentials configured — simulate instead of failing,
        # so the demo flow works end-to-end without a real Twilio account.
        return jsonify({
            "status": "simulated",
            "message": (
                f"Twilio credentials not configured, so this is a SIMULATED alert. "
                f"Would SMS '{zone_name}' risk={risk_label} (score {score}) to {to_number}. "
                f"Fill in backend/.env with real Twilio credentials to send a live SMS."
            ),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model_loaded": _model is not None})


if __name__ == "__main__":
    load_artifacts()
    print(f"[server] model loaded, test AUC={_meta['test_auc']}, "
          f"{len(_zones_raw['zones'])} zones from {DATA_PATH}")
    app.run(port=5000, debug=True, use_reloader=False)
