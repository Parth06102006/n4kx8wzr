from fastapi import APIRouter

from app.api.routes import analytics, utils, wind

api_router = APIRouter()
api_router.include_router(utils.router)
api_router.include_router(wind.router)
api_router.include_router(analytics.router)
