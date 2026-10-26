from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import WindActual, WindForecast


def test_read_empty_actuals(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/wind/actuals")
    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 0
    assert content["data"] == []


def test_read_actuals_with_data(client: TestClient, db: Session) -> None:
    t1 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    db.add(WindActual(start_time=t1, generation_mw=Decimal("5000.5"), source="FUELHH"))
    db.add(WindActual(start_time=t2, generation_mw=Decimal("5200.0"), source="FUELHH"))
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/wind/actuals")
    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 2
    assert len(content["data"]) == 2
    assert float(content["data"][0]["generation_mw"]) == 5000.5

    # Filter with start_time_from
    filter_resp = client.get(
        f"{settings.API_V1_STR}/wind/actuals",
        params={"start_time_from": "2026-01-01T00:15:00Z"},
    )
    assert filter_resp.status_code == 200
    filtered = filter_resp.json()
    assert filtered["count"] == 1
    assert float(filtered["data"][0]["generation_mw"]) == 5200.0


def test_read_forecasts(client: TestClient, db: Session) -> None:
    pub = datetime(2026, 1, 1, 2, 30, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
    db.add(
        WindForecast(
            publish_time=pub,
            start_time=t1,
            generation_mw=Decimal("6000.0"),
            source="WINDFOR",
        )
    )
    db.add(
        WindForecast(
            publish_time=pub,
            start_time=t2,
            generation_mw=Decimal("6100.0"),
            source="WINDFOR",
        )
    )
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/wind/forecasts")
    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 2
    assert len(content["data"]) == 2
    assert float(content["data"][0]["generation_mw"]) == 6000.0


def test_read_summary(client: TestClient, db: Session) -> None:
    # When empty
    resp_empty = client.get(f"{settings.API_V1_STR}/wind/summary")
    assert resp_empty.status_code == 200
    empty_summary = resp_empty.json()
    assert empty_summary["actuals_count"] == 0
    assert empty_summary["forecasts_count"] == 0

    # Seed data
    t = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    db.add(WindActual(start_time=t, generation_mw=Decimal("10000.0"), source="FUELHH"))
    db.add(
        WindForecast(
            publish_time=t,
            start_time=t,
            generation_mw=Decimal("11500.0"),
            source="WINDFOR",
        )
    )
    db.commit()

    resp = client.get(f"{settings.API_V1_STR}/wind/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["actuals_count"] == 1
    assert summary["forecasts_count"] == 1
    assert summary["actual_mean_generation_mw"] == 10000.0
    assert summary["forecast_mean_generation_mw"] == 11500.0
    assert summary["forecast_bias_ratio"] == 1.15


def test_decision_coverage(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/wind/decision-coverage")
    assert response.status_code == 200
    data = response.json()
    assert data["total_decisions"] > 0
    assert data["fully_covered_decisions"] > 0
    assert "data" in data
    assert len(data["data"]) == data["total_decisions"]
