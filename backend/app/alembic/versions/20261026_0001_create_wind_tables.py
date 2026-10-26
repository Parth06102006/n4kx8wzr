"""Create wind actuals and forecasts tables.

Revision ID: 20261026_0001
Revises:
Create Date: 2026-10-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261026_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wind_actuals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_mw", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "start_time",
            name="uq_wind_actual_source_start",
        ),
    )
    op.create_index(
        "ix_wind_actuals_start_time",
        "wind_actuals",
        ["start_time"],
        unique=False,
    )

    op.create_table(
        "wind_forecasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_mw", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "start_time",
            "publish_time",
            name="uq_wind_forecast_source_start_publish",
        ),
    )
    op.create_index(
        "ix_wind_forecasts_start_time",
        "wind_forecasts",
        ["start_time"],
        unique=False,
    )
    op.create_index(
        "ix_wind_forecasts_publish_time",
        "wind_forecasts",
        ["publish_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wind_forecasts_publish_time", table_name="wind_forecasts")
    op.drop_index("ix_wind_forecasts_start_time", table_name="wind_forecasts")
    op.drop_table("wind_forecasts")
    op.drop_index("ix_wind_actuals_start_time", table_name="wind_actuals")
    op.drop_table("wind_actuals")
