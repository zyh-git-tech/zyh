# -*- coding: utf-8 -*-
import json
import os
import secrets
import sys
import uuid
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from image_service import ImageInspectionService
from agent_service import AgentOrchestrator
from knowledge_graph_service import build_knowledge_graph
from models import (
    db, AgentRun, DiagnosisRecord, Equipment, LlmLabeledFeedback, MaintCase,
    PredictiveAnalysis, SopStep, SopTemplate, WorkOrder, WorkOrderStep,
)
from predictive_service import SENSOR_RULES, analyze_series, demo_series, parse_csv_with_profile
from standards_service import STANDARD_RULES, check_parameter
from vector_service import VectorService


app = Flask(__name__)
app_env = os.getenv("APP_ENV", "development").lower()
configured_secret = os.getenv("APP_SECRET_KEY", "").strip()
if app_env == "production" and not configured_secret:
    raise RuntimeError("APP_SECRET_KEY must be set when APP_ENV=production")
app.secret_key = configured_secret or secrets.token_hex(32)
app.config["APP_VERSION"] = os.getenv("APP_VERSION", "0.2.0")

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.abspath(os.path.dirname(sys.executable))
    app.template_folder = os.path.join(sys._MEIPASS, "templates")
    app.static_folder = os.path.join(sys._MEIPASS, "static")
    # PyInstaller 的模板和静态目录只读，业务数据库仍写入可持久化的程序目录。
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'maintenance.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "jfif", "gif", "webp", "bmp"}
db.init_app(app)
vector_engine = VectorService()
image_engine = ImageInspectionService()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file):
    if not file or not file.filename or not allowed_file(file.filename):
        return "", ""
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    safe_name = secure_filename(file.filename) or "inspection.jpg"
    filename = f"{uuid.uuid4().hex[:10]}_{safe_name}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(path)
    return filename, path


def build_profile(query, image_result, matched_docs):
    text = (query or "").lower()
    high_terms = ["断裂", "敲击", "剧烈", "爆燃", "过热", "冒烟", "压力低", "无法启动", "漏油"]
    medium_terms = ["异响", "抖动", "磨损", "积碳", "发黑", "渗漏", "启动困难", "间隙", "松动"]
    risk_score = 24 + sum(10 for term in high_terms if term in text) + sum(5 for term in medium_terms if term in text)
    if image_result:
        risk_score = round(risk_score * 0.55 + image_result["risk_score"] * 0.45)
    risk_score = min(96, max(18, risk_score))
    if risk_score >= 70:
        risk_level, risk_class = "高风险", "danger"
    elif risk_score >= 40:
        risk_level, risk_class = "中风险", "warning"
    else:
        risk_level, risk_class = "低风险", "safe"

    top_score = matched_docs[0]["score"] if matched_docs else 0
    image_conf = image_result["confidence"] if image_result else 0.58
    confidence = min(0.96, 0.58 + top_score * 0.24 + image_conf * 0.12)

    causes = []
    cause_map = [
        (("黑烟", "积碳", "火花塞"), "点火与燃烧质量异常"),
        (("漏油", "渗漏", "油泥"), "密封件老化或结合面失效"),
        (("异响", "敲击", "抖动"), "旋转部件间隙、相位或紧固状态异常"),
        (("压力", "无力", "启动困难"), "气缸密封、活塞环或气门系统异常"),
        (("过热", "高温"), "润滑或冷却回路异常"),
    ]
    combined = text + " " + (image_result["summary"] if image_result else "")
    for terms, cause in cause_map:
        if any(term in combined for term in terms):
            causes.append(cause)
    if not causes:
        causes = ["机械连接、供油点火或传感器状态异常"]
    causes = causes[:3]

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_class": risk_class,
        "confidence": round(confidence, 2),
        "causes": causes,
        "plan": [
            "执行停机、断电与能量隔离，记录故障发生工况。",
            "按召回手册条款检查关键部位，并记录照片与实测参数。",
            "将实测值送入参数红线复核，超差时暂停作业并升级审批。",
            "完成维修后复测、签核并沉淀为可审核案例。",
        ],
    }


agent_engine = AgentOrchestrator(vector_engine, image_engine, build_profile)


