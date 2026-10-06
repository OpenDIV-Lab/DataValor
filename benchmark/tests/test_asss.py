from __future__ import annotations

import pytest
from datamechbench.methods.asss import ASSS_PROVENANCE, evaluate_asss
from datamechbench.methods.valuation_shapley import OptionalMethodUnavailable


def test_asss_variants_are_not_misrepresented_without_auditable_source() -> None:
    assert set(ASSS_PROVENANCE) == {"asss_a", "asss_b"}
    assert all(item["status"] == "unavailable" for item in ASSS_PROVENANCE.values())
    assert all(item["doi"] == "10.1145/3802016" for item in ASSS_PROVENANCE.values())

    for method_id in ASSS_PROVENANCE:
        with pytest.raises(OptionalMethodUnavailable) as error:
            evaluate_asss(method_id)
        assert error.value.reason == "official_implementation_unavailable:asss"


def test_unknown_asss_variant_is_a_programming_error() -> None:
    with pytest.raises(KeyError, match="unknown ASSS"):
        evaluate_asss("adaptive_neyman")
