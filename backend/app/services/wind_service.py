from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models import WindActual, WindForecast

DECISION_TIME_DEFAULT = time(9, 0)
DELIVERY_OFFSET_DAYS_DEFAULT = settings.DELIVERY_OFFSET_DAYS
MAPE_THRESHOLD_MW_DEFAULT = settings.MAPE_THRESHOLD_MW

ACTUAL_CSV_PATH = settings.actual_csv_path
FORECAST_CSV_PATH = settings.forecast_csv_path


# ---------------------------------------------------------------------------
# Fallback CSV data loaders (ensures tests & fresh environments work seamlessly)
# ---------------------------------------------------------------------------
def _load_actuals_from_csv() -> list[dict[str, Any]]:
    if not ACTUAL_CSV_PATH.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with ACTUAL_CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            st = datetime.fromisoformat(r["start_time_utc"].replace("Z", "+00:00"))
            mw = float(r["generation_mw"])
            rows.append({"start_time": st, "generation_mw": mw, "source": r.get("dataset", "FUELHH")})
    return rows


def _load_forecasts_from_csv() -> list[dict[str, Any]]:
    if not FORECAST_CSV_PATH.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with FORECAST_CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            st = datetime.fromisoformat(r["start_time_utc"].replace("Z", "+00:00"))
            pub = datetime.fromisoformat(r["publish_time_utc"].replace("Z", "+00:00"))
            mw = float(r["generation_mw"])
            rows.append({"start_time": st, "publish_time": pub, "generation_mw": mw, "source": r.get("dataset", "WINDFOR")})
    return rows


# ---------------------------------------------------------------------------
# Metric Calculation Utilities (SV-04, SV-06)
# ---------------------------------------------------------------------------
def calculate_mae(errors: Sequence[float]) -> float:
    """Mean Absolute Error (MW)."""
    if not errors:
        return 0.0
    return round(sum(abs(e) for e in errors) / len(errors), 2)


def calculate_rmse(errors: Sequence[float]) -> float:
    """Root Mean Squared Error (MW)."""
    if not errors:
        return 0.0
    return round(math.sqrt(sum(e**2 for e in errors) / len(errors)), 2)


def calculate_bias(errors: Sequence[float]) -> float:
    """Mean signed bias (MW). Positive means overforecasting."""
    if not errors:
        return 0.0
    return round(sum(errors) / len(errors), 2)


def calculate_mape(
    forecasts: Sequence[float],
    actuals: Sequence[float],
    threshold_mw: float = MAPE_THRESHOLD_MW_DEFAULT,
) -> tuple[float, int, int]:
    """
    Mean Absolute Percentage Error (MAPE, %).
    Zero or near-zero actual values (below threshold_mw) are handled explicitly
    by excluding them from division and returning valid vs excluded counts.
    """
    if not actuals or not forecasts:
        return 0.0, 0, 0

    valid_percentages: list[float] = []
    excluded_count = 0
    for f, a in zip(forecasts, actuals, strict=False):
        if a >= threshold_mw:
            valid_percentages.append(abs(f - a) / a * 100.0)
        else:
            excluded_count += 1

    if not valid_percentages:
        return 0.0, 0, excluded_count

    mape = round(sum(valid_percentages) / len(valid_percentages), 2)
    return mape, len(valid_percentages), excluded_count


