"""Migrate the database, import January Elexon CSVs, and verify the load."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine

from app.core.config import settings
from app.wind_csv import january_counts, load_january_csvs, verify_january

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
IMPORT_SCRIPT = REPOSITORY_ROOT / "scripts" / "elexon_history_import.py"
IMPORT_OUTPUT = settings.DATA_DIR


def apply_migrations() -> None:
    """Apply all pending Alembic revisions before querying or loading data."""
    alembic_config = Config(str(ALEMBIC_INI))
    alembic_config.set_main_option(
        "script_location", str(BACKEND_DIR / "app" / "alembic")
    )
    logger.info("Applying database migrations to Alembic head")
    try:
        command.upgrade(alembic_config, "head")
    except OperationalError as exc:
        logger.error(
            "Could not connect to database at %s. Please ensure PostgreSQL is running.",
            settings.DATABASE_URL,
        )
        raise exc


def check_db_data_present(session: Session) -> tuple[bool, dict[str, int]]:
    """Check whether complete January 2026 data is already present in the database."""
    try:
        counts = january_counts(session)
        is_present = (
            counts["actuals"] >= settings.EXPECTED_JANUARY_ACTUALS
            and counts["forecasts"] > 0
        )
        return is_present, counts
    except OperationalError as exc:
        logger.warning(
            "Database unreachable during presence check (%s). Treating DB as unpopulated.",
            exc,
        )
        return False, {"actuals": 0, "forecasts": 0}


def check_csv_data_present() -> tuple[bool, Path, Path]:
    """Check whether normalized actuals and forecast CSVs are present on disk."""
    actual_path = settings.actual_csv_path
    forecast_path = settings.forecast_csv_path
    csv_present = actual_path.is_file() and forecast_path.is_file()
    return csv_present, actual_path, forecast_path


def generate_import_csvs() -> None:
    """Run the external Elexon importer script to fetch and generate the CSV files."""
    if not IMPORT_SCRIPT.is_file():
        raise FileNotFoundError(f"Elexon importer script not found at {IMPORT_SCRIPT}")
    logger.info("Running Elexon importer script to generate CSVs at %s", IMPORT_OUTPUT)
    subprocess.run(
        [sys.executable, str(IMPORT_SCRIPT), "--out", str(IMPORT_OUTPUT)],
        cwd=REPOSITORY_ROOT,
        check=True,
    )


def ensure_data_loaded(session: Session, *, force: bool = False) -> dict[str, Any]:
    """
    Intelligent tiered loader:
    1. Check whether complete data is already present in the database.
       If present and not force, skip importing.
    2. If missing from DB, check whether CSV files are present on disk.
       If missing, run the external import script to fetch and generate them.
    3. Transform and import CSV data into the database and verify.
    """
    # Step 1: Check Database
    is_db_present, counts = check_db_data_present(session)
    if is_db_present and not force:
        logger.info(
            "Data already present in database (%s FUELHH actuals, %s WINDFOR forecasts). Skipping import.",
            counts["actuals"],
            counts["forecasts"],
        )
        return {
            "status": "already_present",
            "actual_rows_present": counts["actuals"],
            "forecast_rows_present": counts["forecasts"],
            "actual_rows_verified": counts["actuals"],
            "forecast_rows_verified": counts["forecasts"],
        }

    # Step 2: Check CSV Files
    csv_present, actual_csv, forecast_csv = check_csv_data_present()
    if not csv_present or force:
        # Step 3: Run script to fetch/generate CSVs if not present
        logger.info(
            "CSV files not found on disk at %s or %s (or force=True). Running import script...",
            actual_csv,
            forecast_csv,
        )
        generate_import_csvs()
        csv_present, actual_csv, forecast_csv = check_csv_data_present()
        if not csv_present:
            raise FileNotFoundError(
                f"Import script completed but expected CSVs were not found at {actual_csv} or {forecast_csv}"
            )
    else:
        logger.info(
            "Data not in DB, but found existing CSV files at %s and %s. Importing directly...",
            actual_csv,
            forecast_csv,
        )

    # Step 4: Transform and load CSV rows into DB
    logger.info("Transforming and importing CSV data into database...")
    loaded = load_january_csvs(session, actual_csv, forecast_csv)
    verified = verify_january(session, loaded["forecast_rows_in_csv"])
    logger.info("Database load verified successfully: %s", verified)
    return {
        "status": "loaded",
        **loaded,
        "actual_rows_verified": verified["actuals"],
        "forecast_rows_verified": verified["forecasts"],
    }


def init(*, force: bool = False) -> dict[str, Any]:
    """Apply migrations and ensure data is loaded according to the tiered hierarchy."""
    apply_migrations()
    engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            return ensure_data_loaded(session, force=force)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize and verify January 2026 wind data."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check presence of data in DB and CSV without modifying anything.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-importing CSV data into database even if already present.",
    )
    args = parser.parse_args()

    if args.check_only:
        csv_present, actual_path, forecast_path = check_csv_data_present()
        logger.info("=== CSV Presence Check ===")
        logger.info(
            "CSV Files: %s (Actuals: %s [%s], Forecasts: %s [%s])",
            "PRESENT" if csv_present else "MISSING",
            actual_path.name,
            "FOUND" if actual_path.is_file() else "NOT FOUND",
            forecast_path.name,
            "FOUND" if forecast_path.is_file() else "NOT FOUND",
        )
        try:
            apply_migrations()
            engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
            with Session(engine) as session:
                db_present, counts = check_db_data_present(session)
                logger.info("=== Database Presence Check ===")
                logger.info(
                    "Database Data: %s (%s actuals, %s forecasts)",
                    "COMPLETE" if db_present else "INCOMPLETE",
                    counts["actuals"],
                    counts["forecasts"],
                )
            engine.dispose()
        except OperationalError:
            logger.warning(
                "Database is currently offline/unreachable at %s. Skipping DB live count check.",
                settings.DATABASE_URL,
            )
        return

    logger.info("Starting January 2026 wind data initialization")
    result = init(force=args.force)
    logger.info(
        "Initialization complete (%s): %s actuals and %s forecasts verified",
        result["status"],
        result["actual_rows_verified"],
        result["forecast_rows_verified"],
    )


if __name__ == "__main__":
    main()
