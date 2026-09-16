/* ------------------------------------------------------------------
   GeoSentinel NER — prototype map logic
   Swap the risk formula or data source here without touching index.html
------------------------------------------------------------------- */

const DATA_URL = "../data/risk_data.json";
const ALERT_API = "http://localhost:5000";

let zoneData = null;
let markers = {}; // id -> leaflet layer
let selectedZoneId = null;
let map;

// ---------- Risk formula (rule-based; swap for ML output later) ----------
// Returns { score: 0-100, label: "Low"|"Medium"|"High" }
function calculateRisk(zone, rainfallOverride) {
  const rainfall = rainfallOverride != null ? rainfallOverride : zone.base_rainfall_mm;

  // Normalize each factor to 0-1
  const rainNorm = Math.min(rainfall / 250, 1);
  const slopeNorm = Math.min(zone.slope_deg / 50, 1);
  const soilNorm = Math.min(zone.soil_moisture_pct / 80, 1);

  // Weighted combination — tune these weights against real historical data
  const score = (rainNorm * 0.45 + slopeNorm * 0.30 + soilNorm * 0.25) * 100;

  let label = "Low";
  if (score >= 65) label = "High";
  else if (score >= 40) label = "Medium";

  return { score: Math.round(score), label };
}

function colorFor(label) {
  if (label === "High") return "#c0392b";
  if (label === "Medium") return "#e0a017";
  return "#2e7d32";
}

// ---------- Map setup ----------
function initMap(center) {
  map = L.map("map").setView([center.lat, center.lng], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
  }).addTo(map);
}

function renderZones(rainfallOverride) {
  let counts = { Low: 0, Medium: 0, High: 0 };

  zoneData.zones.forEach((zone) => {
    const risk = calculateRisk(zone, rainfallOverride);
    counts[risk.label]++;

    const color = colorFor(risk.label);

    if (markers[zone.id]) {
      markers[zone.id].setStyle({ fillColor: color, color: color });
      markers[zone.id]._riskData = risk;
    } else {
      const circle = L.circleMarker([zone.lat, zone.lng], {
        radius: 11,
        fillColor: color,
        color: color,
        weight: 2,
        fillOpacity: 0.75,
      }).addTo(map);

      circle._riskData = risk;
      circle._zone = zone;

      circle.on("click", () => selectZone(zone.id));
      markers[zone.id] = circle;
    }
  });

  updateStats(counts);
}

function selectZone(zoneId) {
  selectedZoneId = zoneId;
  const zone = zoneData.zones.find((z) => z.id === zoneId);
  const risk = markers[zoneId]._riskData;

  document.getElementById("selectedZoneCard").style.display = "block";
  document.getElementById("zoneDetails").innerHTML = `
    <div><b>${zone.name}</b></div>
    <div>Risk: <b style="color:${colorFor(risk.label)}">${risk.label}</b> (score ${risk.score})</div>
    <div>Slope: ${zone.slope_deg}°</div>
    <div>Rainfall: ${zone.base_rainfall_mm} mm</div>
    <div>Soil moisture: ${zone.soil_moisture_pct}%</div>
  `;
  document.getElementById("alertBanner").style.display = "none";
}

function updateStats(counts) {
  document.getElementById("statsRow").innerHTML = `
    <div class="stat-item"><div class="stat-num" style="color:#2e7d32">${counts.Low}</div><div class="stat-label">Low</div></div>
    <div class="stat-item"><div class="stat-num" style="color:#e0a017">${counts.Medium}</div><div class="stat-label">Medium</div></div>
    <div class="stat-item"><div class="stat-num" style="color:#c0392b">${counts.High}</div><div class="stat-label">High</div></div>
  `;
}

// ---------- Slider ----------
function wireSlider() {
  const slider = document.getElementById("rainfallSlider");
  const val = document.getElementById("rainfallVal");

  slider.addEventListener("input", () => {
    val.textContent = slider.value;
    renderZones(Number(slider.value));
    if (selectedZoneId) selectZone(selectedZoneId); // refresh detail card too
  });
}

