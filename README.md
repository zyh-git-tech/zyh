# 工擎智维：工业设备多模态智能检修平台

[![CI](https://github.com/zyh-git-tech/zyh/actions/workflows/ci.yml/badge.svg)](https://github.com/zyh-git-tech/zyh/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Demo](https://img.shields.io/badge/Demo-local--first-orange)](https://github.com/zyh-git-tech/zyh)

> **English summary:** Gongjing Zhiwei is a local-first Flask portfolio demo for multimodal equipment inspection. It combines image inspection, sensor trend analysis, retrieval, executable rule checks, explainable diagnosis, knowledge graphs, and work-order execution in one traceable workflow.

## 项目定位

工擎智维是一个面向工业设备检修的本地优先演示平台。它把故障图片、文本现象、传感器 CSV、合成检修知识、参数红线和电子工单串成一条可追溯的数字线程。

这个项目重点展示三类能力：

- **AI/算法**：图像质量门控、颜色/纹理候选检测、传感器趋势拟合、关键词检索和多模态证据融合。
- **后端工程**：Flask 路由、SQLAlchemy 数据模型、可追溯 Agent 轨迹、错误降级、健康检查和 CI 质量门禁。
- **业务落地**：预测维护、参数红线、知识图谱、专家审核和诊断到工单的闭环流程。

所有知识、规则、图片和 CSV 均为合成演示素材，不代表任何真实厂商规范，也不替代现场安全流程、设备手册或专业人员判断。

## 5 分钟演示

1. 启动应用并打开 <http://127.0.0.1:5000/>，先使用管理员账号登录。
2. 输入“冷机启动困难，火花塞发黑，伴随异响”，上传 `tests/fixtures/engine_sample.ppm`。
3. 勾选内置传感器退化基线，运行 Agent。
4. 查看七步工具轨迹、图片候选区域、趋势风险、检索证据和参数红线。
5. 点击生成工单，完成第一步签核，再到工单中心查看进度。登录后所有页面、API 和工作台功能均可用。

完整讲解稿见 [`docs/demo-script.md`](docs/demo-script.md)，系统数据流见 [`docs/architecture.md`](docs/architecture.md)。

## 功能

- 多模态诊断：从图片提取亮度、沉积比例、纹理和风险特征。
- LangGraph Agent 工作台：把图片分析、传感器趋势、知识检索和红线校验作为受限工具，按输入动态选择调用顺序；无云端密钥时回退本地策略路由。
- 可解释检索：返回匹配证据、命中词、来源和分数。
- 预测性维护：分析温度、振动、压力时序，估计风险窗口。
- 参数红线复核：将演示规则转为机器可执行的范围检查。
- 知识图谱：展示现象、原因、检测、标准、处置和案例关系。
- 闭环工单：从诊断或预测结果生成工单，支持步骤签核和进度追踪。
- 离线优先：未配置云端模型时自动使用本地确定性诊断。
- 可选增强：Chroma 向量检索、Ultralytics YOLO 检测器和可解释预测维护特征，均有自动回退。

## 工程亮点

- 每次 Agent 运行生成 trace id，并保存工具步骤、输入摘要、输出摘要和耗时。
- 图片、传感器、检索、红线和融合诊断任一节点失败时保留轨迹并继续可用流程。
- `/healthz` 提供数据库探活和版本信息，可直接接入 Render 健康检查。
- `evaluate_demo.py` 提供合成基准，当前基线包含风险准确率、原因 Macro-F1 和降级通过率。
- GitHub Actions 在 Python 3.11/3.12 上执行编译、测试、评测和敏感文件审计。

## 快速开始

要求：Python 3.10 或更高版本。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

### Linux/macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

浏览器访问 <http://127.0.0.1:5000>。首次访问会自动创建 SQLite 数据库和演示设备数据。

### 登录配置

应用默认对所有业务页面和 API 启用单账号会话保护；`/login`、`/logout`、`/healthz` 和静态资源保持公开。开发环境可使用明文便捷变量，生产环境应使用哈希：

```powershell
$env:APP_SECRET_KEY="随机长字符串"
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="仅限本地开发"
# 生产环境改用 Werkzeug 生成的哈希：
# python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('CHANGE_ME'))"
$env:ADMIN_PASSWORD_HASH="生成的密码哈希"
```

未登录访问页面会跳转到登录页，成功后自动回到原始地址；`/healthz` 可供平台探活且不要求登录。

### 生产 WSGI

```bash
gunicorn --workers 1 --timeout 120 --bind 0.0.0.0:${PORT:-5000} app:app
```

## Agent 输入格式

传感器 CSV 必须包含以下四列：

```csv
hour,temperature,vibration,pressure
0,68.0,2.2,310
4,69.4,2.5,304
8,71.2,2.8,297
12,72.8,3.1,291
```

公开样例位于 `static/samples/final_demo_sensor.csv`，合成图片位于 `tests/fixtures/engine_sample.ppm`。

## 合成评测

```powershell
.\.venv\Scripts\python.exe evaluate_demo.py
.\.venv\Scripts\python.exe evaluate_demo.py --json
```

评测集位于 `data/demo_eval_cases.json`，覆盖文本、图片、传感器、多模态和错误输入降级。它用于验证行为稳定性，不代表真实工业准确率。

## 页面和 API

| 页面或接口 | 地址 |
| --- | --- |
| 运营驾驶舱 | `/` |
| Agent 工作台 | `/agent` |
| 多模态诊断 | `/diagnosis` |
| 预测维护 | `/predictive` |
| 参数红线 | `/compliance` |
| 知识图谱 | `/knowledge-graph` |
| 工单中心 | `/work-orders` |
| 专家治理 | `/admin/audit` |
| 健康检查 | `GET /healthz` |
| 能力探针 | `GET /api/capabilities` |
| 参数检查 API | `POST /api/parameter-check` |

## 可选云端模型

默认不需要密钥即可运行本地模式。复制 `.env.example` 后，在当前 PowerShell 会话中按需配置：

```powershell
$env:LLM_API_KEY="在阿里云控制台生成的新密钥"
$env:LLM_API_URL="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
$env:LLM_MODEL="qwen-plus"
$env:LLM_PROVIDER="qwen"
```

Agent 工作台和多模态诊断会显示“通义千问增强”或“本地确定性模式”。密钥只应通过本机环境变量或部署平台 Secret 注入，不要写入仓库、截图、日志或提交历史。在线 Demo 默认不启用云端模型。

## 可选模型能力

```powershell
python -m pip install -r requirements-ml.txt
$env:VECTOR_BACKEND="chroma"
$env:VISION_BACKEND="auto"
$env:YOLO_MODEL_PATH="C:\models\best.pt"
python app.py
```

Chroma 首次启动会从合成知识库建立本地 collection；YOLO 只有在 Ultralytics 和权重都可用时启用，否则自动回退。能力状态可查看 `GET /api/capabilities`。预测维护输出包含滚动均值、波动率、稳健异常分数、退化因子、RUL 和置信度；这些是合成演示估计，不代表真实设备寿命精度。

## 评测边界

`evaluate_demo.py` 和 `data/demo_eval_cases.json` 用于复现本地行为回归，输出风险准确率、原因 Macro-F1、降级通过率、RUL 方向通过率和视觉回退通过率。仓库没有真实工业缺陷标注集，YOLO 配置、合成预测样例和 RUL 结果仅用于工程接口演示。

主要配置：`APP_SECRET_KEY`、`DATABASE_URL`、`APP_HOST`、`APP_PORT`、`PORT`、`APP_VERSION`、`FLASK_DEBUG`、`LLM_API_KEY`、`LLM_API_URL`、`LLM_MODEL`、`LLM_PROVIDER`、`LLM_TIMEOUT_SECONDS`。

## Render 部署

仓库提供 [`render.yaml`](render.yaml)。部署步骤：

1. 将代码推送到 GitHub，在 Render 选择 **New Blueprint** 并连接仓库。
2. 使用 Gunicorn 启动 Web Service，Render 会通过 `/healthz` 检查服务状态。
3. 在 Render Secret 中配置 `APP_SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD_HASH`；需要云端 Agent 时再配置 `LLM_API_KEY`、`LLM_API_URL`、`LLM_MODEL`。
4. 使用 Render 分配的 HTTPS 地址打开登录页。登录后驾驶舱、Agent、诊断、预测、工单、SOP、合规和知识图谱等功能全部可用。

未配置模型密钥时，Agent 仍运行本地确定性策略；配置密钥后，LangGraph 会让模型自主选择并循环调用四个只读检修工具，最终结果仍通过本地融合层和人工确认工单流程输出。

Render 免费实例可能休眠；SQLite 数据属于实例本地临时数据，适合公开演示，不适合作为生产持久化数据库。生产环境应替换为托管数据库并增加认证、权限隔离、CSRF、防审计和多租户能力。

## 测试和开发

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest --cov=app --cov=agent_service --cov=image_service --cov=predictive_service --cov=standards_service --cov=vector_service
.\.venv\Scripts\python.exe smoke_test.py
.\.venv\Scripts\python.exe -m ruff check .
```

贡献流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，安全问题见 [`SECURITY.md`](SECURITY.md)，行为规范见 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

## 项目结构

```text
app.py                         Flask 页面、API、健康检查和配置
agent_service.py               本地 Agent 工具编排与 trace 轨迹
image_service.py               图像质量门控和候选区域检测
predictive_service.py          CSV 解析、趋势拟合和维护窗口
vector_service.py              合成知识库检索和可选模型调用
standards_service.py           参数红线规则与解释
data/demo_knowledge_base.json  公开合成知识库
data/demo_eval_cases.json      可复现合成评测集
evaluate_demo.py               评测 CLI
templates/                     Jinja 页面
static/                        CSS、样例 CSV 和上传目录
tests/                         合成素材和 pytest 测试
docs/                          架构说明和演示脚本
```

## 许可证

代码以 [MIT License](LICENSE) 发布。合成演示数据仅用于本项目的运行和测试。
