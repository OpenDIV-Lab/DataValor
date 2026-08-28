"""IID, stratified, grouped and temporal split utilities."""

from __future__ import annotations

import random
from collections import defaultdict


def split_records(records, config=None, *, seed: int = 0):
    if not config: return {"": [dict(row) for row in records]}, {"method": "none"}
    ratios = config.get("ratios", {"train": .8, "test": .2}); names = list(ratios); values = [float(ratios[n]) for n in names]; total = sum(values)
    if not names or total <= 0 or any(v < 0 for v in values): raise ValueError("split ratios must be non-negative")
    values = [v / total for v in values]; rng = random.Random(seed); rows = [dict(row) for row in records]
    method = config.get("method", "random")
    if method in {"temporal", "time", "stream"}: rows.sort(key=lambda row: str(row.get(config["field"])))
    elif method in {"random", "iid"}: rng.shuffle(rows)
    elif method == "stratified":
        groups = defaultdict(list)
        for row in rows: groups[str(row.get(config["field"]))].append(row)
        rows = []
        for group in groups.values(): rng.shuffle(group); rows.extend(group)
    elif method in {"predefined", "group", "domain"}:
        if method == "predefined":
            output = defaultdict(list); mapping = {str(k): str(v) for k, v in config.get("mapping", {}).items()}
            for row in rows: output[mapping.get(str(row.get(config.get("field", "split"))), str(row.get(config.get("field", "split"))))].append(row)
            return dict(output), {"method": method, "counts": {k: len(v) for k, v in output.items()}}
    counts = [int(len(rows) * v) for v in values]
    for i in range(len(rows) - sum(counts)): counts[i % len(counts)] += 1
    output, offset = {}, 0
    for name, count in zip(names, counts): output[name] = rows[offset: offset + count]; offset += count
    return output, {"method": method, "field": config.get("field"), "counts": {k: len(v) for k, v in output.items()}}
