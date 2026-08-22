# 贡献指南

感谢你为工擎智维提交改进。

## 开发环境

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

## 提交前检查

```bash
python -m compileall -q app.py agent_service.py image_service.py knowledge_graph_service.py models.py predictive_service.py standards_service.py vector_service.py
python smoke_test.py
```

请保持变更聚焦，新增行为同时更新测试和 README。不要提交数据库、上传文件、日志、密钥、原始资料或本地构建目录。

## Pull Request

请说明变更动机、主要实现、测试命令和已知限制。涉及界面变更时附上复现步骤或截图描述。
