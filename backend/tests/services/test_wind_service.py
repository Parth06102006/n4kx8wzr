import math
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session

from app.models import WindActual, WindForecast
from app.services import wind_service


def test_calculate_metrics_math() -> None:
    errors = [10.0, -20.0, 30.0]
    # MAE = (10 + 20 + 30) / 3 = 20.0
    assert wind_service.calculate_mae(errors) == 20.0

    # RMSE = sqrt((100 + 400 + 900) / 3) = sqrt(1400/3) = sqrt(466.666) ~= 21.60
    assert wind_service.calculate_rmse(errors) == round(math.sqrt(1400.0 / 3.0), 2)

    # Bias = (10 - 20 + 30) / 3 = 20 / 3 = 6.67
    assert wind_service.calculate_bias(errors) == 6.67

    # MAPE
    forecasts = [110.0, 80.0, 130.0, 50.0]
    actuals = [100.0, 100.0, 100.0, 0.0]  # last is below 10 MW threshold
    mape, valid_count, excluded_count = wind_service.calculate_mape(
        forecasts, actuals, threshold_mw=10.0
    )
    # 10/100, 20/100, 30/100 = 10% + 20% + 30% = avg 20%
    assert mape == 20.0
    assert valid_count == 3
    assert excluded_count == 1


def test_get_daily_summary() -> None:
    observations = [
        {
            "delivery_time": datetime(2026, 1, 15, 1, 0, tzinfo=UTC),
            "forecast_mw": 5000.0,
            "actual_mw": 4000.0,
            "forecast_error": 1000.0,
            "absolute_error": 1000.0,
        },
        {
            "delivery_time": datetime(2026, 1, 15, 2, 0, tzinfo=UTC),
            "forecast_mw": 6000.0,
            "actual_mw": 5000.0,
            "forecast_error": 1000.0,
            "absolute_error": 1000.0,
        },
        {
            "delivery_time": datetime(2026, 1, 16, 1, 0, tzinfo=UTC),
            "forecast_mw": 4000.0,
            "actual_mw": 5000.0,
            "forecast_error": -1000.0,
            "absolute_error": 1000.0,
        },
    ]
    daily = wind_service.get_daily_summary(observations)
    assert len(daily) == 2
    assert daily[0]["delivery_date"] == "2026-01-15"
    assert daily[0]["observations_count"] == 2
    assert daily[0]["mae_mw"] == 1000.0
    assert daily[0]["mean_bias_mw"] == 1000.0

    assert daily[1]["delivery_date"] == "2026-01-16"
    assert daily[1]["observations_count"] == 1
    assert daily[1]["mean_bias_mw"] == -1000.0


def test_service_actual_generation_hourly_aggregation(db: Session) -> None:
    t1 = datetime(2026, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 10, 0, 30, tzinfo=UTC)
    db.add(WindActual(start_time=t1, generation_mw=Decimal("4000.0"), source="FUELHH"))
    db.add(WindActual(start_time=t2, generation_mw=Decimal("6000.0"), source="FUELHH"))
    db.commit()

    results = wind_service.get_actual_generation(db, start_time=t1, end_time=t2)
    assert len(results) == 1
    assert results[0]["delivery_time_utc"] == t1
    assert results[0]["actual_generation_mw"] == 5000.0
    assert results[0]["half_hour_observations_count"] == 2


def test_service_decision_forecasts_and_matching(db: Session) -> None:
    pub_eligible = datetime(2026, 1, 10, 7, 30, tzinfo=UTC)
    pub_ineligible = datetime(2026, 1, 10, 11, 30, tzinfo=UTC)

    deliv_hour = datetime(2026, 1, 11, 12, 0, tzinfo=UTC)
    deliv_hour_actual1 = datetime(2026, 1, 11, 12, 0, tzinfo=UTC)
    deliv_hour_actual2 = datetime(2026, 1, 11, 12, 30, tzinfo=UTC)

    db.add(
        WindForecast(
            publish_time=pub_eligible,
            start_time=deliv_hour,
            generation_mw=Decimal("7000.0"),
            source="WINDFOR",
        )
    )
    db.add(
        WindForecast(
            publish_time=pub_ineligible,
            start_time=deliv_hour,
            generation_mw=Decimal("8500.0"),
            source="WINDFOR",
        )
    )

    db.add(
        WindActual(
            start_time=deliv_hour_actual1,
            generation_mw=Decimal("6000.0"),
            source="FUELHH",
        )
    )
    db.add(
        WindActual(
            start_time=deliv_hour_actual2,
            generation_mw=Decimal("6400.0"),
            source="FUELHH",
        )
    )
    db.commit()

    dec_date = datetime(2026, 1, 10).date()
    matched = wind_service.get_matched_observations(db, decision_dates=[dec_date])
    assert len(matched) == 1
    obs = matched[0]
    assert obs["delivery_time_utc"] == deliv_hour
    assert obs["selected_publish_time_utc"] == pub_eligible
    assert obs["forecast_mw"] == 7000.0
    assert obs["actual_mw"] == 6200.0
    assert obs["forecast_error_mw"] == 800.0
    assert obs["absolute_error_mw"] == 800.0


def test_service_forecast_versions(db: Session) -> None:
    deliv = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)
    pub1 = datetime(2026, 1, 14, 4, 30, tzinfo=UTC)
    pub2 = datetime(2026, 1, 14, 7, 30, tzinfo=UTC)
    pub3 = datetime(2026, 1, 14, 11, 30, tzinfo=UTC)

    db.add(
        WindForecast(
            publish_time=pub1,
            start_time=deliv,
            generation_mw=Decimal("5000.0"),
            source="WINDFOR",
        )
    )
    db.add(
        WindForecast(
            publish_time=pub2,
            start_time=deliv,
            generation_mw=Decimal("5200.0"),
            source="WINDFOR",
        )
    )
    db.add(
        WindForecast(
            publish_time=pub3,
            start_time=deliv,
            generation_mw=Decimal("5800.0"),
            source="WINDFOR",
        )
    )
    db.commit()

    versions = wind_service.get_forecast_versions(db, delivery_time=deliv)
    assert len(versions) == 3
    assert versions[0]["delta_mw"] is None
    assert versions[1]["delta_mw"] == 200.0
    assert versions[2]["delta_mw"] == 600.0

    # Decision cutoff is 2026-01-14 09:00 UTC
    assert versions[0]["is_eligible_for_decision"] is True
    assert versions[1]["is_eligible_for_decision"] is True
    assert versions[1]["is_decision_cutoff_version"] is True  # latest eligible
    assert versions[2]["is_eligible_for_decision"] is False
    assert versions[2]["is_decision_cutoff_version"] is False
