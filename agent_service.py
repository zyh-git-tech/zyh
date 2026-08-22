# -*- coding: utf-8 -*-
"""本地确定性 Agent：把已有检修能力编排成可解释的工具调用链。"""
import re
import time
import uuid

from predictive_service import SENSOR_RULES, analyze_series, demo_series, parse_csv_with_profile
from standards_service import STANDARD_RULES, check_parameter


class AgentOrchestrator:
    """面向展示的工具编排器，不依赖在线大模型或外部服务。"""

    def __init__(self, vector_engine, image_engine, profile_builder):
        self.vector_engine = vector_engine
        self.image_engine = image_engine
        self.profile_builder = profile_builder

    @staticmethod
    def _trace_id():
        return "AG-" + time.strftime("%y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()

    @staticmethod
    def _demo_profile(rows):
        intervals = [b["hour"] - a["hour"] for a, b in zip(rows, rows[1:])]
        return {
            "filename": "内置退化基线 / DEMO-SENSOR-48H",
            "sha256": "BUILTIN-BASELINE-V1",
            "size_bytes": 0,
            "row_count": len(rows),
            "column_count": 4,
            "time_span": rows[-1]["hour"] - rows[0]["hour"],
            "median_interval": intervals[len(intervals) // 2],
            "completeness": 100.0,
            "irregular_intervals": 0,
            "quality_status": "通过",
            "ranges": {
                key: {"min": min(row[key] for row in rows), "max": max(row[key] for row in rows)}
                for key in SENSOR_RULES
            },
        }

    @staticmethod
    def _summary(value, fallback="未提供"):
        if value is None:
            return fallback
        if isinstance(value, str):
            return value[:180]
        return str(value)[:180]

    def _add_step(self, steps, tool, label, input_summary, callback):
        started = time.perf_counter()
        step = {
            "tool": tool, "label": label, "status": "running",
            "input_summary": self._summary(input_summary), "output_summary": "",
            "duration_ms": 0,
        }
        steps.append(step)
        try:
            value = callback()
            step["status"] = "completed"
            step["output_summary"] = self._summary(value)
            return value
        except Exception as exc:  # 展示页保留失败节点，后续工具继续执行
            step["status"] = "failed"
            step["output_summary"] = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            step["duration_ms"] = max(1, round((time.perf_counter() - started) * 1000))

    def _redline_check(self, query, sensor_result):
        text = query or ""
        checks = []
        # 对文本中明确给出的火花塞间隙进行机器校验。
        if "火花塞" in text or "间隙" in text:
            match = re.search(r"(?:间隙|gap)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)", text, re.I)
            if match:
                checks.append({"key": "spark_gap", "result": check_parameter("spark_gap", match.group(1))})
            else:
                rule = STANDARD_RULES["spark_gap"]
                checks.append({"key": "spark_gap", "result": {
                    **rule, "status": "待实测", "severity": "warning",
                    "message": f"请现场测量，标准范围 {rule['min']}–{rule['max']} {rule['unit']}。",
                }})
        if sensor_result:
            for key, metric in sensor_result.get("metrics", {}).items():
                if metric.get("status") in {"预警", "危险"}:
                    checks.append({"key": key, "result": {
                        "name": metric["name"], "unit": metric["unit"], "status": metric["status"],
                        "severity": "danger" if metric["status"] == "危险" else "warning",
                        "message": f"当前值 {metric['current']} {metric['unit']}，请按趋势结果安排复核。",
                    }})
        if not checks:
            checks.append({"key": "general", "result": {
                "name": "通用作业红线", "unit": "", "status": "待实测", "severity": "warning",
                "message": "关键尺寸、扭矩和压力需录入后再关闭工单。",
            }})
        return checks

    def run(self, query_text="", device_model="", image_path=None, sensor_content=None,
            sensor_filename="sensor_data.csv", use_demo_sensor=False):
        steps = []
        trace_id = self._trace_id()
        image_result = None
        sensor_result = None
        source_profile = None

        if image_path:
            image_result = self._add_step(
                steps, "inspect_image", "图像缺陷分析", "上传设备图片",
                lambda: self.image_engine.analyze(image_path),
            )
        else:
            steps.append({"tool": "inspect_image", "label": "图像缺陷分析", "status": "skipped",
                          "input_summary": "未上传图片", "output_summary": "跳过视觉工具", "duration_ms": 0})

        if sensor_content or use_demo_sensor:
            def run_sensor():
                nonlocal source_profile
                if sensor_content:
                    rows, source_profile = parse_csv_with_profile(sensor_content, sensor_filename)
                else:
                    rows = demo_series()
                    source_profile = self._demo_profile(rows)
                result = analyze_series(rows)
                result["source_profile"] = source_profile
                return result
            sensor_result = self._add_step(
                steps, "analyze_sensor", "传感器趋势分析",
                sensor_filename if sensor_content else "内置退化基线",
                run_sensor,
            )
        else:
            steps.append({"tool": "analyze_sensor", "label": "传感器趋势分析", "status": "skipped",
                          "input_summary": "未上传 CSV", "output_summary": "跳过时序工具", "duration_ms": 0})

        visual_summary = image_result.get("summary", "") if image_result else ""
        sensor_summary = sensor_result.get("summary", "") if sensor_result else ""
        final_query = " ".join(item for item in [query_text, device_model, visual_summary, sensor_summary] if item)

        matched_docs = self._add_step(
            steps, "retrieve_knowledge", "维修知识检索", final_query or "通用设备点检",
            lambda: self.vector_engine.search_similar(final_query or "发动机 检修", top_k=4),
        ) or []
        redline_checks = self._add_step(
            steps, "validate_redlines", "参数红线校验", query_text or "待测参数",
            lambda: self._redline_check(query_text, sensor_result),
        ) or []

        profile = self._add_step(
            steps, "build_diagnosis", "融合诊断决策", f"{len(matched_docs)} 条知识证据",
            lambda: self.profile_builder(final_query, image_result, matched_docs),
        ) or self.profile_builder(final_query, image_result, matched_docs)
        if sensor_result and sensor_result.get("risk_level") == "高风险" and profile["risk_level"] != "高风险":
            profile.update({"risk_level": "高风险", "risk_class": "danger"})

        answer = self.vector_engine._offline_diagnostic_fallback(
            final_query, matched_docs[:3], "Agent 本地确定性工具编排"
        )
        if sensor_result:
            answer += f"\n\n时序结论：{sensor_result.get('summary', '')}\n维护窗口：{sensor_result.get('maintenance_window', '待评估')}"
        answer += "\n\n红线状态：" + "；".join(item["result"]["status"] for item in redline_checks)
        profile["answer"] = answer
        profile["redline_checks"] = redline_checks

        draft = self._add_step(
            steps, "prepare_work_order", "生成工单草稿", profile["risk_level"],
            lambda: self._work_order_draft(device_model, query_text, profile, sensor_result),
        ) or {}
        evidence = [{"source": doc.get("source", "本地知识库"), "score": doc.get("score", 0),
                     "text": doc.get("text", "")} for doc in matched_docs]
        if sensor_result:
            evidence.append({"source": "设备传感器时序", "score": 0.96, "text": sensor_result.get("summary", "")})
        return {
            "trace_id": trace_id, "status": "completed", "steps": steps,
            "input": {"device_model": device_model, "query_text": query_text,
                      "has_image": bool(image_path), "has_sensor": bool(sensor_content or use_demo_sensor)},
            "image_result": image_result, "sensor_result": sensor_result,
            "source_profile": source_profile, "evidence": evidence,
            "matched_docs": matched_docs, "diagnosis": profile, "work_order_draft": draft,
        }

    @staticmethod
    def _work_order_draft(device_model, query, profile, sensor_result):
        priority = {"高风险": "P1", "中风险": "P2", "低风险": "P3"}.get(profile["risk_level"], "P2")
        steps = [
            {"title": "执行能量隔离与故障复现", "standard": "停机、断电、挂牌，记录工况"},
            {"title": "按诊断证据检查重点部位", "standard": "逐项对照图片线索与手册来源"},
            {"title": "采集关键实测参数", "standard": "使用参数红线复核并保留测量值"},
            {"title": "执行维修、更换或调整", "standard": "按演示维护规程的力矩与装配顺序执行"},
            {"title": "复测签核并回填经验", "standard": "故障消失、参数合格、附件完整"},
        ]
        if sensor_result:
            steps[1] = {"title": "复核传感器与数据质量", "standard": "确认趋势有效并排除传感器松动"}
            rul = sensor_result.get("rul_hours")
            window = sensor_result.get("maintenance_window", "按趋势安排")
            if rul is not None:
                window += f"；RUL 约 {rul} h（置信度 {sensor_result.get('rul_confidence', 0):.0%}）"
            steps[2] = {"title": "锁定维护窗口", "standard": window}
        return {
            "title": f"{device_model or '通用设备'} · {(query or '综合检修')[:42]}",
            "device_model": device_model or "通用设备", "priority": priority,
            "planned_hours": 3.0 if priority == "P1" else 2.0,
            "estimated_saving": 5800 if priority == "P1" else 2600, "steps": steps,
        }
