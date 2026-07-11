from fastapi import FastAPI

from app.config import get_settings
from app.routes.elevenlabs import router as elevenlabs_router
from app.routes.eligibility import router as eligibility_router
from app.routes.health import router as health_router
from app.routes.twilio import router as twilio_router
from app.safety.db_guard import validate_database_url


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.database_url:
        # Guarantee 1: refuse to boot against a non-allowlisted database.
        validate_database_url(settings.database_url)
    application = FastAPI(title="IntakeAI API")
    application.include_router(health_router)
    application.include_router(eligibility_router)
    application.include_router(twilio_router)
    application.include_router(elevenlabs_router)
    return application


app = create_app()
