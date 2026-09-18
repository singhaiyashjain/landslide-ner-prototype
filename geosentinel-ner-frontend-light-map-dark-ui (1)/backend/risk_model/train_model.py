"""
train_model.py — trains the GeoSentinel risk-scoring model.

Uses scikit-learn's GradientBoostingClassifier: no extra native
dependencies to install beyond requirements.txt, so it runs the same on
everyone's laptop without fighting compiler toolchains the night before a
demo. If your team wants to swap in XGBoost/LightGBM later, only this file
and features.py need to change — server.py just calls model.predict_proba().
"""

import json
import os

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report

from data_gen import generate_dataset
from features import FEATURES

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")


def main():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    df = generate_dataset()
    df.to_csv(os.path.join(ARTIFACTS_DIR, "synthetic_khasi_hills_dataset.csv"), index=False)

    X = df[FEATURES]
    y = df["landslide_occurred"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = GradientBoostingClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.05,
        subsample=0.85, random_state=42,
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    preds = (proba >= 0.5).astype(int)
    auc = roc_auc_score(y_test, proba)
    acc = accuracy_score(y_test, preds)
    report = classification_report(y_test, preds, output_dict=True)

    print(f"[train_model] test AUC={auc:.3f}  accuracy={acc:.3f}")

    joblib.dump(model, os.path.join(ARTIFACTS_DIR, "risk_model.joblib"))

    meta = {
        "features": FEATURES,
        "test_auc": round(float(auc), 4),
        "test_accuracy": round(float(acc), 4),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "classification_report": report,
        "feature_means": {f: round(float(X_train[f].mean()), 3) for f in FEATURES},
        "feature_stds": {f: round(float(X_train[f].std()), 3) for f in FEATURES},
    }
    with open(os.path.join(ARTIFACTS_DIR, "model_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"[train_model] saved model + model_meta.json -> {ARTIFACTS_DIR}")


if __name__ == "__main__":
    main()
