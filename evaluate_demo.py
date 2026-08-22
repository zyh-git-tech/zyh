# -*- coding: utf-8 -*-
"""Run the deterministic synthetic benchmark used in the project documentation."""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from agent_service import AgentOrchestrator
from app import build_profile
from image_service import ImageInspectionService
from vector_service import VectorService


ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "data" / "demo_eval_cases.json"
INVALID_CSV = b"hour,bad_column\n0,1\n"


def _build_engine():
    vector_engine = VectorService()
    image_engine = ImageInspectionService()
    return AgentOrchestrator(vector_engine, image_engine, build_profile)


def _f1_by_label(expected, predicted):
    labels = sorted(set(expected))
    scores = []
    for label in labels:
        tp = sum(item == label and actual == label for item, actual in zip(expected, predicted))
        fp = sum(item != label and actual == label for item, actual in zip(expected, predicted))
        fn = sum(item == label and actual != label for item, actual in zip(expected, predicted))
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0)
    return sum(scores) / len(scores) if scores else 0


def run_benchmark(cases=None):
    cases = cases or json.loads(CASES_PATH.read_text(encoding="utf-8"))
    engine = _build_engine()
    expected_risks, predicted_risks = [], []
    expected_causes, predicted_causes = [], []
    degraded_passes = 0
    failures = []

    with tempfile.TemporaryDirectory(prefix="gongjing-eval-") as temp_dir:
        temp_dir = Path(temp_dir)
        for case in cases:
            image_path = None
            if case.get("image_fixture"):
                image_path = temp_dir / f"{case['id']}.ppm"
                shutil.copy2(ROOT / case["image_fixture"], image_path)
            elif case.get("invalid_image"):
                image_path = temp_dir / f"{case['id']}.txt"
                image_path.write_text("not an image", encoding="utf-8")

            try:
                result = engine.run(
                    query_text=case.get("query_text", ""),
                    device_model="ZONTES-250",
                    image_path=str(image_path) if image_path else None,
                    sensor_content=INVALID_CSV if case.get("invalid_sensor") else None,
                    sensor_filename="invalid.csv",
                    use_demo_sensor=case.get("use_demo_sensor", False),
                )
                diagnosis = result["diagnosis"]
                predicted_risks.append(diagnosis["risk_level"])
                expected_risks.append(case["expected_risk"])
                predicted_causes.append(diagnosis["causes"][0])
                expected_causes.append(case["expected_cause"])
                degraded = any(step["status"] in {"failed", "skipped"} for step in result["steps"])
                if case.get("expects_degraded_step"):
                    if degraded and result["status"] == "completed":
                        degraded_passes += 1
                    else:
                        failures.append({"id": case["id"], "reason": "未保留降级轨迹"})
                if diagnosis["risk_level"] != case["expected_risk"]:
                    failures.append({"id": case["id"], "reason": f"风险等级 {diagnosis['risk_level']} != {case['expected_risk']}"})
                if case["expected_cause"] not in diagnosis["causes"]:
                    failures.append({"id": case["id"], "reason": f"原因标签缺少 {case['expected_cause']}"})
            except Exception as exc:  # benchmark should report a sample failure, not hide it
                failures.append({"id": case["id"], "reason": f"{type(exc).__name__}: {exc}"})

    risk_accuracy = sum(actual == expected for actual, expected in zip(predicted_risks, expected_risks)) / max(1, len(expected_risks))
    return {
        "samples": len(cases),
        "risk_accuracy": round(risk_accuracy, 3),
        "cause_macro_f1": round(_f1_by_label(expected_causes, predicted_causes), 3),
        "degradation_pass_rate": round(degraded_passes / max(1, sum(bool(case.get("expects_degraded_step")) for case in cases)), 3),
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = parser.parse_args()
    report = run_benchmark()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["failures"] else 0
    print(f"samples: {report['samples']}")
    print(f"risk_accuracy: {report['risk_accuracy']:.1%}")
    print(f"cause_macro_f1: {report['cause_macro_f1']:.3f}")
    print(f"degradation_pass_rate: {report['degradation_pass_rate']:.1%}")
    if report["failures"]:
        print("failures:")
        for failure in report["failures"]:
            print(f"- {failure['id']}: {failure['reason']}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
