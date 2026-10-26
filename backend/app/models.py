import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Column, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Database Tables (DB-01, DB-02)
# ---------------------------------------------------------------------------
class WindActual(SQLModel, table=True):
    __tablename__ = "wind_actuals"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "start_time",
            name="uq_wind_actual_source_start",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    start_time: datetime = Field(
        nullable=False,
        index=True,
    )
    generation_mw: Decimal = Field(
        sa_column=Column(Numeric(12, 3), nullable=False),
    )
    source: str = Field(
        default="FUELHH",
        max_length=100,
        nullable=False,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        nullable=False,
    )


class WindForecast(SQLModel, table=True):
    __tablename__ = "wind_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "start_time",
            "publish_time",
            name="uq_wind_forecast_source_start_publish",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    start_time: datetime = Field(
        nullable=False,
        index=True,
    )
    publish_time: datetime = Field(
        nullable=False,
        index=True,
    )
    generation_mw: Decimal = Field(
        sa_column=Column(Numeric(12, 3), nullable=False),
    )
    source: str = Field(
        default="WINDFOR",
        max_length=100,
        nullable=False,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Pagination Standard Schema
# ---------------------------------------------------------------------------
class PaginationMetadata(SQLModel):
    limit: int
    offset: int
    total: int
    has_more: bool


# ---------------------------------------------------------------------------
# API DTOs & Response Models (API-01 to API-06)
# ---------------------------------------------------------------------------

# 1. /api/overview
class OverviewResponse(SQLModel):
    analysis_period: str
    decisions_evaluated: int
    delivery_hours_evaluated: int
    mae_mw: float
    rmse_mw: float
    mape_pct: float
    mean_bias_mw: float
    forecast_generation_mean_mw: float
    actual_generation_mean_mw: float
    coverage_pct: float
    missing_forecast_points: int
    missing_actual_points: int


# 2. /api/forecasts
class ForecastComparisonItem(SQLModel):
    delivery_time_utc: datetime
    decision_date: str
    decision_cutoff_utc: datetime
    selected_publish_time_utc: datetime
    forecast_mw: float
    actual_mw: float
    forecast_error_mw: float
    absolute_error_mw: float


class ForecastComparisonResponse(SQLModel):
    items: list[ForecastComparisonItem]
    pagination: PaginationMetadata

    @property
    def data(self) -> list[ForecastComparisonItem]:
        return self.items


# 3. /api/actuals
class ActualGenerationItem(SQLModel):
    delivery_time_utc: datetime
    actual_generation_mw: float
    half_hour_observations_count: int


class ActualGenerationResponse(SQLModel):
    items: list[ActualGenerationItem]
    pagination: PaginationMetadata

    @property
    def data(self) -> list[ActualGenerationItem]:
        return self.items


# 4. /api/accuracy
class AccuracyMetricsDaily(SQLModel):
    delivery_date: str
    observations_count: int
    mae_mw: float
    rmse_mw: float
    mape_pct: float
    mean_bias_mw: float


class AccuracyResponse(SQLModel):
    mae_mw: float
    rmse_mw: float
    mape_pct: float
    mean_bias_mw: float
    threshold_mw: float
    valid_mape_count: int
    excluded_zero_count: int
    total_observations: int
    daily_metrics: list[AccuracyMetricsDaily]


# 5. /api/forecast-versions
class ForecastVersionItem(SQLModel):
    delivery_time_utc: datetime
    publish_time_utc: datetime
    generation_mw: float
    delta_mw: float | None
    is_eligible_for_decision: bool
    is_decision_cutoff_version: bool


class ForecastVersionsResponse(SQLModel):
    items: list[ForecastVersionItem]
    pagination: PaginationMetadata

    @property
    def versions(self) -> list[ForecastVersionItem]:
        return self.items

    @property
    def versions_count(self) -> int:
        return self.pagination.total


# Backward compatibility schemas
class WindActualPublic(SQLModel):
    id: uuid.UUID
    start_time: datetime
    generation_mw: Decimal
    source: str
    created_at: datetime


class WindActualsPublic(SQLModel):
    data: list[WindActualPublic]
    count: int


class WindForecastPublic(SQLModel):
    id: uuid.UUID
    start_time: datetime
    publish_time: datetime
    generation_mw: Decimal
    source: str
    created_at: datetime


class WindForecastsPublic(SQLModel):
    data: list[WindForecastPublic]
    count: int


class DecisionCoverageItem(SQLModel):
    decision_time_utc: str
    delivery_date: str
    latest_publish_utc: str
    publish_age_hours: float
    forecast_horizon_hours: float
    forecast_resolution_minutes: int
    forecast_points_available: int
    forecast_points_expected: int
    forecast_coverage_pct: float
    actual_periods_available: int
    actual_periods_expected: int
    actual_coverage_pct: float
    first_forecast_start_utc: str
    last_forecast_start_utc: str
    missing_forecast_slots: str = ""
    fully_covered: bool = True


class DecisionCoveragePublic(SQLModel):
    data: list[DecisionCoverageItem]
    total_decisions: int
    fully_covered_decisions: int


class WindSummaryPublic(SQLModel):
    actuals_count: int
    forecasts_count: int
    actuals_start_time_min: datetime | None = None
    actuals_start_time_max: datetime | None = None
    forecasts_start_time_min: datetime | None = None
    forecasts_start_time_max: datetime | None = None
    actual_mean_generation_mw: float | None = None
    forecast_mean_generation_mw: float | None = None
    forecast_bias_ratio: float | None = None


class Message(SQLModel):
    message: str