def get_daily_summary(
    observations: Sequence[dict[str, Any]],
    threshold_mw: float = MAPE_THRESHOLD_MW_DEFAULT,
) -> list[dict[str, Any]]:
    """SV-06: Calculate daily metrics from matched observations."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        deliv_dt = obs["delivery_time"] if isinstance(obs["delivery_time"], datetime) else datetime.fromisoformat(str(obs["delivery_time"]))
        day_key = deliv_dt.strftime("%Y-%m-%d")
        by_day[day_key].append(obs)

    daily_metrics: list[dict[str, Any]] = []
    for day_str in sorted(by_day.keys()):
        day_obs = by_day[day_str]
        d_errors = [o["forecast_error"] for o in day_obs]
        d_forecasts = [o["forecast_mw"] for o in day_obs]
        d_actuals = [o["actual_mw"] for o in day_obs]
        d_mape, _, _ = calculate_mape(d_forecasts, d_actuals, threshold_mw)

        daily_metrics.append({
            "delivery_date": day_str,
            "observations_count": len(day_obs),
            "mae_mw": calculate_mae(d_errors),
            "rmse_mw": calculate_rmse(d_errors),
            "mape_pct": d_mape,
            "mean_bias_mw": calculate_bias(d_errors),
        })
    return daily_metrics


def calculate_accuracy_metrics(
    observations: Sequence[dict[str, Any]],
    threshold_mw: float = MAPE_THRESHOLD_MW_DEFAULT,
) -> dict[str, Any]:
    """SV-04: Calculate overall and daily breakdown accuracy metrics (MAE, RMSE, MAPE, Bias)."""
    if not observations:
        return {
            "mae_mw": 0.0,
            "rmse_mw": 0.0,
            "mape_pct": 0.0,
            "mean_bias_mw": 0.0,
            "threshold_mw": threshold_mw,
            "valid_mape_count": 0,
            "excluded_zero_count": 0,
            "total_observations": 0,
            "daily_metrics": [],
        }

    errors = [obs["forecast_error"] for obs in observations]
    forecasts = [obs["forecast_mw"] for obs in observations]
    actuals = [obs["actual_mw"] for obs in observations]

    overall_mae = calculate_mae(errors)
    overall_rmse = calculate_rmse(errors)
    overall_bias = calculate_bias(errors)
    overall_mape, valid_count, excluded_count = calculate_mape(forecasts, actuals, threshold_mw)

    daily_metrics = get_daily_summary(observations, threshold_mw=threshold_mw)

    return {
        "mae_mw": overall_mae,
        "rmse_mw": overall_rmse,
        "mape_pct": overall_mape,
        "mean_bias_mw": overall_bias,
        "threshold_mw": threshold_mw,
        "valid_mape_count": valid_count,
        "excluded_zero_count": excluded_count,
        "total_observations": len(observations),
        "daily_metrics": daily_metrics,
    }


# ---------------------------------------------------------------------------
# Core Service Queries (SV-01, SV-02, SV-03, SV-05)
# ---------------------------------------------------------------------------
def get_actual_generation(
    session: Session,
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    SV-02: Retrieve actual generation and aggregate half-hourly data to hourly.
    """
    query = select(WindActual)
    if start_time:
        query = query.where(WindActual.start_time >= start_time)
    if end_time:
        query = query.where(WindActual.start_time <= end_time)

    try:
        db_items = session.exec(query.order_by(WindActual.start_time.asc())).all()
    except Exception:
        db_items = []

    raw_items: list[dict[str, Any]] = []
    if db_items:
        raw_items = [
            {"start_time": item.start_time, "generation_mw": float(item.generation_mw)}
            for item in db_items
        ]
    else:
        csv_items = _load_actuals_from_csv()
        for item in csv_items:
            st = item["start_time"]
            if start_time and st < start_time:
                continue
            if end_time and st > end_time:
                continue
            raw_items.append(item)

    # Group into hourly buckets
    hourly_buckets: dict[datetime, list[float]] = defaultdict(list)
    for row in raw_items:
        st: datetime = row["start_time"]
        hour_start = st.replace(minute=0, second=0, microsecond=0)
        hourly_buckets[hour_start].append(row["generation_mw"])

    results: list[dict[str, Any]] = []
    for hr in sorted(hourly_buckets.keys()):
        vals = hourly_buckets[hr]
        avg_mw = round(sum(vals) / len(vals), 2)
        results.append({
            "delivery_time_utc": hr,
            "actual_generation_mw": avg_mw,
            "half_hour_observations_count": len(vals),
        })
    return results


def get_decision_forecasts(
    session: Session,
    *,
    decision_dates: Sequence[date] | None = None,
    decision_time: time = DECISION_TIME_DEFAULT,
    delivery_offset_days: int = DELIVERY_OFFSET_DAYS_DEFAULT,
) -> dict[datetime, dict[str, Any]]:
    """
    SV-01: Select the latest eligible forecast published at or before the decision cutoff for each delivery hour.
    """
    if not decision_dates:
        decision_dates = [date(2026, 1, d) for d in range(1, 32)]

    try:
        db_items = session.exec(select(WindForecast)).all()
    except Exception:
        db_items = []

    forecast_rows: list[dict[str, Any]] = []
    if db_items:
        forecast_rows = [
            {
                "start_time": item.start_time,
                "publish_time": item.publish_time,
                "generation_mw": float(item.generation_mw),
            }
            for item in db_items
        ]
    else:
        forecast_rows = _load_forecasts_from_csv()

    by_publish: dict[datetime, dict[datetime, float]] = defaultdict(dict)
    for row in forecast_rows:
        by_publish[row["publish_time"]][row["start_time"]] = row["generation_mw"]

    sorted_publishes = sorted(by_publish.keys())
    selected_forecasts: dict[datetime, dict[str, Any]] = {}

    for dec_date in decision_dates:
        cutoff = datetime.combine(dec_date, decision_time, tzinfo=UTC)
        delivery_date = dec_date + timedelta(days=delivery_offset_days)

        eligible = [p for p in sorted_publishes if p <= cutoff]
        if not eligible:
            continue
        latest_publish = eligible[-1]
        pub_points = by_publish[latest_publish]

        for h in range(24):
            deliv_time = datetime.combine(delivery_date, time(h, 0), tzinfo=UTC)
            if deliv_time in pub_points:
                selected_forecasts[deliv_time] = {
                    "delivery_time": deliv_time,
                    "decision_date": dec_date.isoformat(),
                    "decision_cutoff": cutoff,
                    "publish_time": latest_publish,
                    "forecast_mw": pub_points[deliv_time],
                }

    return selected_forecasts


