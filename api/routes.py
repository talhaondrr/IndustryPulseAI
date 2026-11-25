"""HTTP routes for health checks, model information and predictions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from api.schemas import BatchRequest, BatchResponse, Prediction, SensorReading
from api.services.prediction_service import PredictionService

router = APIRouter()
UNAVAILABLE = {503: {"description": "Model bu işlemde kullanılamıyor."}}


def require_model(request: Request) -> PredictionService:
    service = request.app.state.prediction_service
    if service is None:
        raise HTTPException(status_code=503, detail="Tahmin modeli kullanılamıyor.")
    return service


Model = Annotated[PredictionService, Depends(require_model)]


@router.get("/")
def root():
    return {"name": "IndustryPulseAI", "docs": "/docs", "health": "/health", "model_info": "/model/info"}


@router.get("/health", responses=UNAVAILABLE)
def health(request: Request):
    ready = request.app.state.prediction_service is not None
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"service": "running", "model": "ready" if ready else "unavailable"},
    )


@router.get("/model/info", responses=UNAVAILABLE)
def model_info(service: Model):
    return service.metadata


@router.post("/predict", response_model=Prediction, responses=UNAVAILABLE)
def predict(reading: SensorReading, service: Model):
    return service.predict([reading])[0]


@router.post("/predict/batch", response_model=BatchResponse, responses=UNAVAILABLE)
def predict_batch(batch: BatchRequest, service: Model):
    return BatchResponse(predictions=service.predict(batch.readings))
