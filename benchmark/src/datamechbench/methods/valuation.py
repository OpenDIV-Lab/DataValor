"""Thin V-track adapters over DataValor contribution algorithms."""

from __future__ import annotations

import importlib.util
import random
import time
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from datavalor.core import DataProduct, DataReference, DataScope, RunContext, TaskContext
from datavalor.data_value import (
    BanzhafValuator,
    ContributionRequest,
    ValuationTarget,
    exact_shapley_values,
    leave_one_out_values,
)
from datavalor.data_value.backends.pydvl import PyDVLContributionValuator

from ..coalition_games import CoalitionGameTable
from ..data import OwnerDataset
from ..models import MethodSpec, ValuationCase, ValuationOutput
from ..registry import MethodRegistry
from .asss import evaluate_asss
from .valuation_model_based import evaluate_model_based
from .valuation_semivalues import evaluate_semivalue
from .valuation_shapley import OptionalMethodUnavailable, evaluate_shapley
from .valuation_sota import evaluate_sota


def _spec(
    method_id: str,
    role: str,
    source: str,
    *,
    stochastic: bool = False,
    requires: tuple[str, ...] = (),
    family_id: str = "",
    implementation_kind: str = "native",
    case_types: frozenset[str] = frozenset({"analytic", "real_owner_data"}),
    estimand: str = "alternative_estimand",
    provenance_kind: str = "paper_variant",
    reference_keys: tuple[str, ...] = (),
    algorithm_location: str = "benchmark method adapter",
    deviations: tuple[str, ...] = (),
) -> MethodSpec:
    return MethodSpec(
        method_id=method_id,
        track="valuation",
        role=role,
        source=source,
        version="1.0",
        family_id=family_id or method_id,
        implementation_kind=implementation_kind,
        stochastic=stochastic,
        requires=requires,
        capabilities=frozenset({"scores"}),
        supported_case_types=case_types,
        estimand=estimand,
        provenance_kind=provenance_kind,
        reference_keys=reference_keys,
        algorithm_location=algorithm_location,
        deviations=deviations,
    )


@dataclass
class _ValuationAdapter:
    spec: MethodSpec
    params: Mapping[str, Any]

    def _evaluate(self, case: ValuationCase, seed: int):
        raise NotImplementedError

    def evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        started = time.perf_counter()
        report = self._evaluate(case, seed)
        if isinstance(report, ValuationOutput):
            scores = report.scores
            utility_calls = report.utility_calls
            extra = dict(report.diagnostics)
        else:
            scores = {item.target_id: float(item.value) for item in report.contributions}
            utility_calls = report.utility_calls
            extra = dict(report.diagnostics)
        return ValuationOutput(
            scores=scores,
            utility_calls=utility_calls,
            diagnostics={
                **extra,
                "method_id": self.spec.method_id,
                "seed": seed,
                "estimand": self.spec.estimand,
                "runtime_seconds": time.perf_counter() - started,
            },
        )


class _RandomAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        rng = random.Random(seed)
        return ValuationOutput({owner: rng.random() for owner in case.owner_ids}, utility_calls=0)


class _FunctionAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int):
        def utility(coalition, context):
            del context
            return case.utility(tuple(coalition))

        if self.spec.method_id == "leave_one_out":
            return leave_one_out_values(case.owner_ids, utility)
        if self.spec.method_id == "shapley_exact":
            return exact_shapley_values(
                case.owner_ids,
                utility,
                max_records=int(self.params.get("max_records", 10)),
            )
        raise KeyError(f"unsupported function adapter: {self.spec.method_id}")


class _ShapleyAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        return evaluate_shapley(self.spec.method_id, case, self.params, seed)


class _SotaShapleyAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        table = case.metadata.get("high_fidelity_game")
        if not isinstance(table, CoalitionGameTable):
            raise OptionalMethodUnavailable("missing_high_fidelity_game")
        return evaluate_sota(
            self.spec.method_id,
            table,
            budget=int(self.params.get("budget", 256)),
            seed=seed,
            official_repo=self.params.get("official_repo"),
            regression_msr_repo=self.params.get("regression_msr_repo"),
            pydvl_python=self.params.get("pydvl_python"),
            epsilon=float(self.params.get("epsilon", 0.5)),
        )


class _AsssAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        del case, seed
        return evaluate_asss(self.spec.method_id)


def _request(case: ValuationCase, options: Mapping[str, Any] | None = None) -> ContributionRequest:
    product = DataProduct(
        product_id=case.case_id,
        title=case.case_id,
        data=DataReference(f"benchmark://{case.case_id}", "owner_bundles"),
        owner_id="benchmark",
    )
    units = tuple(
        ValuationTarget(owner, case.case_id, DataScope.GROUP) for owner in case.owner_ids
    )
    return ContributionRequest(
        product,
        units,
        TaskContext("classification", "classification", utility_metric="accuracy"),
        dict(options or {}),
    )


