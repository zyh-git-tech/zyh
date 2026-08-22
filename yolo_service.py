# -*- coding: utf-8 -*-
"""Optional Ultralytics YOLO adapter with a deterministic availability fallback."""
from pathlib import Path


class YoloInspectionService:
    """Translate Ultralytics detections into the application's stable schema."""

    def __init__(self, model_path="", confidence=0.25):
        self.model_path = str(model_path or "").strip()
        try:
            self.confidence = max(0.01, min(0.99, float(confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.25
        self.model = None
        self.error = ""
        self._load()

    def _load(self):
        if not self.model_path:
            self.error = "YOLO_MODEL_PATH 未配置"
            return
        if not Path(self.model_path).is_file():
            self.error = "YOLO 权重文件不存在"
            return
        try:
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
        except Exception as exc:  # optional dependency/model failures are a normal fallback
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def available(self):
        return self.model is not None

    def analyze(self, image_path):
        if not self.available:
            return None
        results = self.model.predict(source=str(image_path), conf=self.confidence, verbose=False)
        if not results:
            return []
        result = results[0]
        width, height = result.orig_shape[1], result.orig_shape[0]
        names = result.names or {}
        detections = []
        for box in result.boxes:
            coords = [float(value) for value in box.xyxy[0].tolist()]
            x1, y1, x2, y2 = coords
            confidence = float(box.conf[0].item())
            class_id = int(box.cls[0].item())
            label = names.get(class_id, str(class_id)) if isinstance(names, dict) else str(class_id)
            area_ratio = max(0.0, (x2 - x1) * (y2 - y1) / max(1.0, width * height) * 100)
            center_x, center_y = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
            vertical = "上部" if center_y < 1 / 3 else ("中部" if center_y < 2 / 3 else "下部")
            horizontal = "左侧" if center_x < 1 / 3 else ("中央" if center_x < 2 / 3 else "右侧")
            detections.append({
                "label": label,
                "confidence": round(confidence, 2),
                "box": [round(x1 / width, 3), round(y1 / height, 3), round(x2 / width, 3), round(y2 / height, 3)],
                "area_ratio": round(area_ratio, 1),
                "location": vertical + horizontal,
            })
        return detections
