"""Market-facing governance helpers built on the existing rights contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from datavalor.core import ArtifactEnvelope, RightsBundle


@dataclass(frozen=True)
class RightsRestrictionScore:
    score: float
    factors: Mapping[str, float]
    findings: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class RightsRestrictivenessScorer:
    """Describe how restrictive a bundle is on a 0 (open) to 1 scale."""

    def score(self, rights: RightsBundle, evaluated_at: datetime | None = None) -> RightsRestrictionScore:
        now = evaluated_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        expiry = rights.valid_until
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        factors = {
            "purpose": 0.0 if rights.purposes else 1.0,
            "commercial": 0.0 if rights.commercial_use is True else 1.0 if rights.commercial_use is False else 0.5,
            "redistribution": 0.0 if rights.redistribution is True else 1.0 if rights.redistribution is False else 0.5,
            "jurisdiction": 0.0 if not rights.jurisdictions else 1.0 / (1.0 + len(rights.jurisdictions)),
            "exclusivity": 0.0 if not rights.exclusivity or rights.exclusivity in {"none", "non_exclusive"} else 0.5,
            "expiry": 0.0 if expiry is None else 1.0 if expiry <= now else 1.0 / (1.0 + max(0.0, (expiry - now).total_seconds()) / 86400.0),
        }
        weights = {"purpose": 0.20, "commercial": 0.25, "redistribution": 0.20, "jurisdiction": 0.10, "exclusivity": 0.10, "expiry": 0.15}
        value = sum(weights[name] * factors[name] for name in weights)
        findings = tuple(name for name, factor in factors.items() if factor >= 0.5)
        return RightsRestrictionScore(min(1.0, max(0.0, value)), factors, findings, {"evaluated_at": now.isoformat(), "weights": weights})


@dataclass(frozen=True)
class RightsCompatibility:
    compatible: bool
    intersection: RightsBundle
    conflicts: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class RightsCompatibilityEvaluator:
    """Check whether several products retain a usable common rights scope."""

    def evaluate(self, *bundles: RightsBundle, required: RightsBundle | None = None) -> RightsCompatibility:
        if not bundles:
            raise ValueError("at least one rights bundle is required")
        purposes = set(bundles[0].purposes)
        jurisdictions = set(bundles[0].jurisdictions)
        for bundle in bundles[1:]:
            purposes &= set(bundle.purposes)
            jurisdictions &= set(bundle.jurisdictions)
        commercial = all(bundle.commercial_use is True for bundle in bundles)
        redistribution = all(bundle.redistribution is True for bundle in bundles)
        expiries = [item.valid_until for item in bundles if item.valid_until is not None]
        intersection = RightsBundle(tuple(sorted(purposes)), commercial, redistribution, None, min(expiries) if expiries else None, tuple(sorted(jurisdictions)), {"source_count": len(bundles)})
        conflicts: list[str] = []
        if any(bundle.purposes for bundle in bundles) and not purposes:
            conflicts.append("purposes_have_no_intersection")
        if any(bundle.jurisdictions for bundle in bundles) and not jurisdictions:
            conflicts.append("jurisdictions_have_no_intersection")
        if required:
            if not set(required.purposes).issubset(purposes): conflicts.append("required_purpose_unavailable")
            if required.commercial_use is True and not commercial: conflicts.append("required_commercial_use_unavailable")
            if required.redistribution is True and not redistribution: conflicts.append("required_redistribution_unavailable")
            if required.jurisdictions and not set(required.jurisdictions).issubset(jurisdictions): conflicts.append("required_jurisdiction_unavailable")
        return RightsCompatibility(not conflicts, intersection, tuple(conflicts), {"bundle_count": len(bundles)})


@dataclass(frozen=True)
class ArtifactStaleness:
    status: str
    age_seconds: float
    reasons: tuple[str, ...]
    reusable: bool
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class ArtifactStalenessEvaluator:
    """Classify an artifact as valid, incrementally stale, or obsolete."""

    def evaluate(self, artifact: ArtifactEnvelope[Any], *, evaluated_at: datetime | None = None, max_age_seconds: float | None = None, current_checksum: str | None = None, breaking_change: bool = False) -> ArtifactStaleness:
        now = evaluated_at or datetime.now(timezone.utc)
        if now.tzinfo is None: now = now.replace(tzinfo=timezone.utc)
        created = artifact.created_at if artifact.created_at.tzinfo else artifact.created_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - created).total_seconds())
        reasons: list[str] = []
        expected_checksum = artifact.diagnostics.get("data_checksum")
        if max_age_seconds is not None and age > max_age_seconds: reasons.append("age_exceeded")
        if current_checksum is not None and expected_checksum is not None and current_checksum != expected_checksum: reasons.append("checksum_changed")
        if breaking_change: reasons.append("breaking_change")
        obsolete = breaking_change or "checksum_changed" in reasons
        status = "obsolete" if obsolete else "incremental_refresh" if reasons else "valid"
        return ArtifactStaleness(status, age, tuple(reasons), not obsolete, {"max_age_seconds": max_age_seconds, "artifact_id": artifact.artifact_id})


__all__ = ["ArtifactStaleness", "ArtifactStalenessEvaluator", "RightsCompatibility", "RightsCompatibilityEvaluator", "RightsRestrictionScore", "RightsRestrictivenessScorer"]