@app.before_request
def ensure_demo_data():
    if request.endpoint == "healthcheck":
        return
    db.create_all()
    if Equipment.query.count() == 0:
        db.session.add_all([
            Equipment(name="水冷顶置凸轮发动机", model="ZONTES-250"),
            Equipment(name="双缸 V 型动力总成", model="2V49F"),
            Equipment(name="产线通用动力单元", model="GEN-IND-01"),
        ])
        db.session.commit()


@app.route("/agent", methods=["GET"])
def agent_workspace():
    run_id = session.get("agent_run_id")
    run_record = db.session.get(AgentRun, run_id) if run_id else None
    run_data = None
    if run_record:
        try:
            run_data = json.loads(run_record.result_json)
        except (TypeError, json.JSONDecodeError):
            run_data = None
    return render_template(
        "agent.html", run_record=run_record, run_data=run_data,
        equipments=Equipment.query.all(), selected_model=(run_data or {}).get("input", {}).get("device_model", ""),
        query_text=(run_data or {}).get("input", {}).get("query_text", ""),
    )


@app.route("/agent/run", methods=["POST"])
def run_agent_workspace():
    query_text = request.form.get("query_text", "").strip()
    selected_model = request.form.get("device_model", "").strip()
    use_demo_sensor = request.form.get("use_demo_sensor") == "1"
    image_filename, image_path = save_upload(request.files.get("fault_image"))
    sensor_upload = request.files.get("sensor_file")
    sensor_content = None
    sensor_filename = "sensor_data.csv"
    if sensor_upload and sensor_upload.filename:
        sensor_content = sensor_upload.read()
        sensor_filename = secure_filename(sensor_upload.filename) or sensor_filename
    if not any((query_text, image_path, sensor_content, use_demo_sensor)):
        flash("请至少输入故障现象、上传图片或选择内置传感器样例。", "warning")
        return redirect(url_for("agent_workspace"))
    if request.files.get("fault_image") and request.files["fault_image"].filename and not image_path:
        flash("图片格式不受支持，请上传 JPG、PNG、WebP 或 BMP 文件。", "warning")
    try:
        run_data = agent_engine.run(
            query_text=query_text, device_model=selected_model, image_path=image_path,
            sensor_content=sensor_content, sensor_filename=sensor_filename,
            use_demo_sensor=use_demo_sensor,
        )
    except Exception as exc:
        flash(f"Agent 执行失败：{exc}", "warning")
        return redirect(url_for("agent_workspace"))

    run_data["image_filename"] = image_filename
    profile = run_data["diagnosis"]
    diagnosis_record = DiagnosisRecord(
        trace_id=run_data["trace_id"], device_model=selected_model,
        query_text=query_text or "多模态 Agent 综合诊断", image_path=image_filename,
        image_findings=json.dumps(run_data.get("image_result"), ensure_ascii=False) if run_data.get("image_result") else "",
        risk_level=profile["risk_level"], confidence=profile["confidence"], answer=profile["answer"],
        sources_json=json.dumps(run_data.get("evidence", []), ensure_ascii=False),
    )
    db.session.add(diagnosis_record)
    db.session.flush()
    run_record = AgentRun(
        trace_id=run_data["trace_id"],
        input_summary=f"{selected_model or '通用设备'} · {query_text or '多模态综合诊断'}",
        steps_json=json.dumps(run_data["steps"], ensure_ascii=False),
        result_json=json.dumps(run_data, ensure_ascii=False), diagnosis_id=diagnosis_record.id,
    )
    db.session.add(run_record)
    db.session.commit()
    session["agent_run_id"] = run_record.id
    flash("Agent 已完成工具编排，诊断结果和证据链已保存。", "success")
    return redirect(url_for("agent_workspace"))


