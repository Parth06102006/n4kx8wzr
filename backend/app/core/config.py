import warnings
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    HttpUrl,
    PostgresDsn,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look for .env in current directory or one level up
        env_file=(".env", "../.env"),
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    FRONTEND_HOST: str = "http://localhost:5173"
    FASTAPI_ENV: Literal["development"] | None = None

    PROJECT_NAME: str = "Renewable Wind Forecast API"
    SENTRY_DSN: HttpUrl | None = None
    DATABASE_URL: PostgresDsn

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    # Renewable Wind Forecasting Domain Settings
    ANALYSIS_PERIOD: str = "January 2026"
    DELIVERY_OFFSET_DAYS: int = 1
    MAPE_THRESHOLD_MW: float = 10.0

    # Dataset Validation Targets (DB-07)
    EXPECTED_ACTUAL_RECORDS: int = 1584  # Full delivery window (33 days * 48 periods)
    EXPECTED_FORECAST_RECORDS: int = 18704  # All WINDFOR forecast points in import window
    EXPECTED_DECISION_DAYS: int = 31  # 31 day-ahead decisions in January
    EXPECTED_JANUARY_ACTUALS: int = 1488  # 31 days * 48 periods in January
    EXPECTED_JANUARY_FORECAST_POINTS: int = 744  # 31 days * 24 delivery hours

    # Pagination Settings
    PAGINATION_DEFAULT_LIMIT: int = 100
    PAGINATION_MAX_LIMIT: int = 500

    # Data Paths
    DATA_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "elexon"
    ACTUAL_CSV_NAME: str = "actual_wind_fuelhh.csv"
    FORECAST_CSV_NAME: str = "wind_forecasts_windfor.csv"
    DECISION_COVERAGE_CSV_NAME: str = "decision_coverage.csv"

    @property
    def actual_csv_path(self) -> Path:
        return self.DATA_DIR / self.ACTUAL_CSV_NAME

    @property
    def forecast_csv_path(self) -> Path:
        return self.DATA_DIR / self.FORECAST_CSV_NAME

    @property
    def decision_coverage_csv_path(self) -> Path:
        return self.DATA_DIR / self.DECISION_COVERAGE_CSV_NAME

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        for host in self.DATABASE_URL.hosts():
            if host["password"] == "changethis":
                message = 'The DATABASE_URL password is "changethis"; change it for deployments.'
                if self.FASTAPI_ENV == "development":
                    warnings.warn(message, stacklevel=1)
                else:
                    raise ValueError(message)

        return self


settings = Settings()  # type: ignore # ty: ignore[unused-ignore-comment]
