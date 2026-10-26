from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session

from app import crud
from app.models import WindActual, WindForecast


def test_crud_actuals(db: Session) -> None:
    t1 = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
    db.add(
        WindActual(start_time=t1, generation_mw=Decimal("4000.000"), source="FUELHH")
    )
    db.add(
        WindActual(start_time=t2, generation_mw=Decimal("4500.000"), source="FUELHH")
    )
    db.commit()

    items, count = crud.get_actuals(db)
    assert count == 2
    assert len(items) == 2
    assert items[0].generation_mw == Decimal("4000.000")

    items_filtered, count_filtered = crud.get_actuals(
        db, start_time_from=datetime(2026, 1, 15, 8, 15, tzinfo=UTC)
    )
    assert count_filtered == 1
    assert items_filtered[0].start_time == t2


def test_crud_forecasts(db: Session) -> None:
    pub = datetime(2026, 1, 15, 7, 30, tzinfo=UTC)
    t1 = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    db.add(
        WindForecast(
            publish_time=pub,
            start_time=t1,
            generation_mw=Decimal("7000.000"),
            source="WINDFOR",
        )
    )
    db.add(
        WindForecast(
            publish_time=pub,
            start_time=t2,
            generation_mw=Decimal("7200.000"),
            source="WINDFOR",
        )
    )
    db.commit()

    items, count = crud.get_forecasts(db)
    assert count == 2
    assert len(items) == 2


def test_crud_summary(db: Session) -> None:
    t = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    db.add(WindActual(start_time=t, generation_mw=Decimal("2000.000"), source="FUELHH"))
    db.add(
        WindForecast(
            publish_time=t,
            start_time=t,
            generation_mw=Decimal("2500.000"),
            source="WINDFOR",
        )
    )
    db.commit()

    summary = crud.get_summary(db)
    assert summary["actuals_count"] == 1
    assert summary["forecasts_count"] == 1
    assert summary["actual_mean_generation_mw"] == 2000.0
    assert summary["forecast_mean_generation_mw"] == 2500.0
    assert summary["forecast_bias_ratio"] == 1.25
