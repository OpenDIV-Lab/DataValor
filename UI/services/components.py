from __future__ import annotations

from dataclasses import asdict


def component_catalog() -> list[dict]:
    import datavalor.data_eval as evaluation
    import datavalor.data_gov as governance
    import datavalor.data_market as market
    import datavalor.data_price as price
    import datavalor.data_prof as profile
    import datavalor.data_query as query
    import datavalor.data_value as value
    from datavalor.toolkit.analysis import ANALYZERS, FRONTIER_ANALYZERS, RESULT_COMPARATORS

    registries = (
        governance.METADATA_EXTRACTORS, governance.METADATA_CATALOGS,
        governance.SECURITY_SCANNERS, governance.POLICY_EVALUATORS,
        profile.PROFILE_METRICS, profile.PROFILERS, profile.PROFILE_COMPARATORS,
        evaluation.QUALITY_METRICS, evaluation.EVALUATORS,
        evaluation.TASK_UTILITY_EVALUATORS, value.VALUATORS,
        value.CONTRIBUTION_VALUATORS, value.UTILITY_FUNCTIONS,
        price.PRICING_MODELS, price.ONLINE_PRICING_MODELS,
        price.PRICE_CONSTRAINTS, price.PRICING_MECHANISMS,
        market.MARKET_CATALOGS, market.INCENTIVE_POLICIES,
        market.REVENUE_ALLOCATORS, market.TRANSACTION_PROCESSORS,
        market.PARTICIPANT_STRATEGIES, market.MARKET_SIMULATORS,
        query.QUERY_AUTHORIZERS, query.QUERY_PLANNERS, query.QUERY_EXECUTORS,
        query.RESULT_GUARDS, query.DATA_AGENTS,
        ANALYZERS, FRONTIER_ANALYZERS, RESULT_COMPARATORS,
    )
    result = []
    for registry in registries:
        for spec in registry.specs():
            item = asdict(spec)
            item["registry"] = registry.namespace
            result.append(item)
    return sorted(result, key=lambda item: (item["module"], item["kind"], item["name"]))
