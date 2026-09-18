/* ===================================================================
   GeoSentinel NER — frontend logic (Tech 2)

   Everything here is computed client-side from data/risk_data.json.
   calculateRisk() is a rule-based stand-in for the real ML model that
   Tech 1 is training separately (see backend/risk_model/). As long as
   that model's API returns the same { score, label, factors } shape,
   swapping calculateRisk() for a fetch() call is the only change needed.
   =================================================================== */

const DATA_URL = "../data/risk_data.json";

const FEATURE_META = {
  rainfall_mm:              { label: "Rainfall",           weight: 0.22, min: 0,  max: 300, protective: false },
  slope_deg:                { label: "Slope steepness",    weight: 0.20, min: 0,  max: 70,  protective: false },
  soil_moisture_pct:        { label: "Soil moisture",      weight: 0.16, min: 0,  max: 100, protective: false },
  insar_deformation_mm_yr:  { label: "Ground deformation", weight: 0.14, min: -2, max: 40,  protective: false },
  seismic_activity:         { label: "Seismic activity",   weight: 0.14, min: 0,  max: 9,   protective: false },
  human_activity_index:     { label: "Human activity",     weight: 0.08, min: 0,  max: 100, protective: false },
  vegetation_cover_pct:     { label: "Vegetation cover",   weight: 0.12, min: 0,  max: 100, protective: true },
};

const LAYER_META = {
  risk:       { label: "Risk level",       unit: "",   key: null },
  rainfall:   { label: "Rainfall",         unit: "mm", key: "rainfall_mm" },
  soil:       { label: "Soil moisture",    unit: "%",  key: "soil_moisture_pct" },
  seismic:    { label: "Seismic activity", unit: "",   key: "seismic_activity" },
  vegetation: { label: "Vegetation cover", unit: "%",  key: "vegetation_cover_pct" },
};

let map, zoneLayer, infraLayer, safeLayer, evacLine, reportLayer;
let siteData = null;
let currentRainfall = 100;
let currentLayer = "risk";
let infraOn = false;
let reportMode = false;
let pendingReportLatLng = null;
let selectedZoneId = null;
let activityLog = [];
let markersById = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  wireLayerRail();
  wireSlider();
  wireReportFlow();
  wireDetailPanel();

  try {
    const res = await fetch(DATA_URL);
    siteData = await res.json();
  } catch (err) {
    console.error("Could not load risk_data.json — is this served over http(s)? See README.", err);
    document.getElementById("detailEmpty").textContent =
      "Could not load data/risk_data.json. Run this from a local server (see README), not a file:// URL.";
    return;
  }

  initMap();
  recomputeAll();
  renderLegend();
  tickSyncTime();
  setInterval(tickSyncTime, 30000);
}

/* ---------------------- risk model (client-side stand-in) ---------------------- */

function normalize(value, min, max) {
  const n = (value - min) / (max - min);
  return Math.max(0, Math.min(1, n));
}

function calculateRisk(zone, rainfallOverride) {
  const featureRow = {
    rainfall_mm: rainfallOverride != null ? rainfallOverride : zone.base_rainfall_mm,
    slope_deg: zone.slope_deg,
    soil_moisture_pct: zone.soil_moisture_pct,
    insar_deformation_mm_yr: zone.insar_deformation_mm_yr,
    seismic_activity: zone.seismic_activity,
    human_activity_index: zone.human_activity_index,
    vegetation_cover_pct: zone.vegetation_cover_pct,
  };

  let raw = 0;
  const factors = [];

  for (const [key, meta] of Object.entries(FEATURE_META)) {
    const value = featureRow[key];
    const norm = normalize(value, meta.min, meta.max);
    const contribution = meta.protective ? -meta.weight * norm : meta.weight * norm;
    raw += contribution;

    const distFromMid = (norm - 0.5) * 2; // -1..1
    const raises = meta.protective ? distFromMid < 0 : distFromMid > 0;
    factors.push({
      feature: key,
      label: meta.label,
      value,
      direction: raises ? "increases" : "decreases",
      magnitude: Math.abs(distFromMid) * meta.weight,
    });
  }

  // Calibrated so real zone data spans the full Low->High range as the
  // rainfall slider moves, instead of clustering in the middle. FLOOR/CEIL
  // were picked by checking the actual raw score range across all 15
  // zones at rainfall 0-300mm (see repo notes) -- retune if you add zones
  // with very different characteristics.
  const FLOOR = 0.15, CEIL = 0.58;
  const score = Math.round(Math.max(0, Math.min(1, (raw - FLOOR) / (CEIL - FLOOR))) * 100);
  const label = score >= 65 ? "High" : score >= 40 ? "Medium" : "Low";
  factors.sort((a, b) => b.magnitude - a.magnitude);

  return { score, label, factors: factors.slice(0, 4), featureRow };
}

