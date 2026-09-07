from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_prof import (
    CategoricalConcentrationMetric,
    DriftAnalyzer,
    PairwiseCorrelationMetric,
    RobustStatisticsMetric,
    stratified_sample,
)


def _product(name: str = "p") -> DataProduct:
    return DataProduct(name, name, DataReference(f"memory://{name}", "json"), "owner")


def test_robust_statistics_quantiles_and_fences():
    context = RunContext("prof", config={"records": [{"x": 1}, {"x": 2}, {"x": 3}, {"x": 100}]})
    result = RobustStatisticsMetric().measure(_product(), "x", context)
    assert result["statistics"]["median"] == 2.5
    assert result["statistics"]["outlier_count"] == 1
    assert result["statistics"]["q25"] < result["statistics"]["q75"]


def test_categorical_concentration_and_correlation():
    rows = [{"segment": "a", "x": 1, "y": 2}, {"segment": "a", "x": 2, "y": 4}, {"segment": "b", "x": 3, "y": 6}]
    context = RunContext("prof", config={"records": rows})
    concentration = CategoricalConcentrationMetric().measure(_product(), "segment", context)
    assert concentration["statistics"]["distinct_count"] == 2
    assert concentration["statistics"]["top_10_coverage"] == 1
    correlation = PairwiseCorrelationMetric().measure(_product(), "x,y", context)
    assert round(correlation["statistics"]["pearson_r"], 6) == 1


def test_stratified_sample_is_deterministic_and_covers_groups():
    rows = [{"group": "a", "i": i} for i in range(8)] + [{"group": "b", "i": i} for i in range(2)]
    first = stratified_sample(rows, ("group",), 4, seed=7)
    second = stratified_sample(rows, ("group",), 4, seed=7)
    assert first == second
    assert {row["group"] for row in first} == {"a", "b"}


def test_drift_analyzer_numeric_psi_and_categorical_js():
    context = RunContext("drift", config={"reference_records": [{"x": i, "label": "a"} for i in range(10)], "current_records": [{"x": i + 100, "label": "b"} for i in range(10)]})
    report = DriftAnalyzer().analyze(_product("reference"), _product("current"), context)
    assert report.summary["drifted_field_count"] >= 1
    assert {result.method for result in report.fields} == {"psi", "jensen_shannon"}
    assert next(result for result in report.fields if result.field == "x").statistic is not None

