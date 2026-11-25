"""Import recorded cross-validation and holdout results into local MLflow."""

import csv
import json
import os
from hashlib import sha256
from pathlib import Path

import mlflow
from filelock import FileLock
from mlflow import MlflowClient

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".mlflow"
TRACKING_URI = "http://127.0.0.1:5000"
EXPERIMENT = "IndustryPulseAI"
CV_REPORT = "mlp/model_comparison.csv"
CLASSICAL_REPORT = "model_comparison.csv"
TEST_REPORT = "test_metrics.csv"

# MLflow's URL banners contain emoji that redirected Windows consoles may not encode.
os.environ.setdefault("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT", "true")
os.environ.setdefault("MLFLOW_PRINT_MODEL_URLS_ON_CREATION", "false")


def operation_lock(name):
    STATE.mkdir(exist_ok=True)
    return FileLock(STATE / f"{name}.lock", timeout=120)


def csv_rows(name):
    with (ROOT / "results" / name).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def model_parameters():
    from src.mlp_model import FailureMLP
    from src.train_mlp import BATCH_SIZE, EPOCHS, LEARNING_RATE, SEED, THRESHOLD
    from src.train_models import build_models

    models = {
        name: {key: value for key, value in pipeline.named_steps["classifier"].get_params().items()
               if value is not None}
        for name, pipeline in build_models().items()
    }
    models["XGBoost"]["sample_weighting"] = "balanced within each training fold"
    models["MLP"] = {
        "architecture": "-".join(map(str, (FailureMLP.INPUT_SIZE, *FailureMLP.HIDDEN_SIZES, 1))),
        "activation": "ReLU", "loss": "BCEWithLogitsLoss", "optimizer": "Adam",
        "batch_size": BATCH_SIZE, "epochs": EPOCHS, "learning_rate": LEARNING_RATE,
        "base_seed": SEED, "classification_threshold": THRESHOLD,
        "positive_weight": "negative / positive within each training fold",
    }
    return models


def import_runs(uri=TRACKING_URI):
    mlflow.set_tracking_uri(uri)
    client = MlflowClient(tracking_uri=uri)
    with operation_lock("import"):
        experiment = client.get_experiment_by_name(EXPERIMENT)
        experiment_id = experiment.experiment_id if experiment else client.create_experiment(EXPERIMENT)
        classical = {row["model"]: row for row in csv_rows(CLASSICAL_REPORT)}
        parameters = model_parameters()
        cross_validation = csv_rows(CV_REPORT)
        if len(cross_validation) != 7 or {row["model"] for row in cross_validation} != set(parameters):
            raise ValueError("Doğrulanmış yedi model satırı bulunamadı.")
        holdout, = csv_rows(TEST_REPORT)
        if holdout["model"] != "XGBoost":
            raise ValueError("Bağımsız test kaydında XGBoost bekleniyor.")
        imported = {}
        for row, split, report in [
            *((row, "cross_validation", CV_REPORT) for row in cross_validation),
            (holdout, "independent_test", TEST_REPORT),
        ]:
            name = row["model"]
            source = dict(row)
            if split == "cross_validation" and name in classical:
                source = {**classical[name], **source}
            metrics = {key: float(value) for key, value in source.items()
                       if key != "model" and value.strip()}
            artifact_names = [report]
            if split == "independent_test":
                artifact_names += ["confusion_matrix.png", "roc_curve.png", "precision_recall_curve.png"]
            elif name == "MLP":
                artifact_names += ["mlp_metrics.csv", "mlp/training_history.csv", "mlp/architecture.png",
                                   "mlp/training_loss.png", "mlp/validation_performance.png",
                                   "mlp/roc_curve.png", "mlp/precision_recall_curve.png"]
            common = {
                "dataset": "UCI AI4I 2020", "synthetic": True, "dataset_rows": 10000,
                "training_rows": 8000, "holdout_rows": 2000, "failure_rows": 339,
                "split_seed": 42, "stratified_split": True,
            }
            if split == "cross_validation":
                common["validation_folds"] = 5
            else:
                common["classification_threshold"] = 0.5
            params = {**common, **parameters[name]}
            if split == "independent_test":
                params["sample_weighting"] = "balanced across the complete training set"
            identity = sha256(json.dumps([split, name, metrics, params], sort_keys=True, default=str).encode()).hexdigest()
            previous = client.search_runs([experiment_id], f"tags.import_key = '{identity}'", max_results=1)
            saved = previous[0] if previous else None
            if saved is not None and saved.info.status == "FINISHED":
                run_id = saved.info.run_id
            else:
                with mlflow.start_run(run_id=saved.info.run_id if saved else None,
                                      experiment_id=experiment_id, run_name=f"{name} · {split}", tags={
                    "origin": "imported", "evaluation_split": split, "model_name": name,
                    "source_report": f"results/{report}", "import_key": identity,
                }) as run:
                    mlflow.log_params(params)
                    recorded = saved.data.metrics if saved else {}
                    mlflow.log_metrics({key: value for key, value in metrics.items() if recorded.get(key) != value})
                    for artifact in artifact_names:
                        mlflow.log_artifact(str(ROOT / "results" / artifact), "source")
                    if split == "cross_validation":
                        mlflow.log_artifact(str(ROOT / "results/mlp/model_comparison.png"), "shared_comparison")
                        if name in classical:
                            mlflow.log_artifact(str(ROOT / "results" / CLASSICAL_REPORT), "classical_source")
                    run_id = run.info.run_id
            imported[(name, split)] = run_id
        return imported


if __name__ == "__main__":
    for (name, split), run_id in import_runs().items():
        print(f"{name} / {split}: {run_id}")
