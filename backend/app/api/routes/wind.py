import csv
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app import crud
from app.api.deps import SessionDep
from app.core.config import settings
from app.models import (
    DecisionCoverageItem,
    DecisionCoveragePublic,
    WindActualPublic,
    WindActualsPublic,
    WindForecastPublic,
    WindForecastsPublic,
    WindSummaryPublic,
)

router = APIRouter(prefix="/wind", tags=["wind"])

DECISION_COVERAGE_CSV = settings.decision_coverage_csv_path


@router.get("/actuals", response_model=WindActualsPublic)
def read_actuals(
    session: SessionDep,
    start_time_from: datetime | None = Query(
        default=None, description="Filter actuals starting on or after (UTC)"
    ),
    start_time_to: datetime | None = Query(
        default=None, description="Filter actuals starting on or before (UTC)"
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> WindActualsPublic:
    """Retrieve half-hourly actual wind generation outturn (FUELHH)."""
    items, count = crud.get_actuals(
        session,
        start_time_from=start_time_from,
        start_time_to=start_time_to,
        skip=skip,
        limit=limit,
    )
    data = [WindActualPublic.model_validate(item) for item in items]
    return WindActualsPublic(data=data, count=count)


@router.get("/forecasts", response_model=WindForecastsPublic)
def read_forecasts(
    session: SessionDep,
    start_time_from: datetime | None = Query(
        default=None, description="Filter forecasts delivery start on or after (UTC)"
    ),
    start_time_to: datetime | None = Query(
        default=None, description="Filter forecasts delivery start on or before (UTC)"
    ),
    publish_time_from: datetime | None = Query(
        default=None, description="Filter publish time on or after (UTC)"
    ),
    publish_time_to: datetime | None = Query(
        default=None, description="Filter publish time on or before (UTC)"
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> WindForecastsPublic:
    """Retrieve national wind generation forecasts (WINDFOR)."""
    items, count = crud.get_forecasts(
        session,
        start_time_from=start_time_from,
        start_time_to=start_time_to,
        publish_time_from=publish_time_from,
        publish_time_to=publish_time_to,
        skip=skip,
        limit=limit,
    )
    data = [WindForecastPublic.model_validate(item) for item in items]
    return WindForecastsPublic(data=data, count=count)


@router.get("/decision-coverage", response_model=DecisionCoveragePublic)
def read_decision_coverage() -> DecisionCoveragePublic:
    """Retrieve the day-ahead decision coverage audit evaluation for January 2026."""
    if not DECISION_COVERAGE_CSV.is_file():
        raise HTTPException(
            status_code=404,
            detail="Decision coverage report has not been generated yet. Run initial_data.py to generate it.",
        )

    rows: list[DecisionCoverageItem] = []
    with DECISION_COVERAGE_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            forecast_cov = float(row.get("forecast_coverage_pct", 0.0))
            actual_cov = float(row.get("actual_coverage_pct", 0.0))
            fully_covered = forecast_cov >= 100.0 and actual_cov >= 100.0
            rows.append(
                DecisionCoverageItem(
                    decision_time_utc=row["decision_time_utc"],
                    delivery_date=row["delivery_date"],
                    latest_publish_utc=row["latest_publish_utc"],
                    publish_age_hours=float(row["publish_age_hours"]),
                    forecast_horizon_hours=float(row["forecast_horizon_hours"]),
                    forecast_resolution_minutes=int(row["forecast_resolution_minutes"]),
                    forecast_points_available=int(row["forecast_points_available"]),
                    forecast_points_expected=int(row["forecast_points_expected"]),
                    forecast_coverage_pct=forecast_cov,
                    actual_periods_available=int(row["actual_periods_available"]),
                    actual_periods_expected=int(row["actual_periods_expected"]),
                    actual_coverage_pct=actual_cov,
                    first_forecast_start_utc=row["first_forecast_start_utc"],
                    last_forecast_start_utc=row["last_forecast_start_utc"],
                    missing_forecast_slots=row.get("missing_forecast_slots", ""),
                    fully_covered=fully_covered,
                )
            )

    fully_covered = sum(1 for r in rows if r.fully_covered)
    return DecisionCoveragePublic(
        data=rows,
        total_decisions=len(rows),
        fully_covered_decisions=fully_covered,
    )


@router.get("/summary", response_model=WindSummaryPublic)
def read_summary(session: SessionDep) -> WindSummaryPublic:
    """Retrieve overall wind dataset metrics, date ranges, and forecast bias."""
    summary = crud.get_summary(session)
    return WindSummaryPublic(**summary)
