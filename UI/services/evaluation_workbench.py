"""Workbench adapter for DataValor's modality-specific quality metrics."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from datavalor.core import DataProduct, RunContext
from datavalor.data_eval import (
    AudioClippingRateMetric,
    AudioMetadataQualityMetric,
    AudioSilenceRateMetric,
    CompletenessMetric,
    CompositeEvaluator,
    DuplicateRateMetric,
    EvaluationRequest,
    FieldValidityMetric,
    GroupCompletenessParityMetric,
    ImageAspectRatioConsistencyMetric,
    ImageMetadataQualityMetric,
    ImagePixelValidityMetric,
    LabelConflictMetric,
    MultimodalAlignmentMetric,
    MultimodalPackageIntegrityMetric,
    NumericRangeComplianceMetric,
    TabularLabelBalanceMetric,
    TabularNumericStatisticsMetric,
    TabularOutlierRateMetric,
    TabularSchemaConsistencyMetric,
    TextLengthQualityMetric,
    TextLexicalDiversityMetric,
    TextReadabilityMetric,
    TextRepetitionRateMetric,
    VideoBasicCleanliness,
    VideoFormatProbe,
    VideoMotionMetadata,
    VideoOpticalFlowMotionScore,
    VideoPrivacyCVScore,
    VideoSceneSegmentationScore,
    VideoTemporalSSIMConsistency,
)


def _field(key: str, label: str, kind: str, default: Any, **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": kind, "default": default, **extra}


_METRIC_INFO: dict[str, tuple[str, str, str]] = {
    "basic.completeness": ("单元格完整性", "非空字段单元格占比", "higher_is_better"),
    "basic.duplicate_rate": ("重复记录率", "按规范化记录哈希识别重复项", "lower_is_better"),
    "basic.field_validity": ("字段有效性", "检查必需字段与声明类型", "higher_is_better"),
    "tabular.schema_consistency": ("模式一致性", "记录满足字段模式的比例", "higher_is_better"),
    "tabular.numeric_statistics": ("数值字段有效性", "数值覆盖率并报告描述统计", "higher_is_better"),
    "tabular.outlier_rate": ("IQR 异常值率", "使用 Tukey fences 识别稳健异常值", "lower_is_better"),
    "tabular.label_balance": ("标签均衡度", "标签分布的归一化信息熵", "higher_is_better"),
    "advanced.numeric_range_compliance": ("数值范围合规率", "字段落入业务有效范围的比例", "higher_is_better"),
    "advanced.label_conflict": ("标签冲突率", "同一实体出现互斥标签的比例", "lower_is_better"),
    "advanced.group_completeness_parity": ("分组完整性公平度", "不同群体间完整性的最弱组差异", "higher_is_better"),
    "text.length_quality": ("文本长度合规率", "文本 token 数处于指定区间的比例", "higher_is_better"),
    "text.lexical_diversity": ("词汇多样性", "平滑 type-token ratio 与记录覆盖率", "higher_is_better"),
    "text.repetition_rate": ("文本重复率", "记录内重复 token 的平均比例", "lower_is_better"),
    "advanced.text_readability": ("文本可读性", "基于句长与词长的轻量可读性评分", "higher_is_better"),
    "image.metadata_quality": ("图像元数据质量", "尺寸、通道与格式约束满足率", "higher_is_better"),
    "image.aspect_ratio_consistency": ("宽高比一致性", "相对中位宽高比的稳定程度", "higher_is_better"),
    "image.pixel_validity": ("像素有效性", "像素值有限且位于合法范围的比例", "higher_is_better"),
    "audio.metadata_quality": ("音频元数据质量", "时长、采样率与声道约束满足率", "higher_is_better"),
    "audio.clipping_rate": ("削波率", "超过幅值阈值的 PCM 样本比例", "lower_is_better"),
    "audio.silence_rate": ("静音率", "低于静音阈值的样本比例", "lower_is_better"),
    "video.format_probe": ("视频格式探测", "时长、分辨率与帧率约束满足率", "higher_is_better"),
    "video.motion_metadata": ("运动元数据", "基于已登记运动分数的描述指标", "descriptive"),
    "video.optical_flow_motion": ("光流运动强度", "基于采样帧变化的运动质量信号", "descriptive"),
    "video.scene_segmentation": ("场景分段质量", "场景边界覆盖和分段统计", "descriptive"),
    "video.temporal_ssim": ("时序 SSIM 一致性", "相邻帧结构相似性的时序稳定性", "target_is_best"),
    "video.privacy_cv": ("视觉隐私处理率", "人脸和车牌等隐私对象的处理覆盖", "higher_is_better"),
    "video.basic_cleanliness": ("视频基础洁净度", "格式探测与损坏标记的组合检查", "higher_is_better"),
    "multimodal.package_integrity": ("多模态包完整性", "每条记录具备必需模态的比例", "higher_is_better"),
    "multimodal.alignment": ("跨模态时间对齐", "模态时间戳处于容差内的比例", "higher_is_better"),
}

_METRIC_CLASSES = {
    "basic.completeness": "CompletenessMetric",
    "basic.duplicate_rate": "DuplicateRateMetric",
    "basic.field_validity": "FieldValidityMetric",
    "tabular.schema_consistency": "TabularSchemaConsistencyMetric",
    "tabular.numeric_statistics": "TabularNumericStatisticsMetric",
    "tabular.outlier_rate": "TabularOutlierRateMetric",
    "tabular.label_balance": "TabularLabelBalanceMetric",
    "advanced.numeric_range_compliance": "NumericRangeComplianceMetric",
    "advanced.label_conflict": "LabelConflictMetric",
    "advanced.group_completeness_parity": "GroupCompletenessParityMetric",
    "text.length_quality": "TextLengthQualityMetric",
    "text.lexical_diversity": "TextLexicalDiversityMetric",
    "text.repetition_rate": "TextRepetitionRateMetric",
    "advanced.text_readability": "TextReadabilityMetric",
    "image.metadata_quality": "ImageMetadataQualityMetric",
    "image.aspect_ratio_consistency": "ImageAspectRatioConsistencyMetric",
    "image.pixel_validity": "ImagePixelValidityMetric",
    "audio.metadata_quality": "AudioMetadataQualityMetric",
    "audio.clipping_rate": "AudioClippingRateMetric",
    "audio.silence_rate": "AudioSilenceRateMetric",
    "video.format_probe": "VideoFormatProbe",
    "video.motion_metadata": "VideoMotionMetadata",
    "video.optical_flow_motion": "VideoOpticalFlowMotionScore",
    "video.scene_segmentation": "VideoSceneSegmentationScore",
    "video.temporal_ssim": "VideoTemporalSSIMConsistency",
    "video.privacy_cv": "VideoPrivacyCVScore",
    "video.basic_cleanliness": "VideoBasicCleanliness",
    "multimodal.package_integrity": "MultimodalPackageIntegrityMetric",
    "multimodal.alignment": "MultimodalAlignmentMetric",
}


def _metric(name: str, default: bool = False) -> dict[str, Any]:
    label, description, direction = _METRIC_INFO[name]
    return {
        "name": name,
        "label": label,
        "description": description,
        "direction": direction,
        "default": default,
        "implementation": f"datavalor.data_eval.{_METRIC_CLASSES[name]}",
    }


_COMMON_FIELDS = [
    _field("required_fields", "必需字段", "list", []),
    _field("field_types", "字段类型约束", "json", {}),
]

_MODALITIES: dict[str, dict[str, Any]] = {
    "tabular": {
        "label": "表格数据",
        "description": "结构、数值分布、异常值、标签与群体质量",
        "expected_fields": "业务字段；数值列和标签列可单独指定",
        "fields": _COMMON_FIELDS + [
            _field("numeric_field", "数值分析字段", "text", "value"),
            _field("label_field", "标签字段", "text", "label"),
            _field("id_field", "实体 ID 字段", "text", "id"),
            _field("group_field", "分组字段", "text", "group"),
            _field("outlier_whisker", "IQR whisker", "number", 1.5, min=0.01),
            _field("range_minimum", "有效范围下限", "number", 0),
            _field("range_maximum", "有效范围上限", "number", 1),
        ],
        "metrics": [
            _metric("basic.completeness", True), _metric("basic.duplicate_rate", True),
            _metric("basic.field_validity", True), _metric("tabular.schema_consistency"),
            _metric("tabular.numeric_statistics"), _metric("tabular.outlier_rate"),
            _metric("tabular.label_balance"), _metric("advanced.numeric_range_compliance"),
            _metric("advanced.label_conflict"), _metric("advanced.group_completeness_parity"),
        ],
    },
    "text": {
        "label": "文本",
        "description": "长度、词汇多样性、重复和可读性",
        "expected_fields": "每条记录包含可配置的文本字段",
        "fields": [
            _field("text_field", "文本字段", "text", "text"),
            _field("min_tokens", "最少 token 数", "number", 1, min=0),
            _field("max_tokens", "最多 token 数", "number", 512, min=1),
        ],
        "metrics": [
            _metric("basic.completeness"), _metric("basic.duplicate_rate"),
            _metric("text.length_quality", True), _metric("text.lexical_diversity", True),
            _metric("text.repetition_rate", True), _metric("advanced.text_readability"),
        ],
    },
    "image": {
        "label": "图像",
        "description": "图像元数据、几何一致性和像素合法性",
        "expected_fields": "width、height、channels、format，可选 pixels",
        "fields": [
            _field("min_width", "最小宽度", "number", 1, min=1),
            _field("min_height", "最小高度", "number", 1, min=1),
            _field("allowed_formats", "允许格式", "list", ["jpg", "jpeg", "png", "webp"]),
            _field("expected_channels", "允许通道数", "number_list", [1, 3, 4]),
            _field("aspect_tolerance", "宽高比相对容差", "number", 0.05, min=0),
        ],
        "metrics": [
            _metric("image.metadata_quality", True), _metric("image.aspect_ratio_consistency", True),
            _metric("image.pixel_validity"),
        ],
    },
    "audio": {
        "label": "音频",
        "description": "音频元数据、削波和静音区间",
        "expected_fields": "duration、sample_rate、channels，可选 samples",
        "fields": [
            _field("min_duration", "最短时长（秒）", "number", 0.1, min=0),
            _field("sample_rates", "允许采样率", "number_list", [8000, 16000, 44100, 48000]),
            _field("channels", "允许声道数", "number_list", [1, 2]),
            _field("samples_field", "PCM 样本字段", "text", "samples"),
            _field("clipping_threshold", "削波阈值", "number", 0.99, min=0.01, max=1),
            _field("silence_threshold", "静音阈值", "number", 0.01, min=0),
        ],
        "metrics": [
            _metric("audio.metadata_quality", True), _metric("audio.clipping_rate", True),
            _metric("audio.silence_rate", True),
        ],
    },
    "video": {
        "label": "视频",
        "description": "格式、运动、场景、时序一致性、隐私和损坏检查",
        "expected_fields": "duration、width、height、fps，并按指标提供运动或隐私元数据",
        "fields": [
            _field("min_duration", "最短时长（秒）", "number", 0.1, min=0),
            _field("min_width", "最小宽度", "number", 16, min=1),
            _field("min_height", "最小高度", "number", 16, min=1),
            _field("min_fps", "最低帧率", "number", 1, min=0.1),
        ],
        "metrics": [
            _metric("video.format_probe", True), _metric("video.motion_metadata", True),
            _metric("video.optical_flow_motion"), _metric("video.scene_segmentation"),
            _metric("video.temporal_ssim"), _metric("video.privacy_cv"),
            _metric("video.basic_cleanliness", True),
        ],
    },
    "multimodal": {
        "label": "多模态",
        "description": "模态包完整性与跨模态时间对齐",
        "expected_fields": "各模态字段，以及对应 timestamp 字段",
        "fields": [
            _field("required_modalities", "必需模态", "list", ["text", "image"]),
            _field("timestamp_fields", "时间戳字段", "list", ["text_timestamp", "image_timestamp"]),
            _field("alignment_tolerance", "时间对齐容差（秒）", "number", 1, min=0),
        ],
        "metrics": [
            _metric("multimodal.package_integrity", True), _metric("multimodal.alignment", True),
        ],
    },
}


def evaluation_schema() -> dict[str, Any]:
    return {"default_modality": "tabular", "modalities": _MODALITIES}


def _factories(parameters: dict[str, Any]) -> dict[str, Callable[[], Any]]:
    numeric = str(parameters.get("numeric_field", "value"))
    label = str(parameters.get("label_field", "label"))
    text = str(parameters.get("text_field", "text"))
    return {
        "basic.completeness": CompletenessMetric,
        "basic.duplicate_rate": DuplicateRateMetric,
        "basic.field_validity": FieldValidityMetric,
        "tabular.schema_consistency": lambda: TabularSchemaConsistencyMetric(parameters.get("required_fields", ()), parameters.get("field_types", {})),
        "tabular.numeric_statistics": lambda: TabularNumericStatisticsMetric(numeric),
        "tabular.outlier_rate": lambda: TabularOutlierRateMetric(numeric, float(parameters.get("outlier_whisker", 1.5))),
        "tabular.label_balance": lambda: TabularLabelBalanceMetric(label),
        "advanced.numeric_range_compliance": lambda: NumericRangeComplianceMetric(numeric, parameters.get("range_minimum"), parameters.get("range_maximum")),
        "advanced.label_conflict": lambda: LabelConflictMetric(str(parameters.get("id_field", "id")), label),
        "advanced.group_completeness_parity": lambda: GroupCompletenessParityMetric(str(parameters.get("group_field", "group")), tuple(parameters.get("required_fields", ())) or (numeric,)),
        "text.length_quality": lambda: TextLengthQualityMetric(text, int(parameters.get("min_tokens", 1)), int(parameters.get("max_tokens", 512))),
        "text.lexical_diversity": lambda: TextLexicalDiversityMetric(text, int(parameters.get("min_tokens", 1))),
        "text.repetition_rate": lambda: TextRepetitionRateMetric(text),
        "advanced.text_readability": lambda: TextReadabilityMetric(text),
        "image.metadata_quality": lambda: ImageMetadataQualityMetric(int(parameters.get("min_width", 1)), int(parameters.get("min_height", 1)), parameters.get("allowed_formats", ()), parameters.get("expected_channels", ())),
        "image.aspect_ratio_consistency": lambda: ImageAspectRatioConsistencyMetric(float(parameters.get("aspect_tolerance", 0.05))),
        "image.pixel_validity": ImagePixelValidityMetric,
        "audio.metadata_quality": lambda: AudioMetadataQualityMetric(float(parameters.get("min_duration", 0.1)), parameters.get("sample_rates", (8000, 16000, 44100, 48000)), parameters.get("channels", (1, 2))),
        "audio.clipping_rate": lambda: AudioClippingRateMetric(str(parameters.get("samples_field", "samples")), float(parameters.get("clipping_threshold", 0.99))),
        "audio.silence_rate": lambda: AudioSilenceRateMetric(str(parameters.get("samples_field", "samples")), float(parameters.get("silence_threshold", 0.01))),
        "video.format_probe": lambda: VideoFormatProbe(float(parameters.get("min_duration", 0.1)), int(parameters.get("min_width", 16)), int(parameters.get("min_height", 16)), float(parameters.get("min_fps", 1))),
        "video.motion_metadata": VideoMotionMetadata,
        "video.optical_flow_motion": VideoOpticalFlowMotionScore,
        "video.scene_segmentation": VideoSceneSegmentationScore,
        "video.temporal_ssim": VideoTemporalSSIMConsistency,
        "video.privacy_cv": VideoPrivacyCVScore,
        "video.basic_cleanliness": lambda: VideoBasicCleanliness(float(parameters.get("min_duration", 0.1)), int(parameters.get("min_width", 16)), int(parameters.get("min_height", 16)), float(parameters.get("min_fps", 1))),
        "multimodal.package_integrity": lambda: MultimodalPackageIntegrityMetric(tuple(parameters.get("required_modalities", ("text", "image")))),
        "multimodal.alignment": lambda: MultimodalAlignmentMetric(tuple(parameters.get("timestamp_fields", ("text_timestamp", "image_timestamp"))), float(parameters.get("alignment_tolerance", 1.0))),
    }


def run_evaluation(
    product: DataProduct,
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    parameters: dict[str, Any],
    context: RunContext,
):
    modality = str(parameters.get("modality", "tabular"))
    if modality not in _MODALITIES:
        raise ValueError(f"unknown evaluation modality: {modality}")
    available = {item["name"] for item in _MODALITIES[modality]["metrics"]}
    defaults = [item["name"] for item in _MODALITIES[modality]["metrics"] if item["default"]]
    selected = tuple(dict.fromkeys(parameters.get("metrics") or defaults))
    if not selected:
        raise ValueError("at least one quality metric must be selected")
    invalid = [name for name in selected if name not in available]
    if invalid:
        raise ValueError(f"metric {invalid[0]} is not available for {modality}")

    factories = _factories(parameters)
    request = EvaluationRequest(
        metrics=selected,
        options={
            "records": records,
            "fields": tuple(parameters.get("fields", ())),
            "required_fields": tuple(parameters.get("required_fields", ())),
            "field_types": dict(parameters.get("field_types", {})),
        },
    )
    evaluator = CompositeEvaluator()
    report = evaluator.evaluate(product, request, tuple(factories[name]() for name in selected), context)
    report = replace(report, diagnostics={**report.diagnostics, "modality": modality, "selected_metrics": selected})
    return report, evaluator.spec.name


__all__ = ["evaluation_schema", "run_evaluation"]
