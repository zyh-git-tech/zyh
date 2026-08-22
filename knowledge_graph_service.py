# -*- coding: utf-8 -*-
"""工业故障知识图谱：实体、证据关系与可解释路径。"""


TYPE_LABELS = {
    "symptom": "故障现象",
    "cause": "可能原因",
    "check": "检测方法",
    "standard": "标准阈值",
    "action": "处置动作",
    "source": "证据来源",
    "case": "审核案例",
}


def _node(node_id, label, node_type, x, y, description, evidence=""):
    return {
        "id": node_id, "label": label, "type": node_type, "type_label": TYPE_LABELS[node_type],
        "x": x, "y": y, "description": description, "evidence": evidence,
    }


def _edge(source, target, relation, confidence, evidence=""):
    return {
        "source": source, "target": target, "relation": relation,
        "confidence": confidence, "evidence": evidence,
    }


def build_knowledge_graph(approved_cases=None):
    nodes = [
        _node("s_start", "启动困难", "symptom", 90, 95, "冷机或热机条件下起动时间延长、无法起动。"),
        _node("s_knock", "敲击异响", "symptom", 90, 235, "转速相关的机械敲击、周期性冲击或异常振动。"),
        _node("s_oil", "渗油油泥", "symptom", 90, 375, "结合面或密封部位出现油迹、油泥和持续渗漏。"),
        _node("s_power", "动力不足", "symptom", 90, 515, "负载能力下降、加速无力或压缩性能不足。"),

        _node("c_spark", "火花塞积碳/间隙", "cause", 330, 70, "电极积碳、烧蚀或间隙超差导致点火能量不足。"),
        _node("c_seal", "气缸密封失效", "cause", 330, 180, "活塞环、气门或缸体密封状态异常。"),
        _node("c_timing", "配气相位错位", "cause", 330, 290, "正时标记、涨紧器或凸轮轴装配关系异常。"),
        _node("c_crank", "曲轴跳动超差", "cause", 330, 400, "曲轴轴颈跳动或连杆间隙超出技术要求。"),
        _node("c_gasket", "密封件/结合面失效", "cause", 330, 510, "O 型圈、垫片、水封或结合面密封异常。"),

        _node("ck_gap", "塞尺测量电极间隙", "check", 580, 55, "拆下火花塞，清洁后以塞尺测量中心电极间隙。"),
        _node("ck_pressure", "压缩压力测试", "check", 580, 165, "暖机并保持节气门全开，记录最大压缩压力。"),
        _node("ck_marks", "T / IN / EX 标记复核", "check", 580, 275, "曲轴转至压缩上止点，复核转子和凸轮轴刻线。"),
        _node("ck_runout", "百分表跳动测量", "check", 580, 385, "以 V 形架支承曲轴，旋转并记录两端最大跳动。"),
        _node("ck_leak", "清洁保压 / 荧光复核", "check", 580, 495, "清洁表面后运行保压，定位连续渗漏源。"),

        _node("st_gap", "0.7-0.9 mm", "standard", 825, 45, "火花塞电极间隙演示范围。", "合成演示知识库 · 演示参数规则"),
        _node("st_pressure", "演示压力范围", "standard", 825, 155, "压缩压力需与设备型号对应的维护标准比较。", "合成演示知识库 · 压缩测试"),
        _node("st_marks", "基准标记对齐", "standard", 825, 265, "设备处于规定基准位置时复核装配标记。", "合成演示知识库 · 装配校验"),
        _node("st_runout", "演示跳动阈值", "standard", 825, 375, "旋转部件偏差需按项目规则和测量条件复核。", "合成演示知识库 · 旋转部件"),
        _node("st_torque", "密封面按序定扭", "standard", 825, 485, "更换密封后按设备作业规程和力矩要求紧固。", "合成演示知识库 · 密封系统"),

        _node("a_spark", "清洁/更换并复测", "action", 1070, 55, "处理火花塞并按 20±2 N·m 安装，复测起动。"),
        _node("a_seal", "区分环组与气门密封", "action", 1070, 165, "湿式复测并拆检活塞环、气门及密封面。"),
        _node("a_timing", "重新对正与装配", "action", 1070, 275, "按标记恢复配气相位，检查涨紧器释放状态。"),
        _node("a_crank", "校正或更换曲轴", "action", 1070, 385, "超差时在专用校正台处理或更换总成。"),
        _node("a_gasket", "更换密封并保压复验", "action", 1070, 495, "更换失效件、清理结合面并完成复验。"),

        _node("src_manual", "合成演示知识库", "source", 355, 675, "公开的演示排查步骤、参数规则和安全提示。", "data/demo_knowledge_base.json"),
        _node("src_rules", "参数红线规则库", "source", 650, 675, "将手册阈值转成机器可执行校验规则。", "STANDARD_RULES / SENSOR_RULES"),
        _node("src_cases", "专家审核案例库", "source", 945, 675, "经专家审核通过的一线故障闭环案例。", "MaintCase(status=APPROVED)"),
    ]
    edges = [
        _edge("s_start", "c_spark", "可能由", 0.91), _edge("s_start", "c_seal", "可能由", 0.78),
        _edge("s_power", "c_seal", "强关联", 0.88), _edge("s_power", "c_timing", "可能由", 0.72),
        _edge("s_knock", "c_timing", "可能由", 0.82), _edge("s_knock", "c_crank", "强关联", 0.89),
        _edge("s_oil", "c_gasket", "强关联", 0.94),
        _edge("c_spark", "ck_gap", "通过检测", 0.96), _edge("c_seal", "ck_pressure", "通过检测", 0.93),
        _edge("c_timing", "ck_marks", "通过检测", 0.97), _edge("c_crank", "ck_runout", "通过检测", 0.98),
        _edge("c_gasket", "ck_leak", "通过检测", 0.90),
        _edge("ck_gap", "st_gap", "判定依据", 0.99), _edge("ck_pressure", "st_pressure", "判定依据", 0.98),
        _edge("ck_marks", "st_marks", "判定依据", 0.99), _edge("ck_runout", "st_runout", "判定依据", 0.99),
        _edge("ck_leak", "st_torque", "处置约束", 0.86),
        _edge("st_gap", "a_spark", "触发处置", 0.95), _edge("st_pressure", "a_seal", "触发处置", 0.88),
        _edge("st_marks", "a_timing", "触发处置", 0.96), _edge("st_runout", "a_crank", "触发处置", 0.96),
        _edge("st_torque", "a_gasket", "触发处置", 0.91),
        _edge("src_manual", "st_gap", "支撑", 1.0, "演示规则 gap"),
        _edge("src_manual", "st_pressure", "支撑", 1.0, "演示规则 pressure"),
        _edge("src_manual", "st_marks", "支撑", 1.0, "演示规则 marks"),
        _edge("src_manual", "st_runout", "支撑", 1.0, "演示规则 runout"),
        _edge("src_rules", "st_gap", "规则化", 0.98), _edge("src_rules", "st_pressure", "规则化", 0.98),
        _edge("src_cases", "c_spark", "案例增强", 0.76), _edge("src_cases", "c_gasket", "案例增强", 0.74),
    ]

    keyword_targets = [
        (("启动", "火花塞", "积碳"), "s_start", "c_spark"),
        (("异响", "敲击", "抖动"), "s_knock", "c_crank"),
        (("漏油", "渗油", "油泥"), "s_oil", "c_gasket"),
        (("无力", "压力", "动力"), "s_power", "c_seal"),
    ]
    for index, case in enumerate(approved_cases or []):
        text = f"{case.title} {case.fault_description} {case.solution}"
        symptom, cause = "s_start", "c_spark"
        for terms, matched_symptom, matched_cause in keyword_targets:
            if any(term in text for term in terms):
                symptom, cause = matched_symptom, matched_cause
                break
        node_id = f"case_{case.id}"
        case_node = _node(
            node_id, case.title[:16], "case", 1180, 620 + index * 92,
            f"{case.device_model}：{case.fault_description}", f"审核案例 #{case.id}；对策：{case.solution}",
        )
        case_node["case_id"] = case.id
        nodes.append(case_node)
        edges.extend([
            _edge(node_id, symptom, "观测到", 0.88, f"审核案例 #{case.id}"),
            _edge(node_id, cause, "验证了", 0.82, f"审核案例 #{case.id}"),
            _edge("src_cases", node_id, "收录", 1.0),
        ])

    paths = {
        "startup": {"title": "启动困难诊断链", "nodes": ["s_start", "c_spark", "ck_gap", "st_gap", "a_spark"], "conclusion": "先用塞尺验证火花塞间隙；超出 0.7-0.9 mm 时，执行清洁或更换并按标准力矩复装。"},
        "knock": {"title": "敲击异响诊断链", "nodes": ["s_knock", "c_crank", "ck_runout", "st_runout", "a_crank"], "conclusion": "优先用百分表验证曲轴跳动；超过 0.03 mm 时进入校正或更换流程。"},
        "leak": {"title": "渗油油泥诊断链", "nodes": ["s_oil", "c_gasket", "ck_leak", "st_torque", "a_gasket"], "conclusion": "清洁后保压定位泄漏源，更换密封件并按演示规程定扭复验。"},
        "power": {"title": "动力不足诊断链", "nodes": ["s_power", "c_seal", "ck_pressure", "st_pressure", "a_seal"], "conclusion": "以压缩压力区分燃烧与密封问题；低于 1300 kPa 时进一步区分活塞环和气门密封。"},
    }
    type_counts = {node_type: sum(node["type"] == node_type for node in nodes) for node_type in TYPE_LABELS}
    stats = {
        "nodes": len(nodes), "edges": len(edges), "sources": type_counts["source"] + type_counts["case"],
        "standards": type_counts["standard"], "paths": len(paths), "types": type_counts,
    }
    return {"nodes": nodes, "edges": edges, "paths": paths, "stats": stats, "type_labels": TYPE_LABELS}
