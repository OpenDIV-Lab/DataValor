"""Small physical-GPU scheduler with atomic resumability metadata."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Mapping


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2))
    os.replace(temporary, path)


@dataclass(frozen=True)
class GpuJob:
    job_id: str
    command: tuple[str, ...]
    output_dir: Path
    env: Mapping[str, str] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(
            {"job_id": self.job_id, "command": self.command, "env": dict(self.env)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class GpuJobResult:
    job_id: str
    status: str
    physical_gpu: int
    local_cuda_index: int
    returncode: int
    runtime_seconds: float
    cached: bool = False


class GpuScheduler:
    def __init__(self, physical_devices: tuple[int, ...], *, state_dir: Path) -> None:
        if not physical_devices or len(set(physical_devices)) != len(physical_devices):
            raise ValueError("physical GPU IDs must be non-empty and unique")
        if any(device not in range(1, 8) for device in physical_devices):
            raise ValueError("only physical GPUs 1..7 may be scheduled")
        self.physical_devices = tuple(physical_devices)
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def local_cuda_index(self, physical_gpu: int) -> int:
        if physical_gpu not in self.physical_devices:
            raise KeyError(f"GPU {physical_gpu} is not configured")
        return 0

    def run(self, job: GpuJob, *, physical_gpu: int | None = None) -> GpuJobResult:
        device = self.physical_devices[0] if physical_gpu is None else physical_gpu
        local_index = self.local_cuda_index(device)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        completion = job.output_dir / ".complete.json"
        if completion.exists():
            marker = json.loads(completion.read_text())
            if marker.get("job_hash") == job.content_hash:
                return GpuJobResult(
                    job.job_id, "completed", device, local_index, 0, 0.0, cached=True
                )

        environment = {
            **os.environ,
            **dict(job.env),
            "CUDA_VISIBLE_DEVICES": str(device),
            "DATAMECH_PHYSICAL_GPU": str(device),
            "DATAMECH_LOCAL_CUDA_INDEX": str(local_index),
        }
        started = time.perf_counter()
        completed = subprocess.run(job.command, capture_output=True, text=True, env=environment)
        runtime = time.perf_counter() - started
        (job.output_dir / "stdout.log").write_text(completed.stdout)
        (job.output_dir / "stderr.log").write_text(completed.stderr)
        record = {
            "job_id": job.job_id,
            "job_hash": job.content_hash,
            "physical_gpu": device,
            "local_cuda_index": local_index,
            "returncode": completed.returncode,
            "runtime_seconds": runtime,
            "status": "completed" if completed.returncode == 0 else "failed",
        }
        _atomic_json(job.output_dir / ".last_run.json", record)
        if completed.returncode == 0:
            _atomic_json(completion, record)
        return GpuJobResult(
            job.job_id,
            record["status"],
            device,
            local_index,
            completed.returncode,
            runtime,
        )

    def run_many(self, jobs: tuple[GpuJob, ...]) -> tuple[GpuJobResult, ...]:
        ids = [job.job_id for job in jobs]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate job_id in one scheduler submission")
        devices: Queue[int] = Queue()
        for device in self.physical_devices:
            devices.put(device)

        def execute(job: GpuJob) -> GpuJobResult:
            device = devices.get()
            try:
                return self.run(job, physical_gpu=device)
            finally:
                devices.put(device)

        with ThreadPoolExecutor(max_workers=len(self.physical_devices)) as pool:
            futures = [pool.submit(execute, job) for job in jobs]
            return tuple(future.result() for future in futures)


__all__ = ["GpuJob", "GpuJobResult", "GpuScheduler"]
