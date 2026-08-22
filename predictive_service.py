# -*- coding: utf-8 -*-
"""轻量级预测性维护引擎：趋势拟合、越线预测与维护窗口优化。"""
import csv
import hashlib
import io
import math
import statistics


SENSOR_RULES = {
    "temperature": {"name": "轴承温度", "unit": "℃", "direction": "max", "warning": 82.0, "danger": 95.0},
    "vibration": {"name": "振动速度", "unit": "mm/s", "direction": "max", "warning": 4.5, "danger": 7.1},
    "pressure": {"name": "润滑压力", "unit": "kPa", "direction": "min", "warning": 240.0, "danger": 200.0},
}


def demo_series():
    rows = []
    for hour in range(0, 49, 4):
        rows.append({
            "hour": hour,
            "temperature": round(68 + hour * 0.31 + math.sin(hour / 8) * 1.8, 1),
            "vibration": round(2.2 + hour * 0.075 + math.sin(hour / 5) * 0.18, 2),
            "pressure": round(310 - hour * 1.65 + math.sin(hour / 7) * 4, 1),
        })
    return rows


def parse_csv_with_profile(content, filename="sensor_data.csv"):
    """解析上传数据并返回可审计的数据质量回执。"""
    raw_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 编码需为 UTF-8 或 UTF-8 with BOM") from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {"hour", "temperature", "vibration", "pressure"}
    normalized_fields = [name.strip() for name in (reader.fieldnames or [])]
    if not reader.fieldnames or not required.issubset(set(normalized_fields)):
        raise ValueError("CSV 需包含 hour, temperature, vibration, pressure 四列")
    field_map = {name.strip(): name for name in reader.fieldnames}
    rows = []
    for row_number, raw in enumerate(reader, 2):
        try:
            row = {key: float(raw[field_map[key]]) for key in required}
        except (TypeError, ValueError) as exc:
            raise ValueError(f"CSV 第 {row_number} 行存在空值或非数值内容") from exc
        if not all(math.isfinite(value) for value in row.values()):
            raise ValueError(f"CSV 第 {row_number} 行包含无穷值或非法数值")
        rows.append(row)
    if len(rows) < 4:
        raise ValueError("至少需要 4 个连续采样点")
    rows = sorted(rows, key=lambda item: item["hour"])
    hours = [item["hour"] for item in rows]
    if len(hours) != len(set(hours)):
        raise ValueError("hour 列存在重复采样时刻")
    intervals = [b - a for a, b in zip(hours, hours[1:])]
    if any(interval <= 0 for interval in intervals):
        raise ValueError("hour 列必须严格递增")
    median_interval = statistics.median(intervals)
    irregular = sum(abs(item - median_interval) > max(0.01, median_interval * 0.15) for item in intervals)
    expected_points = round((hours[-1] - hours[0]) / median_interval) + 1 if median_interval else len(rows)
    completeness = round(min(100, len(rows) / max(1, expected_points) * 100), 1)
    ranges = {
        key: {"min": round(min(row[key] for row in rows), 2), "max": round(max(row[key] for row in rows), 2)}
        for key in SENSOR_RULES
    }
    profile = {
        "filename": filename,
        "sha256": hashlib.sha256(raw_bytes).hexdigest()[:16].upper(),
        "size_bytes": len(raw_bytes),
        "row_count": len(rows),
        "column_count": len(normalized_fields),
        "time_span": round(hours[-1] - hours[0], 2),
        "median_interval": round(median_interval, 2),
        "completeness": completeness,
        "irregular_intervals": irregular,
        "quality_status": "通过" if completeness >= 95 and irregular == 0 else "需关注",
        "ranges": ranges,
    }
    return rows, profile


def parse_csv(content):
    rows, _ = parse_csv_with_profile(content)
    return rows


def _linear_fit(xs, ys):
    count = len(xs)
    mean_x, mean_y = sum(xs) / count, sum(ys) / count
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator if denominator else 0
    intercept = mean_y - slope * mean_x
    predicted = [slope * x + intercept for x in xs]
    residual = sum((y - p) ** 2 for y, p in zip(ys, predicted))
    total = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1 - residual / total if total else 1
    return slope, intercept, max(0, min(1, r2))


def _robust_features(values, rule, current, slope):
    """Return explainable, standard-library-only health features."""
    window = values[-min(5, len(values)):]
    rolling_mean = statistics.fmean(window)
    mean = statistics.median(values)
    deviations = [abs(value - mean) for value in values]
    mad = statistics.median(deviations) or 1e-9
    robust_z = abs(current - mean) / (1.4826 * mad)
    trend_score = min(1.0, abs(slope) / max(abs(rule["danger"] - rule["warning"]), 1.0) * 12)
    if rule["direction"] == "max":
        threshold_ratio = (current - rule["warning"]) / max(1.0, rule["danger"] - rule["warning"])
    else:
        threshold_ratio = (rule["warning"] - current) / max(1.0, rule["warning"] - rule["danger"])
    threshold_score = max(0.0, min(1.0, threshold_ratio))
    volatility = statistics.pstdev(window) / max(abs(rolling_mean), 1e-9)
    anomaly_score = max(0.0, min(100.0, robust_z * 12 + trend_score * 28 + threshold_score * 60))
    return {
        "rolling_mean": round(rolling_mean, 3),
        "volatility": round(volatility, 4),
        "robust_anomaly_score": round(anomaly_score, 1),
    }


