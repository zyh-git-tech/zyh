# 工擎智维：工业设备多模态智能检修平台

> **English summary:** Gongjing Zhiwei is a local-first Flask demo for multimodal equipment inspection. It combines image inspection, sensor trend analysis, retrieval, rule checks, explainable diagnosis, knowledge graphs, and work-order execution in one traceable workflow.

工擎智维是一个本地优先的工业设备检修演示平台。它把故障图片、文本现象、传感器 CSV、合成检修知识、参数红线和电子工单串成一条可追溯的数字线程，适合课程设计、技术展示和本地原型验证。

本项目使用合成演示知识和演示参数规则，不代表任何厂商的真实维修规范，也不替代现场安全流程、设备手册或专业人员判断。

## 功能

- **多模态诊断**：从图片提取亮度、沉积比例、纹理和风险特征。
- **本地 Agent 工作台**：编排图片分析、传感器趋势、知识检索、红线校验、融合诊断和工单草稿。
- **可解释检索**：返回匹配证据、命中词、风险等级和原因链。
- **预测性维护**：分析温度、振动、压力时序，估计风险窗口。
- **参数红线复核**：将演示规则转为机器可执行的范围检查。
- **知识图谱**：展示现象、原因、检测、标准、处置和案例之间的关系。
- **闭环工单**：从诊断或预测结果生成工单，支持步骤签核和进度追踪。
- **离线优先**：未配置云端模型时，系统自动使用本地确定性诊断。

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

浏览器访问 <http://127.0.0.1:5000>。

首次访问会自动创建 SQLite 数据库和演示设备数据。数据库、上传文件和运行日志均为本地运行产物，不会作为公开仓库内容提交。

## Agent 演示

打开 <http://127.0.0.1:5000/agent>，输入故障现象，可选上传图片和传感器 CSV，也可以勾选内置退化基线。一次运行会依次执行：

```text
图片分析 -> 传感器趋势 -> 知识检索 -> 参数红线 -> 融合诊断 -> 工单草稿
```

传感器 CSV 需要包含以下四列：

```csv
hour,temperature,vibration,pressure
0,68.0,2.2,310
4,69.4,2.5,304
8,71.2,2.8,297
12,72.8,3.1,291
```

完整样例位于 `static/samples/final_demo_sensor.csv`。

## 可选云端模型

复制 `.env.example` 中的变量到当前终端或部署环境。默认不需要密钥即可运行本地模式。

```powershell
$env:APP_SECRET_KEY="replace-with-a-random-value"
$env:LLM_API_KEY="your-api-key"
$env:LLM_API_URL="https://api.openai.com/v1/chat/completions"
$env:LLM_MODEL="gpt-4o-mini"
.\.venv\Scripts\python.exe app.py
```

应用配置：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `APP_SECRET_KEY` | 每次启动随机生成 | Flask 会话签名 |
| `DATABASE_URL` | `sqlite:///maintenance.db` | 数据库连接 |
| `APP_HOST` | `127.0.0.1` | 监听地址 |
| `APP_PORT` | `5000` | 监听端口 |
| `FLASK_DEBUG` | `0` | 本地调试开关 |
| `LLM_API_KEY` | 空 | 可选云端模型密钥 |
| `LLM_API_URL` | OpenAI 兼容地址 | 模型接口地址 |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称 |

## 页面入口

| 页面 | 地址 |
| --- | --- |
| 运营驾驶舱 | `/` |
| Agent 工作台 | `/agent` |
| 多模态诊断 | `/diagnosis` |
| 预测维护 | `/predictive` |
| 参数红线 | `/compliance` |
| 知识图谱 | `/knowledge-graph` |
| 工单中心 | `/work-orders` |
| 专家治理 | `/admin/audit` |

## 测试

```powershell
.\.venv\Scripts\python.exe smoke_test.py
```

测试使用内存数据库和 `tests/fixtures/engine_sample.ppm` 合成图片，不需要网络或云端模型密钥。

## 项目结构

```text
app.py                         Flask 页面和 API
agent_service.py               本地 Agent 工具编排
image_service.py               图片特征分析
predictive_service.py          传感器趋势和维护窗口
vector_service.py              本地检索和可选模型调用
data/demo_knowledge_base.json  公开的合成演示知识库
templates/                     Jinja 页面
static/                       CSS、样例 CSV 和静态资源
tests/fixtures/                合成测试素材
smoke_test.py                  端到端冒烟测试
```

## 开发与贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请阅读 [SECURITY.md](SECURITY.md)。行为规范见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## GitHub 发布

```bash
git clone YOUR_REPOSITORY_URL
cd YOUR_REPOSITORY_NAME
git checkout -b feature/your-change
git add .
git commit -m "describe your change"
git push -u origin feature/your-change
```

## 许可证

代码以 [MIT License](LICENSE) 发布。合成演示数据仅用于本项目的运行和测试。
