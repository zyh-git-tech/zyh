# -*- coding: utf-8 -*-
"""LangGraph runtime for the inspection workspace.

The existing deterministic orchestrator remains the compatibility layer for
result formatting and persistence. This runtime owns state routing, tool
selection, and an optional OpenAI-compatible tool-calling loop.
"""
import os
from typing import Any, TypedDict

from agent_service import AgentOrchestrator

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph
except ImportError:
    HumanMessage = SystemMessage = StructuredTool = ChatOpenAI = None
    END = START = StateGraph = None


class _State(TypedDict, total=False):
    order: list[str]
    index: int
    selected: list[str]


class LangGraphAgentOrchestrator:
    """Route inspection inputs through a graph and preserve the legacy API."""

    def __init__(self, vector_engine, image_engine, profile_builder):
        self.legacy = AgentOrchestrator(vector_engine, image_engine, profile_builder)
        self.vector_engine = vector_engine

    @staticmethod
    def _model_available():
        return bool(os.getenv("LLM_API_KEY", "").strip()) and ChatOpenAI is not None

    def _tool_calling_order(self, query_text, device_model, has_image, has_sensor):
        """Ask the compatible chat model to rank tools; validate against a whitelist."""
        if not self._model_available():
            return None
        try:
            base_url = os.getenv(
                "LLM_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            ).rstrip("/").removesuffix("/chat/completions")
            model = ChatOpenAI(
                api_key=os.getenv("LLM_API_KEY"),
                base_url=base_url,
                model=os.getenv("LLM_MODEL", "qwen-plus"),
                temperature=0,
                timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
                max_retries=1,
            )
            tools = [
                StructuredTool.from_function(lambda: "image", name="inspect_image", description="检查上传图片"),
                StructuredTool.from_function(lambda: "sensor", name="analyze_sensor", description="分析传感器数据"),
                StructuredTool.from_function(lambda: "knowledge", name="retrieve_knowledge", description="检索维修知识"),
                StructuredTool.from_function(lambda: "redline", name="validate_redlines", description="校验参数红线"),
            ]
            response = model.bind_tools(tools).invoke([
                SystemMessage(content=(
                    "你是检修 Agent 的规划器。只从工具列表中选择工具，按依赖排序。"
                    "输出工具调用即可，不执行维修、不创建工单。"
                )),
                HumanMessage(content=(
                    f"设备={device_model or '未指定'}; 现象={query_text or '未提供'}; "
                    f"图片={'有' if has_image else '无'}; 传感器={'有' if has_sensor else '无'}"
                )),
            ])
            names = [call.get("name") for call in getattr(response, "tool_calls", []) or []]
            allowed = {"inspect_image", "analyze_sensor", "retrieve_knowledge", "validate_redlines"}
            selected = [name for name in names if name in allowed]
            if selected:
                return selected
        except Exception:
            return None
        return None

    @staticmethod
    def _policy_order(has_image, has_sensor):
        order = []
        if has_image:
            order.append("inspect_image")
        if has_sensor:
            order.append("analyze_sensor")
        order.extend(["retrieve_knowledge", "validate_redlines"])
        return order

    @staticmethod
    def _normalize_order(planned, has_image, has_sensor):
        """Keep planner output within the executable, dependency-safe tool plan."""
        available_perception = []
        if has_image:
            available_perception.append("inspect_image")
        if has_sensor:
            available_perception.append("analyze_sensor")

        normalized = []
        for name in planned or []:
            if name in available_perception and name not in normalized:
                normalized.append(name)
        for name in available_perception:
            if name not in normalized:
                normalized.append(name)
        normalized.extend(["retrieve_knowledge", "validate_redlines"])
        return normalized

    def _graph(self, order):
        if StateGraph is None:
            return None

        def choose(state: _State):
            index = state.get("index", 0)
            if index >= len(order):
                return {"selected": state.get("selected", [])}
            return {"selected": state.get("selected", []) + [order[index]], "index": index + 1}

        def route(state: _State):
            return "next" if state.get("index", 0) < len(order) else "done"

        graph = StateGraph(_State)
        graph.add_node("select_tool", choose)
        graph.add_edge(START, "select_tool")
        graph.add_conditional_edges("select_tool", route, {"next": "select_tool", "done": END})
        return graph.compile()

    def run(self, **kwargs: Any):
        has_image = bool(kwargs.get("image_path"))
        has_sensor = bool(kwargs.get("sensor_content") or kwargs.get("use_demo_sensor"))
        selected = self._tool_calling_order(
            kwargs.get("query_text", ""), kwargs.get("device_model", ""), has_image, has_sensor
        )
        available = {"retrieve_knowledge", "validate_redlines"}
        if has_image:
            available.add("inspect_image")
        if has_sensor:
            available.add("analyze_sensor")
        valid_selected = [name for name in selected or [] if name in available]
        mode = "tool-calling" if valid_selected else "policy"
        order = self._normalize_order(valid_selected, has_image, has_sensor) if valid_selected else self._policy_order(
            has_image, has_sensor
        )
        graph = self._graph(order)
        if graph:
            route_result = graph.invoke({"order": order, "index": 0, "selected": []})
            order = route_result.get("selected", order)
        result = self.legacy.run(tool_order=order, **kwargs)
        result["runtime"] = {
            "framework": "LangGraph" if graph else "兼容策略",
            "mode": mode,
            "selected_tools": order,
            "human_confirmation": "required_for_work_order",
        }
        if mode == "tool-calling":
            result["llm_status"].update({"active": "qwen", "configured": True, "error": ""})
        if mode == "tool-calling":
            result["steps"].insert(0, {
                "tool": "select_tools",
                "label": "Agent 动态工具决策",
                "status": "completed",
                "input_summary": "根据输入证据选择工具顺序",
                "output_summary": " → ".join(order),
                "duration_ms": 1,
            })
        result["status"] = "completed"
        return result
