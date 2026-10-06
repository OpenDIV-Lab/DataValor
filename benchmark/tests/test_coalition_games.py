from __future__ import annotations

import pytest
from datamechbench.coalition_games import CoalitionGameTable


def test_table_is_complete_immutable_and_order_independent_hash() -> None:
    values = {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}
    table = CoalitionGameTable(("a", "b"), values, fidelity="low")
    reordered = CoalitionGameTable(
        ("a", "b"), {3: 4.0, 2: 2.0, 1: 1.0, 0: 0.0}, fidelity="low"
    )

    values[1] = 99.0
    assert table.value(("a",)) == pytest.approx(1.0)
    assert table.value(("b", "a")) == pytest.approx(4.0)
    assert table.content_hash == reordered.content_hash
    with pytest.raises(TypeError):
        table.values[1] = 7.0  # type: ignore[index]


def test_table_rejects_incomplete_or_unknown_coalitions() -> None:
    with pytest.raises(ValueError, match="complete"):
        CoalitionGameTable(("a", "b"), {0: 0.0, 1: 1.0}, fidelity="high")

    table = CoalitionGameTable(("a",), {0: 0.0, 1: 1.0}, fidelity="high")
    with pytest.raises(KeyError, match="unknown owner"):
        table.value(("missing",))
