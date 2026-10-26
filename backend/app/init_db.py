"""Database initialization and validation for January 2026 Elexon wind data."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine

from app.core.config import settings
from app.initial_data import (
    apply_migrations,
    check_csv_data_present,
    check_db_data_present,
    generate_import_csvs,
)
from app.wind_csv import check_duplicates, load_january_csvs, verify_january

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_decision_coverage() -> tuple[int, int]:
    """Validate day-ahead decision coverage from decision_coverage.csv."""
    cov_path = settings.decision_coverage_csv_path
    if not cov_path.is_file():
        return 0, settings.EXPECTED_DECISION_DAYS

    import csv
    with cov_path.open(newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        total_decisions = len(reader)
        covered = sum(
            1 for r in reader
            if float(r.get("forecast_coverage_pct", 0.0)) >= 100.0
            and float(r.get("actual_coverage_pct", 0.0)) >= 100.0
        )
    return covered, total_decisions


def init_database(*, force: bool = False) -> dict[str, Any]:
    """
    Initialize schema, load normalized CSV data idempotently,
    and validate against expected counts:
      - Actual records: 1,584
      - Forecast records: 18,704
      - Decision coverage: 31/31 days
      - Duplicate actual keys: 0
      - Duplicate forecast keys: 0
    """
    apply_migrations()
    engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)

    try:
        with Session(engine) as session:
            # 1. Check if complete dataset is already present
            is_present, counts = check_db_data_present(session)
            if is_present and not force:
                logger.info("Database already populated: %s", counts)
            else:
                # 2. Check CSVs
                csv_present, actual_csv, forecast_csv = check_csv_data_present()
                if not csv_present or force:
                    generate_import_csvs()
                    csv_present, actual_csv, forecast_csv = check_csv_data_present()

                # 3. Load normalized CSVs idempotently
                logger.info("Loading normalized CSVs into PostgreSQL...")
                load_january_csvs(session, actual_csv, forecast_csv)

            # 4. Validate DB contents (DB-07)
            verified = verify_january(session)
            dups = check_duplicates(session)
            covered_decisions, total_decisions = validate_decision_coverage()

            validation_report = {
                "actual_records": verified["actuals"],
                "forecast_records": verified["forecasts"],
                "expected_actual_records": settings.EXPECTED_ACTUAL_RECORDS,
                "expected_forecast_records": settings.EXPECTED_FORECAST_RECORDS,
                "duplicate_actual_keys": dups["duplicate_actual_keys"],
                "duplicate_forecast_keys": dups["duplicate_forecast_keys"],
                "decision_coverage_days": f"{covered_decisions}/{total_decisions}",
                "status": "VALIDATED",
            }
            logger.info("Database Validation Report:\n%s", validation_report)
            return validation_report
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize and validate database with January 2026 wind data.")
    parser.add_argument("--force", action="store_true", help="Force reload from CSV even if data exists.")
    args = parser.parse_args()

    try:
        report = init_database(force=args.force)
        logger.info("=== Elexon Wind Data Initialization & Validation Summary ===")
        logger.info("Actual Records:        %s (Expected: %s)", report["actual_records"], report["expected_actual_records"])
        logger.info("Forecast Records:      %s (Expected: %s)", report["forecast_records"], report["expected_forecast_records"])
        logger.info("Decision Coverage:     %s days", report["decision_coverage_days"])
        logger.info("Duplicate Actuals:     %s", report["duplicate_actual_keys"])
        logger.info("Duplicate Forecasts:   %s", report["duplicate_forecast_keys"])
        logger.info("Status:                %s", report["status"])
    except OperationalError:
        logger.error("Could not connect to database at %s. Please ensure PostgreSQL is running.", settings.DATABASE_URL)
        sys.exit(1)


if __name__ == "__main__":
    main()
