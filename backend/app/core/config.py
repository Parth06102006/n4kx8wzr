import warnings
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
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
    SECRET_KEY: str | None = None
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
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
    DECISION_TIME_UTC: str = "09:00"
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

    # Optional / Legacy compatibility fields
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        if self.SECRET_KEY:
            self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        for host in self.DATABASE_URL.hosts():
            self._check_default_secret("DATABASE_URL password", host["password"])
        if self.FIRST_SUPERUSER_PASSWORD:
            self._check_default_secret(
                "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
            )

        return self


settings = Settings()  # type: ignore # ty: ignore[unused-ignore-comment]