@app.route("/agent/work-order", methods=["POST"])
def create_agent_work_order():
    run_id = request.form.get("run_id", type=int) or session.get("agent_run_id")
    run_record = db.session.get(AgentRun, run_id) if run_id else None
    if not run_record:
        flash("请先运行一次 Agent 诊断。", "warning")
        return redirect(url_for("agent_workspace"))
    if run_record.work_order_id:
        return redirect(url_for("work_order_detail", order_id=run_record.work_order_id))
    run_data = json.loads(run_record.result_json)
    draft = run_data.get("work_order_draft", {})
    diagnosis = db.session.get(DiagnosisRecord, run_record.diagnosis_id)
    if not diagnosis:
        flash("诊断记录不存在，请重新运行 Agent。", "warning")
        return redirect(url_for("agent_workspace"))
    order = WorkOrder(
        order_no="WO-" + datetime.now().strftime("%y%m%d%H%M") + uuid.uuid4().hex[:3].upper(),
        diagnosis_id=diagnosis.id, title=draft.get("title", "Agent 综合检修任务"),
        device_model=draft.get("device_model", diagnosis.device_model or "通用设备"),
        priority=draft.get("priority", "P2"), assignee=request.form.get("assignee", "待分配"),
        status="待处理", planned_hours=draft.get("planned_hours", 2.0),
        estimated_saving=draft.get("estimated_saving", 2600),
    )
    db.session.add(order)
    db.session.flush()
    db.session.add_all([
        WorkOrderStep(order_id=order.id, step_num=index, title=item["title"], standard=item.get("standard", ""))
        for index, item in enumerate(draft.get("steps", []), 1)
    ])
    run_record.work_order_id = order.id
    db.session.commit()
    flash(f"已根据 Agent 草稿生成工单 {order.order_no}。", "success")
    return redirect(url_for("work_order_detail", order_id=order.id))


@app.before_request
def ensure_remaining_demo_data():
    """保留原项目的演示 SOP 与工单初始化逻辑。"""
    if request.endpoint == "healthcheck":
        return
    if SopTemplate.query.count() == 0:
        template = SopTemplate(
            equipment_model="ZONTES-250", maint_level="日常检修",
            title="ZONTES-250 火花塞与配气正时标准点检规程",
        )
        db.session.add(template)
        db.session.flush()
        db.session.add_all([
            SopStep(template_id=template.id, step_num=1, instruction="执行停机、断电和燃油隔离，确认工位已挂牌。", compliance_warning="未完成能量隔离不得拆卸或盘车。"),
            SopStep(template_id=template.id, step_num=2, instruction="拆下火花塞并用塞尺测量电极间隙，标准范围 0.7–0.9 mm。", compliance_warning="间隙超差、瓷体破损或电极烧蚀时必须更换。"),
            SopStep(template_id=template.id, step_num=3, instruction="安装时手动预紧 3 圈，再使用定扭扳手紧固至 20±2 N·m。", compliance_warning="禁止直接使用冲击工具盲目打紧。"),
            SopStep(template_id=template.id, step_num=4, instruction="复装后启动复测，记录怠速、异响、温度与泄漏状态。", compliance_warning="复测未通过不得关闭工单。"),
        ])
        db.session.commit()

    if WorkOrder.query.count() == 0:
        order = WorkOrder(
            order_no="WO-DEMO-001", title="ZONTES-250 启动困难例行排查",
            device_model="ZONTES-250", priority="P2", assignee="张工",
            status="执行中", progress=50, planned_hours=2.5, estimated_saving=3200,
        )
        db.session.add(order)
        db.session.flush()
        db.session.add_all([
            WorkOrderStep(order_id=order.id, step_num=1, title="执行能源隔离与外观检查", standard="确认断电、无泄漏", status="已完成", measured_value="已挂牌"),
            WorkOrderStep(order_id=order.id, step_num=2, title="测量火花塞间隙", standard="0.7–0.9 mm", status="已完成", measured_value="1.1 mm"),
            WorkOrderStep(order_id=order.id, step_num=3, title="更换火花塞并按标准扭矩安装", standard="20±2 N·m"),
            WorkOrderStep(order_id=order.id, step_num=4, title="复测与关闭工单", standard="启动正常、无异常报码"),
        ])
        db.session.commit()