function riskColor(label) {
  return label === "High" ? "#E15B4F" : label === "Medium" ? "#D69E3A" : "#4C9A6B";
}

/* ---------------------- map setup ---------------------- */

function initMap() {
  map = L.map("map", { zoomControl: true }).setView(
    [siteData.center.lat, siteData.center.lng], 10
  );

  // Standard colorful OSM tiles, darkened via CSS filter (see style.css
  // `.leaflet-tile-pane`) so the map keeps its natural palette -- green
  // forest, blue water, warm roads -- just on a dark background, instead
  // of switching to a flat monochrome "dark" tile set that loses it.
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
    subdomains: "abc",
  }).addTo(map);

  zoneLayer = L.layerGroup().addTo(map);
  infraLayer = L.layerGroup();
  safeLayer = L.layerGroup().addTo(map);
  reportLayer = L.layerGroup().addTo(map);

  siteData.safe_points.forEach((sp) => {
    L.marker([sp.lat, sp.lng], {
      icon: L.divIcon({ className: "", html: '<div class="safe-dot"></div>', iconSize: [12, 12] }),
    })
      .bindPopup(`<b>${sp.name}</b><br>Designated safe point`)
      .addTo(safeLayer);
  });

  (siteData.infrastructure || []).forEach((item) => {
    if (item.type === "road") {
      L.polyline(item.coords, { color: "#8A98A6", weight: 2, dashArray: "4 5", opacity: 0.8 })
        .bindPopup(`<b>${item.name}</b>`)
        .addTo(infraLayer);
    } else if (item.type === "hydro") {
      L.marker([item.lat, item.lng], {
        icon: L.divIcon({ className: "", html: '<div style="font-size:16px;">&#9889;</div>', iconSize: [20, 20] }),
      })
        .bindPopup(`<b>${item.name}</b><br>Hydropower site`)
        .addTo(infraLayer);
    }
  });

  map.on("click", (e) => {
    if (reportMode) openReportModal(e.latlng);
  });
}

function recomputeAll() {
  zoneLayer.clearLayers();
  markersById = {};

  let highCount = 0;

  siteData.zones.forEach((zone) => {
    const result = calculateRisk(zone, currentRainfall);
    zone._risk = result;
    if (result.label === "High") highCount++;

    const color = layerColor(zone, result);
    const isHigh = result.label === "High" && currentLayer === "risk";

    const marker = L.marker([zone.lat, zone.lng], {
      icon: L.divIcon({
        className: `zone-dot-wrap${isHigh ? " pulse-high" : ""}`,
        html: `<div class="zone-dot" style="background:${color}"></div>`,
        iconSize: [16, 16],
      }),
    });

    marker.on("click", () => selectZone(zone.id));
    marker.addTo(zoneLayer);
    markersById[zone.id] = marker;
  });

  document.getElementById("statZones").textContent = siteData.zones.length;
  document.getElementById("statHigh").textContent = highCount;
  document.getElementById("statSensors").textContent = siteData.zones.length;

  if (selectedZoneId) renderDetailPanel(selectedZoneId);
}

function layerColor(zone, riskResult) {
  if (currentLayer === "risk") return riskColor(riskResult.label);

  const meta = LAYER_META[currentLayer];
  const featMeta = FEATURE_META[meta.key];
  const value = zone[meta.key];
  const norm = normalize(value, featMeta ? featMeta.min : 0, featMeta ? featMeta.max : 100);
  if (norm > 0.66) return "#E15B4F";
  if (norm > 0.33) return "#D69E3A";
  return "#4C9A6B";
}

/* ---------------------- layer rail ---------------------- */

function wireLayerRail() {
  document.querySelectorAll(".layer-btn[data-layer]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".layer-btn[data-layer]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentLayer = btn.dataset.layer;
      if (siteData) {
        recomputeAll();
        renderLegend();
      }
    });
  });

  document.getElementById("infraToggle").addEventListener("click", (e) => {
    infraOn = !infraOn;
    e.currentTarget.classList.toggle("on", infraOn);
    if (infraOn) {
      infraLayer.addTo(map);
    } else {
      map.removeLayer(infraLayer);
    }
  });

  document.getElementById("reportToggle").addEventListener("click", () => {
    setReportMode(!reportMode);
  });
}

