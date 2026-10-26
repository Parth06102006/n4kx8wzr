"""Unit tests for the Elexon history importer (no network access required)."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import elexon_history_import as importer


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


class TimestampTests(unittest.TestCase):
    def test_parses_zulu_and_offsets(self) -> None:
        self.assertEqual(
            importer.parse_iso_datetime("2026-01-01T00:00:00Z"), utc(2026, 1, 1)
        )
        self.assertEqual(
            importer.parse_iso_datetime("2026-01-01T01:00:00+01:00"), utc(2026, 1, 1)
        )

    def test_rejects_naive_timestamps(self) -> None:
        with self.assertRaises(ValueError):
            importer.parse_iso_datetime("2026-01-01T00:00:00")


class SettlementDayTests(unittest.TestCase):
    def test_period_counts_across_dst(self) -> None:
        self.assertEqual(importer.settlement_periods_in_day(date(2026, 1, 15)), 48)
        self.assertEqual(importer.settlement_periods_in_day(date(2026, 3, 29)), 46)
        self.assertEqual(importer.settlement_periods_in_day(date(2026, 10, 25)), 50)

    def test_winter_day_starts_at_midnight_utc(self) -> None:
        self.assertEqual(
            importer.local_day_start_utc(date(2026, 1, 15)), utc(2026, 1, 15)
        )

    def test_summer_day_starts_at_2300_utc(self) -> None:
        self.assertEqual(
            importer.local_day_start_utc(date(2026, 6, 1)), utc(2026, 5, 31, 23)
        )


def actual_record(start: datetime, generation: int | None = 10_000) -> dict:
    return {
        "dataset": "FUELHH",
        "publishTime": importer.iso(start + timedelta(minutes=30)),
        "startTime": importer.iso(start),
        "settlementDate": start.astimezone(importer.LONDON).date().isoformat(),
        "settlementPeriod": (
            int(
                (
                    start
                    - importer.local_day_start_utc(
                        start.astimezone(importer.LONDON).date()
                    )
                ).total_seconds()
                // 1800
            )
            + 1
        ),
        "fuelType": "WIND",
        "generation": generation,
    }


class ActualValidationTests(unittest.TestCase):
    def test_accepts_valid_half_hour(self) -> None:
        validator = importer.Validator()
        rows = importer.normalise_actuals(
            [actual_record(utc(2026, 1, 2, 0, 0))], "raw.json", validator
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(validator.errors, 0)

    def test_flags_null_generation(self) -> None:
        validator = importer.Validator()
        rows = importer.normalise_actuals(
            [actual_record(utc(2026, 1, 2, 0, 0), generation=None)],
            "raw.json",
            validator,
        )
        self.assertEqual(rows, [])
        self.assertGreaterEqual(validator.errors, 1)
        self.assertIn(
            "actual_generation_null",
            [issue["code"] for issue in validator.summary()["issues"]],
        )

    def test_flags_out_of_range_generation(self) -> None:
        validator = importer.Validator()
        importer.normalise_actuals(
            [actual_record(utc(2026, 1, 2, 0, 0), generation=1_000_000)],
            "raw.json",
            validator,
        )
        codes = [issue["code"] for issue in validator.summary()["issues"]]
        self.assertIn("actual_generation_range", codes)

    def test_dedupe_keeps_latest_publish(self) -> None:
        validator = importer.Validator()
        first = importer.normalise_actuals(
            [actual_record(utc(2026, 1, 2, 0, 0), generation=1)],
            "first.json",
            validator,
        )[0]
        second = importer.normalise_actuals(
            [actual_record(utc(2026, 1, 2, 0, 0), generation=2)],
            "second.json",
            validator,
        )[0]
        # Give the second copy a later publish time.
        second = importer.ActualRow(
            start_time=second.start_time,
            publish_time=second.publish_time + timedelta(minutes=30),
            settlement_date=second.settlement_date,
            settlement_period=second.settlement_period,
            generation_mw=second.generation_mw,
            raw_file=second.raw_file,
        )
        rows = importer.dedupe_actuals([second, first], validator)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].generation_mw, 2)  # later publish wins
        self.assertEqual(validator.warnings, 1)

    def test_coverage_reports_missing_period(self) -> None:
        validator = importer.Validator()
        rows = []
        start = importer.local_day_start_utc(date(2026, 1, 2))
        for index in range(47):
            rows.append(
                importer.ActualRow(
                    start_time=start + timedelta(minutes=30 * index),
                    publish_time=start + timedelta(minutes=30 * index + 30),
                    settlement_date=date(2026, 1, 2),
                    settlement_period=index + 1,
                    generation_mw=1000.0,
                    raw_file="raw.json",
                )
            )
        coverage = importer.check_actual_coverage(
            rows, date(2026, 1, 2), date(2026, 1, 2), validator
        )
        self.assertEqual(coverage["missing_periods"], 1)
        self.assertEqual(coverage["expected_periods"], 48)
        self.assertEqual(validator.errors, 2)  # missing period + incomplete day
        codes = {issue["code"] for issue in validator.summary()["issues"]}
        self.assertIn("actual_missing_period", codes)
        self.assertIn("actual_day_incomplete", codes)


def forecast_row(
    publish: datetime, start: datetime, generation: float = 10_000
) -> importer.ForecastRow:
    return importer.ForecastRow(
        publish_time=publish,
        start_time=start,
        generation_mw=generation,
        raw_file="windfor.json",
    )


def decision_forecasts(publish: datetime) -> list[importer.ForecastRow]:
    rows = []
    start = importer.local_day_start_utc(date(2026, 1, 2))
    for index in range(24):
        rows.append(forecast_row(publish, start + timedelta(hours=index)))
    return rows


class DecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actuals = []
        start = importer.local_day_start_utc(date(2026, 1, 2))
        for index in range(48):
            self.actuals.append(
                importer.ActualRow(
                    start_time=start + timedelta(minutes=30 * index),
                    publish_time=start + timedelta(minutes=30 * index + 30),
                    settlement_date=date(2026, 1, 2),
                    settlement_period=index + 1,
                    generation_mw=9000.0,
                    raw_file="fuelhh.json",
                )
            )

    def test_prefers_latest_publish_before_decision(self) -> None:
        early = decision_forecasts(utc(2026, 1, 1, 7, 30))
        late = [
            importer.ForecastRow(
                publish_time=utc(2026, 1, 1, 12, 25),
                start_time=row.start_time,
                generation_mw=1234.0,
                raw_file="late.json",
            )
            for row in early
        ]
        validator = importer.Validator()
        rows = importer.build_decision_rows(
            self.actuals,
            early + late,
            [date(2026, 1, 1)],
            time(9, 0),
            1,
            1,
            validator,
        )
        self.assertEqual(rows[0]["latest_publish_utc"], "2026-01-01T07:30:00Z")
        self.assertEqual(rows[0]["forecast_coverage_pct"], "100.0")
        self.assertEqual(rows[0]["actual_coverage_pct"], "100.0")
        self.assertEqual(validator.errors, 0)

    def test_reports_forecast_gap(self) -> None:
        publish = utc(2026, 1, 1, 7, 30)
        forecasts = decision_forecasts(publish)[:23]
        validator = importer.Validator()
        rows = importer.build_decision_rows(
            self.actuals, forecasts, [date(2026, 1, 1)], time(9, 0), 1, 1, validator
        )
        self.assertEqual(rows[0]["forecast_points_available"], 23)
        self.assertEqual(rows[0]["forecast_points_expected"], 24)
        self.assertIn(
            "decision_forecast_gap", [i["code"] for i in validator.summary()["issues"]]
        )

    def test_reports_no_publish_yet(self) -> None:
        validator = importer.Validator()
        rows = importer.build_decision_rows(
            self.actuals,
            [forecast_row(utc(2026, 1, 1, 12, 25), utc(2026, 1, 2))],
            [date(2026, 1, 1)],
            time(9, 0),
            1,
            1,
            validator,
        )
        self.assertEqual(rows[0]["latest_publish_utc"], "")
        self.assertIn(
            "decision_no_forecast", [i["code"] for i in validator.summary()["issues"]]
        )


class ForecastTests(unittest.TestCase):
    def test_resolution_detection(self) -> None:
        times = [utc(2026, 1, 1, hour) for hour in range(5)]
        self.assertEqual(importer.forecast_resolution_minutes(times), 60)
        base = utc(2026, 1, 1)
        half_hours = [base + timedelta(minutes=30 * index) for index in range(4)]
        self.assertEqual(importer.forecast_resolution_minutes(half_hours), 30)

    def test_dedupe_conflicting_rows_keeps_first_and_warns(self) -> None:
        publish = utc(2026, 1, 1, 7, 30)
        start = utc(2026, 1, 2)
        validator = importer.Validator()
        rows = importer.dedupe_forecasts(
            [forecast_row(publish, start, 1), forecast_row(publish, start, 2)],
            validator,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].generation_mw, 1)
        self.assertIn(
            "forecast_duplicate_conflict",
            [i["code"] for i in validator.summary()["issues"]],
        )


if __name__ == "__main__":
    unittest.main()