@app.route("/")
def dashboard():
    orders = WorkOrder.query.order_by(WorkOrder.updated_at.desc()).all()
    diagnoses = DiagnosisRecord.query.order_by(DiagnosisRecord.created_at.desc()).limit(6).all()
    approved_cases = MaintCase.query.filter_by(status="APPROVED").count()
    completed = sum(1 for item in orders if item.status == "已完成")
    active = sum(1 for item in orders if item.status in {"待处理", "执行中"})
    high_risk = DiagnosisRecord.query.filter_by(risk_level="高风险").count()
    avg_conf = db.session.query(db.func.avg(DiagnosisRecord.confidence)).scalar() or 0.86
    stats = {
        "equipment": Equipment.query.count(),
        "knowledge": len(vector_engine.knowledge_base) + approved_cases,
        "active_orders": active,
        "completion_rate": round(completed / len(orders) * 100) if orders else 0,
        "high_risk": high_risk,
        "avg_confidence": round(avg_conf * 100),
        "saving": int(sum(item.estimated_saving for item in orders)),
    }
    return render_template("dashboard.html", stats=stats, orders=orders[:5], diagnoses=diagnoses)


@app.route("/diagnosis", methods=["GET", "POST"])
def diagnosis():
    query_text = ""
    selected_model = ""
    llm_answer = ""
    matched_docs = []
    image_result = None
    image_filename = ""
    profile = None
    diagnosis_record = None

    if request.method == "POST":
        query_text = request.form.get("query_text", "").strip()
        selected_model = request.form.get("device_model", "").strip()
        image_upload = request.files.get("fault_image")
        image_filename, image_path = save_upload(image_upload)
        if image_upload and image_upload.filename and not image_path:
            flash("图片未接收：请上传 JPG、JPEG、JFIF、PNG、WebP 或 BMP 格式。", "warning")
        if image_path:
            try:
                image_result = image_engine.analyze(image_path)
            except Exception as exc:
                image_result = {
                    "summary": f"图像解析异常：{exc}", "findings": [], "detections": [],
                    "risk_score": 30, "confidence": 0.4, "quality_score": 0,
                    "quality_status": "解析失败", "overlay_filename": image_filename,
                    "pipeline": ["文件接收", "格式校验未通过"],
                    "metrics": {"brightness": 0, "dark_ratio": 0, "rust_ratio": 0, "texture": 0,
                                "sharpness": 0, "width": 0, "height": 0},
                }

        visual_context = image_result["summary"] if image_result else ""
        final_query = " ".join(part for part in [query_text, visual_context, selected_model] if part)
        if final_query:
            approved_cases = MaintCase.query.filter_by(status="APPROVED").all()
            dynamic_docs = [{
                "id": f"case_{case.id}",
                "text": f"【已审核现场案例】设备 {case.device_model}；故障：{case.fault_description}；对策：{case.solution}",
                "source": f"一线经验案例 #{case.id}",
            } for case in approved_cases]
            matched_docs = vector_engine.search_similar(final_query, top_k=4, dynamic_cases=dynamic_docs)
            llm_answer = vector_engine.call_llm(final_query, matched_docs[:3])
            profile = build_profile(final_query, image_result, matched_docs)
            trace_id = "DX-" + datetime.now().strftime("%y%m%d-%H%M") + "-" + uuid.uuid4().hex[:4].upper()
            diagnosis_record = DiagnosisRecord(
                trace_id=trace_id, device_model=selected_model, query_text=query_text or "仅图像输入",
                image_path=image_filename, image_findings=json.dumps(image_result, ensure_ascii=False) if image_result else "",
                risk_level=profile["risk_level"], confidence=profile["confidence"], answer=llm_answer,
                sources_json=json.dumps([{"source": d["source"], "score": d["score"], "text": d["text"]} for d in matched_docs], ensure_ascii=False),
            )
            db.session.add(diagnosis_record)
            db.session.commit()
            session["diagnosis_result_id"] = diagnosis_record.id
    else:
        diagnosis_result_id = session.get("diagnosis_result_id")
        diagnosis_record = db.session.get(DiagnosisRecord, diagnosis_result_id) if diagnosis_result_id else None
        if diagnosis_record:
            query_text = diagnosis_record.query_text
            selected_model = diagnosis_record.device_model or ""
            llm_answer = diagnosis_record.answer
            image_filename = diagnosis_record.image_path or ""
            image_result = json.loads(diagnosis_record.image_findings) if diagnosis_record.image_findings else None
            matched_docs = json.loads(diagnosis_record.sources_json) if diagnosis_record.sources_json else []
            profile = build_profile(query_text, image_result, matched_docs)

    return render_template(
        "index.html", equipments=Equipment.query.all(), query_text=query_text,
        selected_model=selected_model, llm_answer=llm_answer, matched_docs=matched_docs,
        image_result=image_result, image_filename=image_filename, profile=profile,
        diagnosis_record=diagnosis_record,
    )


