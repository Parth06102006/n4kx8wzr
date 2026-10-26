from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import WindActual, WindForecast


def get_actuals(
    session: Session,
    *,
    start_time_from: datetime | None = None,
    start_time_to: datetime | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[WindActual], int]:
    statement = select(WindActual)
    count_statement = select(func.count()).select_from(WindActual)

    if start_time_from:
        statement = statement.where(WindActual.start_time >= start_time_from)
        count_statement = count_statement.where(
            WindActual.start_time >= start_time_from
        )
    if start_time_to:
        statement = statement.where(WindActual.start_time <= start_time_to)
        count_statement = count_statement.where(WindActual.start_time <= start_time_to)

    count = session.exec(count_statement).one()
    items = session.exec(
        statement.order_by(col(WindActual.start_time).asc()).offset(skip).limit(limit)
    ).all()
    return list(items), count


def get_forecasts(
    session: Session,
    *,
    start_time_from: datetime | None = None,
    start_time_to: datetime | None = None,
    publish_time_from: datetime | None = None,
    publish_time_to: datetime | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[WindForecast], int]:
    statement = select(WindForecast)
    count_statement = select(func.count()).select_from(WindForecast)

    if start_time_from:
        statement = statement.where(WindForecast.start_time >= start_time_from)
        count_statement = count_statement.where(
            WindForecast.start_time >= start_time_from
        )
    if start_time_to:
        statement = statement.where(WindForecast.start_time <= start_time_to)
        count_statement = count_statement.where(
            WindForecast.start_time <= start_time_to
        )
    if publish_time_from:
        statement = statement.where(WindForecast.publish_time >= publish_time_from)
        count_statement = count_statement.where(
            WindForecast.publish_time >= publish_time_from
        )
    if publish_time_to:
        statement = statement.where(WindForecast.publish_time <= publish_time_to)
        count_statement = count_statement.where(
            WindForecast.publish_time <= publish_time_to
        )

    count = session.exec(count_statement).one()
    items = session.exec(
        statement.order_by(
            col(WindForecast.publish_time).asc(),
            col(WindForecast.start_time).asc(),
        )
        .offset(skip)
        .limit(limit)
    ).all()
    return list(items), count


def get_summary(session: Session) -> dict[str, Any]:
    actuals_count = session.exec(select(func.count()).select_from(WindActual)).one()
    forecasts_count = session.exec(select(func.count()).select_from(WindForecast)).one()

    actuals_bounds = session.exec(
        select(
            func.min(WindActual.start_time),
            func.max(WindActual.start_time),
            func.avg(WindActual.generation_mw),
        )
    ).one()

    forecasts_bounds = session.exec(
        select(
            func.min(WindForecast.start_time),
            func.max(WindForecast.start_time),
            func.avg(WindForecast.generation_mw),
        )
    ).one()

    actual_mean = float(actuals_bounds[2]) if actuals_bounds[2] is not None else None
    forecast_mean = (
        float(forecasts_bounds[2]) if forecasts_bounds[2] is not None else None
    )
    bias_ratio = (
        round(forecast_mean / actual_mean, 4)
        if actual_mean and forecast_mean and actual_mean > 0
        else None
    )

    return {
        "actuals_count": actuals_count,
        "forecasts_count": forecasts_count,
        "actuals_start_time_min": actuals_bounds[0],
        "actuals_start_time_max": actuals_bounds[1],
        "forecasts_start_time_min": forecasts_bounds[0],
        "forecasts_start_time_max": forecasts_bounds[1],
        "actual_mean_generation_mw": actual_mean,
        "forecast_mean_generation_mw": forecast_mean,
        "forecast_bias_ratio": bias_ratio,
    }
