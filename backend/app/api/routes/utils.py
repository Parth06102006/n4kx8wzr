from fastapi import APIRouter

router = APIRouter(prefix="/utils", tags=["utils"])


@router.get("/health-check/")
async def health_check() -> bool:
    """System health check used by container orchestrator."""
    return True
