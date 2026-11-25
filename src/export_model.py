"""Fit the selected XGBoost pipeline and export trusted local artifacts."""

import json
import platform
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
import numpy as np
import pandas as pd

from src.preprocessing import FEATURES, split_data

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
PIPELINE_FILE = MODELS / "xgboost_pipeline.joblib"
METADATA_FILE = MODELS / "model_metadata.json"
MODEL_NAME = "XGBoost"
MODEL_VERSION = "1.0.0"
THRESHOLD = 0.5


def previous_metrics():
    sources = {
        "cross_validation": ROOT / "results/model_comparison.csv",
        "independent_test": ROOT / "results/test_metrics.csv",
    }
    metrics = {}
    for name, path in sources.items():
        table = pd.read_csv(path)
        row = table.loc[table["model"].eq(MODEL_NAME)].drop(columns="model")
        if len(row) != 1:
            raise ValueError(f"{path.name} dosyasında bir XGBoost sonucu bekleniyordu.")
        metrics[name] = {"source": path.relative_to(ROOT).as_posix(), **row.to_dict("records")[0]}
    metrics["cross_validation"]["folds"] = 5
    metrics["independent_test"]["records"] = 2_000
    return metrics


def export_model():
    from src.train_models import build_models, fit_model, load_training_data

    X, y = load_training_data()
    X_train, _, y_train, _ = split_data(X, y)
    model, _ = fit_model(build_models()[MODEL_NAME], X_train, y_train)
    trained_at = datetime.now(timezone.utc)
    parameters = model.named_steps["classifier"].get_params()
    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "trained_at": trained_at.isoformat(),
        "input_features": FEATURES,
        "training_records": len(y_train),
        "hyperparameters": {
            key: "NaN" if isinstance(value, float) and np.isnan(value) else value
            for key, value in parameters.items() if value is not None
        },
        "class_weighting": "balanced sample weights calculated from the 8,000 training records",
        "decision_threshold": THRESHOLD,
        "decision_rule": "failure_score > decision_threshold",
        "library_versions": {
            "python": platform.python_version(),
            **{name: version(name) for name in ("joblib", "numpy", "pandas", "scipy", "scikit-learn", "xgboost")},
        },
        "dataset": {
            "name": "AI4I 2020 Predictive Maintenance Dataset",
            "source": "public.ml_training_data",
            "synthetic": True,
            "records": len(y),
            "failures": int(y.sum()),
            "training_failures": int(y_train.sum()),
            "split": {"test_size": 0.2, "stratified": True, "random_state": 42},
        },
        "previous_metrics": previous_metrics(),
        "limitations": [
            "Veri seti sentetiktir ve sonuçlar gerçek fabrikalardaki performansı garanti etmez.",
            "XGBoost skoru kalibre edilmiş gerçek dünya arıza olasılığı değildir.",
        ],
    }
    MODELS.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=MODELS) as folder:
        model_path = Path(folder) / PIPELINE_FILE.name
        metadata_path = Path(folder) / METADATA_FILE.name
        joblib.dump(model, model_path, compress=3)
        reloaded = joblib.load(model_path)
        np.testing.assert_array_equal(model.predict(X_train), reloaded.predict(X_train))
        np.testing.assert_array_equal(model.predict_proba(X_train), reloaded.predict_proba(X_train))
        metadata["artifact_sha256"] = sha256(model_path.read_bytes()).hexdigest()
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        model_path.replace(PIPELINE_FILE)
        metadata_path.replace(METADATA_FILE)
    print(f"Pipeline kaydedildi. {len(y_train)} eğitim satırının sınıfları ve skorları birebir eşleşti.")


if __name__ == "__main__":
    export_model()
