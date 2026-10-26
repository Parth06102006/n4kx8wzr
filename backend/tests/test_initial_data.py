from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session

from app.core.config import settings
from app.initial_data import (
    check_csv_data_present,
    check_db_data_present,
    ensure_data_loaded,
)
from app.models import WindActual, WindForecast


def test_check_db_data_present_empty(db: Session) -> None:
    is_present, counts = check_db_data_present(db)
    assert is_present is False
    assert counts["actuals"] == 0
    assert counts["forecasts"] == 0


def test_check_csv_data_present() -> None:
    csv_present, actual_path, forecast_path = check_csv_data_present()
    assert csv_present is True
    assert actual_path.name == settings.ACTUAL_CSV_NAME
    assert forecast_path.name == settings.FORECAST_CSV_NAME


def test_ensure_data_loaded_when_db_already_present(db: Session) -> None:
    t1 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    db.add(WindForecast(publish_time=t1, start_time=t1, generation_mw=Decimal("5000.0"), source="WINDFOR"))
    for i in range(settings.EXPECTED_ACTUAL_RECORDS):
        st = datetime(2025, 12, 31, 0, 0, tzinfo=UTC)
        st_unique = datetime.fromtimestamp(st.timestamp() + i * 1800, tz=UTC)
        db.add(WindActual(start_time=st_unique, generation_mw=Decimal("1000.0"), source="FUELHH"))
    db.commit()

    is_present, counts = check_db_data_present(db)
    assert is_present is True

    result = ensure_data_loaded(db, force=False)
    assert result["status"] == "already_present"
    assert result["actual_rows_verified"] == settings.EXPECTED_ACTUAL_RECORDS


def test_ensure_data_loaded_from_csv(db: Session) -> None:
    result = ensure_data_loaded(db, force=False)
    assert result["status"] == "loaded"
    assert result["actual_rows_verified"] == settings.EXPECTED_ACTUAL_RECORDS
    assert result["forecast_rows_verified"] == settings.EXPECTED_FORECAST_RECORDS

    # Running a second time should immediately hit step 1: already_present
    second_result = ensure_data_loaded(db, force=False)
    assert second_result["status"] == "already_present"
