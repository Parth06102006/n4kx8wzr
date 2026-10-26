from fastapi.testclient import TestClient


def test_endpoint_overview(client: TestClient) -> None:
    for path in ["/api/overview", "/api/v1/overview"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["analysis_period"] == "January 2026"
        assert data["decisions_evaluated"] > 0
        assert data["delivery_hours_evaluated"] > 0
        assert "mae_mw" in data
        assert "rmse_mw" in data
        assert "mape_pct" in data
        assert "mean_bias_mw" in data
        assert "forecast_generation_mean_mw" in data
        assert "actual_generation_mean_mw" in data
        assert "coverage_pct" in data
        assert data["coverage_pct"] > 0


def test_endpoint_forecasts_paginated(client: TestClient) -> None:
    # 1. Query with delivery_date, limit, and offset (matching user spec)
    response = client.get("/api/forecasts", params={"delivery_date": "2026-01-15", "limit": 100, "offset": 0})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "pagination" in data
    pagination = data["pagination"]
    assert pagination["limit"] == 100
    assert pagination["offset"] == 0
    assert pagination["total"] == 24
    assert pagination["has_more"] is False
    assert len(data["items"]) == 24

    first_item = data["items"][0]
    assert "delivery_time_utc" in first_item
    assert "forecast_mw" in first_item
    assert "actual_mw" in first_item
    assert "forecast_error_mw" in first_item
    assert "absolute_error_mw" in first_item

    # 2. Query all with pagination (limit 10, offset 0 -> has_more is True)
    paginated_resp = client.get("/api/forecasts", params={"limit": 10, "offset": 0})
    assert paginated_resp.status_code == 200
    pag_data = paginated_resp.json()
    assert pag_data["pagination"]["limit"] == 10
    assert pag_data["pagination"]["offset"] == 0
    assert pag_data["pagination"]["total"] == 744
    assert pag_data["pagination"]["has_more"] is True
    assert len(pag_data["items"]) == 10


def test_endpoint_actuals_paginated(client: TestClient) -> None:
    response = client.get("/api/actuals", params={"limit": 50, "offset": 0})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "pagination" in data
    assert data["pagination"]["limit"] == 50
    assert data["pagination"]["offset"] == 0
    assert data["pagination"]["total"] > 0
    assert len(data["items"]) == 50

    first_item = data["items"][0]
    assert "delivery_time_utc" in first_item
    assert "actual_generation_mw" in first_item
    assert "half_hour_observations_count" in first_item


def test_endpoint_accuracy(client: TestClient) -> None:
    response = client.get("/api/accuracy")
    assert response.status_code == 200
    data = response.json()
    assert data["mae_mw"] > 0
    assert data["rmse_mw"] > 0
    assert data["mape_pct"] > 0
    assert "mean_bias_mw" in data
    assert data["total_observations"] > 0
    assert len(data["daily_metrics"]) > 0

    first_day = data["daily_metrics"][0]
    assert "delivery_date" in first_day
    assert "mae_mw" in first_day
    assert "rmse_mw" in first_day
    assert "mape_pct" in first_day
    assert "mean_bias_mw" in first_day


def test_endpoint_forecast_versions_paginated(client: TestClient) -> None:
    # Query with delivery_date matching user specification
    response = client.get("/api/forecast-versions", params={"delivery_date": "2026-01-15", "limit": 100, "offset": 0})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "pagination" in data
    assert data["pagination"]["limit"] == 100
    assert data["pagination"]["total"] > 0
    assert len(data["items"]) > 0

    first_v = data["items"][0]
    assert "delivery_time_utc" in first_v
    assert "publish_time_utc" in first_v
    assert "generation_mw" in first_v
    assert "is_eligible_for_decision" in first_v

    # Verify query by specific delivery_time also works
    deliv_time = "2026-01-15T12:00:00Z"
    resp_time = client.get("/api/forecast-versions", params={"delivery_time": deliv_time})
    assert resp_time.status_code == 200
    data_time = resp_time.json()
    assert data_time["pagination"]["total"] > 0
    cutoff_versions = [v for v in data_time["items"] if v["is_decision_cutoff_version"]]
    assert len(cutoff_versions) == 1


def test_endpoint_export_csv(client: TestClient) -> None:
    response = client.get("/api/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().split("\r\n") if "\r\n" in response.text else response.text.strip().split("\n")
    assert len(lines) > 1
    headers = lines[0].split(",")
    assert "delivery_time_utc" in headers
    assert "forecast_mw" in headers
    assert "actual_mw" in headers
    assert "forecast_error_mw" in headers
    assert "absolute_error_mw" in headers
