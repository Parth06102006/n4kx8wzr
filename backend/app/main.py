from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.api.routes import analytics
from app.core.config import settings

FRONTEND_DIR = Path(__file__).parent / "frontend"


def custom_generate_unique_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    prefix = "v1" if "/v1/" in route.path or route.path.startswith("/api/v1") else "api"
    return f"{prefix}-{tag}-{route.name}"


if settings.SENTRY_DSN and settings.FASTAPI_ENV != "development":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        str(settings.FRONTEND_HOST).rstrip("/"),
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost",
        "http://127.0.0.1",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", include_in_schema=False)
async def root_health_check() -> bool:
    """Compatibility health endpoint for monitors requesting /health."""
    return True

# Route both /api/v1/... and direct /api/... for the requested endpoints
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix="/api")

if FRONTEND_DIR.is_dir():
    app.frontend("/", directory=FRONTEND_DIR)