@app.route("/healthz")
def healthcheck():
    """轻量健康检查，供本地探活和 Render 使用。"""
    try:
        db.create_all()
        db.session.execute(db.text("SELECT 1"))
        return jsonify({
            "status": "ok",
            "version": app.config["APP_VERSION"],
            "database": "ok",
        })
    except Exception as exc:
        app.logger.warning("healthcheck database failure: %s", exc)
        return jsonify({
            "status": "degraded",
            "version": app.config["APP_VERSION"],
            "database": "error",
        }), 503


@app.route("/diagnosis/reset", methods=["POST"])
def reset_diagnosis():
    session.pop("diagnosis_result_id", None)
    flash("多模态诊断结果已重置。", "success")
    return redirect(url_for("diagnosis"))


@app.route("/sop")
def show_sop():
    selected_model = request.args.get("model", "")
    selected_level = request.args.get("level", "")
    if selected_model and selected_level:
        session["sop_selection"] = {"model": selected_model, "level": selected_level}
    elif saved_selection := session.get("sop_selection"):
        selected_model = saved_selection.get("model", "")
        selected_level = saved_selection.get("level", "")
    models = sorted({eq.model for eq in Equipment.query.all()})
    steps, sop_title = [], ""
    if selected_model and selected_level:
        template = SopTemplate.query.filter_by(equipment_model=selected_model, maint_level=selected_level).first()
        if template:
            sop_title = template.title
            steps = SopStep.query.filter_by(template_id=template.id).order_by(SopStep.step_num).all()
        else:
            sop_title = f"{selected_model} · {selected_level} 智能作业指引"
            docs = vector_engine.search_similar(f"{selected_model} {selected_level} 拆卸 安装 安全 力矩", top_k=4)
            steps = [type("GuideStep", (), {
                "step_num": index, "instruction": doc["text"],
                "compliance_warning": f"执行依据：{doc['source']}，关键参数须录入红线复核。",
            })() for index, doc in enumerate(docs, 1)]
    return render_template("sop.html", models=models, steps=steps, sop_title=sop_title, selected_model=selected_model, selected_level=selected_level)


@app.route("/sop/reset", methods=["POST"])
def reset_sop():
    session.pop("sop_selection", None)
    flash("智能 SOP 已重置。", "success")
    return redirect(url_for("show_sop"))


@app.route("/compliance")
def compliance():
    return render_template("compliance.html", rules=STANDARD_RULES, check_state=session.get("parameter_check"))


@app.route("/compliance/reset", methods=["POST"])
def reset_compliance():
    session.pop("parameter_check", None)
    flash("参数红线复核结果已重置。", "success")
    return redirect(url_for("compliance"))


