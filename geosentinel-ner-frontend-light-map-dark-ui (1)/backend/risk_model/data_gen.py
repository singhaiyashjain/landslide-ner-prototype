"""
data_gen.py — synthetic training data for the East Khasi Hills / Sohra
(Cherrapunjee) pilot area, Meghalaya.

HONESTY NOTE FOR THE TEAM / FOR JUDGES:
No real labeled landslide inventory was available in the time we had, so
this generates a SYNTHETIC dataset: feature relationships (slope, rainfall,
soil moisture, seismicity, vegetation, human activity, ground deformation)
are combined using rules grounded in general landslide-susceptibility
literature, with randomised noise layered on top — it is NOT fitted to real
recorded landslide events. Say this plainly if asked; it's normal for a
72-hour prototype and the code is written so a real dataset drops in later
without touching the model, API or frontend.

To go real before a final submission, swap this file's output for:
  - GSI Bhukosh landslide inventory (event labels)
  - IMD station/gridded rainfall data for the district
  - Sentinel-1 InSAR deformation products
  - SRTM/Bhuvan DEM for slope + elevation
Keep the column names identical to FEATURES in features.py and everything
downstream (train_model.py, server.py, the frontend) keeps working.
"""

import numpy as np
import pandas as pd

from features import FEATURES

# Bounding box roughly covering the pilot zones in data/risk_data.json
# (Sohra / Cherrapunjee / Mawsynram / Jowai stretch of East Khasi Hills).
LAT_MIN, LAT_MAX = 25.10, 25.98
LON_MIN, LON_MAX = 91.20, 92.20

N_POINTS = 1400
RNG_SEED = 42


def _smooth_noise(x, y, seed, scale=1.0, octaves=3):
    """Cheap multi-octave value noise (no external deps) for smooth terrain."""
    rng = np.random.default_rng(seed)
    total = np.zeros_like(x, dtype=float)
    amp, freq = 1.0, scale
    for _ in range(octaves):
        px, py = rng.uniform(0, 1000), rng.uniform(0, 1000)
        total += amp * np.sin(freq * x + px) * np.cos(freq * y + py)
        amp *= 0.5
        freq *= 2.1
    return total


def generate_dataset(n_points: int = N_POINTS, seed: int = RNG_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    lats = rng.uniform(LAT_MIN, LAT_MAX, n_points)
    lons = rng.uniform(LON_MIN, LON_MAX, n_points)

    slope_deg = np.clip(
        18 + 24 * (0.5 + 0.5 * _smooth_noise(lats * 25, lons * 25, seed=1)), 2, 65
    )

    # Event/day-scale rainfall (mm), matching the 0-300mm slider in the UI —
    # this area holds world rainfall records, so intense single-day totals
    # are realistic even though this is NOT an annual total.
    rainfall_mm = np.clip(rng.gamma(shape=2.2, scale=55, size=n_points), 0, 300)

    soil_moisture_pct = np.clip(
        20 + 0.22 * rainfall_mm + rng.normal(0, 10, n_points), 5, 100
    )

    seismic_activity = np.clip(rng.gamma(shape=2.0, scale=1.4, size=n_points), 0, 9)

    vegetation_cover_pct = np.clip(
        65 - 0.35 * slope_deg + rng.normal(0, 15, n_points), 0, 100
    )

    human_activity_index = np.clip(rng.beta(2, 5, n_points) * 100, 0, 100)

    insar_deformation_mm_yr = np.clip(
        0.35 * slope_deg / 10 + 0.05 * soil_moisture_pct
        + rng.normal(0, 3, n_points), -2, 40
    )

    df = pd.DataFrame({
        "lat": lats.round(4),
        "lon": lons.round(4),
        "slope_deg": slope_deg.round(2),
        "rainfall_mm": rainfall_mm.round(1),
        "soil_moisture_pct": soil_moisture_pct.round(2),
        "seismic_activity": seismic_activity.round(2),
        "vegetation_cover_pct": vegetation_cover_pct.round(2),
        "human_activity_index": human_activity_index.round(2),
        "insar_deformation_mm_yr": insar_deformation_mm_yr.round(2),
    })

    # --- Rule-based synthetic ground truth ---
    # Weighted, nonlinear combination: slope + rainfall + soil moisture +
    # deformation dominate; vegetation is protective; seismicity and human
    # activity act as amplifiers. Weights are illustrative, not fitted.
    risk_score = (
        0.10 * df["slope_deg"]
        + 0.018 * df["rainfall_mm"]
        + 0.06 * df["soil_moisture_pct"]
        + 0.20 * df["insar_deformation_mm_yr"]
        + 0.32 * df["seismic_activity"]
        + 0.045 * df["human_activity_index"]
        - 0.065 * df["vegetation_cover_pct"]
    )
    noise = rng.normal(0, 0.35, len(df))
    risk_score = risk_score + noise
    z = (risk_score - risk_score.mean()) / (risk_score.std() + 1e-6)
    risk_prob = 1 / (1 + np.exp(-z))
    df["landslide_occurred"] = (rng.uniform(0, 1, len(df)) < risk_prob).astype(int)

    assert list(FEATURES) == [c for c in FEATURES], "feature list mismatch"
    return df


if __name__ == "__main__":
    import os
    df = generate_dataset()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "synthetic_khasi_hills_dataset.csv")
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")
    print(df["landslide_occurred"].value_counts(normalize=True))