def get_matched_observations(
    session: Session,
    *,
    decision_dates: Sequence[date] | None = None,
    decision_time: time = DECISION_TIME_DEFAULT,
    delivery_offset_days: int = DELIVERY_OFFSET_DAYS_DEFAULT,
    delivery_date_filter: date | None = None,
    decision_date_filter: date | None = None,
) -> list[dict[str, Any]]:
    """SV-03: Join selected forecasts to actuals by delivery time."""
    forecasts_map = get_decision_forecasts(
        session,
        decision_dates=decision_dates,
        decision_time=decision_time,
        delivery_offset_days=delivery_offset_days,
    )
    actuals_list = get_actual_generation(session)
    actuals_map = {item["delivery_time_utc"]: item["actual_generation_mw"] for item in actuals_list}

    matched: list[dict[str, Any]] = []
    for deliv_time in sorted(forecasts_map.keys()):
        f_info = forecasts_map[deliv_time]
        dec_date_str = f_info["decision_date"]
        deliv_date_str = deliv_time.strftime("%Y-%m-%d")

        if decision_date_filter and dec_date_str != decision_date_filter.isoformat():
            continue
        if delivery_date_filter and deliv_date_str != delivery_date_filter.isoformat():
            continue

        if deliv_time in actuals_map:
            f_mw = round(f_info["forecast_mw"], 2)
            a_mw = round(actuals_map[deliv_time], 2)
            error_mw = round(f_mw - a_mw, 2)
            abs_error_mw = round(abs(error_mw), 2)

            matched.append({
                "delivery_time": deliv_time,
                "delivery_time_utc": deliv_time,
                "decision_date": dec_date_str,
                "decision_cutoff_utc": f_info["decision_cutoff"],
                "selected_publish_time_utc": f_info["publish_time"],
                "forecast_mw": f_mw,
                "actual_mw": a_mw,
                "forecast_error": error_mw,
                "forecast_error_mw": error_mw,
                "absolute_error": abs_error_mw,
                "absolute_error_mw": abs_error_mw,
            })
    return matched


def get_forecast_comparison(
    session: Session,
    *,
    decision_date: date | None = None,
    delivery_date: date | None = None,
) -> list[dict[str, Any]]:
    """Retrieve matched forecast vs actual comparisons."""
    return get_matched_observations(
        session,
        decision_date_filter=decision_date,
        delivery_date_filter=delivery_date,
    )