function renderLegend() {
  const el = document.getElementById("mapLegend");
  const meta = LAYER_META[currentLayer];
  if (currentLayer === "risk") {
    el.innerHTML = `
      <div class="legend-title">RISK LEVEL</div>
      <div class="legend-row"><span class="dot low"></span>Low</div>
      <div class="legend-row"><span class="dot medium"></span>Medium</div>
      <div class="legend-row"><span class="dot high"></span>High</div>
    `;
  } else {
    el.innerHTML = `
      <div class="legend-title">${meta.label.toUpperCase()}${meta.unit ? " (" + meta.unit + ")" : ""}</div>
      <div class="legend-row"><span class="dot legend-a"></span>Low</div>
      <div class="legend-row"><span class="dot legend-b"></span>Moderate</div>
      <div class="legend-row"><span class="dot legend-c"></span>Elevated</div>
    `;
  }
}

/* ---------------------- rainfall slider ---------------------- */

function wireSlider() {
  const slider = document.getElementById("rainfallSlider");
  const val = document.getElementById("rainfallVal");
  slider.addEventListener("input", () => {
    currentRainfall = Number(slider.value);
    val.textContent = currentRainfall;
    if (siteData) recomputeAll();
  });
}

/* ---------------------- zone detail panel ---------------------- */

function wireDetailPanel() {
  document.getElementById("detailPanel").addEventListener("click", (e) => {
    if (e.target.id === "closePanelBtn") closeDetailPanel();
    if (e.target.id === "sendSmsBtn") triggerAlert("sms");
    if (e.target.id === "triggerIvrBtn") triggerAlert("ivr");
    if (e.target.id === "reportHereBtn") {
      const zone = siteData.zones.find((z) => z.id === selectedZoneId);
      if (zone) openReportModal({ lat: zone.lat, lng: zone.lng });
    }
  });
}

function selectZone(zoneId) {
  selectedZoneId = zoneId;
  renderDetailPanel(zoneId);
  document.getElementById("detailPanel").classList.add("open");
  document.getElementById("detailEmpty").style.display = "none";
  document.getElementById("detailInner").style.display = "block";
  drawEvacRoute(zoneId);
}

function closeDetailPanel() {
  selectedZoneId = null;
  document.getElementById("detailPanel").classList.remove("open");
  if (evacLine) { map.removeLayer(evacLine); evacLine = null; }
}

function renderDetailPanel(zoneId) {
  const zone = siteData.zones.find((z) => z.id === zoneId);
  if (!zone) return;
  const { score, label, factors, featureRow } = zone._risk;

  const factorsHtml = factors.map((f) => `
    <div class="factor-row ${f.direction === "increases" ? "up" : "down"}">
      <span class="factor-dir">${f.direction === "increases" ? "&#9650;" : "&#9660;"}</span>
      <span class="factor-name">${f.label}</span>
      <div class="factor-bar-track"><div class="factor-bar-fill" style="width:${Math.min(100, f.magnitude * 400)}%"></div></div>
    </div>
  `).join("");

  const safe = siteData.safe_points.find((s) => s.id === zone.nearest_safe);

  document.getElementById("detailInner").innerHTML = `
    <div class="zone-header">
      <h2>${zone.name}</h2>
      <button class="close-panel" id="closePanelBtn">&times;</button>
    </div>
    <div class="zone-coords">${zone.lat.toFixed(4)}, ${zone.lng.toFixed(4)}</div>

    <div class="risk-badge ${label}">
      <span class="score">${score}</span>
      <span class="label">${label} risk</span>
    </div>

    <div class="section-label">WHY FLAGGED</div>
    ${factorsHtml}

    <div class="section-label">CURRENT READINGS</div>
    <div class="readings-grid">
      <div class="reading"><div class="r-val">${featureRow.rainfall_mm} mm</div><div class="r-label">Rainfall (event)</div></div>
      <div class="reading"><div class="r-val">${zone.slope_deg}&deg;</div><div class="r-label">Slope</div></div>
      <div class="reading"><div class="r-val">${zone.soil_moisture_pct}%</div><div class="r-label">Soil moisture</div></div>
      <div class="reading"><div class="r-val">${zone.seismic_activity}</div><div class="r-label">Seismic index</div></div>
      <div class="reading"><div class="r-val">${zone.vegetation_cover_pct}%</div><div class="r-label">Vegetation cover</div></div>
      <div class="reading"><div class="r-val">${zone.insar_deformation_mm_yr} mm/yr</div><div class="r-label">Ground deformation</div></div>
    </div>

    ${safe ? `
    <div class="section-label">EVACUATION ROUTE</div>
    <div class="evac-note">Nearest designated safe point: <b>${safe.name}</b>, shown as a dashed line on the map.</div>
    ` : ""}

    <div class="section-label">ALERTS</div>
    <div class="action-row">
      <button class="btn primary" id="sendSmsBtn">Send SMS alert</button>
      <button class="btn" id="triggerIvrBtn">Trigger IVR call</button>
    </div>
    <button class="btn ghost full" id="reportHereBtn" style="margin-top:8px;">Report ground condition here</button>
    <div class="inline-status" id="alertStatus"></div>
  `;
}

