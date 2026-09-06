"""Text-specific quality metrics implemented without heavyweight NLP deps."""

from __future__ import annotations

import re
from collections import Counter

from datavalor.core import ComponentSpec

from ._modal_utils import clamp, result, rows
from .interfaces import QualityMetric
from .models import ScoreDirection

_TOKEN = re.compile(r"\b[\w']+\b", re.UNICODE)


def _tokens(value):
    return _TOKEN.findall(str(value or "").casefold())


class TextLexicalDiversityMetric(QualityMetric):
    """Smoothed type-token ratio with record coverage."""

    def __init__(self, text_field="text", min_tokens=1):
        self.text_field, self.min_tokens = text_field, int(min_tokens)

    @property
    def spec(self):
        return ComponentSpec("text.lexical_diversity", "1.1.0", "data_eval", "quality_metric", capabilities=("text", "lexical"))

    def compute(self, product, request, context):
        data = rows(product, request)
        tokens = [token for row in data for token in _tokens(row.get(self.text_field))]
        covered = sum(len(_tokens(row.get(self.text_field))) >= self.min_tokens for row in data)
        ratio = len(set(tokens)) / len(tokens) if tokens else 0.0
        score = clamp(0.7 * ratio + 0.3 * covered / len(data)) if data else 0.0
        return result(self.spec.name, "lexical_diversity", request, product, score, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "token_count": len(tokens), "unique_tokens": len(set(tokens)), "coverage": covered / len(data) if data else 0.0})


class TextLengthQualityMetric(QualityMetric):
    """Score records close to a configured token-length interval."""

    def __init__(self, text_field="text", min_tokens=1, max_tokens=512):
        self.text_field, self.min_tokens, self.max_tokens = text_field, int(min_tokens), int(max_tokens)
        if self.min_tokens < 0 or self.max_tokens < self.min_tokens:
            raise ValueError("invalid text token length interval")

    @property
    def spec(self):
        return ComponentSpec("text.length_quality", "1.0.0", "data_eval", "quality_metric", capabilities=("text", "length"))

    def compute(self, product, request, context):
        data = rows(product, request)
        lengths = [len(_tokens(row.get(self.text_field))) for row in data]
        valid = [length for length in lengths if self.min_tokens <= length <= self.max_tokens]
        violations = [{"row": index, "token_count": length} for index, length in enumerate(lengths) if not self.min_tokens <= length <= self.max_tokens]
        return result(self.spec.name, "text_length", request, product, len(valid) / len(lengths) if lengths else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(lengths), "valid_count": len(valid), "min_tokens": self.min_tokens, "max_tokens": self.max_tokens, "mean_tokens": sum(lengths) / len(lengths) if lengths else 0.0}, evidence_items=violations)


class TextRepetitionRateMetric(QualityMetric):
    """Fraction of repeated tokens, useful for detecting templated text."""

    def __init__(self, text_field="text"):
        self.text_field = text_field

    @property
    def spec(self):
        return ComponentSpec("text.repetition_rate", "1.0.0", "data_eval", "quality_metric", capabilities=("text", "deduplication"))

    def compute(self, product, request, context):
        data = rows(product, request)
        rates = []
        evidence = []
        for index, row in enumerate(data):
            tokens = _tokens(row.get(self.text_field))
            counts = Counter(tokens)
            repeated = sum(count - 1 for count in counts.values() if count > 1)
            rate = repeated / len(tokens) if tokens else 0.0
            rates.append(rate)
            if rate > 0.5:
                evidence.append({"row": index, "repetition_rate": rate})
        return result(self.spec.name, "repetition", request, product, sum(rates) / len(rates) if rates else 0.0, ScoreDirection.LOWER_IS_BETTER, context, statistics={"record_count": len(data), "high_repetition_count": len(evidence)}, evidence_items=evidence)


__all__ = ["TextLengthQualityMetric", "TextLexicalDiversityMetric", "TextRepetitionRateMetric"]
