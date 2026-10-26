"""Idempotent CSV loading and verification for Elexon wind data."""

from __future__ import annotations

import csv
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.core.config import settings
from app.models import WindActual, WindForecast

EXPECTED_ACTUAL_RECORDS = settings.EXPECTED_ACTUAL_RECORDS
EXPECTED_FORECAST_RECORDS = settings.EXPECTED_FORECAST_RECORDS


def _parse_timestamp(value: str, *, field: str, line: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"CSV line {line}: invalid {field} timestamp {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"CSV line {line}: {field} timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _parse_csv_rows(path: Path, *, dataset: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required Elexon CSV does not exist: {path}")

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"start_time_utc", "generation_mw", "dataset"}
        if dataset == "FUELHH":
            required.add("fuel_type")
        else:
            required.add("publish_time_utc")
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path} is missing required columns: {', '.join(sorted(missing))}"
            )

        for line, row in enumerate(reader, start=2):
            if row["dataset"] != dataset:
                raise ValueError(
                    f"CSV line {line}: expected dataset {dataset}, got {row['dataset']!r}"
                )
            start_time = _parse_timestamp(
                row["start_time_utc"], field="start_time_utc", line=line
            )
            if dataset == "FUELHH" and row["fuel_type"] != "WIND":
                raise ValueError(
                    f"CSV line {line}: expected fuel_type WIND, got {row['fuel_type']!r}"
                )
            try:
                generation = Decimal(row["generation_mw"])
            except Exception as exc:
                raise ValueError(
                    f"CSV line {line}: invalid generation_mw {row['generation_mw']!r}"
                ) from exc
            if not generation.is_finite() or generation < 0 or generation > 30_000:
                raise ValueError(
                    f"CSV line {line}: generation_mw outside 0..30000: {generation}"
                )

            model_row: dict[str, Any] = {
                "id": uuid.uuid4(),
                "start_time": start_time,
                "generation_mw": generation,
                "source": dataset,
                "created_at": datetime.now(UTC),
            }
            if dataset == "WINDFOR":
                model_row["publish_time"] = _parse_timestamp(
                    row["publish_time_utc"], field="publish_time_utc", line=line
                )
            rows.append(model_row)
    return rows


def _insert_idempotently(
    session: Session,
    model: type[WindActual] | type[WindForecast],
    rows: list[dict[str, Any]],
    *,
    batch_size: int = 1000,
) -> int:
    inserted = 0
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "postgresql"

    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        if dialect_name == "sqlite":
            statement = sqlite_insert(model).values(batch).on_conflict_do_nothing()
        else:
            statement = pg_insert(model).values(batch).on_conflict_do_nothing()
        result = session.exec(statement)
        inserted += result.rowcount or 0
    return inserted


def db_counts(session: Session) -> dict[str, int]:
    actual_res = session.exec(
        select(func.count()).select_from(WindActual)
    ).one()
    forecast_res = session.exec(
        select(func.count()).select_from(WindForecast)
    ).one()
    actual_count = actual_res[0] if hasattr(actual_res, "__getitem__") else actual_res
    forecast_count = forecast_res[0] if hasattr(forecast_res, "__getitem__") else forecast_res
    return {"actuals": int(actual_count), "forecasts": int(forecast_count)}


# Alias for backwards compatibility
january_counts = db_counts


def check_duplicates(session: Session) -> dict[str, int]:
    """Check for duplicate keys in the database tables."""
    # Actuals unique: (source, start_time)
    actual_dups = session.exec(
        select(func.count())
        .select_from(
            select(WindActual.source, WindActual.start_time)
            .group_by(WindActual.source, WindActual.start_time)
            .having(func.count() > 1)
            .subquery()
        )
    ).one()
    # Forecasts unique: (source, start_time, publish_time)
    forecast_dups = session.exec(
        select(func.count())
        .select_from(
            select(WindForecast.source, WindForecast.start_time, WindForecast.publish_time)
            .group_by(WindForecast.source, WindForecast.start_time, WindForecast.publish_time)
            .having(func.count() > 1)
            .subquery()
        )
    ).one()

    act_d = actual_dups[0] if hasattr(actual_dups, "__getitem__") else actual_dups
    fc_d = forecast_dups[0] if hasattr(forecast_dups, "__getitem__") else forecast_dups
    return {"duplicate_actual_keys": int(act_d), "duplicate_forecast_keys": int(fc_d)}


def load_january_csvs(
    session: Session,
    actual_csv: Path,
    forecast_csv: Path,
) -> dict[str, int]:
    """Load normalized CSV rows; unique constraints make batch inserts idempotent."""
    actual_rows = _parse_csv_rows(actual_csv, dataset="FUELHH")
    forecast_rows = _parse_csv_rows(forecast_csv, dataset="WINDFOR")

    inserted_actuals = _insert_idempotently(session, WindActual, actual_rows)
    inserted_forecasts = _insert_idempotently(session, WindForecast, forecast_rows)
    session.commit()
    return {
        "actual_rows_in_csv": len(actual_rows),
        "forecast_rows_in_csv": len(forecast_rows),
        "actual_rows_inserted": inserted_actuals,
        "forecast_rows_inserted": inserted_forecasts,
    }


def verify_january(
    session: Session,
    expected_forecasts: int = EXPECTED_FORECAST_RECORDS,
    expected_actuals: int = EXPECTED_ACTUAL_RECORDS,
) -> dict[str, int]:
    counts = db_counts(session)
    dups = check_duplicates(session)

    if dups["duplicate_actual_keys"] > 0 or dups["duplicate_forecast_keys"] > 0:
        raise RuntimeError(
            f"Database duplicate check failed: {dups}"
        )

    if counts["actuals"] < expected_actuals:
        raise RuntimeError(
            f"Actuals verification failed: expected at least {expected_actuals}, "
            f"found {counts['actuals']}"
        )
    if counts["forecasts"] < expected_forecasts:
        raise RuntimeError(
            f"Forecast verification failed: expected at least {expected_forecasts}, "
            f"found {counts['forecasts']}"
        )
    return {**counts, **dups}
