import random
from pathlib import Path

from datavalor.core import canonical_record_hash, read_jsonl, write_jsonl
from datavalor.data_gov import JSONLAdapter, adapter_from_uri
from datavalor.toolkit.benchmark import (
    LocalDatasetProvider,
    ParametricProvider,
    apply_perturbations,
    split_records,
)


def test_jsonl_adapter_and_canonical_hash(tmp_path: Path):
    path = tmp_path / "rows.jsonl"
    write_jsonl(path, [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}])
    assert read_jsonl(path)[0]["id"] == 1
    adapter = JSONLAdapter(path)
    assert adapter.materialize(limit=1) == [{"id": 1, "label": "a"}]
    digest, count = canonical_record_hash(adapter.materialize())
    assert len(digest) == 64 and count == 2
    assert adapter_from_uri(path).metadata.format == "jsonl"


def test_local_provider_and_parametric_provider_are_reproducible(tmp_path: Path):
    path = tmp_path / "rows.csv"
    path.write_text("x,label\n1,a\n2,b\n", encoding="utf-8")
    provider = LocalDatasetProvider(path=str(path))
    first = provider.generate(rng=random.Random(3)).records
    second = provider.generate(rng=random.Random(99)).records
    assert first == second and first[0]["x"] == 1
    synthetic = ParametricProvider(num_rows=3, fields={"x": {"distribution": "sequence", "start": 1}})
    assert synthetic.generate(rng=random.Random(1)).records == [{"x": 1}, {"x": 2}, {"x": 3}]


def test_perturbation_and_split_audit():
    rows = [{"id": i, "label": "a" if i < 3 else "b"} for i in range(6)]
    transformed, audit = apply_perturbations(rows, [{"method": "missingness", "probability": 1.0, "fields": ["label"]}], seed=7)
    assert all(row["label"] is None for row in transformed)
    assert audit[0]["seed"] == 7
    splits, metadata = split_records(rows, {"method": "random", "ratios": {"train": 0.5, "test": 0.5}}, seed=7)
    assert sum(map(len, splits.values())) == len(rows)
    assert metadata["counts"]["train"] + metadata["counts"]["test"] == len(rows)