// ---------- Alert button ----------
// Wired to backend/alerts.py. That server auto-detects whether real
// Twilio credentials are configured: if so it sends a real SMS, if not
// (or if the call fails) it returns a "simulated" result instead of
// erroring out. Either way we get a real response to show, and the
// alert gets logged so /alerts can feed the "Recent Alerts" panel.
function wireAlertButton() {
  document.getElementById("alertBtn").addEventListener("click", async () => {
    if (!selectedZoneId) return;
    const zone = zoneData.zones.find((z) => z.id === selectedZoneId);
    const risk = markers[selectedZoneId]._riskData;
    const toNumber = document.getElementById("alertPhone").value.trim();

    const banner = document.getElementById("alertBanner");
    banner.style.display = "block";
    banner.innerHTML = `Sending alert for <b>${zone.name}</b>…`;

    try {
      const res = await fetch(`${ALERT_API}/send-alert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to_number: toNumber || null,
          zone: zone.name,
          risk: risk.label,
          score: risk.score,
        }),
      });
      const result = await res.json();
      renderAlertResult(banner, result);
      loadAlertFeed();
    } catch (err) {
      // Backend not running / network issue — don't leave the demo hanging.
      banner.innerHTML = `⚠️ Could not reach the alert server at ${ALERT_API}.<br>
        Start it with <code>python alerts.py --server</code> in the backend folder.<br>
        <em>${err.message}</em>`;
    }
  });
}

function renderAlertResult(banner, result) {
  const statusLabel =
    result.status === "sent"
      ? "✅ SENT (real SMS)"
      : result.status === "error-fallback"
      ? "⚠️ SIMULATED (Twilio call failed, fell back)"
      : "🔶 SIMULATED";

  banner.innerHTML = `${statusLabel} — <b>${result.zone}</b>, Risk: ${result.risk} (score ${result.score})<br>
    <span class="hint">${result.note}</span>`;
}

// ---------- Recent alerts feed (backend/alerts.py -> /alerts) ----------
async function loadAlertFeed() {
  const feed = document.getElementById("alertFeed");
  try {
    const res = await fetch(`${ALERT_API}/alerts`);
    const alerts = await res.json();
    if (!alerts.length) {
      feed.innerHTML = `<p class="hint">No alerts sent yet this session.</p>`;
      return;
    }
    feed.innerHTML = alerts
      .slice(0, 8)
      .map((a) => {
        const badgeClass = a.status === "sent" ? "sent" : "simulated";
        const time = new Date(a.timestamp).toLocaleTimeString();
        return `<div class="alert-feed-item">
          <span class="feed-badge ${badgeClass}">${a.status}</span>
          <b>${a.zone}</b> — ${a.risk} <span class="hint">${time}</span>
        </div>`;
      })
      .join("");
  } catch (err) {
    feed.innerHTML = `<p class="hint">Alert server offline — start backend/alerts.py --server to see live history.</p>`;
  }
}

async function checkBackendMode() {
  const badge = document.getElementById("backendMode");
  try {
    const res = await fetch(`${ALERT_API}/health`);
    const data = await res.json();
    badge.textContent = data.mode === "live" ? "LIVE" : "SIMULATION";
    badge.className = `mode-badge ${data.mode === "live" ? "live" : "sim"}`;
  } catch (err) {
    badge.textContent = "OFFLINE";
    badge.className = "mode-badge offline";
  }
}

// ---------- Boot ----------
async function boot() {
  const res = await fetch(DATA_URL);
  zoneData = await res.json();

  initMap(zoneData.center);
  renderZones();
  wireSlider();
  wireAlertButton();
  checkBackendMode();
  loadAlertFeed();
}

boot().catch((err) => {
  document.getElementById("map").innerHTML =
    '<p style="padding:20px;color:#c0392b;">Could not load risk_data.json. ' +
    "If you opened this file directly (file://), start a local server instead:<br><br>" +
    "<code>python -m http.server 8000</code> or use VS Code's Live Server extension, " +
    "then open <code>http://localhost:8000/frontend/index.html</code></p>";
  console.error(err);
});
