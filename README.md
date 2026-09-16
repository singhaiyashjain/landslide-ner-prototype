# GeoSentinel NER — Landslide Early Warning Prototype

AI-based landslide risk monitoring prototype for North Eastern India. Built for SIH internal hackathon.

## Folder structure
```
data/       risk_data.json        ← Tech 1: zone data + risk inputs
frontend/   index.html, map.js, style.css  ← Tech 2: Leaflet map, slider, UI
backend/    alerts.py, requirements.txt    ← Tech 3: Twilio SMS alerts
```

## Quick start — run the map (Tech 2 / anyone)
The map loads `data/risk_data.json` via `fetch()`, which browsers block on
`file://` URLs. Run a local server from the **repo root**:

```bash
python -m http.server 8000
```
Then open: `http://localhost:8000/frontend/index.html`

(Or use VS Code's "Live Server" extension — right-click `frontend/index.html` → "Open with Live Server".)

## What's already working
- Leaflet map centered on a sample NER district
- 15 sample zones plotted, color-coded Low/Medium/High
- Rainfall slider that recalculates risk live and recolors zones
- Click a zone → detail card with slope, rainfall, soil moisture, score
- "Simulate Alert" button → shows an alert banner (UI only, not wired to SMS yet)

## Where each person edits

**Tech 1 (Data & Risk Engine)**
Edit `data/risk_data.json` — replace sample zones with real district data.
Tune the risk formula in `frontend/map.js` → `calculateRisk()`. Keep the
same return shape (`{ score, label }`) and everything downstream keeps working.

**Tech 2 (Frontend Map)**
Everything in `frontend/`. The slider, popup, and legend are wired — extend
`renderZones()` in `map.js` for new visuals (e.g. evacuation route lines).

**Tech 3 (Alerts & Integration)**
1. `cd backend && pip install -r requirements.txt`
2. `cp ../.env.example ../.env` and fill in real Twilio credentials
3. Test manually: `python alerts.py` (edit the test number first)
4. To wire it to the frontend button:
   - Run `python alerts.py --server` (starts a Flask endpoint on port 5000)
   - In `frontend/map.js`, inside `wireAlertButton()`, replace the banner-only
     code with a `fetch("http://localhost:5000/send-alert", {...})` call
     (a commented example is already in that function)

## Git workflow
```bash
git pull                      # before starting work
# ... make changes ...
git add .
git commit -m "what you did"
git push                      # share your work
```

## Notes
- Risk formula is rule-based (rainfall + slope + soil moisture, weighted).
  Swap for a trained ML model later without touching the frontend, as long
  as the output shape stays `{ score: number, label: "Low"|"Medium"|"High" }`.
- Never commit `.env` — it's already in `.gitignore`.
