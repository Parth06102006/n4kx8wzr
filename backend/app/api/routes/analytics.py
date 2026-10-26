from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import (
    AccuracyResponse,
    ActualGenerationItem,
    ActualGenerationResponse,
    ForecastComparisonItem,
    ForecastComparisonResponse,
    ForecastVersionItem,
    ForecastVersionsResponse,
    OverviewResponse,
    PaginationMetadata,
)
from app.services import wind_service

router = APIRouter(tags=["analytics"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(session: SessionDep) -> OverviewResponse:
    """
    API-01: Executive summary
    Summary metrics, decision evaluation, and dataset coverage for January 2026.
    """
    data = wind_service.get_overview(session)
    return OverviewResponse(**data)


@router.get("/forecasts", response_model=ForecastComparisonResponse)
def get_forecast_comparison(
    session: SessionDep,
    delivery_date: Annotated[date | None, Query(description="Filter by delivery date (YYYY-MM-DD)")] = None,
    decision_date: Annotated[date | None, Query(description="Filter by decision date (YYYY-MM-DD)")] = None,
    limit: Annotated[int, Query(ge=1, le=settings.PAGINATION_MAX_LIMIT, description="Number of records to return")] = settings.PAGINATION_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
) -> ForecastComparisonResponse:
    """
    API-02: Forecast versus actual time series
    Compare forecasts available at the 09:00 UTC cutoff with matching actual generation.
    """
    observations = wind_service.get_forecast_comparison(
        session,
        decision_date=decision_date,
        delivery_date=delivery_date,
    )
    total = len(observations)
    paginated_obs = observations[offset : offset + limit]
    items = [ForecastComparisonItem(**obs) for obs in paginated_obs]
    has_more = (offset + limit) < total

    return ForecastComparisonResponse(
        items=items,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            total=total,
            has_more=has_more,
        ),
    )


@router.get("/actuals", response_model=ActualGenerationResponse)
def get_actual_generation(
    session: SessionDep,
    start_time: Annotated[datetime | None, Query(description="Filter start timestamp on or after (UTC)")] = None,
    end_time: Annotated[datetime | None, Query(description="Filter end timestamp on or before (UTC)")] = None,
    limit: Annotated[int, Query(ge=1, le=settings.PAGINATION_MAX_LIMIT, description="Number of records to return")] = settings.PAGINATION_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
) -> ActualGenerationResponse:
    """
    API-03: Actual wind generation
    Retrieve hourly aggregated actual wind generation from FUELHH observations.
    """
    raw_items = wind_service.get_actual_generation(session, start_time=start_time, end_time=end_time)
    total = len(raw_items)
    paginated_items = raw_items[offset : offset + limit]
    items = [ActualGenerationItem(**item) for item in paginated_items]
    has_more = (offset + limit) < total

    return ActualGenerationResponse(
        items=items,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            total=total,
            has_more=has_more,
        ),
    )


@router.get("/accuracy", response_model=AccuracyResponse)
def get_accuracy_metrics(
    session: SessionDep,
    threshold_mw: Annotated[float, Query(description="Minimum MW threshold for MAPE calculation to handle zero values")] = settings.MAPE_THRESHOLD_MW,
    delivery_date: Annotated[date | None, Query(description="Filter by delivery date (YYYY-MM-DD)")] = None,
    decision_date: Annotated[date | None, Query(description="Filter by decision date (YYYY-MM-DD)")] = None,
) -> AccuracyResponse:
    """
    API-04: Forecast accuracy metrics
    Quantify errors: MAE, RMSE, MAPE (handling zero/near-zero actuals), and Mean signed bias with daily breakdowns.
    """
    observations = wind_service.get_matched_observations(
        session,
        decision_date_filter=decision_date,
        delivery_date_filter=delivery_date,
    )
    metrics = wind_service.calculate_accuracy_metrics(observations, threshold_mw=threshold_mw)
    return AccuracyResponse(**metrics)


@router.get("/forecast-versions", response_model=ForecastVersionsResponse)
def get_forecast_versions(
    session: SessionDep,
    delivery_date: Annotated[date | None, Query(description="Delivery date (YYYY-MM-DD), e.g. 2026-01-15")] = None,
    delivery_time: Annotated[datetime | None, Query(description="Specific delivery hour timestamp (UTC), e.g. 2026-01-15T12:00:00Z")] = None,
    limit: Annotated[int, Query(ge=1, le=settings.PAGINATION_MAX_LIMIT, description="Number of records to return")] = settings.PAGINATION_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
) -> ForecastVersionsResponse:
    """
    API-05: Forecast publication and revision history
    Track forecast revisions over time and demonstrate which version was eligible at the decision cutoff.
    """
    # If neither delivery_date nor delivery_time is provided, default to first day of decisions
    if not delivery_date and not delivery_time:
        delivery_date = date(2026, 1, 2)

    versions_data = wind_service.get_forecast_versions(
        session,
        delivery_date=delivery_date,
        delivery_time=delivery_time,
    )
    total = len(versions_data)
    paginated_versions = versions_data[offset : offset + limit]
    items = [ForecastVersionItem(**v) for v in paginated_versions]
    has_more = (offset + limit) < total

    return ForecastVersionsResponse(
        items=items,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            total=total,
            has_more=has_more,
        ),
    )


@router.get("/export")
def export_forecast_comparison_csv(
    session: SessionDep,
    delivery_date: Annotated[date | None, Query(description="Filter by delivery date (YYYY-MM-DD)")] = None,
    decision_date: Annotated[date | None, Query(description="Filter by decision date (YYYY-MM-DD)")] = None,
) -> Response:
    """
    API-06: Export matched observations as CSV
    Download a CSV containing delivery time, decision cutoff, selected forecast publication,
    forecast MW, actual MW, signed error, and absolute error.
    """
    observations = wind_service.get_matched_observations(
        session,
        decision_date_filter=decision_date,
        delivery_date_filter=delivery_date,
    )
    csv_content = wind_service.export_forecast_comparison_csv(observations)
    filename = "wind_forecast_comparison_january_2026.csv"
    if delivery_date:
        filename = f"wind_forecast_comparison_{delivery_date.isoformat()}.csv"
    elif decision_date:
        filename = f"wind_forecast_comparison_decision_{decision_date.isoformat()}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
