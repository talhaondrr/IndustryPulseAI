"""Load the released local model and run the preprocessing/model pipeline."""

import json
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO

import joblib
import pandas as pd
from sklearn.pipeline import Pipeline

from api.schemas import Prediction, SensorReading
from src.export_model import METADATA_FILE, MODELS, PIPELINE_FILE, THRESHOLD
from src.preprocessing import FEATURES

COLUMNS = {
    "type": "Type",
    "air_temperature": "Air temperature [K]",
    "process_temperature": "Process temperature [K]",
    "rotational_speed": "Rotational speed [rpm]",
    "torque": "Torque [Nm]",
    "tool_wear": "Tool wear [min]",
}


class PredictionService:
    def __init__(self, pipeline, metadata):
        self.pipeline = pipeline
        self.metadata = metadata

    @classmethod
    def load(cls):
        for path in (METADATA_FILE, PIPELINE_FILE):
            if path.parent != MODELS or path.resolve() != path:
                raise ValueError("Model dosyası proje içindeki sabit yerel konumda olmalıdır.")
        metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        payload = PIPELINE_FILE.read_bytes()
        if sha256(payload).hexdigest() != metadata["artifact_sha256"]:
            raise ValueError("Pipeline ve metadata dosyaları eşleşmiyor.")
        if (metadata["input_features"] != FEATURES or metadata["decision_threshold"] != THRESHOLD
                or not isinstance(metadata["model_version"], str)):
            raise ValueError("Model metadata şeması veya karar eşiği uyumsuz.")
        # Joblib can execute code while loading. The fixed local release is the trust boundary.
        pipeline = joblib.load(BytesIO(payload))
        if (not isinstance(pipeline, Pipeline)
                or list(pipeline.feature_names_in_) != FEATURES or list(pipeline.classes_) != [0, 1]):
            raise ValueError("Pipeline özellikleri veya sınıfları uyumsuz.")
        return cls(pipeline, metadata)

    def predict(self, readings: list[SensorReading]) -> list[Prediction]:
        frame = pd.DataFrame([reading.model_dump() for reading in readings]).rename(columns=COLUMNS)
        scores = self.pipeline.predict_proba(frame[FEATURES])[:, 1]
        timestamp = datetime.now(timezone.utc)
        threshold = self.metadata["decision_threshold"]
        return [
            Prediction(
                predicted_class=int(score > threshold),
                failure_score=float(score),
                decision_threshold=threshold,
                model_version=self.metadata["model_version"],
                prediction_timestamp=timestamp,
            )
            for score in scores
        ]
