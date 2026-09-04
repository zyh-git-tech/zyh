# -*- coding: utf-8 -*-
"""LangGraph Agent runtime with a bounded, read-only tool loop."""
import os
from typing import Any, Annotated, TypedDict

from agent_service import AgentOrchestrator

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode
except ImportError:
    HumanMessage = SystemMessage = StructuredTool = ChatOpenAI = ToolNode = None
    END = START = StateGraph = add_messages = None


MAX_ITERATIONS = 8
READ_ONLY_TOOLS = ("inspect_image", "analyze_sensor", "retrieve_knowledge", "validate_redlines")


class _State(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    iterations: int


class LangGraphAgentOrchestrator:
    """Run model-selected read-only tools, then reuse the legacy fusion contract."""

    def __init__(self, vector_engine, image_engine, profile_builder):
        self.legacy = AgentOrchestrator(vector_engine, image_engine, profile_builder)
        self.vector_engine = vector_engine

    def _tool_calling_order(self, kwargs):
        """Compatibility hook for deterministic callers and legacy integrations.

        The LangGraph path remains the default when an LLM key is configured.
        Returning ``None`` keeps normal model-driven routing unchanged.
        """
        return None

    def _run_compatibility_plan(self, kwargs, requested):
        """Execute an injected plan through the same read-only tool cache."""
        allowed = set(READ_ONLY_TOOLS)
        has_image = bool(kwargs.get("image_path"))
        has_sensor = bool(kwargs.get("sensor_content") or kwargs.get("use_demo_sensor"))
        order = []
        for name in requested or []:
            if name not in allowed or name in order:
                continue
            if name == "inspect_image" and not has_image:
                continue
            if name == "analyze_sensor" and not has_sensor:
                continue
            order.append(name)
        if not order:
            return None
        for required in ("retrieve_knowledge", "validate_redlines"):
            if required not in order:
                order.append(required)
        order = [name for name in READ_ONLY_TOOLS if name in order]
        evidence = {
            "query": " ".join(filter(None, [kwargs.get("query_text", ""), kwargs.get("device_model", "")])),
            "tool_results": {name: 1 for name in order},
            "image_result": None,
            "sensor_result": None,
            "matched_docs": [],
            "redline_checks": [],
        }
        tools = {tool.name: tool for tool in self._build_tools(kwargs, evidence)}
        for name in order:
            tools[name].invoke({})
        return evidence, order

    @staticmethod
    def _model_available():
        return bool(os.getenv("LLM_API_KEY", "").strip()) and ChatOpenAI is not None and StateGraph is not None

    def _build_tools(self, kwargs, evidence):
        image_path = kwargs.get("image_path")
        sensor_content = kwargs.get("sensor_content")
        sensor_filename = kwargs.get("sensor_filename", "sensor_data.csv")
        use_demo_sensor = kwargs.get("use_demo_sensor", False)
        query_text = kwargs.get("query_text", "")

        def inspect_image():
            if evidence["image_result"] is not None:
                return evidence["image_result"]
            if not image_path:
                return {"status": "skipped", "reason": "未上传图片"}
            result = self.legacy.image_engine.analyze(image_path)
            evidence["image_result"] = result
            return result

        def analyze_sensor():
            if evidence["sensor_result"] is not None:
                return evidence["sensor_result"]
            if not (sensor_content or use_demo_sensor):
                return {"status": "skipped", "reason": "未提供传感器数据"}
            result = self.legacy._run_sensor_input(sensor_content, sensor_filename, use_demo_sensor)
            evidence["sensor_result"] = result
            return result

        def retrieve_knowledge():
            if evidence["matched_docs"]:
                return evidence["matched_docs"]
            result = self.vector_engine.search_similar(evidence["query"] or "发动机 检修", top_k=4)
            evidence["matched_docs"] = result
            return result

        def validate_redlines():
            if evidence["redline_checks"]:
                return evidence["redline_checks"]
            result = self.legacy._redline_check(query_text, evidence.get("sensor_result"))
            evidence["redline_checks"] = result
            return result

        return [
            StructuredTool.from_function(inspect_image, name="inspect_image", description="检查上传设备图片并返回视觉证据"),
            StructuredTool.from_function(analyze_sensor, name="analyze_sensor", description="分析传感器 CSV 或内置时序样例"),
            StructuredTool.from_function(retrieve_knowledge, name="retrieve_knowledge", description="检索维修知识和历史证据"),
            StructuredTool.from_function(validate_redlines, name="validate_redlines", description="校验参数红线并返回风险状态"),
        ]

    def _run_tool_loop(self, kwargs):
        requested = self._tool_calling_order(kwargs)
        if requested is not None:
            return self._run_compatibility_plan(kwargs, requested)
        if not self._model_available():
            return None
        evidence = {
            "query": " ".join(filter(None, [kwargs.get("query_text", ""), kwargs.get("device_model", "")])),
            "tool_results": {}, "image_result": None, "sensor_result": None,
            "matched_docs": [], "redline_checks": [],
        }
        tools = self._build_tools(kwargs, evidence)
        tool_map = {tool.name: tool for tool in tools}
        try:
            base_url = os.getenv(
                "LLM_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            ).rstrip("/").removesuffix("/chat/completions")
            model = ChatOpenAI(
                api_key=os.getenv("LLM_API_KEY"), base_url=base_url,
                model=os.getenv("LLM_MODEL", "qwen-plus"), temperature=0,
                timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")), max_retries=1,
            ).bind_tools(tools)
            graph = StateGraph(_State)

            def call_model(state):
                iterations = state.get("iterations", 0) + 1
                if iterations > MAX_ITERATIONS:
                    from langchain_core.messages import AIMessage
                    return {"iterations": iterations, "messages": [AIMessage(content="达到工具调用上限") ]}
                return {"iterations": iterations, "messages": [model.invoke(state["messages"])]}

            graph.add_node("agent", call_model)
            graph.add_node("tools", ToolNode(tools))
            graph.add_edge(START, "agent")

            def route(state):
                last = state.get("messages", [])[-1] if state.get("messages") else None
                calls = getattr(last, "tool_calls", []) or []
                if calls and state.get("iterations", 0) < MAX_ITERATIONS:
                    return "tools"
                return END

            graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
            graph.add_edge("tools", "agent")
            prompt = (
                "你是工业设备检修 Agent。根据现场输入自主选择只读工具，先获取证据再总结。"
                "只能调用 inspect_image、analyze_sensor、retrieve_knowledge、validate_redlines。"
                "不得创建工单、写数据库或执行维修。工具结果充分后直接给出结论。"
            )
            user_input = (
                f"设备={kwargs.get('device_model') or '未指定'}; 现象={kwargs.get('query_text') or '未提供'}; "
                f"图片={'有' if kwargs.get('image_path') else '无'}; "
                f"传感器={'有' if kwargs.get('sensor_content') or kwargs.get('use_demo_sensor') else '无'}"
            )
            state = graph.compile().invoke({
                "messages": [SystemMessage(content=prompt), HumanMessage(content=user_input)],
                "iterations": 0,
            })
            for message in state.get("messages", []):
                for call in getattr(message, "tool_calls", []) or []:
                    name = call.get("name")
                    if name in tool_map:
                        evidence["tool_results"][name] = evidence["tool_results"].get(name, 0) + 1
            return evidence
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    def run(self, **kwargs: Any):
        loop = self._run_tool_loop(kwargs)
        if isinstance(loop, tuple):
            evidence, order = loop
            result = self.legacy.run(tool_order=order, precomputed=evidence, **kwargs)
            result["runtime"] = {"framework": "LangGraph", "mode": "tool-calling", "selected_tools": order,
                                  "tool_loop": True, "max_iterations": MAX_ITERATIONS,
                                  "human_confirmation": "required_for_work_order"}
            result["steps"].insert(0, {"tool": "select_tools", "label": "Agent 自主工具选择", "status": "completed",
                                       "input_summary": "兼容调用方提供工具计划", "output_summary": " → ".join(order),
                                       "duration_ms": 1})
            return result
        mode = "tool-calling" if loop and not loop.get("error") and loop.get("tool_results") else "policy"
        if mode == "tool-calling":
            precomputed = {key: loop[key] for key in ("image_result", "sensor_result", "matched_docs", "redline_checks")}
            order = [name for name in READ_ONLY_TOOLS if loop["tool_results"].get(name)]
            result = self.legacy.run(tool_order=order, precomputed=precomputed, **kwargs)
            result["runtime"] = {"framework": "LangGraph", "mode": mode, "selected_tools": order,
                                  "tool_loop": True, "max_iterations": MAX_ITERATIONS,
                                  "human_confirmation": "required_for_work_order"}
            result["steps"].insert(0, {"tool": "agent_loop", "label": "Agent 自主工具调用循环", "status": "completed",
                                       "input_summary": "模型根据证据自主选择只读工具", "output_summary": " → ".join(order),
                                       "duration_ms": 1})
            return result

        order = self._policy_order(bool(kwargs.get("image_path")), bool(kwargs.get("sensor_content") or kwargs.get("use_demo_sensor")))
        result = self.legacy.run(tool_order=order, **kwargs)
        result["runtime"] = {"framework": "LangGraph", "mode": "policy", "selected_tools": order,
                              "tool_loop": False, "max_iterations": MAX_ITERATIONS,
                              "human_confirmation": "required_for_work_order"}
        return result

    @staticmethod
    def _policy_order(has_image, has_sensor):
        order = []
        if has_image:
            order.append("inspect_image")
        if has_sensor:
            order.append("analyze_sensor")
        return order + ["retrieve_knowledge", "validate_redlines"]
