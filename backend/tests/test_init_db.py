from app.init_db import validate_decision_coverage
from app.wind_csv import EXPECTED_ACTUAL_RECORDS, EXPECTED_FORECAST_RECORDS


def test_validate_decision_coverage() -> None:
    covered, total = validate_decision_coverage()
    assert covered == 31
    assert total == 31


def test_expected_counts_config() -> None:
    assert EXPECTED_ACTUAL_RECORDS == 1584
    assert EXPECTED_FORECAST_RECORDS == 18704