function drawEvacRoute(zoneId) {
  if (evacLine) { map.removeLayer(evacLine); evacLine = null; }
  const zone = siteData.zones.find((z) => z.id === zoneId);
  const safe = siteData.safe_points.find((s) => s.id === zone?.nearest_safe);
  if (!zone || !safe) return;
  evacLine = L.polyline(
    [[zone.lat, zone.lng], [safe.lat, safe.lng]],
    { color: "#4FD1C5", weight: 2.5, dashArray: "6 6", opacity: 0.85 }
  ).addTo(map);
}

/* ---------------------- alerts (simulated) ---------------------- */

function triggerAlert(channel) {
  const zone = siteData.zones.find((z) => z.id === selectedZoneId);
  if (!zone) return;
  const { score, label } = zone._risk;

  const statusEl = document.getElementById("alertStatus");
  if (channel === "sms") {
    statusEl.textContent = `SMS simulated \u2014 alert for ${zone.name} (${label}, score ${score}) sent to district control room.`;
    logEvent("&#128231;", `SMS alert simulated for ${zone.name}`);
  } else {
    statusEl.textContent = `IVR simulated \u2014 automated voice call placed to the local ward office for ${zone.name}.`;
    logEvent("&#9742;", `IVR call simulated for ${zone.name}`);
  }
  statusEl.classList.add("show");
}

/* ---------------------- community reporting ---------------------- */

function wireReportFlow() {
  document.getElementById("cancelReportMode").addEventListener("click", () => setReportMode(false));
  document.getElementById("reportCancelBtn").addEventListener("click", closeReportModal);
  document.getElementById("reportSubmitBtn").addEventListener("click", submitReport);
}

function setReportMode(on) {
  reportMode = on;
  document.getElementById("reportToggle").classList.toggle("on", on);
  document.getElementById("reportBanner").classList.toggle("active", on);
}

function openReportModal(latlng) {
  pendingReportLatLng = latlng;
  document.getElementById("reportModalCoords").textContent = `${latlng.lat.toFixed(4)}, ${latlng.lng.toFixed(4)}`;
  document.getElementById("reportModalBackdrop").classList.add("open");
}

function closeReportModal() {
  document.getElementById("reportModalBackdrop").classList.remove("open");
  pendingReportLatLng = null;
}

function submitReport() {
  if (!pendingReportLatLng) return;
  const type = document.getElementById("reportType").value;
  const notes = document.getElementById("reportNotes").value.trim();

  L.marker([pendingReportLatLng.lat, pendingReportLatLng.lng], {
    icon: L.divIcon({ className: "", html: '<div class="report-marker" style="width:14px;height:14px;"></div>', iconSize: [14, 14] }),
  })
    .bindPopup(`<b>${type}</b>${notes ? "<br>" + notes : ""}`)
    .addTo(reportLayer);

  logEvent("&#128204;", `Community report: ${type}`);

  document.getElementById("reportNotes").value = "";
  closeReportModal();
  setReportMode(false);
}

/* ---------------------- activity log ---------------------- */

function logEvent(iconHtml, text) {
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  activityLog.unshift({ time, iconHtml, text });
  activityLog = activityLog.slice(0, 20);
  renderLog();
}

function renderLog() {
  const el = document.getElementById("logList");
  if (activityLog.length === 0) {
    el.innerHTML = '<div class="log-empty">No activity yet.</div>';
    return;
  }
  el.innerHTML = activityLog.map((entry) => `
    <div class="log-entry">
      <span class="log-time">${entry.time}</span>
      <span class="log-icon">${entry.iconHtml}</span>
      <span>${entry.text}</span>
    </div>
  `).join("");
}

/* ---------------------- sync clock ---------------------- */

function tickSyncTime() {
  const el = document.getElementById("syncTime");
  const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  el.textContent = `synced ${now}`;
}
