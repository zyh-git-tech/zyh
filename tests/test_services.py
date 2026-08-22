# -*- coding: utf-8 -*-
import pytest
from types import SimpleNamespace

from predictive_service import analyze_series, demo_series, parse_csv_with_profile
from standards_service import check_parameter
import vector_service
from vector_service import ChromaBackend, VectorService


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
    assert "anomaly_score" in result
    assert "rul_hours" in result
    assert all("rolling_mean" in metric and "robust_anomaly_score" in metric for metric in result["metrics"].values())


def test_predictive_features_distinguish_stable_and_spike_sequences():
    stable = [{"hour": index * 4, "temperature": 70, "vibration": 2.2, "pressure": 310} for index in range(8)]
    spike = stable[:-1] + [{"hour": 28, "temperature": 95, "vibration": 7.5, "pressure": 190}]
    assert analyze_series(stable)["anomaly_score"] < 10
    assert analyze_series(spike)["anomaly_score"] > 50


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


def test_chroma_backend_keeps_compatible_result_shape(monkeypatch, tmp_path):
    class Collection:
        def count(self):
            return 0

        def upsert(self, **kwargs):
            self.documents = kwargs["documents"]
            self.metadatas = kwargs["metadatas"]

        def query(self, **kwargs):
            return {"documents": [[self.documents[0]]], "distances": [[0.2]], "metadatas": [[self.metadatas[0]]]}

    collection = Collection()
    fake_module = SimpleNamespace(PersistentClient=lambda path: SimpleNamespace(
        get_or_create_collection=lambda name, **kwargs: collection
    ))
    monkeypatch.setitem(__import__("sys").modules, "chromadb", fake_module)
    backend = ChromaBackend(tmp_path)
    result = backend.search([{"text": "合成知识", "source": "演示"}], "知识", 1)[0]
    assert result["backend"] == "chroma"
    assert {"source", "text", "score", "matched_terms", "backend"} <= set(result)


def test_vector_service_falls_back_when_chroma_initialization_fails(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(vector_service, "ChromaBackend", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mock")))
    service = VectorService()
    assert service.backend_name == "keyword"
    assert service.backend_error
