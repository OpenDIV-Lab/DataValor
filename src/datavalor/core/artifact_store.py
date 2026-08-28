"""Filesystem artifact store implementing the DataValor ArtifactStore contract."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .artifact import ArtifactEnvelope, ArtifactRef, ArtifactStatus
from .component import ComponentSpec
from .context import RunContext
from .interfaces import ArtifactStore
from .io import ensure_dir, file_sha256


class LocalArtifactStore(ArtifactStore):
    """Store envelopes as JSON files addressed by artifact id."""

    def __init__(self, root: str | Path):
        self.root = ensure_dir(root)

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
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return ArtifactRef(artifact.artifact_id, artifact.kind, artifact.schema_version, str(path), file_sha256(path))

    def get(self, reference: ArtifactRef, context: RunContext) -> ArtifactEnvelope[Any]:
        del context
        path = Path(reference.uri or self._path(reference.artifact_id))
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        producer = ComponentSpec(**payload.pop("producer"))
        payload["producer"] = producer
        payload["status"] = ArtifactStatus(payload.get("status", "succeeded"))
        payload.pop("created_at", None)
        payload["parents"] = tuple(ArtifactRef(**item) for item in payload.get("parents", ()))
        payload["evidence"] = ()
        return ArtifactEnvelope(**payload)

    def exists(self, reference: ArtifactRef, context: RunContext) -> bool:
        del context
        return Path(reference.uri or self._path(reference.artifact_id)).is_file()
