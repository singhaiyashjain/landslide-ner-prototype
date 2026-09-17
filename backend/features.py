"""
features.py — shared feature schema + a lightweight "why" explanation.

We deliberately avoid a hard dependency on the `shap` package: it's a heavy
install and one more thing that can fail on someone's laptop the night
before a demo. Instead compute_contributions() gives an approximate,
human-readable breakdown using the trained model's own feature importances
weighted by how far each zone's value sits from the training mean. It's not
as rigorous as real SHAP values, but it answers the judges' question
("why is this zone flagged?") which is what actually matters for the demo.

If you later want real SHAP (e.g. `pip install shap`), swap the body of
compute_contributions() for a shap.TreeExplainer call — everything else
(the API response shape) stays the same.
"""

FEATURES = [
    "slope_deg",
    "rainfall_mm",
    "soil_moisture_pct",
    "seismic_activity",
    "vegetation_cover_pct",
    "human_activity_index",
    "insar_deformation_mm_yr",
]

FEATURE_LABELS = {
    "slope_deg": "Slope steepness",
    "rainfall_mm": "Rainfall",
    "soil_moisture_pct": "Soil moisture",
    "seismic_activity": "Seismic activity",
    "vegetation_cover_pct": "Vegetation cover",
    "human_activity_index": "Human activity (roads/construction)",
    "insar_deformation_mm_yr": "Ground deformation (InSAR proxy)",
}

# Features where a HIGHER value is protective (reduces risk), so the sign
# of their contribution should be flipped when explaining "why risky".
PROTECTIVE_FEATURES = {"vegetation_cover_pct"}


def score_to_label(score_0_100: float) -> str:
    if score_0_100 >= 65:
        return "High"
    if score_0_100 >= 40:
        return "Medium"
    return "Low"


def compute_contributions(model, feature_row: dict, feature_means: dict, feature_stds: dict, top_n: int = 4):
    """
    Approximate per-feature contribution to this zone's risk, using the
    trained model's global feature_importances_ scaled by how unusual this
    zone's value is (z-score vs the training set). Returns a list of
    {feature, label, direction, magnitude} sorted by magnitude, largest first.
    """
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return []

    contributions = []
    for feat, importance in zip(FEATURES, importances):
        mean = feature_means.get(feat, 0.0)
        std = feature_stds.get(feat, 1.0) or 1.0
        value = feature_row.get(feat, mean)
        z = (value - mean) / std

        raises_risk = z > 0
        if feat in PROTECTIVE_FEATURES:
            raises_risk = not raises_risk

        magnitude = float(importance) * abs(float(z))
        contributions.append({
            "feature": feat,
            "label": FEATURE_LABELS.get(feat, feat),
            "value": round(float(value), 2),
            "direction": "increases" if raises_risk else "decreases",
            "magnitude": round(magnitude, 4),
        })

    contributions.sort(key=lambda c: c["magnitude"], reverse=True)
    return contributions[:top_n]
