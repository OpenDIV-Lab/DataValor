"""阶段 7：按模态执行 DataEval 指标并生成统一质量报告。

运行：``PYTHONPATH=src python examples/11_stage7_multimodal_evaluation.py``
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_eval import (
    AudioClippingRateMetric,
    AudioMetadataQualityMetric,
    AudioSilenceRateMetric,
    CompositeEvaluator,
    EvaluationRequest,
    ImageAspectRatioConsistencyMetric,
    ImageMetadataQualityMetric,
    ImagePixelValidityMetric,
    MultimodalAlignmentMetric,
    MultimodalPackageIntegrityMetric,
    TabularLabelBalanceMetric,
    TabularNumericStatisticsMetric,
    TabularOutlierRateMetric,
    TabularSchemaConsistencyMetric,
    TextLengthQualityMetric,
    TextLexicalDiversityMetric,
    TextRepetitionRateMetric,
    VideoBasicCleanliness,
    VideoFormatProbe,
    VideoOpticalFlowMotionScore,
    VideoPrivacyCVScore,
    VideoSceneSegmentationScore,
    VideoTemporalSSIMConsistency,
)

ROOT = Path(__file__).resolve().parents[1]


def _product(modality: str) -> DataProduct:
    return DataProduct(
        f"stage7-{modality}",
        f"{modality} evaluation fixture",
        DataReference(f"memory://stage7/{modality}", "json"),
        "stage7-owner",
        tags=(modality, "evaluation"),
    )


def _run(modality, records, metrics):
    product = _product(modality)
    request = EvaluationRequest(options={"records": records})
    report = CompositeEvaluator().evaluate(product, request, metrics, RunContext(f"stage7-{modality}"))
    return {
        "product_id": report.product_id,
        "summary": report.summary,
        "metrics": [asdict(metric) for metric in report.metrics],
        "diagnostics": report.diagnostics,
    }


def main():
    tabular = _run(
        "tabular",
        [
            {"value": 1, "label": "A"},
            {"value": 2, "label": "A"},
            {"value": 3, "label": "B"},
            {"value": 80, "label": "B"},
        ],
        [
            TabularSchemaConsistencyMetric(required_fields=("value", "label"), field_types={"value": "number", "label": "string"}),
            TabularNumericStatisticsMetric("value"),
            TabularOutlierRateMetric("value"),
            TabularLabelBalanceMetric("label"),
        ],
    )
    text = _run(
        "text",
        [{"text": "Data quality enables reliable valuation."}, {"text": "quality quality evidence"}],
        [TextLexicalDiversityMetric(), TextLengthQualityMetric(max_tokens=10), TextRepetitionRateMetric()],
    )
    image = _run(
        "image",
        [{"width": 640, "height": 480, "format": "png", "channels": 3, "pixels": [0, 0.5, 255]}, {"width": 320, "height": 240, "format": "png", "channels": 3, "pixels": [0, 256]}],
        [ImageMetadataQualityMetric(allowed_formats=("png",), expected_channels=(3,)), ImageAspectRatioConsistencyMetric(tolerance=0.1), ImagePixelValidityMetric()],
    )
    audio = _run(
        "audio",
        [{"duration": 3, "sample_rate": 16000, "channels": 1, "samples": [0, 0.2, 1]}, {"duration": 0, "sample_rate": 8000, "channels": 2, "samples": [0, 0]}],
        [AudioMetadataQualityMetric(), AudioClippingRateMetric(), AudioSilenceRateMetric()],
    )
    video = _run(
        "video",
        [{"duration": 5, "fps": 25, "width": 1280, "height": 720, "frames_data": [[0, 0], [1, 0], [1, 2]], "scene_boundaries": [0, 2], "temporal_ssim": [0.92, 0.88], "face_count": 2, "blurred_private_count": 1}],
        [VideoFormatProbe(), VideoBasicCleanliness(), VideoOpticalFlowMotionScore(), VideoSceneSegmentationScore(), VideoTemporalSSIMConsistency(), VideoPrivacyCVScore()],
    )
    multimodal = _run(
        "multimodal",
        [{"id": "r1", "text": "hello", "image": "img-1", "text_timestamp": 1.0, "image_timestamp": 1.3}, {"id": "r2", "text": "world", "image": "img-2", "text_timestamp": 2.0, "image_timestamp": 5.0}],
        [MultimodalPackageIntegrityMetric(required_modalities=("text", "image")), MultimodalAlignmentMetric(tolerance=1.0)],
    )
    output = {"status": "succeeded", "modalities": {"tabular": tabular, "text": text, "image": image, "audio": audio, "video": video, "multimodal": multimodal}}
    out_dir = ROOT / "outputs/stage7-evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": output["status"], "output": str(out_dir / "result.json"), "modalities": {name: data["summary"] for name, data in output["modalities"].items()}}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
