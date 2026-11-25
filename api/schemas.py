"""HTTP input and output contracts for sensor predictions."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_BATCH_SIZE = 100
# Respect the numeric representation of the training schema and XGBoost.
FLOAT32_MAX = 3.4028234663852886e38
INT32_MAX = 2_147_483_647
Temperature = Annotated[float, Field(strict=True, gt=0, le=FLOAT32_MAX, allow_inf_nan=False)]
NonnegativeFloat = Annotated[float, Field(strict=True, ge=0, le=FLOAT32_MAX, allow_inf_nan=False)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0, le=INT32_MAX)]


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["L", "M", "H"]
    air_temperature: Temperature
    process_temperature: Temperature
    rotational_speed: NonnegativeInt
    torque: NonnegativeFloat
    tool_wear: NonnegativeInt


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: list[SensorReading] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class Prediction(BaseModel):
    predicted_class: Literal[0, 1]
    failure_score: float
    decision_threshold: float
    model_version: str
    prediction_timestamp: datetime


class BatchResponse(BaseModel):
    predictions: list[Prediction]
