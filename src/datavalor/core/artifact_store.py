"""Filesystem artifact store implementing the DataValor ArtifactStore contract."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifact import ArtifactEnvelope, ArtifactRef, ArtifactStatus
from .component import ComponentSpec
from .context import RunContext
from .interfaces import ArtifactStore
from .io import ensure_dir, file_sha256, write_json


class LocalArtifactStore(ArtifactStore):
    """Store envelopes as JSON files addressed by artifact id."""

    def __init__(self, root: str | Path):
        self.root = ensure_dir(root)

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            "artifact_store.local_json",
            "1.0.0",
            "core",
            "artifact_store",
            capabilities=("local", "json", "checksum"),
        )

    def _path(self, artifact_id: str) -> Path:
        safe = artifact_id.replace("/", "_").replace("..", "_")
        return self.root / f"{safe}.json"

    def put(self, artifact: ArtifactEnvelope[Any], context: RunContext) -> ArtifactRef:
        del context
        path = self._path(artifact.artifact_id)
        payload = asdict(artifact)
        payload["status"] = artifact.status.value
        payload["producer"] = asdict(artifact.producer)
        payload["parents"] = [asdict(parent) for parent in artifact.parents]
        payload["evidence"] = [asdict(item) for item in artifact.evidence]
        payload["created_at"] = artifact.created_at.isoformat()
        # Use the shared atomic writer so a killed run cannot leave a partial
        # artifact that looks valid to a later pipeline step.
        write_json(path, payload)
        return ArtifactRef(artifact.artifact_id, artifact.kind, artifact.schema_version, str(path), file_sha256(path))

    def get(self, reference: ArtifactRef, context: RunContext) -> ArtifactEnvelope[Any]:
        del context
        path = Path(reference.uri or self._path(reference.artifact_id))
        if not path.is_file():
            raise FileNotFoundError(path)
        if reference.checksum:
            actual_checksum = file_sha256(path)
            if actual_checksum != reference.checksum:
                raise ValueError(
                    f"Artifact checksum mismatch for {reference.artifact_id!r}: "
                    f"expected {reference.checksum}, got {actual_checksum}"
                )
        payload = json.loads(path.read_text(encoding="utf-8"))
        producer = ComponentSpec(**payload.pop("producer"))
        payload["producer"] = producer
        payload["status"] = ArtifactStatus(payload.get("status", "succeeded"))
        created_at = payload.pop("created_at", None)
        if created_at:
            payload["created_at"] = datetime.fromisoformat(created_at)
        payload["parents"] = tuple(ArtifactRef(**item) for item in payload.get("parents", ()))
        from .artifact import Evidence

        payload["evidence"] = tuple(Evidence(**item) for item in payload.get("evidence", ()))
        return ArtifactEnvelope(**payload)

    def exists(self, reference: ArtifactRef, context: RunContext) -> bool:
        del context
        return Path(reference.uri or self._path(reference.artifact_id)).is_file()
