"""DataEval: reproducible data-quality evaluation."""

from .audio import AudioClippingRateMetric, AudioMetadataQualityMetric, AudioSilenceRateMetric
from .builtins import (
    CompletenessMetric,
    CompositeEvaluator,
    DuplicateRateMetric,
    FieldValidityMetric,
)
from .image import (
    ImageAspectRatioConsistencyMetric,
    ImageMetadataQualityMetric,
    ImagePixelValidityMetric,
)
from .interfaces import DataEvaluator, QualityMetric, TaskUtilityEvaluator
from .models import (
    EvaluationReport,
    EvaluationRequest,
    MetricResult,
    ScoreDirection,
    TaskUtilityResult,
)
from .multimodal import MultimodalAlignmentMetric, MultimodalPackageIntegrityMetric
from .operators import FieldSummaryMetric, LexicalDiversityMetric, lexical_diversity
from .registry import EVALUATORS, QUALITY_METRICS, TASK_UTILITY_EVALUATORS
from .tabular import (
    TabularLabelBalanceMetric,
    TabularNumericStatisticsMetric,
    TabularOutlierRateMetric,
    TabularSchemaConsistencyMetric,
)
from .task_utility import CallableTaskUtility, RecordCountUtility
from .text import TextLengthQualityMetric, TextLexicalDiversityMetric, TextRepetitionRateMetric
from .video import (
    VideoBasicCleanliness,
    VideoFormatProbe,
    VideoMotionMetadata,
    VideoOpticalFlowMotionScore,
    VideoPrivacyCVScore,
    VideoSceneSegmentationScore,
    VideoTemporalSSIMConsistency,
    get_video_metadata,
    iter_sampled_frames,
)

for _component, _registry in (
    (CompletenessMetric, QUALITY_METRICS),
    (DuplicateRateMetric, QUALITY_METRICS),
    (FieldValidityMetric, QUALITY_METRICS),
    (TabularSchemaConsistencyMetric, QUALITY_METRICS),
    (TabularNumericStatisticsMetric, QUALITY_METRICS),
    (TabularOutlierRateMetric, QUALITY_METRICS),
    (TabularLabelBalanceMetric, QUALITY_METRICS),
    (TextLengthQualityMetric, QUALITY_METRICS),
    (TextLexicalDiversityMetric, QUALITY_METRICS),
    (TextRepetitionRateMetric, QUALITY_METRICS),
    (ImageMetadataQualityMetric, QUALITY_METRICS),
    (ImageAspectRatioConsistencyMetric, QUALITY_METRICS),
    (ImagePixelValidityMetric, QUALITY_METRICS),
    (AudioMetadataQualityMetric, QUALITY_METRICS),
    (AudioClippingRateMetric, QUALITY_METRICS),
    (AudioSilenceRateMetric, QUALITY_METRICS),
    (VideoFormatProbe, QUALITY_METRICS),
    (VideoMotionMetadata, QUALITY_METRICS),
    (VideoOpticalFlowMotionScore, QUALITY_METRICS),
    (VideoSceneSegmentationScore, QUALITY_METRICS),
    (VideoTemporalSSIMConsistency, QUALITY_METRICS),
    (VideoPrivacyCVScore, QUALITY_METRICS),
    (VideoBasicCleanliness, QUALITY_METRICS),
    (MultimodalPackageIntegrityMetric, QUALITY_METRICS),
    (MultimodalAlignmentMetric, QUALITY_METRICS),
    (CompositeEvaluator, EVALUATORS),
):
    if _component().spec.name not in _registry:
        _registry.register(_component().spec, _component)

# Optional backends are imported lazily by users from ``data_eval.backends``;
# these names are intentionally not imported here to keep the core import
# dependency-free.

__all__ = [
    "EVALUATORS",
    "QUALITY_METRICS",
    "TASK_UTILITY_EVALUATORS",
    "DataEvaluator",
    "EvaluationReport",
    "EvaluationRequest",
    "MetricResult",
    "QualityMetric",
    "ScoreDirection",
    "TaskUtilityEvaluator",
    "TaskUtilityResult",
    "FieldSummaryMetric",
    "LexicalDiversityMetric",
    "lexical_diversity",
    "CallableTaskUtility",
    "RecordCountUtility",
    "CompletenessMetric",
    "CompositeEvaluator",
    "DuplicateRateMetric",
    "FieldValidityMetric",
    "TabularLabelBalanceMetric",
    "TabularNumericStatisticsMetric",
    "TabularOutlierRateMetric",
    "TabularSchemaConsistencyMetric",
    "TextLengthQualityMetric",
    "TextLexicalDiversityMetric",
    "TextRepetitionRateMetric",
    "ImageAspectRatioConsistencyMetric",
    "ImageMetadataQualityMetric",
    "ImagePixelValidityMetric",
    "AudioClippingRateMetric",
    "AudioMetadataQualityMetric",
    "AudioSilenceRateMetric",
    "VideoBasicCleanliness",
    "VideoFormatProbe",
    "VideoMotionMetadata",
    "VideoOpticalFlowMotionScore",
    "VideoPrivacyCVScore",
    "VideoSceneSegmentationScore",
    "VideoTemporalSSIMConsistency",
    "get_video_metadata",
    "iter_sampled_frames",
    "MultimodalAlignmentMetric",
    "MultimodalPackageIntegrityMetric",
]