def analyze_series(rows):
    xs = [row["hour"] for row in rows]
    last_hour = xs[-1]
    metrics = {}
    crossing_candidates = []
    severity_points = []

    for key, rule in SENSOR_RULES.items():
        values = [row[key] for row in rows]
        slope, intercept, r2 = _linear_fit(xs, values)
        current = values[-1]
        danger = rule["danger"]
        if abs(slope) > 1e-9:
            crossing_hour = (danger - intercept) / slope
            hours_to_cross = crossing_hour - last_hour
            moving_toward = (rule["direction"] == "max" and slope > 0) or (rule["direction"] == "min" and slope < 0)
            if moving_toward and hours_to_cross > 0:
                crossing_candidates.append((hours_to_cross, key))
            elif moving_toward and hours_to_cross <= 0:
                crossing_candidates.append((0, key))
        else:
            hours_to_cross = None

        if rule["direction"] == "max":
            warning_ratio = max(0, (current - rule["warning"]) / max(1, danger - rule["warning"]))
            status = "危险" if current >= danger else ("预警" if current >= rule["warning"] else "正常")
        else:
            warning_ratio = max(0, (rule["warning"] - current) / max(1, rule["warning"] - danger))
            status = "危险" if current <= danger else ("预警" if current <= rule["warning"] else "正常")
        severity_points.append(min(1.4, warning_ratio))
        robust = _robust_features(values, rule, current, slope)
        metrics[key] = {
            **rule, "current": round(current, 2), "slope": round(slope, 4),
            "r2": round(r2, 2), "status": status,
            "hours_to_cross": round(hours_to_cross, 1) if hours_to_cross is not None and hours_to_cross >= 0 else None,
            **robust,
        }

    predicted_hours = min((item[0] for item in crossing_candidates), default=None)
    trend_penalty = sum(min(28, max(0, point * 24)) for point in severity_points)
    time_penalty = 0 if predicted_hours is None else max(0, 32 - min(32, predicted_hours / 4))
    health_score = max(5, min(98, round(96 - trend_penalty - time_penalty)))
    if predicted_hours is not None and predicted_hours <= 8 or health_score < 45:
        risk_level, maintenance_window = "高风险", "建议 8 小时内停机检修"
    elif predicted_hours is not None and predicted_hours <= 72 or health_score < 70:
        risk_level, maintenance_window = "中风险", "建议在未来 24–72 小时生产窗口维护"
    else:
        risk_level, maintenance_window = "低风险", "可纳入 7 日计划维护并持续监测"

    primary_key = min(crossing_candidates, default=(None, "vibration"))[1]
    primary = metrics[primary_key]
    anomaly_score = round(min(100.0, statistics.fmean(item["robust_anomaly_score"] for item in metrics.values()) * 0.55
                              + max(severity_points) * 35), 1)
    degradation_factors = [metric["name"] for metric in metrics.values()
                           if metric["status"] != "正常" or abs(metric["slope"]) > 0.02]
    degradation_factors = degradation_factors or [primary["name"]]
    if predicted_hours is None:
        rul_confidence = 0.35 if len(rows) < 8 else round(max(0.4, primary["r2"] * 0.7), 2)
        rul_explanation = "当前数据未形成可靠危险阈值交点，RUL 仅作趋势参考。"
    else:
        rul_confidence = round(max(0.35, min(0.95, primary["r2"] * 0.75 + min(0.2, len(rows) / 100))), 2)
        rul_explanation = f"基于{primary['name']}线性趋势与危险阈值估计。"
    explanations = [
        f"异常分数 {anomaly_score}/100，综合稳健偏离、趋势方向和阈值距离。",
        f"主要退化因子：{'、'.join(degradation_factors)}。",
        rul_explanation,
    ]
    summary = (
        f"当前健康度 {health_score} 分，主要退化因子为{primary['name']}，"
        f"当前值 {primary['current']} {primary['unit']}，趋势斜率 {primary['slope']:+g}/{primary['unit']}·h。"
    )
    if predicted_hours is not None:
        summary += f" 按当前趋势预计约 {predicted_hours:.1f} 小时后触达危险阈值。"
    else:
        summary += " 当前趋势周期内尚未预测到危险阈值交点。"

    return {
        "health_score": health_score, "risk_level": risk_level,
        "predicted_hours": round(predicted_hours, 1) if predicted_hours is not None else None,
        "rul_hours": round(predicted_hours, 1) if predicted_hours is not None else None,
        "rul_confidence": rul_confidence,
        "anomaly_score": anomaly_score,
        "degradation_factors": degradation_factors,
        "explanations": explanations,
        "maintenance_window": maintenance_window, "primary_metric": primary_key,
        "summary": summary, "metrics": metrics, "series": rows,
        "recommendations": [
            f"优先复核{primary['name']}传感器与对应机械部位，排除采集漂移。",
            "将预测越线时间与生产排程对齐，选择损失最低的停机窗口。",
            "维护后重新采集不少于 4 个点，验证趋势是否回归稳定。",
        ],
    }
