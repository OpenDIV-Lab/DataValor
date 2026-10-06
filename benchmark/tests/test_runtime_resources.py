from __future__ import annotations

from datamechbench.resources import resource_path


def test_runtime_catalog_resources_are_discoverable() -> None:
    references = resource_path("catalog", "references.yaml")
    mechanisms = resource_path("catalog", "mechanisms.yaml")

    assert references.is_file()
    assert mechanisms.is_file()


def test_runtime_submission_template_is_discoverable() -> None:
    assert resource_path("submission_template", "submission.yaml").is_file()
    assert resource_path("submission_template", "results.jsonl").is_file()
