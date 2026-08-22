# YOLO 可选检测器

项目默认使用可解释的 Pillow/NumPy 规则检测。安装 `requirements-ml.txt` 并提供权重后，`VISION_BACKEND=auto` 会自动启用 Ultralytics YOLO；缺少依赖或权重时回退规则路径。

## 数据集布局

```text
datasets/engine-defects/
  images/train/
  images/val/
  labels/train/
  labels/val/
  data.yaml
```

`data.yaml` 示例：

```yaml
path: datasets/engine-defects
train: images/train
val: images/val
names: [oil_leak, carbon, rust, wear]
```

训练命令：

```powershell
python -m pip install -r requirements-ml.txt
yolo detect train data=datasets/engine-defects/data.yaml model=yolo11n.pt epochs=50 imgsz=640
```

将训练得到的 `best.pt` 放在本机并设置 `YOLO_MODEL_PATH`。权重、真实设备图片和下载缓存不提交到 Git。本仓库只包含合成接口样例，没有真实工业标注集，因此不宣称工业准确率。
