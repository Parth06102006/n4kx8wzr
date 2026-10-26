#!/usr/bin/env python3
"""Import historical Elexon wind outturn (FUELHH) and wind forecasts (WINDFOR).

The importer is deliberately dependency-free (Python standard library only) so it
can be re-run from a clean checkout. It:

* fetches FUELHH ``fuelType=WIND`` actuals by settlement date;
* fetches WINDFOR forecast *publishes* by publish time (the API has no
  ``startTime`` filter for WINDFOR - filtering is done locally and validated);
* stores the exact API response bytes plus request metadata for auditing;
* writes normalised CSVs and a validation report;
* produces a day-ahead decision coverage table for January 2026 by default.

Typical use::

    python3 scripts/elexon_history_import.py

Repeat the same command to reuse the cached raw responses. Add ``--refresh`` to
download them again. See docs/elexon-import.md for details.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

API_BASE = "https://data.elexon.co.uk/bmrs/api/v1/datasets"

# FUELHH settlement dates and periods are defined in GB local time, not UTC.
# During BST a settlement day starts at 23:00 UTC the previous day and DST
# transition days have 46 or 50 settlement periods.
LONDON = ZoneInfo("Europe/London")
USER_AGENT = "renewable-forecast-elexon-import/1.0"
SCHEMA_VERSION = 1

# January 2026 is GMT, so a settlement day is exactly 48 half-hours. These
# defaults keep one day of padding around January so that a day-ahead decision
# on 31 January has a complete 1 February delivery day.
DEFAULT_DELIVERY_START = date(2025, 12, 31)
DEFAULT_DELIVERY_END = date(2026, 2, 1)
DEFAULT_DECISION_START = date(2026, 1, 1)
DEFAULT_DECISION_END = date(2026, 1, 31)
DEFAULT_DECISION_TIME = dtime(9, 0)

# Sanity bounds in MW. GB wind outturn has stayed well inside these; values
# outside them almost certainly mean a unit or parsing problem.
MIN_PLAUSIBLE_MW = 0
MAX_PLAUSIBLE_MW = 30_000
MAX_ISSUE_EXAMPLES = 5
ACTUAL_CHUNK_DAYS = 31
FORECAST_CHUNK_DAYS = 3


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_datetime(value: Any) -> datetime:
    """Parse an Elexon ISO-8601 timestamp and normalise it to UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"not an ISO-8601 timestamp: {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value!r}")
    return parsed.astimezone(UTC)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_clock(value: str) -> dtime:
    return dtime.fromisoformat(value)


def daterange_inclusive(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def local_day_start_utc(day: date) -> datetime:
    """First instant of a GB settlement day, expressed in UTC."""
    return datetime.combine(day, dtime(0, 0), tzinfo=LONDON).astimezone(UTC)


def settlement_periods_in_day(day: date) -> int:
    """Number of half-hour settlement periods in a GB settlement day (46/48/50)."""
    duration = local_day_start_utc(day + timedelta(days=1)) - local_day_start_utc(day)
    return int(duration.total_seconds() // 1800)


def chunk_dates(start: date, end: date, days: int) -> list[tuple[date, date]]:
    if end < start:
        raise ValueError("end date precedes start date")
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def chunk_datetimes(
    start: datetime, end: datetime, days: int
) -> list[tuple[datetime, datetime]]:
    if end <= start:
        raise ValueError("end time must be after start time")
    chunks: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=days), end)
        chunks.append((current, chunk_end))
        current = chunk_end
    return chunks


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_write_csv(
    path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(fieldnames), lineterminator="\n"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Validation collection
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    count: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)

    def add(self, example: dict[str, Any]) -> None:
        self.count += 1
        if len(self.examples) < MAX_ISSUE_EXAMPLES:
            self.examples.append(example)


class Validator:
    def __init__(self) -> None:
        self._issues: dict[tuple[str, str], Issue] = {}
        self.checks: dict[str, Any] = {}

    def add(self, severity: str, code: str, message: str, **example: Any) -> None:
        key = (severity, code)
        issue = self._issues.get(key)
        if issue is None:
            issue = Issue(severity=severity, code=code, message=message)
            self._issues[key] = issue
        issue.add(example)

    def error(self, code: str, message: str, **example: Any) -> None:
        self.add("error", code, message, **example)

    def warn(self, code: str, message: str, **example: Any) -> None:
        self.add("warning", code, message, **example)

    @property
    def errors(self) -> int:
        return sum(i.count for i in self._issues.values() if i.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(i.count for i in self._issues.values() if i.severity == "warning")

    def summary(self) -> dict[str, Any]:
        return {
            "status": "error"
            if self.errors
            else ("warning" if self.warnings else "ok"),
            "error_count": self.errors,
            "warning_count": self.warnings,
            "issues": [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "count": issue.count,
                    "examples": issue.examples,
                }
                for issue in sorted(
                    self._issues.values(), key=lambda i: (i.severity, i.code)
                )
            ],
            "checks": self.checks,
        }


