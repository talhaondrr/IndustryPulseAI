"""Register and verify a copy of the existing XGBoost pipeline."""

from importlib.metadata import version as package_version

import mlflow
import numpy as np
from mlflow import MlflowClient, sklearn
from mlflow.models import infer_signature

from api.services.prediction_service import PredictionService
from mlops.tracking import TRACKING_URI, import_runs, operation_lock
from src.preprocessing import split_data
from src.train_models import load_training_data

MODEL_NAME = "IndustryPulse-XGBoost"
ALIAS = "verified"


def register_pipeline(uri=TRACKING_URI):
    run_id = import_runs(uri)[("XGBoost", "cross_validation")]
    mlflow.set_registry_uri(uri)
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    service = PredictionService.load()
    metadata = service.metadata
    digest = metadata["artifact_sha256"]
    features, labels = load_training_data()
    train, _, _, _ = split_data(features, labels)
    expected = service.pipeline.predict(train)
    expected_scores = service.pipeline.predict_proba(train)

    with operation_lock("registry"):
        versions = client.search_model_versions(f"name = '{MODEL_NAME}'")
        existing = next((version for version in versions if version.tags.get("artifact_sha256") == digest), None)
        if existing is None:
            client.log_dict(run_id, metadata, "registry/deployment_metadata.json")
            logged = sklearn.log_model(
                service.pipeline, name="xgboost_pipeline", run_id=run_id,
                signature=infer_signature(train, expected),
                serialization_format="cloudpickle", pip_requirements=[
                    f"{name}=={version}" for name, version in metadata["library_versions"].items()
                    if name != "python"
                ] + [f"cloudpickle=={package_version('cloudpickle')}"],
                metadata={"deployment_model_version": metadata["model_version"], "artifact_sha256": digest},
            )
            existing = mlflow.register_model(logged.model_uri, MODEL_NAME, tags={
                "artifact_sha256": digest, "deployment_model_version": metadata["model_version"],
                "decision_threshold": str(metadata["decision_threshold"]),
                "dataset": metadata["dataset"]["name"], "synthetic": "true",
            })
        model_uri = f"models:/{MODEL_NAME}/{existing.version}"
        reloaded = sklearn.load_model(model_uri)
        np.testing.assert_array_equal(expected, reloaded.predict(train))
        np.testing.assert_array_equal(expected_scores, reloaded.predict_proba(train))
        client.set_model_version_tag(MODEL_NAME, existing.version, "parity_rows", str(len(train)))
        client.set_model_version_tag(MODEL_NAME, existing.version, "verification", "verified")
        client.set_registered_model_alias(MODEL_NAME, ALIAS, existing.version)
        return client.get_model_version(MODEL_NAME, existing.version)


if __name__ == "__main__":
    verified = register_pipeline()
    print(f"{verified.name} v{verified.version}: {verified.tags['parity_rows']} satır birebir eşleşti.")
