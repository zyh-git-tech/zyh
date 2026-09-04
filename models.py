# -*- coding: utf-8 -*-
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    """登录账号与其私有业务记录。"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

class Equipment(db.Model):
    """
    设备主台账表
    """
    __tablename__ = 'equipments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(50), nullable=False, unique=True)

class SopTemplate(db.Model):
    """
    SOP作业指导书母表
    """
    __tablename__ = 'sop_templates'
    id = db.Column(db.Integer, primary_key=True)
    equipment_model = db.Column(db.String(50), nullable=False)
    maint_level = db.Column(db.String(20), nullable=False)  # 日常检修 / 中修 / 大修
    title = db.Column(db.String(200), nullable=False)

class SopStep(db.Model):
    """
    SOP步骤子表（带合规性强制校验提醒）
    """
    __tablename__ = 'sop_steps'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('sop_templates.id'), nullable=False)
    step_num = db.Column(db.Integer, nullable=False)
    instruction = db.Column(db.Text, nullable=False)
    compliance_warning = db.Column(db.Text, nullable=True)  # 安全防范提醒

class MaintCase(db.Model):
    """
    一线检修案例积累表（专家审批后，可并入 RAG 检索上下文）
    """
    __tablename__ = 'maint_cases'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    device_model = db.Column(db.String(50), nullable=False)
    fault_description = db.Column(db.Text, nullable=False)
    solution = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.String(256), nullable=True)
    status = db.Column(db.String(20), default='PENDING')     # PENDING / APPROVED / REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LlmLabeledFeedback(db.Model):
    """
    用户手动纠正大模型输出结果的标注反馈表
    """
    __tablename__ = 'llm_labeled_feedbacks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    query_text = db.Column(db.Text, nullable=False)
    original_output = db.Column(db.Text, nullable=False)
    corrected_output = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DiagnosisRecord(db.Model):
    """一次可追溯的多模态诊断记录。"""
    __tablename__ = 'diagnosis_records'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    trace_id = db.Column(db.String(32), nullable=False, unique=True, index=True)
    device_model = db.Column(db.String(50), nullable=True)
    query_text = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.String(256), nullable=True)
    image_findings = db.Column(db.Text, nullable=True)
    risk_level = db.Column(db.String(20), nullable=False, default='中风险')
    confidence = db.Column(db.Float, nullable=False, default=0.70)
    answer = db.Column(db.Text, nullable=False)
    sources_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class WorkOrder(db.Model):
    """由诊断一键生成的检修工单。"""
    __tablename__ = 'work_orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    order_no = db.Column(db.String(32), nullable=False, unique=True, index=True)
    diagnosis_id = db.Column(db.Integer, db.ForeignKey('diagnosis_records.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    device_model = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default='P2')
    assignee = db.Column(db.String(50), nullable=False, default='待分配')
    status = db.Column(db.String(20), nullable=False, default='待处理')
    progress = db.Column(db.Integer, nullable=False, default=0)
    planned_hours = db.Column(db.Float, nullable=False, default=2.0)
    estimated_saving = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    diagnosis = db.relationship('DiagnosisRecord', backref=db.backref('work_orders', lazy=True))
    steps = db.relationship(
        'WorkOrderStep', backref='work_order', lazy=True,
        cascade='all, delete-orphan', order_by='WorkOrderStep.step_num'
    )


class WorkOrderStep(db.Model):
    """工单的可执行、可签核步骤。"""
    __tablename__ = 'work_order_steps'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    step_num = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    standard = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='待执行')
    measured_value = db.Column(db.String(100), nullable=True)
    operator_note = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)


class PredictiveAnalysis(db.Model):
    """设备时序健康预测与维护窗口建议。"""
    __tablename__ = 'predictive_analyses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    analysis_no = db.Column(db.String(32), nullable=False, unique=True, index=True)
    device_model = db.Column(db.String(50), nullable=False)
    operating_hours = db.Column(db.Float, nullable=False, default=0)
    health_score = db.Column(db.Integer, nullable=False)
    risk_level = db.Column(db.String(20), nullable=False)
    predicted_hours = db.Column(db.Float, nullable=True)
    maintenance_window = db.Column(db.String(100), nullable=False)
    sensor_json = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    diagnosis_id = db.Column(db.Integer, db.ForeignKey('diagnosis_records.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    diagnosis = db.relationship('DiagnosisRecord', backref=db.backref('predictive_analyses', lazy=True))


class AgentRun(db.Model):
    """可展示、可追溯的一次 Agent 工具编排运行记录。"""
    __tablename__ = 'agent_runs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    trace_id = db.Column(db.String(32), nullable=False, unique=True, index=True)
    input_summary = db.Column(db.Text, nullable=False, default='')
    steps_json = db.Column(db.Text, nullable=False, default='[]')
    result_json = db.Column(db.Text, nullable=False, default='{}')
    diagnosis_id = db.Column(db.Integer, db.ForeignKey('diagnosis_records.id'), nullable=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    diagnosis = db.relationship('DiagnosisRecord', backref=db.backref('agent_runs', lazy=True))
    work_order = db.relationship('WorkOrder', backref=db.backref('agent_runs', lazy=True))