@app.route("/predictive", methods=["GET", "POST"])
def predictive_maintenance():
    result = None
    analysis_record = None
    source_profile = None
    selected_model = request.form.get("device_model", "") if request.method == "POST" else ""
    use_demo = request.form.get("use_demo") == "1" if request.method == "POST" else False
    if request.method == "POST":
        try:
            upload = request.files.get("sensor_file")
            if upload and upload.filename:
                rows, source_profile = parse_csv_with_profile(upload.read(), secure_filename(upload.filename))
            else:
                rows = demo_series()
                use_demo = True
                intervals = [b["hour"] - a["hour"] for a, b in zip(rows, rows[1:])]
                source_profile = {
                    "filename": "内置退化基线 / DEMO-SENSOR-48H",
                    "sha256": "BUILTIN-BASELINE-V1",
                    "size_bytes": 0,
                    "row_count": len(rows), "column_count": 4,
                    "time_span": rows[-1]["hour"] - rows[0]["hour"],
                    "median_interval": intervals[len(intervals) // 2],
                    "completeness": 100.0, "irregular_intervals": 0,
                    "quality_status": "通过",
                    "ranges": {
                        key: {"min": min(row[key] for row in rows), "max": max(row[key] for row in rows)}
                        for key in SENSOR_RULES
                    },
                }
            result = analyze_series(rows)
            result["source_profile"] = source_profile
            trace_id = "DX-PM-" + datetime.now().strftime("%y%m%d-%H%M") + "-" + uuid.uuid4().hex[:3].upper()
            answer = result["summary"] + "\n\n维护窗口：" + result["maintenance_window"] + "\n" + "\n".join(
                f"{index}. {item}" for index, item in enumerate(result["recommendations"], 1)
            )
            diagnosis_record = DiagnosisRecord(
                trace_id=trace_id, device_model=selected_model or "GEN-IND-01",
                query_text="预测性维护时序预警", risk_level=result["risk_level"],
                confidence=0.82 + min(0.12, sum(item["r2"] for item in result["metrics"].values()) / 30),
                answer=answer, sources_json=json.dumps([
                    {"source": "设备传感器时序", "score": 0.96, "text": result["summary"]},
                    {"source": "ISO 10816 振动分级映射", "score": 0.88, "text": "振动速度预警 4.5 mm/s，危险阈值 7.1 mm/s"},
                    {"source": "本地参数红线库", "score": 0.86, "text": "温度、振动、润滑压力联合趋势判定"},
                ], ensure_ascii=False),
            )
            db.session.add(diagnosis_record)
            db.session.flush()
            analysis_record = PredictiveAnalysis(
                analysis_no="PM-" + datetime.now().strftime("%y%m%d%H%M") + uuid.uuid4().hex[:6].upper(),
                device_model=selected_model or "GEN-IND-01", operating_hours=rows[-1]["hour"],
                health_score=result["health_score"], risk_level=result["risk_level"],
                predicted_hours=result["predicted_hours"], maintenance_window=result["maintenance_window"],
                sensor_json=json.dumps(rows, ensure_ascii=False), result_json=json.dumps(result, ensure_ascii=False),
                diagnosis_id=diagnosis_record.id,
            )
            db.session.add(analysis_record)
            db.session.commit()
            session["predictive_result_id"] = analysis_record.id
        except ValueError as exc:
            flash(str(exc), "warning")
    else:
        predictive_result_id = session.get("predictive_result_id")
        analysis_record = db.session.get(PredictiveAnalysis, predictive_result_id) if predictive_result_id else None
        if analysis_record:
            selected_model = analysis_record.device_model
            result = json.loads(analysis_record.result_json)
            source_profile = result.get("source_profile")
    recent = PredictiveAnalysis.query.order_by(PredictiveAnalysis.created_at.desc()).limit(5).all()
    return render_template(
        "predictive.html", equipments=Equipment.query.all(), selected_model=selected_model,
        result=result, analysis_record=analysis_record, recent=recent, rules=SENSOR_RULES,
        use_demo=use_demo, source_profile=source_profile,
    )


@app.route("/predictive/reset", methods=["POST"])
def reset_predictive_maintenance():
    session.pop("predictive_result_id", None)
    flash("健康预测结果已重置。", "success")
    return redirect(url_for("predictive_maintenance"))


@app.route("/api/parameter-check", methods=["POST"])
def parameter_check():
    payload = request.get_json(silent=True) or request.form
    try:
        result = check_parameter(payload.get("rule_key"), payload.get("value"))
        session["parameter_check"] = {
            "rule_key": payload.get("rule_key"), "value": payload.get("value"), "result": result,
        }
        return jsonify({"status": "success", "result": result})
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "请输入有效数值。"}), 400
    except KeyError:
        return jsonify({"status": "error", "message": "参数规则不存在。"}), 404


@app.route("/work-orders")
def work_orders():
    status = request.args.get("status", "")
    if status not in {"", "待处理", "执行中", "已完成"}:
        status = ""
    query = WorkOrder.query.order_by(WorkOrder.updated_at.desc())
    if status:
        query = query.filter_by(status=status)
    return render_template("work_orders.html", orders=query.all(), selected_status=status)


