"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.analytics import router as analytics_router

from api.routes import router
from api.services.prediction_service import PredictionService

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.prediction_service = PredictionService.load()
    except Exception as error:
        LOGGER.error("Yerel model yüklenemedi (%s).", type(error).__name__)
        app.state.prediction_service = None
    yield


app = FastAPI(
    title="IndustryPulseAI Tahmin API'si",
    version="1.0.0",
    description="Sentetik AI4I verisiyle eğitilmiş XGBoost modelinden arıza skoru üretir.",
    lifespan=lifespan,
    docs_url=None,
)
app.include_router(router)
app.include_router(analytics_router)
app.mount("/swagger-assets", StaticFiles(directory=Path(__file__).parent / "static" / "swagger"),
          name="swagger-assets")


@app.get("/docs", include_in_schema=False)
def swagger_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="IndustryPulseAI - Swagger UI",
        swagger_js_url="/swagger-assets/swagger-ui-bundle.js",
        swagger_css_url="/swagger-assets/swagger-ui.css",
        swagger_favicon_url="data:,",
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, error: RequestValidationError):
    # Do not echo inputs: invalid JSON may contain NaN or Infinity.
    detail = [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})