class _BanzhafAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int):
        request = _request(case, {"max_records": int(self.params.get("max_records", 16))})

        def utility(product, selection, task, context):
            del product, task, context
            return case.utility(tuple(selection))

        return BanzhafValuator().value_contributions(request, utility, RunContext("benchmark", seed=seed))


class _NativeSemivalueAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        return evaluate_semivalue(self.spec.method_id, case, self.params, seed)


class _ModelBasedAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        return evaluate_model_based(self.spec.method_id, case, self.params, seed)


class _PyDVLAdapter(_ValuationAdapter):
    def _evaluate(self, case: ValuationCase, seed: int):
        if importlib.util.find_spec("pydvl") is None:
            raise OptionalMethodUnavailable("optional_dependency_missing:pydvl")
        options = dict(self.params)
        estimator = options.pop("estimator", None)
        if estimator is None and "external_data" not in options:
            dataset = case.metadata.get("owner_dataset")
            if not isinstance(dataset, OwnerDataset):
                raise OptionalMethodUnavailable("unsupported_case_type:pydvl_requires_owner_dataset")
            # pyDVL 0.10 separates the grouped training dataset from the
            # validation dataset used by ModelUtility's scorer.
            from pydvl.valuation import (
                Dataset,
                GroupedDataset,
                MaxUpdates,
                ModelUtility,
                SupervisedScorer,
                TMCShapleyValuation,
            )

            data_groups = np.full(len(dataset.x_train), -1, dtype=int)
            for group_index, owner in enumerate(case.owner_ids):
                data_groups[list(dataset.owner_rows[owner])] = group_index
            if np.any(data_groups < 0):
                raise ValueError("all training rows must belong to an owner group")
            train = Dataset(x=dataset.x_train, y=dataset.y_train)
            grouped = GroupedDataset.from_dataset(
                train,
                data_groups=data_groups,
                group_names=case.owner_ids,
            )
            validation = Dataset(x=dataset.x_validation, y=dataset.y_validation)
            model = Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "model",
                        LogisticRegression(C=1.0, max_iter=2000, random_state=seed),
                    ),
                ]
            )
            scorer = SupervisedScorer(
                "accuracy",
                test_data=validation,
                default=case.utility(()),
                range=(0.0, 1.0),
            )
            estimator = TMCShapleyValuation(
                utility=ModelUtility(model, scorer),
                is_done=MaxUpdates(int(options.pop("samples", 256))),
                seed=seed,
                show_warnings=False,
                progress=False,
            )
            options["external_data"] = grouped
        request = _request(case, options)

        def utility(product, selection, task, context):
            del product, task, context
            return case.utility(tuple(selection))

        return PyDVLContributionValuator(estimator=estimator, method="tmc_shapley").value_contributions(
            request,
            utility,
            RunContext("benchmark", seed=seed),
        )