@app.route("/work-orders/create", methods=["POST"])
def create_work_order():
    diagnosis_id = request.form.get("diagnosis_id", type=int)
    record = DiagnosisRecord.query.get_or_404(diagnosis_id)
    predictive_id = request.form.get("predictive_id", type=int)
    predictive = PredictiveAnalysis.query.get(predictive_id) if predictive_id else None
    priority = {"高风险": "P1", "中风险": "P2", "低风险": "P3"}.get(record.risk_level, "P2")
    order = WorkOrder(
        order_no="WO-" + datetime.now().strftime("%y%m%d%H%M") + uuid.uuid4().hex[:3].upper(),
        diagnosis_id=record.id, title=f"{record.device_model or '通用设备'} · {record.query_text[:42]}",
        device_model=record.device_model or "通用设备", priority=priority,
        assignee=request.form.get("assignee", "待分配"), status="待处理",
        planned_hours=3.0 if priority == "P1" else 2.0, estimated_saving=5800 if priority == "P1" else 2600,
    )
    db.session.add(order)
    db.session.flush()
    if predictive:
        prediction = json.loads(predictive.result_json)
        primary = prediction["metrics"][prediction["primary_metric"]]
        steps = [
            ("复核传感器与数据质量", f"校验{primary['name']}传感器，排除漂移与松动"),
            ("锁定最优停机窗口", predictive.maintenance_window),
            (f"检查{primary['name']}关联部位", f"当前 {primary['current']} {primary['unit']}，危险阈值 {primary['danger']} {primary['unit']}"),
            ("执行预防性维护", "按设备维护规程完成润滑、紧固、调整或部件更换"),
            ("重建健康基线", "维护后连续采集不少于 4 个点并确认趋势回归"),
        ]
    else:
        steps = [
            ("执行能量隔离与故障复现", "停机、断电、挂牌，记录工况"),
            ("按诊断证据检查重点部位", "逐项对照图片线索与手册来源"),
            ("采集关键实测参数", "使用参数红线复核并保留测量值"),
            ("执行维修、更换或调整", "按演示维护规程的力矩与装配顺序执行"),
            ("复测签核并回填经验", "故障消失、参数合格、附件完整"),
        ]
    db.session.add_all([WorkOrderStep(order_id=order.id, step_num=i, title=title, standard=standard) for i, (title, standard) in enumerate(steps, 1)])
    db.session.commit()
    flash(f"已生成工单 {order.order_no}，诊断证据和追溯编号已自动关联。", "success")
    return redirect(url_for("work_order_detail", order_id=order.id))


@app.route("/work-orders/<int:order_id>")
def work_order_detail(order_id):
    return render_template("work_order_detail.html", order=WorkOrder.query.get_or_404(order_id))


@app.route("/work-orders/<int:order_id>/delete", methods=["POST"])
def delete_work_order(order_id):
    order = WorkOrder.query.get_or_404(order_id)
    order_no = order.order_no
    db.session.delete(order)
    db.session.commit()
    flash(f"工单 {order_no} 已删除。", "success")
    return redirect(url_for("work_orders"))


@app.route("/work-orders/<int:order_id>/steps/<int:step_id>", methods=["POST"])
def update_work_order_step(order_id, step_id):
    order = WorkOrder.query.get_or_404(order_id)
    step = WorkOrderStep.query.filter_by(id=step_id, order_id=order.id).first_or_404()
    step.status = "已完成" if request.form.get("completed") == "1" else "待执行"
    step.measured_value = request.form.get("measured_value", "").strip()
    step.operator_note = request.form.get("operator_note", "").strip()
    step.completed_at = datetime.utcnow() if step.status == "已完成" else None
    db.session.flush()
    done = WorkOrderStep.query.filter_by(order_id=order.id, status="已完成").count()
    total = WorkOrderStep.query.filter_by(order_id=order.id).count()
    order.progress = round(done / total * 100) if total else 0
    order.status = "已完成" if order.progress == 100 else ("执行中" if done else "待处理")
    db.session.commit()
    flash("步骤记录已更新，工单进度自动重算。", "success")
    return redirect(url_for("work_order_detail", order_id=order.id))


@app.route("/knowledge-graph")
def knowledge_graph():
    approved_cases = MaintCase.query.filter_by(status="APPROVED").order_by(MaintCase.created_at.desc()).all()
    graph = build_knowledge_graph(approved_cases)
    return render_template("knowledge_graph.html", graph=graph, approved_count=len(approved_cases))


