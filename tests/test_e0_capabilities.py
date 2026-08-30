from datavalor.core import (
    CapabilityStatus,
    CapabilityUnavailableError,
    probe_capabilities,
    probe_capability,
    require_capability,
)
from datavalor.toolkit import probe_external_capabilities


def test_probe_does_not_import_optional_module():
    status = probe_capability("json", "json", distribution="pip")
    assert isinstance(status, CapabilityStatus)
    assert status.available is True
    missing = probe_capability("missing", "module_that_does_not_exist_datavalor")
    assert missing.available is False
    assert "not installed" in (missing.reason or "")


def test_require_capability_translates_missing_dependency():
    try:
        require_capability("missing", "module_that_does_not_exist_datavalor", extra="quality")
    except CapabilityUnavailableError as exc:
        assert "quality" in str(exc)
    else:
        raise AssertionError("missing capability should raise")


def test_probe_many_and_external_inventory():
    statuses = probe_capabilities(({"name": "json", "module": "json"}, {"name": "missing", "module": "module_that_does_not_exist_datavalor"}))
    assert [item.name for item in statuses] == ["json", "missing"]
    external = probe_external_capabilities()
    assert {item.name for item in external} >= {"pydvl", "cleanlab", "mesa"}