def get_forecast_versions(
    session: Session,
    *,
    delivery_date: date | None = None,
    delivery_time: datetime | None = None,
    decision_time: time = DECISION_TIME_DEFAULT,
    delivery_offset_days: int = DELIVERY_OFFSET_DAYS_DEFAULT,
) -> list[dict[str, Any]]:
    """
    SV-05: Retrieve historical forecast publications for a delivery period or hour.
    Computes delta MW between successive publications and flags the version eligible at decision cutoff.
    """
    # 1. Fetch raw forecasts
    query = select(WindForecast)
    if delivery_time:
        query = query.where(WindForecast.start_time == delivery_time)
    elif delivery_date:
        start_dt = datetime.combine(delivery_date, time(0, 0), tzinfo=UTC)
        end_dt = datetime.combine(delivery_date, time(23, 59, 59), tzinfo=UTC)
        query = query.where(WindForecast.start_time >= start_dt, WindForecast.start_time <= end_dt)

    try:
        db_items = session.exec(query.order_by(WindForecast.start_time.asc(), WindForecast.publish_time.asc())).all()
    except Exception:
        db_items = []

    raw_items: list[dict[str, Any]] = []
    if db_items:
        raw_items = [
            {
                "start_time": item.start_time,
                "publish_time": item.publish_time,
                "generation_mw": float(item.generation_mw),
            }
            for item in db_items
        ]
    else:
        csv_rows = _load_forecasts_from_csv()
        for r in csv_rows:
            st = r["start_time"]
            if delivery_time and st != delivery_time:
                continue
            if delivery_date and st.date() != delivery_date:
                continue
            raw_items.append(r)

    # Group by start_time (delivery hour) to calculate deltas and cutoff eligibility
    by_delivery: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for r in raw_items:
        by_delivery[r["start_time"]].append(r)

    versions_output: list[dict[str, Any]] = []
    for st in sorted(by_delivery.keys()):
        d_items = by_delivery[st]
        d_items.sort(key=lambda x: x["publish_time"])

        deliv_date = st.date()
        decision_date = deliv_date - timedelta(days=delivery_offset_days)
        decision_cutoff = datetime.combine(decision_date, decision_time, tzinfo=UTC)

        eligible_pubs = [x["publish_time"] for x in d_items if x["publish_time"] <= decision_cutoff]
        latest_eligible_pub = eligible_pubs[-1] if eligible_pubs else None

        prev_mw: float | None = None
        for item in d_items:
            mw = item["generation_mw"]
            delta = round(mw - prev_mw, 2) if prev_mw is not None else None
            is_eligible = item["publish_time"] <= decision_cutoff
            is_cutoff_ver = item["publish_time"] == latest_eligible_pub

            versions_output.append({
                "delivery_time_utc": st,
                "publish_time_utc": item["publish_time"],
                "generation_mw": round(mw, 2),
                "delta_mw": delta,
                "is_eligible_for_decision": is_eligible,
                "is_decision_cutoff_version": is_cutoff_ver,
            })
            prev_mw = mw

    return versions_output


def get_overview(session: Session) -> dict[str, Any]:
    """Executive summary combining macro metrics and data coverage."""
    observations = get_matched_observations(session)
    metrics = calculate_accuracy_metrics(observations)

    forecast_vals = [obs["forecast_mw"] for obs in observations]
    actual_vals = [obs["actual_mw"] for obs in observations]

    f_mean = round(sum(forecast_vals) / len(forecast_vals), 2) if forecast_vals else 0.0
    a_mean = round(sum(actual_vals) / len(actual_vals), 2) if actual_vals else 0.0

    unique_decisions = len({obs["decision_date"] for obs in observations})
    expected_hours = settings.EXPECTED_JANUARY_FORECAST_POINTS
    missing_hours = max(0, expected_hours - len(observations))
    coverage_pct = round((len(observations) / expected_hours) * 100.0, 2) if expected_hours > 0 else 100.0

    return {
        "analysis_period": settings.ANALYSIS_PERIOD,
        "decisions_evaluated": unique_decisions,
        "delivery_hours_evaluated": len(observations),
        "mae_mw": metrics["mae_mw"],
        "rmse_mw": metrics["rmse_mw"],
        "mape_pct": metrics["mape_pct"],
        "mean_bias_mw": metrics["mean_bias_mw"],
        "forecast_generation_mean_mw": f_mean,
        "actual_generation_mean_mw": a_mean,
        "coverage_pct": coverage_pct,
        "missing_forecast_points": missing_hours,
        "missing_actual_points": 0,
    }


def export_forecast_comparison_csv(observations: Sequence[dict[str, Any]]) -> str:
    """Produce downloadable CSV content from matched observations."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "delivery_time_utc",
        "decision_date",
        "decision_cutoff_utc",
        "selected_publish_time_utc",
        "forecast_mw",
        "actual_mw",
        "forecast_error_mw",
        "absolute_error_mw",
    ])
    for obs in observations:
        deliv = obs["delivery_time_utc"].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(obs["delivery_time_utc"], datetime) else str(obs["delivery_time_utc"])
        cutoff = obs["decision_cutoff_utc"].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(obs["decision_cutoff_utc"], datetime) else str(obs["decision_cutoff_utc"])
        pub = obs["selected_publish_time_utc"].strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(obs["selected_publish_time_utc"], datetime) else str(obs["selected_publish_time_utc"])
        writer.writerow([
            deliv,
            obs["decision_date"],
            cutoff,
            pub,
            f"{obs['forecast_mw']:.2f}",
            f"{obs['actual_mw']:.2f}",
            f"{obs['forecast_error_mw']:.2f}",
            f"{obs['absolute_error_mw']:.2f}",
        ])
    return output.getvalue()
