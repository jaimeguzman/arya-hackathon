from fastapi import FastAPI

from app.config import get_settings
from app.routes.health import router as health_router


def create_app() -> FastAPI:
    get_settings()
    application = FastAPI(title="IntakeAI API")
    application.include_router(health_router)
    return application


app = create_app()
