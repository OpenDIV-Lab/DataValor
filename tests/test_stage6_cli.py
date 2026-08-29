import json
from pathlib import Path

from datavalor.cli import main


def test_cli_profile_and_evaluate(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"uri": str(Path("data/examples/text.jsonl"))}), encoding="utf-8")
    profile = tmp_path / "profile.json"
    assert main(["profile", "--config", str(config), "--output", str(profile)]) == 0
    assert json.loads(profile.read_text(encoding="utf-8"))["record_count"] == 2
    evaluation = tmp_path / "evaluation.json"
    assert main(["evaluate", "--config", str(config), "--output", str(evaluation)]) == 0
    assert json.loads(evaluation.read_text(encoding="utf-8"))["name"] == "text.lexical_diversity"
