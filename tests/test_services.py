# -*- coding: utf-8 -*-
import pytest
from types import SimpleNamespace
from agent_service import AgentOrchestrator
from langgraph_agent import LangGraphAgentOrchestrator

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


def test_qwen_chat_completion_uses_configured_endpoint(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Qwen 检修建议"}}]}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setenv("LLM_API_KEY", "TEST_TOKEN")
    monkeypatch.setenv("LLM_API_URL", "https://qwen.example.test/v1/chat/completions")
    monkeypatch.setenv("LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(vector_service.requests, "post", fake_post)
    service = VectorService()

    assert service.call_llm("启动困难", [{"source": "演示", "text": "检查点火"}]) == "Qwen 检修建议"
    assert captured["url"] == "https://qwen.example.test/v1/chat/completions"
    assert captured["json"]["model"] == "qwen-plus"
    assert captured["headers"]["Authorization"] == "Bearer TEST_TOKEN"
    assert captured["timeout"] == 45.0
    assert service.llm_capabilities()["active"] == "qwen"


def test_qwen_timeout_returns_offline_fallback(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "TEST_TOKEN")
    monkeypatch.setattr(
        vector_service.requests, "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(vector_service.requests.Timeout()),
    )
    service = VectorService()

    answer = service.call_llm("启动困难", [{"source": "演示", "text": "检查点火"}])

    assert "本地演示诊断模式" in answer
    assert service.llm_capabilities()["active"] == "offline"
    assert service.llm_capabilities()["error"] == "请求超时"


@pytest.mark.parametrize("failure", ["http", "json"])
def test_qwen_error_response_returns_sanitized_fallback(monkeypatch, failure):
    class Response:
        def raise_for_status(self):
            if failure == "http":
                error = vector_service.requests.HTTPError("401 secret detail")
                error.response = SimpleNamespace(status_code=401)
                raise error

        def json(self):
            return {"unexpected": "shape"}

    monkeypatch.setenv("LLM_API_KEY", "TEST_TOKEN")
    monkeypatch.setattr(vector_service.requests, "post", lambda *args, **kwargs: Response())
    service = VectorService()

    answer = service.call_llm("启动困难", [{"source": "演示", "text": "检查点火"}])

    assert "本地演示诊断模式" in answer
    assert "secret detail" not in service.llm_capabilities()["error"]
    assert service.llm_capabilities()["active"] == "offline"


def test_agent_records_llm_generation_step():
    calls = []

    class FakeVector:
        def search_similar(self, query, top_k=4):
            return [{"source": "演示", "text": "检查点火", "score": 0.8, "matched_terms": []}]

        def call_llm(self, query, docs):
            calls.append((query, docs))
            return "云端建议"

        def llm_capabilities(self):
            return {"provider": "qwen", "model": "qwen-plus", "configured": True, "active": "qwen", "error": ""}

    agent = AgentOrchestrator(FakeVector(), SimpleNamespace(analyze=lambda path: {}), lambda *args: {
        "risk_score": 25, "risk_level": "低风险", "risk_class": "safe", "confidence": 0.7,
        "causes": ["测试"], "plan": [],
    })
    result = agent.run(query_text="启动困难")

    assert calls
    assert result["diagnosis"]["answer"].startswith("云端建议")
    assert any(step["tool"] == "generate_diagnostic_answer" for step in result["steps"])


class _AgentVector:
    def search_similar(self, query, top_k=4):
        return [{"source": "演示", "text": "检查点火", "score": 0.8, "matched_terms": []}]

    def call_llm(self, query, docs):
        return "本地建议"

    def _offline_diagnostic_fallback(self, query, docs, reason):
        return "本地建议"

    def llm_capabilities(self):
        return {"provider": "qwen", "model": "qwen-plus", "configured": False, "active": "offline", "error": ""}


def _langgraph_agent():
    return LangGraphAgentOrchestrator(
        _AgentVector(),
        SimpleNamespace(analyze=lambda path: {"summary": "图片证据"}),
        lambda *args: {
            "risk_score": 25, "risk_level": "低风险", "risk_class": "safe", "confidence": 0.7,
            "causes": ["测试"], "plan": [],
        },
    )


def test_langgraph_policy_route_preserves_legacy_trace(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    result = _langgraph_agent().run(query_text="启动困难")

    assert result["runtime"]["framework"] == "LangGraph"
    assert result["runtime"]["mode"] == "policy"
    assert result["runtime"]["selected_tools"] == ["retrieve_knowledge", "validate_redlines"]
    assert [step["tool"] for step in result["steps"]] == [
        "inspect_image", "analyze_sensor", "retrieve_knowledge", "validate_redlines",
        "build_diagnosis", "generate_diagnostic_answer", "prepare_work_order",
    ]


def test_langgraph_policy_includes_only_available_perception_tools(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    result = _langgraph_agent().run(image_path="fixture.png", use_demo_sensor=False)

    assert result["runtime"]["selected_tools"] == ["inspect_image", "retrieve_knowledge", "validate_redlines"]
    assert result["image_result"] == {"summary": "图片证据"}
    assert result["sensor_result"] is None


def test_langgraph_model_plan_is_filtered_and_completed(monkeypatch):
    agent = _langgraph_agent()
    monkeypatch.setattr(agent, "_tool_calling_order", lambda *args: [
        "validate_redlines", "unknown_tool", "inspect_image", "inspect_image", "analyze_sensor",
    ])
    result = agent.run(image_path="fixture.png", use_demo_sensor=False)

    assert result["runtime"]["mode"] == "tool-calling"
    assert result["runtime"]["selected_tools"] == ["inspect_image", "retrieve_knowledge", "validate_redlines"]
    assert result["steps"][0]["tool"] == "select_tools"
    assert "unknown_tool" not in result["runtime"]["selected_tools"]


def test_langgraph_malformed_model_plan_falls_back_to_policy(monkeypatch):
    agent = _langgraph_agent()
    monkeypatch.setattr(agent, "_tool_calling_order", lambda *args: ["unknown_tool"])
    result = agent.run(query_text="启动困难")

    assert result["runtime"]["mode"] == "policy"
    assert result["runtime"]["selected_tools"] == ["retrieve_knowledge", "validate_redlines"]
