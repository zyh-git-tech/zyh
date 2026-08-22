# 3 分钟演示脚本

## 演示前

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

打开 <http://127.0.0.1:5000/agent>。

## 现场操作

1. 设备型号选择 `ZONTES-250`。
2. 故障现象输入：`冷机启动困难，火花塞发黑，伴随异响，间隙 1.2 mm`。
3. 上传 `tests/fixtures/engine_sample.ppm`。
4. 勾选内置传感器退化基线并运行。
5. 先展示六步 Agent 轨迹，再展示图片候选区域和传感器维护窗口。
6. 指出 `1.2 mm` 超出演示规则 `0.7–0.9 mm`，说明红线结果如何进入诊断证据。
7. 点击生成工单，完成第一步签核，展示进度从 0% 变为 20%。

## 讲解要点

- **算法**：图像服务使用亮度、颜色、梯度和网格候选实现可解释检测；传感器服务使用线性趋势和阈值交点估计维护窗口。
- **工程**：任何工具失败都会保留 failed 节点，Agent 仍能返回文本诊断；每次运行都有 trace id。
- **业务**：诊断不是终点，结果可以进入红线复核、工单签核和专家审核。
- **边界**：当前素材和规则全部合成，在线 Demo 关闭云端模型，不宣称真实工业准确率。

## 备用路径

- 没有图片时仅输入文本，展示本地降级流程。
- 直接打开 `/predictive`，选择内置样例展示趋势图。
- 打开 `/knowledge-graph` 和 `/admin/audit`，展示知识治理闭环。

## 可选后端对比

1. 默认离线：保持 `VECTOR_BACKEND=keyword`、`VISION_BACKEND=heuristic`，无需下载模型。
2. Chroma：安装 `requirements-ml.txt`，设置 `VECTOR_BACKEND=chroma`，打开 `/api/capabilities` 展示检索后端；初始化失败会回到关键词检索。
3. YOLO：设置 `VISION_BACKEND=yolo` 和本地 `YOLO_MODEL_PATH`，重新运行同一张合成图片，对比统一检测框输出；权重不可用时继续使用规则检测。
