# -*- coding: utf-8 -*-
"""无需外部服务的端到端冒烟测试。"""
import os
from io import BytesIO

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from app import app
from models import AgentRun, db, DiagnosisRecord, MaintCase, PredictiveAnalysis, WorkOrder, WorkOrderStep


def run():
    app.config.update(TESTING=True)
    results = []
    with app.test_client() as client:
        login_response = client.post("/login", data={"username": os.getenv("ADMIN_USERNAME", "admin"), "password": os.getenv("ADMIN_PASSWORD", "admin")})
        assert login_response.status_code == 302
        for path in [
            "/", "/agent", "/diagnosis", "/predictive", "/work-orders", "/sop",
            "/compliance", "/knowledge-graph", "/upload", "/admin/audit",
        ]:
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
            results.append((path, response.status_code, len(response.data)))

        fixture_image = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "engine_sample.ppm")
        with open(fixture_image, "rb") as image_file, open(
            os.path.join(os.path.dirname(__file__), "static", "samples", "final_demo_sensor.csv"), "rb"
        ) as sensor_file:
            response = client.post("/agent/run", data={
                "device_model": "ZONTES-250",
                "query_text": "冷机启动困难，火花塞发黑，伴随异响，间隙 1.2 mm",
            "fault_image": (image_file, "engine.jpg"),
                "sensor_file": (sensor_file, "final_demo_sensor.csv"),
            }, follow_redirects=True)
        required_agent_labels = ["Agent 综合结论", "图像缺陷分析", "传感器趋势分析", "维修知识检索", "参数红线校验", "融合诊断决策"]
        assert response.status_code == 200 and all(label.encode("utf-8") in response.data for label in required_agent_labels)
        agent_run = AgentRun.query.order_by(AgentRun.id.desc()).first()
        assert agent_run and agent_run.diagnosis_id and len(__import__("json").loads(agent_run.steps_json)) == 7
        assert all(step["status"] == "completed" for step in __import__("json").loads(agent_run.steps_json))
        results.append(("Agent 综合诊断与轨迹保存", response.status_code, agent_run.trace_id))

        response = client.post("/agent/work-order", data={"run_id": agent_run.id}, follow_redirects=True)
        agent_run = db.session.get(AgentRun, agent_run.id)
        assert response.status_code == 200 and agent_run.work_order_id
        assert db.session.get(WorkOrder, agent_run.work_order_id).diagnosis_id == agent_run.diagnosis_id
        results.append(("Agent 确认生成工单", response.status_code, agent_run.work_order_id))

        response = client.post("/agent/run", data={"query_text": "仅文本输入：冷机启动困难"}, follow_redirects=True)
        assert response.status_code == 200 and "Agent 综合结论".encode("utf-8") in response.data
        results.append(("Agent 仅文本降级运行", response.status_code, "completed"))

        response = client.post("/agent/run", data={"sensor_file": (BytesIO(b"a,b\n1,2\n"), "bad.csv")}, follow_redirects=True)
        assert response.status_code == 200 and "传感器趋势分析".encode("utf-8") in response.data
        results.append(("Agent 错误 CSV 保留轨迹", response.status_code, "failed step"))

        response = client.post("/agent/run", data={
            "query_text": "错误图片格式仍应保留文本诊断", "fault_image": (BytesIO(b"not an image"), "bad.txt"),
        }, follow_redirects=True)
        assert response.status_code == 200 and "图片格式不受支持".encode("utf-8") in response.data
        results.append(("Agent 错误图片格式提示", response.status_code, "warning"))

        response = client.post("/diagnosis", data={
            "device_model": "ZONTES-250",
            "query_text": "冷机启动困难，火花塞发黑，伴随异响",
            "fault_image": (open(fixture_image, "rb"), "engine.jpg"),
        })
        assert response.status_code == 200 and "可解释视觉检测".encode("utf-8") in response.data
        results.append(("POST /diagnosis", response.status_code, len(response.data)))
        diagnosis = DiagnosisRecord.query.order_by(DiagnosisRecord.id.desc()).first()
        response = client.get("/diagnosis")
        assert response.status_code == 200 and diagnosis.trace_id.encode("utf-8") in response.data
        response = client.post("/diagnosis/reset", follow_redirects=True)
        assert response.status_code == 200 and diagnosis.trace_id.encode("utf-8") not in response.data
        results.append(("诊断结果保留与重置", response.status_code, diagnosis.trace_id))

        csv_data = b"hour,temperature,vibration,pressure\n0,68,2.2,310\n4,70,2.5,300\n8,74,3.1,282\n12,79,3.8,260\n"
        response = client.post("/predictive", data={
            "device_model": "GEN-IND-01", "sensor_file": (BytesIO(csv_data), "fixture.csv"),
        })
        assert response.status_code == 200 and b"fixture.csv" in response.data
        assert "数据接入回执".encode("utf-8") in response.data
        results.append(("CSV 源文件接入", response.status_code, len(csv_data)))

        response = client.post("/api/parameter-check", json={"rule_key": "spark_gap", "value": 1.2})
        assert response.status_code == 200 and response.json["result"]["status"] == "超差"
        results.append(("POST /api/parameter-check", response.status_code, "超差"))
        response = client.get("/compliance")
        assert response.status_code == 200 and b'<div class="risk-banner danger">' in response.data
        response = client.post("/compliance/reset", follow_redirects=True)
        assert response.status_code == 200 and b'<div class="risk-banner danger">' not in response.data
        results.append(("红线复核结果保留与重置", response.status_code, "spark_gap"))

        response = client.get("/sop", query_string={"model": "ZONTES-250", "level": "日常检修"})
        assert response.status_code == 200 and "ZONTES-250 火花塞与配气正时标准点检规程".encode("utf-8") in response.data
        response = client.get("/diagnosis")
        response = client.get("/sop")
        assert response.status_code == 200 and "ZONTES-250 火花塞与配气正时标准点检规程".encode("utf-8") in response.data
        response = client.post("/sop/reset", follow_redirects=True)
        assert response.status_code == 200 and "ZONTES-250 火花塞与配气正时标准点检规程".encode("utf-8") not in response.data
        results.append(("智能 SOP 结果保留与重置", response.status_code, "ZONTES-250"))

        response = client.post("/predictive", data={"device_model": "GEN-IND-01", "use_demo": "1"})
        assert response.status_code == 200
        analysis = PredictiveAnalysis.query.order_by(PredictiveAnalysis.id.desc()).first()
        assert analysis and analysis.diagnosis_id
        results.append(("POST /predictive", response.status_code, analysis.health_score))
        response = client.get("/predictive")
        assert response.status_code == 200 and b'id="trendChart"' in response.data
        response = client.post("/predictive/reset", follow_redirects=True)
        assert response.status_code == 200 and b'id="trendChart"' not in response.data
        results.append(("预测结果保留与重置", response.status_code, analysis.analysis_no))

        response = client.post("/work-orders/create", data={
            "diagnosis_id": analysis.diagnosis_id, "predictive_id": analysis.id,
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'href="/work-orders"' in response.data
        order = WorkOrder.query.order_by(WorkOrder.id.desc()).first()
        assert order and len(order.steps) == 5
        results.append(("预测 -> 工单", response.status_code, order.order_no))
        response = client.get("/work-orders", query_string={"status": "待处理"})
        assert response.status_code == 200 and b"chip active" in response.data
        results.append(("工单状态筛选高亮", response.status_code, "待处理"))

        step = order.steps[0]
        response = client.post(
            f"/work-orders/{order.id}/steps/{step.id}",
            data={"completed": "1", "measured_value": "传感器校验正常"},
            follow_redirects=True,
        )
        order = db.session.get(WorkOrder, order.id)
        assert response.status_code == 200 and order.progress == 20
        results.append(("工单步骤签核", response.status_code, order.progress))

        response = client.post(f"/work-orders/{order.id}/delete", follow_redirects=True)
        assert response.status_code == 200
        assert db.session.get(WorkOrder, order.id) is None
        assert WorkOrderStep.query.filter_by(order_id=order.id).count() == 0
        results.append(("删除工单", response.status_code, order.order_no))

        graph_case = MaintCase(
            title="启动困难审核案例", device_model="ZONTES-250", status="APPROVED",
            fault_description="冷机启动延迟", solution="复核火花塞间隙并更换积碳部件",
        )
        db.session.add(graph_case)
        db.session.commit()
        graph_case_id = graph_case.id
        graph_response = client.get("/knowledge-graph")
        assert b"KG-3.0" in graph_response.data and "故障路径推演".encode("utf-8") in graph_response.data
        assert f"case_{graph_case_id}".encode("utf-8") in graph_response.data
        response = client.post(f"/knowledge-graph/cases/{graph_case_id}/delete", follow_redirects=True)
        assert response.status_code == 200 and db.session.get(MaintCase, graph_case_id) is None
        assert f"case_{graph_case_id}".encode("utf-8") not in response.data
        results.append(("删除图谱审核案例节点", response.status_code, graph_case_id))
        results.append(("交互知识图谱", graph_response.status_code, len(graph_response.data)))

        audit_cases = [
            MaintCase(title="待审筛选案例", device_model="ZONTES-250", fault_description="待审现象", solution="待审对策", status="PENDING"),
            MaintCase(title="通过筛选案例", device_model="ZONTES-250", fault_description="通过现象", solution="通过对策", status="APPROVED"),
            MaintCase(title="驳回筛选案例", device_model="ZONTES-250", fault_description="驳回现象", solution="驳回对策", status="REJECTED"),
        ]
        db.session.add_all(audit_cases)
        db.session.commit()
        pending_case_id, approved_case_id, rejected_case_id = (case.id for case in audit_cases)
        for status, title in [("pending", "待审筛选案例"), ("approved", "通过筛选案例"), ("rejected", "驳回筛选案例")]:
            response = client.get("/admin/audit", query_string={"status": status})
            assert response.status_code == 200 and title.encode("utf-8") in response.data
        response = client.post(f"/admin/audit/review/{approved_case_id}", follow_redirects=True)
        assert response.status_code == 200 and db.session.get(MaintCase, approved_case_id).status == "PENDING"
        response = client.post(f"/admin/audit/delete/{rejected_case_id}", data={"status": "rejected"}, follow_redirects=True)
        assert response.status_code == 200 and db.session.get(MaintCase, rejected_case_id) is None
        results.append(("专家治理台状态筛选", response.status_code, "pending/approved/rejected"))

        assert DiagnosisRecord.query.count() >= 3
        print("records", DiagnosisRecord.query.count(), PredictiveAnalysis.query.count(), WorkOrder.query.count())
        for item in results:
            print(item)


if __name__ == "__main__":
    run()
