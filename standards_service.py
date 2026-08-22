# -*- coding: utf-8 -*-
"""工业参数红线规则库与可解释校验。"""


STANDARD_RULES = {
    "spark_gap": {"name": "火花塞电极间隙", "unit": "mm", "min": 0.7, "max": 0.9, "source": "合成演示规则·点火系统"},
    "spark_torque": {"name": "火花塞安装扭矩", "unit": "N·m", "min": 18, "max": 22, "source": "合成演示规则·紧固复核"},
    "cylinder_pressure": {"name": "1500 r/min 气缸压力", "unit": "kPa", "min": 1300, "max": 1900, "source": "合成演示规则·压缩测试"},
    "crank_runout": {"name": "曲轴轴颈跳动", "unit": "mm", "min": 0, "max": 0.03, "source": "合成演示规则·旋转部件"},
    "engine_mount_torque": {"name": "发动机悬挂螺栓扭矩", "unit": "N·m", "min": 60, "max": 70, "source": "合成演示规则·设备紧固"},
    "rear_axle_torque": {"name": "后平叉轴扭矩", "unit": "N·m", "min": 105, "max": 115, "source": "合成演示规则·设备紧固"},
}


def check_parameter(rule_key, value):
    rule = STANDARD_RULES.get(rule_key)
    if not rule:
        raise KeyError("未知参数规则")
    number = float(value)
    if rule["min"] <= number <= rule["max"]:
        status = "合格"
        severity = "safe"
        message = f"实测值处于 {rule['min']}–{rule['max']} {rule['unit']} 标准区间内。"
        deviation = 0
    else:
        severity = "danger"
        nearest = rule["min"] if number < rule["min"] else rule["max"]
        deviation = abs(number - nearest)
        direction = "低于下限" if number < rule["min"] else "高于上限"
        status = "超差"
        message = f"实测值{direction} {deviation:g} {rule['unit']}，触发作业红线，请暂停流转并复核。"
    return {**rule, "value": number, "status": status, "severity": severity, "message": message, "deviation": deviation}
