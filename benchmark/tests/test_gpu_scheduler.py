from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from datamechbench.gpu_scheduler import GpuJob, GpuScheduler


def test_scheduler_only_accepts_physical_gpus_one_through_seven(tmp_path: Path) -> None:
    scheduler = GpuScheduler((1, 3, 7), state_dir=tmp_path)
    assert scheduler.physical_devices == (1, 3, 7)
    assert scheduler.local_cuda_index(3) == 0
    with pytest.raises(ValueError, match="physical GPUs 1..7"):
        GpuScheduler((0, 1), state_dir=tmp_path)
    with pytest.raises(ValueError, match="physical GPUs 1..7"):
        GpuScheduler((8,), state_dir=tmp_path)


def test_duplicate_job_ids_cannot_be_scheduled_together(tmp_path: Path) -> None:
    scheduler = GpuScheduler((1, 2), state_dir=tmp_path)
    job = GpuJob("same", (sys.executable, "-c", "pass"), tmp_path / "same")
    with pytest.raises(ValueError, match="duplicate job_id"):
        scheduler.run_many((job, job))


def test_failed_job_has_no_completion_marker_and_resumes(tmp_path: Path) -> None:
    attempts = tmp_path / "attempts.txt"
    code = (
        "from pathlib import Path; import os; "
        f"p=Path({str(attempts)!r}); n=int(p.read_text())+1 if p.exists() else 1; "
        "p.write_text(str(n)); "
        "assert os.environ['CUDA_VISIBLE_DEVICES']=='1'; "
        "assert os.environ['DATAMECH_LOCAL_CUDA_INDEX']=='0'; "
        "raise SystemExit(1 if n==1 else 0)"
    )
    scheduler = GpuScheduler((1,), state_dir=tmp_path / "state")
    job = GpuJob("retry", (sys.executable, "-c", code), tmp_path / "output")

    first = scheduler.run(job)
    assert first.status == "failed"
    assert not (job.output_dir / ".complete.json").exists()

    second = scheduler.run(job)
    assert second.status == "completed"
    marker = json.loads((job.output_dir / ".complete.json").read_text())
    assert marker["physical_gpu"] == 1
    assert marker["local_cuda_index"] == 0
    assert not list(job.output_dir.glob("*.tmp"))