def require_mapping(
    value: Any, validator: Validator, code: str, **ctx: Any
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        validator.error(code, "response record is not a JSON object", **ctx)
        return None
    return value


def require_timestamp(
    record: dict[str, Any], field_name: str, validator: Validator, code: str, **ctx: Any
) -> datetime | None:
    try:
        return parse_iso_datetime(record.get(field_name))
    except (TypeError, ValueError) as exc:
        validator.error(code, f"invalid {field_name}: {exc}", **ctx)
        return None


def require_int(
    record: dict[str, Any], field_name: str, validator: Validator, code: str, **ctx: Any
) -> int | None:
    value = record.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        validator.error(code, f"{field_name} is not an integer: {value!r}", **ctx)
        return None
    return value


def validate_generation(
    value: Any, validator: Validator, code: str, **ctx: Any
) -> float | None:
    if value is None:
        validator.error(f"{code}_null", "generation is null", **ctx)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        validator.error(code, f"generation is not numeric: {value!r}", **ctx)
        return None
    number = float(value)
    if not math.isfinite(number):
        validator.error(code, f"generation is not finite: {value!r}", **ctx)
        return None
    if not (MIN_PLAUSIBLE_MW <= number <= MAX_PLAUSIBLE_MW):
        validator.error(
            f"{code}_range",
            f"generation {number} MW outside plausible range "
            f"[{MIN_PLAUSIBLE_MW}, {MAX_PLAUSIBLE_MW}] MW",
            **ctx,
        )
        return None
    return number


# ---------------------------------------------------------------------------
# HTTP client and raw store
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    url: str
    body: bytes
    records: list[dict[str, Any]]
    status: int
    headers: dict[str, str]


class ElexonClient:
    def __init__(
        self,
        timeout: float = 60.0,
        max_retries: int = 5,
        request_interval: float = 0.2,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_interval = request_interval
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)

    def fetch(self, dataset: str, params: dict[str, Any]) -> FetchResult:
        url = (
            f"{API_BASE}/{dataset}/stream?{urllib.parse.urlencode(params, doseq=True)}"
        )
        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle()
            request = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    status = response.status
                    headers = {k.lower(): v for k, v in response.headers.items()}
                self._last_request_at = time.monotonic()
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                body_text = exc.read().decode("utf-8", errors="replace")[:1000]
                if (
                    exc.code in (408, 425, 429, 500, 502, 503, 504)
                    and attempt < self.max_retries
                ):
                    retry_after = (
                        exc.headers.get("Retry-After") if exc.headers else None
                    )
                    try:
                        wait = float(retry_after) if retry_after else delay
                    except ValueError:
                        wait = delay
                    print(
                        f"  HTTP {exc.code} for {dataset}; retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{self.max_retries})",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    delay = min(delay * 2, 30.0)
                    last_error = exc
                    continue
                raise RuntimeError(
                    f"Elexon API error {exc.code} for {url}: {body_text}"
                ) from exc
            except urllib.error.URLError as exc:
                self._last_request_at = time.monotonic()
                if attempt < self.max_retries:
                    print(
                        f"  network error for {dataset}: {exc.reason}; retrying in {delay:.1f}s",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    last_error = exc
                    continue
                raise RuntimeError(
                    f"Elexon API network error for {url}: {exc.reason}"
                ) from exc

            try:
                records = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Elexon API returned non-JSON for {url}: {exc}"
                ) from exc
            if not isinstance(records, list):
                raise TypeError(
                    f"Elexon API returned {type(records).__name__}, expected a list: {url}"
                )
            if not all(isinstance(item, dict) for item in records):
                raise RuntimeError(f"Elexon API returned a non-object row: {url}")
            return FetchResult(
                url=url, body=body, records=records, status=status, headers=headers
            )

        raise RuntimeError(
            f"Elexon API request failed after retries: {url}"
        ) from last_error


class RawStore:
    """Content-addressed-enough raw response cache with a JSON sidecar audit trail."""

    def __init__(
        self, root: Path, client: ElexonClient, refresh: bool, offline: bool
    ) -> None:
        self.root = root
        self.client = client
        self.refresh = refresh
        self.offline = offline

    def load_or_fetch(
        self, dataset: str, label: str, params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raw_path = self.root / dataset / f"{label}.json"
        meta_path = self.root / dataset / f"{label}.meta.json"
        display_path = raw_path.relative_to(self.root.parent)

        if not self.refresh and raw_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                body = raw_path.read_bytes()
                if meta.get("sha256") == sha256_bytes(body):
                    records = json.loads(body)
                    if not isinstance(records, list):
                        raise ValueError("cached raw payload is not a list")
                    meta = dict(meta)
                    meta["from_cache"] = True
                    meta["raw_file"] = str(display_path)
                    return records, meta
            except (OSError, ValueError, json.JSONDecodeError):
                pass  # corrupt cache: fall through and re-fetch

        if self.offline:
            raise RuntimeError(
                f"offline mode but no valid cached response at {raw_path}"
            )

        result = self.client.fetch(dataset, params)
        fetched_at = utc_now()
        meta = {
            "dataset": dataset,
            "url": result.url,
            "params": params,
            "fetched_at_utc": iso(fetched_at),
            "http_status": result.status,
            "content_type": result.headers.get("content-type"),
            "bytes": len(result.body),
            "sha256": sha256_bytes(result.body),
            "records": len(result.records),
            "raw_file": str(display_path),
            "from_cache": False,
        }
        atomic_write_bytes(raw_path, result.body)
        atomic_write_json(meta_path, meta)
        return result.records, meta


# ---------------------------------------------------------------------------
# Normalisation and validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActualRow:
    start_time: datetime
    publish_time: datetime
    settlement_date: date
    settlement_period: int
    generation_mw: float
    raw_file: str

    def as_csv(self) -> dict[str, Any]:
        return {
            "start_time_utc": iso(self.start_time),
            "publish_time_utc": iso(self.publish_time),
            "settlement_date": self.settlement_date.isoformat(),
            "settlement_period": self.settlement_period,
            "fuel_type": "WIND",
            "generation_mw": f"{self.generation_mw:g}",
            "dataset": "FUELHH",
            "raw_file": self.raw_file,
        }


@dataclass(frozen=True)
class ForecastRow:
    publish_time: datetime
    start_time: datetime
    generation_mw: float
    raw_file: str

    @property
    def lead_hours(self) -> float:
        return (self.start_time - self.publish_time).total_seconds() / 3600.0

    def as_csv(self) -> dict[str, Any]:
        return {
            "publish_time_utc": iso(self.publish_time),
            "start_time_utc": iso(self.start_time),
            "lead_hours": f"{self.lead_hours:.2f}",
            "generation_mw": f"{self.generation_mw:g}",
            "dataset": "WINDFOR",
            "raw_file": self.raw_file,
        }


def normalise_actuals(
    records: Iterable[dict[str, Any]], raw_file: str, validator: Validator
) -> list[ActualRow]:
    rows: list[ActualRow] = []
    for index, raw in enumerate(records):
        record = require_mapping(
            raw, validator, "actual_record_type", index=index, raw_file=raw_file
        )
        if record is None:
            continue
        ctx = {"startTime": record.get("startTime"), "raw_file": raw_file}
        if record.get("dataset") != "FUELHH":
            validator.error(
                "actual_dataset", f"unexpected dataset {record.get('dataset')!r}", **ctx
            )
        if record.get("fuelType") != "WIND":
            validator.error(
                "actual_fuel_type",
                f"unexpected fuelType {record.get('fuelType')!r}",
                **ctx,
            )
            continue

        start_time = require_timestamp(
            record, "startTime", validator, "actual_start_time", **ctx
        )
        publish_time = require_timestamp(
            record, "publishTime", validator, "actual_publish_time", **ctx
        )
        settlement_period = require_int(
            record, "settlementPeriod", validator, "actual_settlement_period", **ctx
        )
        try:
            settlement_date = parse_date(str(record.get("settlementDate")))
        except ValueError:
            validator.error(
                "actual_settlement_date",
                f"invalid settlementDate {record.get('settlementDate')!r}",
                **ctx,
            )
            settlement_date = None  # type: ignore[assignment]
        generation = validate_generation(
            record.get("generation"), validator, "actual_generation", **ctx
        )
        if None in (
            start_time,
            publish_time,
            settlement_period,
            settlement_date,
            generation,
        ):
            continue

        if start_time.minute not in (0, 30) or start_time.second != 0:
            validator.error(
                "actual_resolution",
                "startTime is not aligned to a half-hour boundary",
                **ctx,
            )
        expected_period = (
            int(
                (
                    start_time
                    - local_day_start_utc(start_time.astimezone(LONDON).date())
                ).total_seconds()
                // 1800
            )
            + 1
        )
        if settlement_period != expected_period:
            validator.error(
                "actual_period_mismatch",
                f"settlementPeriod {settlement_period} does not match startTime "
                f"(expected {expected_period})",
                **ctx,
            )
        if settlement_date != start_time.astimezone(LONDON).date():
            validator.error(
                "actual_date_mismatch",
                f"settlementDate {settlement_date} does not match local settlement "
                f"date {start_time.astimezone(LONDON).date()}",
                **ctx,
            )
        delay_minutes = (publish_time - start_time).total_seconds() / 60.0
        if delay_minutes < 0:
            validator.error(
                "actual_publish_before_start", "publishTime precedes startTime", **ctx
            )
        elif delay_minutes > 90:
            validator.warn(
                "actual_publish_delay",
                f"outturn published {delay_minutes:.0f} minutes after period start",
                **ctx,
            )
        rows.append(
            ActualRow(
                start_time=start_time,
                publish_time=publish_time,
                settlement_date=settlement_date,
                settlement_period=settlement_period,
                generation_mw=generation,
                raw_file=raw_file,
            )
        )
    return rows


def normalise_forecasts(
    records: Iterable[dict[str, Any]], raw_file: str, validator: Validator
) -> list[ForecastRow]:
    rows: list[ForecastRow] = []
    for index, raw in enumerate(records):
        record = require_mapping(
            raw, validator, "forecast_record_type", index=index, raw_file=raw_file
        )
        if record is None:
            continue
        ctx = {
            "publishTime": record.get("publishTime"),
            "startTime": record.get("startTime"),
            "raw_file": raw_file,
        }
        if record.get("dataset") != "WINDFOR":
            validator.error(
                "forecast_dataset",
                f"unexpected dataset {record.get('dataset')!r}",
                **ctx,
            )
        publish_time = require_timestamp(
            record, "publishTime", validator, "forecast_publish_time", **ctx
        )
        start_time = require_timestamp(
            record, "startTime", validator, "forecast_start_time", **ctx
        )
        generation = validate_generation(
            record.get("generation"), validator, "forecast_generation", **ctx
        )
        if None in (publish_time, start_time, generation):
            continue
        rows.append(
            ForecastRow(
                publish_time=publish_time,
                start_time=start_time,
                generation_mw=generation,
                raw_file=raw_file,
            )
        )
    return rows


def dedupe_actuals(rows: Sequence[ActualRow], validator: Validator) -> list[ActualRow]:
    """Keep one row per (startTime, fuelType), preferring the latest publish."""
    by_key: dict[datetime, ActualRow] = {}
    for row in rows:
        existing = by_key.get(row.start_time)
        if existing is None:
            by_key[row.start_time] = row
            continue
        validator.warn(
            "actual_duplicate",
            "duplicate (startTime, fuelType) row; keeping latest publishTime",
            startTime=iso(row.start_time),
            kept=iso(max(existing.publish_time, row.publish_time)),
        )
        if row.publish_time > existing.publish_time:
            by_key[row.start_time] = row
    return sorted(by_key.values(), key=lambda row: row.start_time)


def dedupe_forecasts(
    rows: Sequence[ForecastRow], validator: Validator
) -> list[ForecastRow]:
    by_key: dict[tuple[datetime, datetime], ForecastRow] = {}
    for row in rows:
        key = (row.publish_time, row.start_time)
        if key in by_key:
            if by_key[key].generation_mw != row.generation_mw:
                validator.warn(
                    "forecast_duplicate_conflict",
                    "duplicate (publishTime, startTime) row with different generation; "
                    "keeping first occurrence",
                    publishTime=iso(row.publish_time),
                    startTime=iso(row.start_time),
                )
            continue
        by_key[key] = row
    return sorted(by_key.values(), key=lambda row: (row.publish_time, row.start_time))


def check_actual_coverage(
    rows: Sequence[ActualRow],
    delivery_start: date,
    delivery_end: date,
    validator: Validator,
) -> dict[str, Any]:
    expected: list[datetime] = []
    per_day_expected: dict[str, int] = {}
    for day in daterange_inclusive(delivery_start, delivery_end):
        day_start = local_day_start_utc(day)
        periods = settlement_periods_in_day(day)
        per_day_expected[day.isoformat()] = periods
        expected.extend(
            day_start + timedelta(minutes=30 * index) for index in range(periods)
        )
    actual = {row.start_time for row in rows}
    missing = [timestamp for timestamp in expected if timestamp not in actual]
    extra = sorted(actual - set(expected))
    per_day_actual = Counter(
        row.start_time.astimezone(LONDON).date().isoformat() for row in rows
    )
    for day, expected_count in per_day_expected.items():
        count = per_day_actual.get(day, 0)
        if count != expected_count:
            validator.error(
                "actual_day_incomplete",
                f"{day} has {count} half-hour periods, expected {expected_count}",
                day=day,
                count=count,
            )
    if missing:
        validator.error(
            "actual_missing_period",
            "delivery window is missing FUELHH half-hour periods",
            count=len(missing),
            first=iso(missing[0]),
            last=iso(missing[-1]),
        )
    if extra:
        validator.warn(
            "actual_unexpected_period",
            "FUELHH returned periods outside the requested delivery window",
            count=len(extra),
            first=iso(extra[0]),
            last=iso(extra[-1]),
        )
    return {
        "expected_periods": len(expected),
        "available_periods": len(actual & set(expected)),
        "missing_periods": len(missing),
        "missing_examples": [iso(value) for value in missing[:MAX_ISSUE_EXAMPLES]],
        "unexpected_periods": len(extra),
        "per_day_counts": {
            day: {
                "available": per_day_actual.get(day, 0),
                "expected": per_day_expected[day],
            }
            for day in per_day_expected
        },
    }


def forecast_resolution_minutes(times: Sequence[datetime]) -> int | None:
    ordered = sorted(times)
    deltas = [
        int((later - earlier).total_seconds() // 60)
        for earlier, later in itertools.pairwise(ordered)
    ]
    if not deltas:
        return None
    return Counter(deltas).most_common(1)[0][0]


def check_forecast_quality(
    rows: Sequence[ForecastRow],
    validator: Validator,
    fetched_after: datetime,
) -> dict[str, Any]:
    by_publish: dict[datetime, list[ForecastRow]] = defaultdict(list)
    for row in rows:
        by_publish[row.publish_time].append(row)

    resolutions: Counter[int] = Counter()
    horizon_min: float | None = None
    horizon_max: float | None = None
    for publish_time, publish_rows in by_publish.items():
        starts = [row.start_time for row in publish_rows]
        resolution = forecast_resolution_minutes(starts)
        if resolution is None:
            continue
        resolutions[resolution] += 1
        if resolution != 60:
            validator.warn(
                "forecast_resolution",
                f"publish {iso(publish_time)} has {resolution}-minute resolution, expected 60",
                publishTime=iso(publish_time),
                resolution_minutes=resolution,
            )
        min_lead = min(row.lead_hours for row in publish_rows)
        max_lead = max(row.lead_hours for row in publish_rows)
        horizon_min = min_lead if horizon_min is None else min(horizon_min, min_lead)
        horizon_max = max_lead if horizon_max is None else max(horizon_max, max_lead)
        if publish_time > fetched_after + timedelta(minutes=5):
            validator.error(
                "forecast_publish_in_future",
                "publishTime is after the time the response was fetched",
                publishTime=iso(publish_time),
            )

    minute_distribution = Counter(row.publish_time.minute for row in rows)
    if set(minute_distribution) - {0, 30}:
        validator.warn(
            "forecast_publish_alignment",
            "some WINDFOR publishes are not aligned to :00/:30 (observed late publish)",
            minute_counts=dict(sorted(minute_distribution.items())),
        )

    return {
        "records": len(rows),
        "publishes": len(by_publish),
        "publishes_per_day": dict(
            sorted(
                Counter(
                    publish_time.date().isoformat() for publish_time in by_publish
                ).items()
            )
        ),
        "publish_time_minutes": dict(sorted(minute_distribution.items())),
        "resolution_minutes": dict(sorted(resolutions.items())),
        "rows_per_publish": dict(
            sorted(
                Counter(
                    len(publish_rows) for publish_rows in by_publish.values()
                ).items()
            )
        ),
        "horizon_hours_min": horizon_min,
        "horizon_hours_max": horizon_max,
        "start_time_min": iso(min(row.start_time for row in rows)) if rows else None,
        "start_time_max": iso(max(row.start_time for row in rows)) if rows else None,
    }


# ---------------------------------------------------------------------------
# Decision coverage
# ---------------------------------------------------------------------------


def build_decision_rows(
    actuals: Sequence[ActualRow],
    forecasts: Sequence[ForecastRow],
    decision_dates: Sequence[date],
    decision_time: dtime,
    delivery_offset_days: int,
    delivery_span_days: int,
    validator: Validator,
) -> list[dict[str, Any]]:
    by_publish: dict[datetime, list[ForecastRow]] = defaultdict(list)
    for row in forecasts:
        by_publish[row.publish_time].append(row)
    publish_times = sorted(by_publish)
    actual_times = {row.start_time for row in actuals}

    output: list[dict[str, Any]] = []
    for decision_date in decision_dates:
        decision_ts = datetime.combine(decision_date, decision_time, tzinfo=UTC)
        delivery_date = decision_date + timedelta(days=delivery_offset_days)
        delivery_start = local_day_start_utc(delivery_date)
        delivery_end = local_day_start_utc(
            delivery_date + timedelta(days=delivery_span_days)
        )

        eligible = [publish for publish in publish_times if publish <= decision_ts]
        if not eligible:
            validator.error(
                "decision_no_forecast",
                "no WINDFOR publish at or before the decision time",
                decisionTime=iso(decision_ts),
            )
            output.append(
                {
                    "decision_time_utc": iso(decision_ts),
                    "delivery_date": delivery_date.isoformat(),
                    "latest_publish_utc": "",
                }
            )
            continue
        latest = eligible[-1]
        rows = by_publish[latest]
        rows_in_delivery = [
            row for row in rows if delivery_start <= row.start_time < delivery_end
        ]
        resolution = forecast_resolution_minutes([row.start_time for row in rows]) or 60
        expected_points = max(
            1, int((delivery_end - delivery_start).total_seconds() // (resolution * 60))
        )
        available_points = len(rows_in_delivery)
        missing_slots = []
        point = delivery_start
        step = timedelta(minutes=resolution)
        present = {row.start_time for row in rows}
        while point < delivery_end:
            if point not in present:
                missing_slots.append(point)
            point += step

        expected_actual = sum(
            settlement_periods_in_day(day)
            for day in daterange_inclusive(
                delivery_date, delivery_date + timedelta(days=delivery_span_days - 1)
            )
        )
        available_actual = sum(
            1 for t in actual_times if delivery_start <= t < delivery_end
        )
        coverage_pct = (
            100.0 * available_points / expected_points if expected_points else 0.0
        )
        actual_pct = (
            100.0 * available_actual / expected_actual if expected_actual else 0.0
        )

        if coverage_pct < 100:
            validator.error(
                "decision_forecast_gap",
                f"{delivery_date} delivery has {expected_points - available_points} missing "
                f"forecast points from publish {iso(latest)}",
                decisionTime=iso(decision_ts),
                deliveryDate=delivery_date.isoformat(),
                latestPublish=iso(latest),
                missing=len(missing_slots),
            )
        if actual_pct < 100:
            validator.error(
                "decision_actual_gap",
                f"{delivery_date} delivery has {expected_actual - available_actual} missing "
                "actual half-hour periods",
                decisionTime=iso(decision_ts),
                deliveryDate=delivery_date.isoformat(),
            )

        output.append(
            {
                "decision_time_utc": iso(decision_ts),
                "delivery_date": delivery_date.isoformat(),
                "latest_publish_utc": iso(latest),
                "publish_age_hours": f"{(decision_ts - latest).total_seconds() / 3600.0:.2f}",
                "forecast_horizon_hours": f"{(delivery_start - latest).total_seconds() / 3600.0:.2f}",
                "forecast_resolution_minutes": resolution,
                "forecast_points_available": available_points,
                "forecast_points_expected": expected_points,
                "forecast_coverage_pct": f"{coverage_pct:.1f}",
                "actual_periods_available": available_actual,
                "actual_periods_expected": expected_actual,
                "actual_coverage_pct": f"{actual_pct:.1f}",
                "first_forecast_start_utc": (
                    iso(rows_in_delivery[0].start_time) if rows_in_delivery else ""
                ),
                "last_forecast_start_utc": (
                    iso(rows_in_delivery[-1].start_time) if rows_in_delivery else ""
                ),
                "missing_forecast_slots": ";".join(
                    iso(value) for value in missing_slots[:10]
                ),
            }
        )
    return output


def check_decision_time_sensitivity(
    forecasts: Sequence[ForecastRow],
    decision_dates: Sequence[date],
    delivery_offset_days: int,
    delivery_span_days: int,
) -> dict[str, Any]:
    """Check delivery coverage for every half-hour decision time.

    WINDFOR publishes are anchored to a window ending at 21:00 UTC two days
    after the publish date. A decision before the first 02:30 publish therefore
    relies on the previous day's 22:30 publish, which ends at 21:00 on the
    delivery day and cannot cover the final two hours without lookahead.
    """
    by_publish: dict[datetime, list[ForecastRow]] = defaultdict(list)
    for row in forecasts:
        by_publish[row.publish_time].append(row)
    publish_times = sorted(by_publish)

    clock_times = [dtime(hour, minute) for hour in range(24) for minute in (0, 30)]
    total = 0
    complete = 0
    coverage_by_clock: dict[str, list[float]] = defaultdict(list)
    gap_examples: dict[str, dict[str, Any]] = {}

    for decision_date in decision_dates:
        delivery_date = decision_date + timedelta(days=delivery_offset_days)
        delivery_start = local_day_start_utc(delivery_date)
        delivery_end = local_day_start_utc(
            delivery_date + timedelta(days=delivery_span_days)
        )
        for clock in clock_times:
            decision_ts = datetime.combine(decision_date, clock, tzinfo=UTC)
            eligible = [publish for publish in publish_times if publish <= decision_ts]
            total += 1
            label = clock.strftime("%H:%M")
            if not eligible:
                coverage_by_clock[label].append(0.0)
                gap_examples.setdefault(
                    label, {"reason": "no publish at or before decision time"}
                )
                continue
            latest = eligible[-1]
            rows = by_publish[latest]
            resolution = (
                forecast_resolution_minutes([row.start_time for row in rows]) or 60
            )
            expected = max(
                1,
                int(
                    (delivery_end - delivery_start).total_seconds() // (resolution * 60)
                ),
            )
            available = sum(
                1 for row in rows if delivery_start <= row.start_time < delivery_end
            )
            pct = 100.0 * available / expected
            coverage_by_clock[label].append(pct)
            if pct == 100.0:
                complete += 1
            else:
                gap_examples.setdefault(
                    label,
                    {
                        "decision_time": label,
                        "latest_publish": iso(latest),
                        "available": available,
                        "expected": expected,
                        "missing_start": iso(
                            delivery_start
                            + timedelta(
                                minutes=resolution
                                * next(
                                    index
                                    for index in range(expected)
                                    if delivery_start
                                    + timedelta(minutes=resolution * index)
                                    not in {row.start_time for row in rows}
                                )
                            )
                        ),
                    },
                )

    incomplete_clocks = sorted(
        (
            (label, min(values))
            for label, values in coverage_by_clock.items()
            if min(values) < 100.0
        ),
        key=lambda item: item[0],
    )
    return {
        "checks": total,
        "fully_covered": complete,
        "incomplete": total - complete,
        "worst_coverage_pct": round(
            min(min(values) for values in coverage_by_clock.values()), 1
        ),
        "incomplete_decision_times": [label for label, _ in incomplete_clocks],
        "gap_examples": {
            label: gap_examples[label]
            for label, _ in incomplete_clocks[:6]
            if label in gap_examples
        },
    }


# ---------------------------------------------------------------------------
# Import orchestration
# ---------------------------------------------------------------------------


@dataclass
class ImportConfig:
    out_dir: Path
    delivery_start: date
    delivery_end: date
    decision_start: date
    decision_end: date
    decision_time: dtime
    delivery_offset_days: int
    delivery_span_days: int
    refresh: bool
    offline: bool
    request_interval: float
    timeout: float
    max_retries: int


def import_history(config: ImportConfig) -> int:
    started_at = utc_now()
    raw_root = config.out_dir / "raw"
    client = ElexonClient(
        timeout=config.timeout,
        max_retries=config.max_retries,
        request_interval=config.request_interval,
    )
    store = RawStore(raw_root, client, refresh=config.refresh, offline=config.offline)
    validator = Validator()

    delivery_start_dt = local_day_start_utc(config.delivery_start)
    delivery_end_dt = local_day_start_utc(config.delivery_end + timedelta(days=1))
    # Forecasts for a 09:00 decision on 1 January are published from 31 December,
    # and the last January decision can look up to three days ahead.
    forecast_fetch_start = delivery_start_dt
    forecast_fetch_end = delivery_end_dt
    decision_dates = list(
        daterange_inclusive(config.decision_start, config.decision_end)
    )

    required_delivery_days = {
        decision_date + timedelta(days=config.delivery_offset_days)
        for decision_date in decision_dates
    }
    for day in sorted(required_delivery_days):
        if not (config.delivery_start <= day <= config.delivery_end):
            raise SystemExit(
                f"decision {day - timedelta(days=config.delivery_offset_days)} needs delivery day "
                f"{day}, outside the import window {config.delivery_start}..{config.delivery_end}. "
                "Widen --delivery-start/--delivery-end."
            )

    print(
        f"Importing Elexon wind history\n"
        f"  delivery window : {config.delivery_start} .. {config.delivery_end}\n"
        f"  decisions       : {config.decision_start} .. {config.decision_end} "
        f"at {config.decision_time.strftime('%H:%M')} UTC "
        f"(delivery +{config.delivery_offset_days}d, {config.delivery_span_days}d)\n"
        f"  output          : {config.out_dir}"
    )

    raw_files: list[dict[str, Any]] = []

    # -- FUELHH actuals -----------------------------------------------------
    actual_rows: list[ActualRow] = []
    for chunk_start, chunk_end in chunk_dates(
        config.delivery_start, config.delivery_end, ACTUAL_CHUNK_DAYS
    ):
        label = f"FUELHH_WIND_{chunk_start.isoformat()}_{chunk_end.isoformat()}"
        params = {
            "fuelType": "WIND",
            "settlementDateFrom": chunk_start.isoformat(),
            "settlementDateTo": chunk_end.isoformat(),
        }
        print(f"  FUELHH {chunk_start} .. {chunk_end} ...", end="", flush=True)
        records, meta = store.load_or_fetch("FUELHH", label, params)
        chunk_rows = normalise_actuals(records, meta["raw_file"], validator)
        actual_rows.extend(chunk_rows)
        raw_files.append(meta)
        print(
            f" {len(chunk_rows)} rows ({'cache' if meta.get('from_cache') else 'fetched'})"
        )

    actuals = dedupe_actuals(actual_rows, validator)

    # -- WINDFOR forecasts --------------------------------------------------
    forecast_rows: list[ForecastRow] = []
    for chunk_start, chunk_end in chunk_datetimes(
        forecast_fetch_start, forecast_fetch_end, FORECAST_CHUNK_DAYS
    ):
        label = (
            f"WINDFOR_{chunk_start.strftime('%Y-%m-%dT%H%MZ')}"
            f"_{chunk_end.strftime('%Y-%m-%dT%H%MZ')}"
        )
        params = {
            "publishDateTimeFrom": iso(chunk_start),
            "publishDateTimeTo": iso(chunk_end),
        }
        print(
            f"  WINDFOR {iso(chunk_start)} .. {iso(chunk_end)} ...", end="", flush=True
        )
        records, meta = store.load_or_fetch("WINDFOR", label, params)
        chunk_rows = normalise_forecasts(records, meta["raw_file"], validator)
        forecast_rows.extend(chunk_rows)
        raw_files.append(meta)
        print(
            f" {len(chunk_rows)} rows ({'cache' if meta.get('from_cache') else 'fetched'})"
        )

    forecasts = dedupe_forecasts(forecast_rows, validator)

    # Only keep forecast points that can matter for the delivery window. Raw
    # files retain the full API response (including points outside the window).
    forecasts_in_window = [
        row
        for row in forecasts
        if delivery_start_dt <= row.start_time < delivery_end_dt
    ]

    # -- Validation ---------------------------------------------------------
    actual_coverage = check_actual_coverage(
        actuals, config.delivery_start, config.delivery_end, validator
    )
    forecast_quality = check_forecast_quality(forecasts, validator, started_at)
    decision_rows = build_decision_rows(
        actuals,
        forecasts,
        decision_dates,
        config.decision_time,
        config.delivery_offset_days,
        config.delivery_span_days,
        validator,
    )
    decision_time_sensitivity = check_decision_time_sensitivity(
        forecasts,
        decision_dates,
        config.delivery_offset_days,
        config.delivery_span_days,
    )

    validator.checks["actuals"] = {
        "records": len(actuals),
        "start_time_min": iso(actuals[0].start_time) if actuals else None,
        "start_time_max": iso(actuals[-1].start_time) if actuals else None,
        "generation_mw_min": min(row.generation_mw for row in actuals)
        if actuals
        else None,
        "generation_mw_max": max(row.generation_mw for row in actuals)
        if actuals
        else None,
        "generation_mw_mean": (
            round(statistics.fmean(row.generation_mw for row in actuals), 1)
            if actuals
            else None
        ),
        "coverage": actual_coverage,
    }
    validator.checks["forecasts"] = {
        **forecast_quality,
        "records_in_delivery_window": len(forecasts_in_window),
    }
    validator.checks["decisions"] = {
        "decision_days": len(decision_dates),
        "forecast_days_fully_covered": sum(
            1 for row in decision_rows if row.get("forecast_coverage_pct") == "100.0"
        ),
        "forecast_days_with_gaps": [
            row["delivery_date"]
            for row in decision_rows
            if row.get("forecast_coverage_pct") != "100.0"
        ],
        "actual_days_fully_covered": sum(
            1 for row in decision_rows if row.get("actual_coverage_pct") == "100.0"
        ),
        "time_sensitivity": decision_time_sensitivity,
    }

    # Unit sanity check: both datasets should be MW with comparable magnitudes.
    if actuals and forecasts_in_window:
        actual_mean = statistics.fmean(row.generation_mw for row in actuals)
        forecast_mean = statistics.fmean(
            row.generation_mw for row in forecasts_in_window
        )
        ratio = forecast_mean / actual_mean if actual_mean else float("inf")
        validator.checks["units"] = {
            "assumed_unit": "MW",
            "actual_mean_mw": round(actual_mean, 1),
            "forecast_mean_mw": round(forecast_mean, 1),
            "forecast_to_actual_mean_ratio": round(ratio, 3),
        }
        if not 0.5 <= ratio <= 2.0:
            validator.warn(
                "unit_ratio",
                f"mean forecast/actual ratio {ratio:.2f} is implausible for MW values",
                actual_mean=round(actual_mean, 1),
                forecast_mean=round(forecast_mean, 1),
            )

    # -- Outputs ------------------------------------------------------------
    actual_csv = config.out_dir / "actual_wind_fuelhh.csv"
    forecast_csv = config.out_dir / "wind_forecasts_windfor.csv"
    decision_csv = config.out_dir / "decision_coverage.csv"
    report_json = config.out_dir / "validation_report.json"
    manifest_json = config.out_dir / "import_manifest.json"

    atomic_write_csv(
        actual_csv,
        [
            "start_time_utc",
            "publish_time_utc",
            "settlement_date",
            "settlement_period",
            "fuel_type",
            "generation_mw",
            "dataset",
            "raw_file",
        ],
        (row.as_csv() for row in actuals),
    )
    atomic_write_csv(
        forecast_csv,
        [
            "publish_time_utc",
            "start_time_utc",
            "lead_hours",
            "generation_mw",
            "dataset",
            "raw_file",
        ],
        (row.as_csv() for row in forecasts_in_window),
    )
    decision_fields = [
        "decision_time_utc",
        "delivery_date",
        "latest_publish_utc",
        "publish_age_hours",
        "forecast_horizon_hours",
        "forecast_resolution_minutes",
        "forecast_points_available",
        "forecast_points_expected",
        "forecast_coverage_pct",
        "actual_periods_available",
        "actual_periods_expected",
        "actual_coverage_pct",
        "first_forecast_start_utc",
        "last_forecast_start_utc",
        "missing_forecast_slots",
    ]
    atomic_write_csv(decision_csv, decision_fields, decision_rows)

    report = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "actuals": f"{API_BASE}/FUELHH/stream",
            "forecasts": f"{API_BASE}/WINDFOR/stream",
            "docs": "https://bmrs.elexon.co.uk/api-documentation",
        },
        "config": {
            "delivery_start": config.delivery_start.isoformat(),
            "delivery_end": config.delivery_end.isoformat(),
            "decision_start": config.decision_start.isoformat(),
            "decision_end": config.decision_end.isoformat(),
            "decision_time": config.decision_time.strftime("%H:%M"),
            "delivery_offset_days": config.delivery_offset_days,
            "delivery_span_days": config.delivery_span_days,
        },
        **validator.summary(),
    }
    atomic_write_json(report_json, report)

    outputs = []
    for path, rows in (
        (actual_csv, len(actuals)),
        (forecast_csv, len(forecasts_in_window)),
        (decision_csv, len(decision_rows)),
        (report_json, None),
    ):
        outputs.append(
            {
                "path": str(path),
                "rows": rows,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso(started_at),
        "api_base": API_BASE,
        "config": report["config"],
        "raw_files": [
            {
                "dataset": meta["dataset"],
                "url": meta["url"],
                "params": meta["params"],
                "fetched_at_utc": meta.get("fetched_at_utc"),
                "http_status": meta.get("http_status"),
                "content_type": meta.get("content_type"),
                "bytes": meta.get("bytes"),
                "sha256": meta.get("sha256"),
                "records": meta.get("records"),
                "path": meta.get("raw_file"),
                "from_cache": meta.get("from_cache", False),
            }
            for meta in raw_files
        ],
        "outputs": outputs,
        "validation_status": report["status"],
    }
    atomic_write_json(manifest_json, manifest)

    # -- Console summary ----------------------------------------------------
    status = report["status"].upper()
    print(
        f"\n{status}: {len(actuals)} actual rows, {len(forecasts)} forecast rows "
        f"({len(forecasts_in_window)} in delivery window), {len(decision_rows)} decisions"
    )
    if report["issues"]:
        print("Validation issues:")
        for issue in report["issues"]:
            print(
                f"  [{issue['severity']}] {issue['code']}: {issue['message']} (x{issue['count']})"
            )
            for example in issue["examples"][:2]:
                print(f"      {example}")
    print(
        f"Actual coverage: {actual_coverage['available_periods']}/"
        f"{actual_coverage['expected_periods']} half-hours"
    )
    decisions_ok = report["checks"]["decisions"]["forecast_days_fully_covered"]
    print(
        f"Decision forecast coverage: {decisions_ok}/{len(decision_rows)} delivery days fully covered"
    )
    sweep = decision_time_sensitivity
    print(
        f"Decision-time sweep: {sweep['fully_covered']}/{sweep['checks']} decision times "
        f"fully covered; incomplete at "
        f"{', '.join(sweep['incomplete_decision_times']) or 'none'} "
        f"(worst {sweep['worst_coverage_pct']}%)"
    )
    print(f"Outputs written to {config.out_dir}")
    return 1 if validator.errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import Elexon FUELHH wind outturn and WINDFOR wind forecasts."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/elexon"),
        help="output directory (default: data/elexon)",
    )
    parser.add_argument(
        "--delivery-start",
        type=parse_date,
        default=DEFAULT_DELIVERY_START,
        help=f"first delivery date to import (default: {DEFAULT_DELIVERY_START})",
    )
    parser.add_argument(
        "--delivery-end",
        type=parse_date,
        default=DEFAULT_DELIVERY_END,
        help=f"last delivery date to import, inclusive (default: {DEFAULT_DELIVERY_END})",
    )
    parser.add_argument(
        "--decision-start",
        type=parse_date,
        default=DEFAULT_DECISION_START,
        help=f"first decision date (default: {DEFAULT_DECISION_START})",
    )
    parser.add_argument(
        "--decision-end",
        type=parse_date,
        default=DEFAULT_DECISION_END,
        help=f"last decision date (default: {DEFAULT_DECISION_END})",
    )
    parser.add_argument(
        "--decision-time",
        type=parse_clock,
        default=DEFAULT_DECISION_TIME,
        help="UTC clock time of each daily decision (default: 09:00)",
    )
    parser.add_argument(
        "--delivery-offset-days",
        type=int,
        default=1,
        help="days between a decision date and its delivery day (default: 1, day-ahead)",
    )
    parser.add_argument(
        "--delivery-span-days",
        type=int,
        default=1,
        help="delivery days to check per decision (default: 1)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download raw responses instead of using the cache",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="fail instead of downloading when a cache entry is missing",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.2,
        help="minimum seconds between API requests (default: 0.2)",
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--max-retries", type=int, default=5, help="retries for 429/5xx/network errors"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.delivery_span_days < 1:
        raise SystemExit("--delivery-span-days must be at least 1")
    if not (0 <= args.delivery_offset_days <= 7):
        raise SystemExit("--delivery-offset-days must be between 0 and 7")
    config = ImportConfig(
        out_dir=args.out,
        delivery_start=args.delivery_start,
        delivery_end=args.delivery_end,
        decision_start=args.decision_start,
        decision_end=args.decision_end,
        decision_time=args.decision_time,
        delivery_offset_days=args.delivery_offset_days,
        delivery_span_days=args.delivery_span_days,
        refresh=args.refresh,
        offline=args.offline,
        request_interval=args.request_interval,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    return import_history(config)


if __name__ == "__main__":
    raise SystemExit(main())
