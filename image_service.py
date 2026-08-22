# -*- coding: utf-8 -*-
"""可解释的本地图像检测服务，无需 GPU 或外部模型。"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


class ImageInspectionService:
    """从真实像素中完成质量门控、候选缺陷分割和区域定位。"""

    MAX_SIDE = 720
    GRID_SIZE = 6

    @staticmethod
    def _location_name(row, col):
        vertical = "上部" if row < 2 else ("中部" if row < 4 else "下部")
        horizontal = "左侧" if col < 2 else ("中央" if col < 4 else "右侧")
        return vertical + horizontal

    @staticmethod
    def _draw_label(draw, xy, text, color):
        font = ImageFont.load_default()
        left, top = xy
        box = draw.textbbox((left, top), text, font=font)
        draw.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill=color)
        draw.text((left, top), text, fill="white", font=font)

    def analyze(self, image_path):
        path = Path(image_path)
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            original_size = image.size
            image.thumbnail((self.MAX_SIDE, self.MAX_SIDE))

        pixels = np.asarray(image, dtype=np.float32)
        gray = pixels.mean(axis=2)
        red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        brightness = float(gray.mean())
        contrast = float(gray.std())
        dark_mask = gray < 62
        bright_mask = gray > 218
        oil_mask = (red > green * 1.07) & (green > blue * 1.05) & (gray < 165)
        rust_mask = (red > 92) & (red > green * 1.22) & (green > blue * 1.05) & (gray < 190)

        gx = np.zeros_like(gray)
        gy = np.zeros_like(gray)
        gx[:, 1:] = np.abs(np.diff(gray, axis=1))
        gy[1:, :] = np.abs(np.diff(gray, axis=0))
        gradient = (gx + gy) / 2
        texture = float(gradient.mean())
        sharpness = float(np.percentile(gradient, 90))
        texture_mask = gradient > max(24.0, float(np.percentile(gradient, 78)))

        dark_ratio = float(dark_mask.mean())
        bright_ratio = float(bright_mask.mean())
        oil_ratio = float(oil_mask.mean())
        rust_ratio = float(rust_mask.mean())
        exposure_penalty = abs(brightness - 128) / 128 * 34 + (dark_ratio + bright_ratio) * 24
        resolution_score = min(100.0, min(original_size) / 7.2)
        sharpness_score = min(100.0, sharpness * 3.2)
        quality_score = round(max(18, min(99, resolution_score * 0.35 + sharpness_score * 0.4 + (100 - exposure_penalty) * 0.25)))
        quality_status = "合格" if quality_score >= 60 else ("可分析" if quality_score >= 42 else "建议补拍")

        anomaly = (
            dark_mask.astype(np.float32) * 0.38
            + oil_mask.astype(np.float32) * 0.30
            + rust_mask.astype(np.float32) * 0.42
            + texture_mask.astype(np.float32) * 0.20
        )
        height, width = gray.shape
        candidates = []
        for row in range(self.GRID_SIZE):
            y1, y2 = height * row // self.GRID_SIZE, height * (row + 1) // self.GRID_SIZE
            for col in range(self.GRID_SIZE):
                x1, x2 = width * col // self.GRID_SIZE, width * (col + 1) // self.GRID_SIZE
                region_score = float(anomaly[y1:y2, x1:x2].mean())
                if region_score >= 0.16:
                    candidates.append((region_score, row, col, (x1, y1, x2, y2)))
        candidates.sort(reverse=True)

        detections = []
        used_cells = set()
        for region_score, row, col, box in candidates:
            if any(abs(row - old_row) <= 1 and abs(col - old_col) <= 1 for old_row, old_col in used_cells):
                continue
            x1, y1, x2, y2 = box
            region = np.s_[y1:y2, x1:x2]
            signals = {
                "积碳/热损伤候选": float(dark_mask[region].mean()) * 1.05,
                "油液附着候选": float(oil_mask[region].mean()) * 1.25,
                "锈蚀/氧化候选": float(rust_mask[region].mean()) * 1.35,
                "划痕/粗糙磨损候选": float(texture_mask[region].mean()) * 0.72,
            }
            label, signal = max(signals.items(), key=lambda item: item[1])
            confidence = min(0.94, 0.48 + region_score * 0.8 + signal * 0.35)
            detections.append({
                "label": label,
                "location": self._location_name(row, col),
                "confidence": round(confidence, 2),
                "area_ratio": round((x2 - x1) * (y2 - y1) / (width * height) * 100, 1),
                "box": [round(x1 / width, 3), round(y1 / height, 3), round(x2 / width, 3), round(y2 / height, 3)],
            })
            used_cells.add((row, col))
            if len(detections) == 3:
                break

        findings = []
        if dark_ratio >= 0.30 and contrast >= 38:
            findings.append("深色沉积区域占比较高，存在积碳、烧蚀或油泥附着线索")
        elif dark_ratio >= 0.18:
            findings.append("检测到局部深色异常区域，建议复核表面沉积与热损伤")
        if oil_ratio >= 0.10:
            findings.append("棕黄色油性像素特征明显，存在渗油或润滑油污染线索")
        if rust_ratio >= 0.06:
            findings.append("红棕色氧化特征集中，建议复核锈蚀和高温变色")
        if texture >= 24:
            findings.append("高频纹理密集，可能存在划痕、裂纹边缘或粗糙磨损")
        elif texture >= 15:
            findings.append("表面纹理波动偏高，建议近距离检查磨损边界")
        if bright_ratio >= 0.24 and contrast >= 48:
            findings.append("高亮反光区域较多，液体附着或金属裸露需人工复核")
        if not findings:
            findings.append("未发现强异常像素模式，建议结合故障现象和实测参数复核")

        risk_score = 18 + min(34, dark_ratio * 92) + min(26, oil_ratio * 120) + min(18, rust_ratio * 120) + min(18, max(0, texture - 12) * 0.8)
        risk_score = round(min(96, risk_score))
        confidence = min(0.94, 0.48 + contrast / 360 + min(texture, 35) / 260 + quality_score / 900)
        if quality_score < 42:
            confidence = min(confidence, 0.62)

        overlay = image.convert("RGBA")
        tint = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
        tint_pixels = np.asarray(tint).copy()
        tint_pixels[anomaly >= 0.38] = [232, 74, 76, 78]
        tint = Image.fromarray(tint_pixels, mode="RGBA")
        overlay = Image.alpha_composite(overlay, tint)
        draw = ImageDraw.Draw(overlay)
        colors = [(225, 64, 69, 255), (233, 147, 23, 255), (22, 119, 255, 255)]
        for index, detection in enumerate(detections):
            x1, y1, x2, y2 = detection["box"]
            box = (int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height))
            color = colors[index]
            draw.rectangle(box, outline=color, width=max(2, width // 240))
            self._draw_label(draw, (box[0] + 4, box[1] + 4), f"R{index + 1} {detection['confidence']:.0%}", color)
        overlay_path = path.with_name(path.stem + "_analysis.png")
        overlay.convert("RGB").save(overlay_path, "PNG", optimize=True)

        summary = "；".join(findings)
        return {
            "summary": summary,
            "findings": findings,
            "detections": detections,
            "risk_score": risk_score,
            "confidence": round(confidence, 2),
            "quality_score": quality_score,
            "quality_status": quality_status,
            "overlay_filename": overlay_path.name,
            "pipeline": ["EXIF 方向校正", "拍摄质量门控", "颜色/纹理分割", "网格候选定位", "多模态证据融合"],
            "metrics": {
                "brightness": round(brightness, 1),
                "contrast": round(contrast, 1),
                "dark_ratio": round(dark_ratio * 100, 1),
                "oil_ratio": round(oil_ratio * 100, 1),
                "rust_ratio": round(rust_ratio * 100, 1),
                "texture": round(texture, 1),
                "sharpness": round(sharpness, 1),
                "width": original_size[0],
                "height": original_size[1],
            },
        }