def register_valuation_methods(registry: MethodRegistry) -> None:
    entries = (
        (_spec("random", "baseline", "benchmark", stochastic=True), _RandomAdapter),
        (_spec("leave_one_out", "baseline", "DataValor"), _FunctionAdapter),
        (_spec("shapley_exact", "oracle", "DataValor", estimand="ordinary_shapley"), _FunctionAdapter),
        (_spec("shapley_mc", "method", "DataValor", stochastic=True, estimand="ordinary_shapley"), _ShapleyAdapter),
        (
            _spec("banzhaf_exact", "method", "DataValor", family_id="data_banzhaf"),
            _BanzhafAdapter,
        ),
        (_spec("tmc_shapley", "method", "DataValor", stochastic=True, estimand="ordinary_shapley"), _ShapleyAdapter),
        (_spec("owen_shapley", "method", "DataValor", stochastic=True, estimand="ordinary_shapley"), _ShapleyAdapter),
        (_spec("shapley_antithetic", "method", "DataValor", stochastic=True, estimand="ordinary_shapley"), _ShapleyAdapter),
        (_spec("shapley_stratified", "method", "DataValor", stochastic=True, estimand="ordinary_shapley"), _ShapleyAdapter),
        (_spec("shapley_exact_low_residual", "method", "DataValor", stochastic=True, estimand="ordinary_shapley"), _ShapleyAdapter),
        (
            _spec(
                "shapiq_svarm",
                "method",
                "shapiq 1.7.0",
                stochastic=True,
                requires=("shapiq==1.7.0",),
                implementation_kind="external_adapter",
                estimand="ordinary_shapley",
                provenance_kind="official_adapter",
                reference_keys=("svarm", "shapiq"),
                algorithm_location="shapiq.SVARM",
            ),
            _SotaShapleyAdapter,
        ),
        *(
            (
                _spec(
                    method_id,
                    "method",
                    "shapiq 1.7.0",
                    stochastic=True,
                    requires=("shapiq==1.7.0",),
                    implementation_kind="external_adapter",
                    estimand="ordinary_shapley",
                    provenance_kind="official_adapter",
                    reference_keys=reference_keys,
                    algorithm_location=algorithm_location,
                ),
                _SotaShapleyAdapter,
            )
            for method_id, reference_keys, algorithm_location in (
                ("shapiq_stratified_sampling", ("shapiq",), "shapiq.StratifiedSamplingSV"),
                ("shapiq_kernel_shap", ("shapiq", "unbiased_kernel_shap"), "shapiq.KernelSHAP"),
                ("shapiq_unbiased_kernel_shap", ("shapiq", "unbiased_kernel_shap"), "shapiq.UnbiasedKernelSHAP"),
                ("shapiq_owen", ("shapiq",), "shapiq.OwenSamplingSV"),
                ("shapiq_leverage_shap", ("shapiq",), "shapiq.LeverageSHAP"),
            )
        ),
        (
            _spec(
                "official_linear_regression_msr",
                "method",
                "NeurIPS 2025 authors repository",
                stochastic=True,
                requires=("official Regression MSR repository",),
                implementation_kind="external_adapter",
                estimand="ordinary_shapley",
                provenance_kind="official_adapter",
                reference_keys=("regression_msr",),
                algorithm_location="regressionMSR.estimators.regMSR.LinearMSR",
            ),
            _SotaShapleyAdapter,
        ),
        *(
            (
                _spec(
                    method_id,
                    "method",
                    "AAAI 2024 authors repository",
                    stochastic=True,
                    requires=("official SVARM repository",),
                    implementation_kind="external_adapter",
                    estimand="ordinary_shapley",
                    provenance_kind="official_adapter",
                    reference_keys=("svarm",),
                    algorithm_location=location,
                ),
                _SotaShapleyAdapter,
            )
            for method_id, location in (
                ("official_stratified_svarm", "ApproxMethods/SVARM/StratifiedSVARM.py"),
                ("official_stratified_svarm_plus", "ApproxMethods/SVARM/StratifiedSVARMnoReplacement.py"),
            )
        ),
        *(
            (
                _spec(
                    method_id,
                    "method",
                    "Pang et al. 2026",
                    stochastic=True,
                    implementation_kind="external_adapter",
                    estimand="ordinary_shapley",
                    provenance_kind="diagnostic_reference",
                    reference_keys=("asss",),
                    algorithm_location="unavailable pending auditable source",
                    deviations=("no numeric implementation is claimed",),
                ),
                _AsssAdapter,
            )
            for method_id in ("asss_a", "asss_b")
        ),
        *(
            (
                _spec(
                    method_id,
                    "method",
                    "pyDVL 0.10.0",
                    stochastic=True,
                    requires=("pyDVL==0.10.0", "Python 3.10-3.12 worker"),
                    implementation_kind="external_adapter",
                    estimand="ordinary_shapley",
                    provenance_kind="official_adapter",
                    reference_keys=("pydvl_repo", *reference_keys),
                    algorithm_location=location,
                ),
                _SotaShapleyAdapter,
            )
            for method_id, reference_keys, location in (
                ("pydvl_vrds", ("data_shapley",), "pydvl.valuation.VRDSSampler"),
                ("pydvl_owen", (), "pydvl.valuation.OwenSampler"),
                ("pydvl_group_testing", ("knn_shapley",), "pydvl.valuation.GroupTestingShapleyValuation"),
            )
        ),
        (_spec("beta_shapley", "method", "Kwon & Zou 2022"), _NativeSemivalueAdapter),
        (_spec("ame", "method", "Lin et al. 2022", stochastic=True), _NativeSemivalueAdapter),
        (_spec("least_core_exact", "method", "Yan & Procaccia 2021"), _NativeSemivalueAdapter),
        (_spec("least_core_mc", "method", "pyDVL least-core", stochastic=True), _NativeSemivalueAdapter),
        (
            _spec(
                "knn_shapley",
                "method",
                "Jia et al. 2019",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "data_oob",
                "method",
                "Kwon & Zou 2023",
                stochastic=True,
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "influence_function",
                "method",
                "Koh & Liang 2017",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "tracin_cp",
                "method",
                "Pruthi et al. 2020 / dattri",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "gradient_cosine",
                "method",
                "dattri Grad-Cos",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "datainf",
                "method",
                "Kwon et al. 2024 DataInf",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "volume_shapley",
                "method",
                "Xu et al. 2021 Volume Shapley Value",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "robust_volume_shapley",
                "method",
                "Xu et al. 2021 Robust Volume Shapley Value",
                case_types=frozenset({"real_owner_data"}),
            ),
            _ModelBasedAdapter,
        ),
        (
            _spec(
                "pydvl_tmc_shapley",
                "method",
                "pyDVL 0.10.x",
                stochastic=True,
                requires=("pydvl==0.10.*",),
                family_id="tmc_shapley",
                implementation_kind="external_adapter",
                case_types=frozenset({"real_owner_data"}),
                estimand="ordinary_shapley",
            ),
            _PyDVLAdapter,
        ),
    )
    for spec, adapter in entries:
        registry.register(spec, lambda params, spec=spec, adapter=adapter: adapter(spec, params))


__all__ = ["OptionalMethodUnavailable", "register_valuation_methods"]
