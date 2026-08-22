from image_service import ImageInspectionService
from yolo_service import YoloInspectionService


def test_yolo_missing_weight_is_available_as_fallback(monkeypatch):
    monkeypatch.setenv("VISION_BACKEND", "yolo")
    monkeypatch.setenv("YOLO_MODEL_PATH", "tests/fixtures/missing.pt")
    service = ImageInspectionService()
    assert service.backend_name == "heuristic"
    assert service.backend_error


def test_yolo_confidence_has_safe_default_for_bad_config():
    service = YoloInspectionService("", "bad-value")
    assert service.confidence == 0.25
    assert not service.available