@app.route("/knowledge-graph/cases/<int:case_id>/delete", methods=["POST"])
def delete_knowledge_graph_case(case_id):
    case = MaintCase.query.filter_by(id=case_id, status="APPROVED").first_or_404()
    case_title = case.title
    db.session.delete(case)
    db.session.commit()
    flash(f"审核案例【{case_title}】已删除，知识图谱已同步更新。", "success")
    return redirect(url_for("knowledge_graph"))


@app.route("/upload", methods=["GET", "POST"])
def upload_experience():
    if request.method == "POST":
        filename, _ = save_upload(request.files.get("case_image"))
        db.session.add(MaintCase(
            title=request.form.get("title", "").strip(), device_model=request.form.get("device_model", "").strip(),
            fault_description=request.form.get("fault_description", "").strip(), solution=request.form.get("solution", "").strip(),
            image_path=filename, status="PENDING",
        ))
        db.session.commit()
        flash("案例已进入专家审核队列，通过后将实时加入检索知识底座。", "success")
        return redirect(url_for("upload_experience"))
    return render_template("upload.html")


@app.route("/admin/audit")
def audit_panel():
    status_map = {
        "pending": ("PENDING", "待审", "warning"),
        "approved": ("APPROVED", "通过", "safe"),
        "rejected": ("REJECTED", "驳回", "danger"),
    }
    selected_status = request.args.get("status", "pending")
    if selected_status not in status_map:
        selected_status = "pending"
    db_status, status_label, status_class = status_map[selected_status]
    status_counts = {
        key: MaintCase.query.filter_by(status=value[0]).count()
        for key, value in status_map.items()
    }
    return render_template(
        "audit.html",
        cases=MaintCase.query.filter_by(status=db_status).order_by(MaintCase.created_at.desc()).all(),
        selected_status=selected_status, status_label=status_label, status_class=status_class,
        status_counts=status_counts,
    )


@app.route("/admin/audit/approve/<int:case_id>", methods=["POST"])
def approve_action(case_id):
    case = MaintCase.query.get_or_404(case_id)
    case.status = "APPROVED"
    db.session.commit()
    flash(f"案例【{case.title}】已通过，知识底座实时版本 +1。", "success")
    return redirect(url_for("audit_panel"))


@app.route("/admin/audit/reject/<int:case_id>", methods=["POST"])
def reject_action(case_id):
    case = MaintCase.query.get_or_404(case_id)
    case.status = "REJECTED"
    db.session.commit()
    flash(f"案例【{case.title}】已驳回。", "warning")
    return redirect(url_for("audit_panel"))


@app.route("/admin/audit/review/<int:case_id>", methods=["POST"])
def review_audit_case(case_id):
    case = MaintCase.query.filter(MaintCase.id == case_id, MaintCase.status.in_(["APPROVED", "REJECTED"])).first_or_404()
    case.status = "PENDING"
    db.session.commit()
    flash(f"案例【{case.title}】已打回待审列表。", "success")
    return redirect(url_for("audit_panel", status="pending"))


@app.route("/admin/audit/delete/<int:case_id>", methods=["POST"])
def delete_audit_case(case_id):
    case = MaintCase.query.get_or_404(case_id)
    case_title = case.title
    selected_status = request.form.get("status", "pending")
    if selected_status not in {"pending", "approved", "rejected"}:
        selected_status = "pending"
    db.session.delete(case)
    db.session.commit()
    flash(f"案例【{case_title}】已删除。", "success")
    return redirect(url_for("audit_panel", status=selected_status))


@app.route("/feedback/correct", methods=["POST"])
def submit_correction():
    corrected_output = request.form.get("corrected_output", "").strip()
    if not corrected_output:
        return jsonify({"status": "error", "message": "修正内容不能为空。"}), 400
    db.session.add(LlmLabeledFeedback(
        query_text=request.form.get("query_text", ""), original_output=request.form.get("original_output", ""),
        corrected_output=corrected_output,
    ))
    db.session.commit()
    return jsonify({"status": "success", "message": "专家纠偏样本已进入持续学习语料池。"})


if __name__ == "__main__":
    app.run(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT") or os.getenv("APP_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
