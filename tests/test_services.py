# -*- coding: utf-8 -*-
import pytest

from predictive_service import analyze_series, demo_series, parse_csv_with_profile
from standards_service import check_parameter
from vector_service import VectorService


def test_sensor_parser_returns_auditable_profile():
    content = b"hour,temperature,vibration,pressure\n0,68,2.2,310\n4,70,2.5,300\n8,74,3.1,282\n12,79,3.8,260\n"
    rows, profile = parse_csv_with_profile(content, "fixture.csv")

    assert len(rows) == 4
    assert profile["filename"] == "fixture.csv"
    assert profile["quality_status"] == "通过"
    assert profile["sha256"]


def test_sensor_parser_rejects_missing_columns():
    with pytest.raises(ValueError, match="hour, temperature, vibration, pressure"):
        parse_csv_with_profile(b"hour,value\n0,1\n")


def test_sensor_analysis_exposes_risk_and_trend_metrics():
    result = analyze_series(demo_series())

    assert result["risk_level"] in {"低风险", "中风险", "高风险"}
    assert result["health_score"] > 0
    assert set(result["metrics"]) == {"temperature", "vibration", "pressure"}


def test_parameter_check_reports_out_of_range_value():
    result = check_parameter("spark_gap", 1.2)

    assert result["status"] == "超差"
    assert result["severity"] == "danger"
    assert result["deviation"] == pytest.approx(0.3)


def test_vector_search_returns_explainable_evidence():
    results = VectorService().search_similar("冷机启动困难 火花塞 积碳", top_k=2)

    assert len(results) == 2
    assert all("source" in item and "matched_terms" in item and "score" in item for item in results)
    assert results[0]["score"] >= results[1]["score"]
