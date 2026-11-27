const OfflineExecutionEngine = (() => {
  let sequence = 0;

  const now = () => new Date().toISOString();
  const identifier = (prefix) => `${prefix}-offline-${Date.now().toString(36)}-${(++sequence).toString(36)}`;
  const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const unit = (value, fallback = 0) => Math.min(1, Math.max(0, finite(value, fallback)));
  const rounded = (value, digits = 6) => Number(finite(value).toFixed(digits));
  const present = (value) => value !== null && value !== undefined && value !== "";
  const copy = (value) => JSON.parse(JSON.stringify(value ?? null));
  const mean = (values) => values.length ? values.reduce((sum, value) => sum + finite(value), 0) / values.length : 0;
  const currency = (parameters, product) => String(parameters.currency || product?.metadata?.currency || "CNY");
  const money = (amount, code) => ({ amount: rounded(Math.max(0, amount), 6), currency: code });

  function stable(value) {
    if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
    if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
    return JSON.stringify(value);
  }

  function inferredType(values) {
    const nonempty = values.filter(present);
    if (!nonempty.length) return "unknown";
    if (nonempty.every((value) => typeof value === "number" || (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))))) return "number";
    if (nonempty.every((value) => typeof value === "boolean")) return "boolean";
    if (nonempty.every((value) => !Number.isNaN(Date.parse(value)) && /[-T:/]/.test(String(value)))) return "datetime";
    if (nonempty.every(Array.isArray)) return "array";
    return "string";
  }

  function profile(product, parameters) {
    const records = (product.records || []).slice(0, parameters.sample_size || undefined);
    const requested = parameters.fields || [];
    const names = requested.length ? requested : [...new Set(records.flatMap((record) => Object.keys(record || {})))];
    const fields = names.map((name) => {
      const values = records.map((record) => record?.[name]);
      const nonempty = values.filter(present);
      const distribution = {};
      nonempty.slice(0, 1000).forEach((value) => { const key = typeof value === "object" ? stable(value) : String(value); distribution[key] = (distribution[key] || 0) + 1; });
      const numeric = nonempty.map(Number).filter(Number.isFinite);
      return {
        name, inferred_type: inferredType(values), count: records.length,
        missing_count: records.length - nonempty.length,
        distinct_count: new Set(nonempty.map(stable)).size,
        distribution: Object.fromEntries(Object.entries(distribution).sort((left, right) => right[1] - left[1]).slice(0, 8)),
        statistics: numeric.length ? { minimum: Math.min(...numeric), maximum: Math.max(...numeric), mean: rounded(mean(numeric)) } : {},
        examples: parameters.include_examples ? nonempty.slice(0, 3) : [],
      };
    });
    return { record_count: records.length, field_count: fields.length, fields, properties: { sampled: Boolean(parameters.sample_size && parameters.sample_size < (product.records || []).length), sample_size: records.length }, diagnostics: { backend: "offline.basic_data_profiler" } };
  }

  function governance(product, parameters) {
    const purpose = String(parameters.operation || "analytics");
    const rights = product.rights || {};
    const purposes = rights.purposes || [];
    const violations = [];
    if (purposes.length && !purposes.includes(purpose)) violations.push({ code: "purpose_not_permitted", message: `许可用途不包含 ${purpose}` });
    if (parameters.commercial_use === true && rights.commercial_use !== true) violations.push({ code: "commercial_use_not_permitted", message: "许可不允许商业使用" });
    const fields = [...new Set((product.records || []).flatMap((record) => Object.keys(record || {})))];
    const patterns = [
      [/email|e_mail/i, "email"], [/phone|mobile|tel/i, "phone"], [/address|postcode|zip/i, "address"],
      [/name|patient|subject_id|hadm_id|person/i, "identifier"], [/ssn|identity|passport/i, "government_identifier"],
    ];
    const findings = fields.flatMap((field) => patterns.filter(([pattern]) => pattern.test(field)).map(([, kind]) => ({ field_name: field, kind, message: `字段名匹配 ${kind} 规则` })));
    return {
      product_id: product.product_id, operation: purpose,
      decision: violations.length && parameters.strict_rights !== false ? "deny" : findings.length ? "allow_with_controls" : "allow",
      reasons: violations, violations,
      metadata: { attributes: { source: product.metadata?.provenance?.publisher || product.owner_id, record_count: (product.records || []).length, format: product.data?.format || "records", license: product.rights?.license || "unspecified" } },
      security: { findings, scanned_fields: fields, status: findings.length ? "review" : "clear" },
    };
  }

  function quartiles(values) {
    const sorted = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    if (!sorted.length) return [0, 0];
    const at = (p) => sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p))];
    return [at(0.25), at(0.75)];
  }

  function evaluationMetric(name, records, parameters) {
    const fields = [...new Set(records.flatMap((record) => Object.keys(record || {})))];
    const cells = records.length * fields.length;
    const filled = records.reduce((total, record) => total + fields.filter((field) => present(record?.[field])).length, 0);
    const required = parameters.required_fields || fields;
    if (name === "basic.completeness") return [cells ? filled / cells : 0, "completeness", "higher_is_better", { filled_cells: filled, total_cells: cells }];
    if (name === "basic.duplicate_rate") return [records.length ? (records.length - new Set(records.map(stable)).size) / records.length : 0, "uniqueness", "lower_is_better", { duplicate_records: records.length - new Set(records.map(stable)).size }];
    if (name === "basic.field_validity" || name === "tabular.schema_consistency") {
      const valid = records.filter((record) => required.every((field) => present(record?.[field]))).length;
      return [records.length ? valid / records.length : 0, "validity", "higher_is_better", { valid_records: valid, required_fields: required }];
    }
    if (name === "tabular.numeric_statistics") {
      const numericCells = records.reduce((count, record) => count + fields.filter((field) => present(record?.[field]) && Number.isFinite(Number(record[field]))).length, 0);
      const presentCells = Math.max(1, filled);
      return [numericCells / presentCells, "numeric_validity", "higher_is_better", { numeric_cells: numericCells, present_cells: filled }];
    }
    if (name === "tabular.outlier_rate") {
      let numeric = [];
      fields.forEach((field) => { const values = records.map((record) => record?.[field]).filter((value) => present(value) && Number.isFinite(Number(value))); if (values.length >= 4) numeric = numeric.concat(values.map(Number)); });
      const [q1, q3] = quartiles(numeric); const spread = q3 - q1; const outliers = numeric.filter((value) => value < q1 - 1.5 * spread || value > q3 + 1.5 * spread).length;
      return [numeric.length ? outliers / numeric.length : 0, "outliers", "lower_is_better", { outliers, numeric_values: numeric.length }];
    }
    if (name === "tabular.label_balance") {
      const label = parameters.label_field || "label"; const counts = {};
      records.filter((record) => present(record?.[label])).forEach((record) => { counts[record[label]] = (counts[record[label]] || 0) + 1; });
      const total = Object.values(counts).reduce((sum, value) => sum + value, 0); const classes = Object.keys(counts).length;
      const entropy = total && classes > 1 ? -Object.values(counts).reduce((sum, count) => { const p = count / total; return sum + p * Math.log(p); }, 0) / Math.log(classes) : classes === 1 ? 1 : 0;
      return [entropy, "balance", "higher_is_better", { class_counts: counts }];
    }
    if (name.includes("range_compliance")) {
      const ranges = parameters.numeric_ranges || {}; let checked = 0; let valid = 0;
      records.forEach((record) => Object.entries(ranges).forEach(([field, bounds]) => { if (present(record?.[field]) && Number.isFinite(Number(record[field]))) { checked += 1; valid += Number(record[field]) >= finite(bounds.min, -Infinity) && Number(record[field]) <= finite(bounds.max, Infinity) ? 1 : 0; } }));
      return [checked ? valid / checked : 0, "validity", "higher_is_better", { checked, valid }];
    }
    if (name.includes("text.")) {
      const textFields = parameters.text_fields || fields.filter((field) => records.some((record) => typeof record?.[field] === "string"));
      const texts = records.flatMap((record) => textFields.map((field) => record?.[field]).filter((value) => typeof value === "string"));
      const tokens = texts.flatMap((value) => value.trim().split(/\s+/).filter(Boolean));
      if (name.includes("repetition")) return [tokens.length ? 1 - new Set(tokens).size / tokens.length : 0, "repetition", "lower_is_better", { tokens: tokens.length }];
      return [tokens.length ? Math.min(1, new Set(tokens).size / Math.sqrt(tokens.length * Math.max(1, texts.length))) : 0, "text_quality", "higher_is_better", { records: texts.length, tokens: tokens.length }];
    }
    const signal = unit(productSignal(records, name), 0.5);
    return [signal, "registered_metadata", name.includes("rate") ? "lower_is_better" : "higher_is_better", { source: "record metadata" }];
  }

  function productSignal(records, name) {
    const leaf = name.split(".").at(-1);
    const values = records.map((record) => record?.[leaf] ?? record?.metadata?.[leaf]).filter((value) => Number.isFinite(Number(value))).map(Number);
    return values.length ? mean(values) : 0.5;
  }

  function evaluate(product, parameters) {
    const records = product.records || [];
    const names = parameters.metrics?.length ? parameters.metrics : ["basic.completeness", "basic.duplicate_rate", "basic.field_validity"];
    const metrics = names.map((name) => {
      const [value, dimension, direction, statistics] = evaluationMetric(name, records, parameters);
      return { name, metric: name, dimension, value: unit(value), direction, statistics };
    });
    return { product_id: product.product_id, metrics, summary: { status: "succeeded", completed: metrics.length }, diagnostics: { modality: parameters.modality || "tabular", failures: [], engine: "offline.transparent_metrics" } };
  }

  function safeExpression(expression, variables) {
    const source = String(expression || "base_value * quality");
    if (!/^[A-Za-z0-9_+\-*/().\s]+$/.test(source)) throw new Error("symbolic expression contains unsupported characters");
    const substituted = source.replace(/[A-Za-z_][A-Za-z0-9_]*/g, (name) => {
      if (!(name in variables)) throw new Error(`unknown symbolic variable: ${name}`);
      return `(${finite(variables[name])})`;
    });
    // The character and identifier checks above reduce the expression to numeric arithmetic only.
    return Function(`"use strict"; return (${substituted});`)();
  }

  function valueProduct(product, parameters) {
    const method = String(parameters.method || "valuation.weighted_user_task");
    const base = Math.max(0, finite(parameters.base_value, 100000));
    const code = currency(parameters, product);
    const vector = parameters.evaluation_vector || {};
    let estimates = [];
    const estimate = (target, value, components, explanation = {}) => ({ target_id: target, product_id: product.product_id, value: rounded(Math.max(0, value)), currency: code, unit: "monetary", components, explanation });
    if (method === "valuation.weighted_user_task") {
      const score = unit(mean(Object.values(vector).map(Number)));
      estimates = [estimate(product.product_id, base * score, { weighted_quality: score, base_value: base, raw_value: base * score })];
    } else if (method === "valuation.quality_adjusted") {
      const quality = unit(vector.quality); const uniqueness = unit(vector.uniqueness, 1); const freshness = unit(vector.freshness, 1);
      const taskFactor = 0.7 * quality + 0.3 * uniqueness; const qualityFactor = finite(parameters.quality_floor, 0.5) + (1 - finite(parameters.quality_floor, 0.5)) * taskFactor; const freshnessFactor = 1 - finite(parameters.freshness_weight, 0.2) + finite(parameters.freshness_weight, 0.2) * freshness;
      estimates = [estimate(product.product_id, base * qualityFactor * freshnessFactor, { task_factor: rounded(taskFactor), quality_factor: rounded(qualityFactor), freshness_factor: rounded(freshnessFactor), base_value: base })];
    } else if (method === "valuation.scenario") {
      Object.entries(parameters.scenarios || { base: {}, conservative: { quality: 0.7 }, optimistic: { quality: 1 } }).forEach(([name, overrides]) => {
        const values = { ...vector, ...overrides }; const quality = unit(values.quality); const uniqueness = unit(values.uniqueness, 1); const freshness = unit(values.freshness, 1); const factor = (0.5 + 0.5 * (0.7 * quality + 0.3 * uniqueness)) * (0.8 + 0.2 * freshness);
        estimates.push(estimate(`${product.product_id}@${name}`, base * factor, { scenario_value: rounded(base * factor) }, { scenario: name, assumptions: overrides }));
      });
    } else if (method === "valuation.risk_adjusted") {
      const quality = unit(vector.quality ?? vector.utility); const stdError = Math.max(0, finite(parameters.uncertainty?.std_error ?? vector.std_error)); const penalty = finite(parameters.risk_aversion, 0.5) * 1.96 * base * stdError;
      estimates = [estimate(product.product_id, base * quality - penalty, { quality, raw_value: base * quality, risk_penalty: rounded(penalty), base_value: base }, { risk_aversion: finite(parameters.risk_aversion, 0.5) })];
    } else if (method === "valuation.counterfactual") {
      const baseline = parameters.baseline_vector || {}; const weights = parameters.metric_weights || {}; const keys = new Set([...Object.keys(vector), ...Object.keys(baseline)]); let delta = 0;
      keys.forEach((key) => { delta += finite(weights[key], 1) * (finite(vector[key]) - finite(baseline[key])); });
      estimates = [estimate(product.product_id, base * delta, { incremental_score: rounded(delta), value_per_unit: base }, { observed_vector: vector, baseline_vector: baseline, metric_weights: weights })];
    } else if (method === "valuation.symbolic") {
      const result = safeExpression(parameters.expression, { ...vector, base_value: base });
      estimates = [estimate(product.product_id, result, { expression_value: rounded(result), base_value: base }, { expression: parameters.expression })];
    } else if (method === "valuation.market_context") {
      const factors = parameters.market_factors || {}; const weighted = 0.2 * unit(factors.demand_fit) + 0.2 * unit(factors.quality) + 0.15 * unit(factors.freshness) + 0.15 * unit(factors.scarcity) + 0.15 * unit(factors.rights, 1) + 0.15 * unit(factors.supply_stability); const multiplier = Math.max(finite(parameters.factor_floor), weighted * (1 + finite(parameters.scarcity_weight, 0.25) * unit(factors.scarcity)));
      estimates = [estimate(product.product_id, base * multiplier - finite(parameters.risk_penalty), { market_factor: rounded(weighted), scarcity_multiplier: rounded(multiplier), risk_penalty: finite(parameters.risk_penalty), base_value: base })];
    } else if (method === "valuation.scarcity_adjusted") {
      const premium = 1 + unit(parameters.scarcity) * unit(parameters.task_relevance) * Math.max(0, finite(parameters.scarcity_weight, 0.5));
      estimates = [estimate(product.product_id, base * premium, { scarcity: unit(parameters.scarcity), task_relevance: unit(parameters.task_relevance), scarcity_premium: rounded(premium - 1), base_value: base })];
    } else if (method === "valuation.incremental_coverage") {
      const factor = unit(parameters.incremental_coverage) * unit(parameters.quality) * unit(parameters.task_relevance);
      estimates = [estimate(product.product_id, base * factor, { incremental_coverage: unit(parameters.incremental_coverage), quality: unit(parameters.quality), task_relevance: unit(parameters.task_relevance), coverage_factor: rounded(factor), base_value: base })];
    } else if (method === "valuation.substitution_adjusted") {
      const substitutes = (parameters.substitutes || []).filter((item) => item.available !== false); const substituteCoverage = Math.min(1, substitutes.reduce((best, item) => Math.max(best, unit(item.coverage) * unit(item.quality_ratio) * unit(item.task_relevance, 1)), 0)); const unique = unit(parameters.unique_fraction, 0.8); const factor = unique + (1 - unique) * (1 - substituteCoverage);
      estimates = [estimate(product.product_id, base * factor, { unique_fraction: unique, substitute_coverage: rounded(substituteCoverage), substitution_factor: rounded(factor), base_value: base })];
    } else if (method === "valuation.time_decay") {
      const age = Math.max(0, finite(parameters.age_days)); const halfLife = Math.max(0.01, finite(parameters.half_life_days, 30)); const sensitivity = unit(parameters.time_sensitivity, 1); const rawDecay = 2 ** (-age / halfLife); const decay = (1 - sensitivity) + sensitivity * rawDecay;
      estimates = [estimate(product.product_id, base * decay, { base_value: base, age_days: age, half_life_days: halfLife, time_sensitivity: sensitivity, decay_factor: rounded(decay) })];
    } else if (method === "valuation.update_stream") {
      const rate = Math.max(-0.99, finite(parameters.discount_rate, 0.05)); const updates = parameters.updates || []; const contributions = updates.map((item) => finite(item.marginal_value) * unit(item.delivery_probability, 1) * unit(item.quality, 1) / ((1 + rate) ** Math.max(0, finite(item.period)))); const total = contributions.reduce((sum, value) => sum + value, 0);
      estimates = [estimate(product.product_id, total, { discounted_updates: contributions.map((value) => rounded(value)), discount_rate: rate, base_value: base })];
    } else throw new Error(`offline valuation method is not supported: ${method}`);
    return { product_id: product.product_id, method, valuator: method, mode: "task_specific", estimates, diagnostics: { engine: "offline.transparent_valuation" } };
  }

  function priceProduct(product, parameters) {
    const model = String(parameters.model || "pricing.quality_freshness"); const code = currency(parameters, product); const records = finite(parameters.records, (product.records || []).length); let amount; let components = {};
    if (model === "pricing.cost_plus") { const cost = finite(parameters.preparation_cost) + finite(parameters.operation_cost) + finite(parameters.acquisition_cost); amount = cost * (1 + Math.max(0, finite(parameters.margin_rate))); components = { total_cost: cost, margin_rate: finite(parameters.margin_rate), margin: amount - cost }; }
    else if (model === "pricing.value_based") { const value = finite(parameters.estimated_value); amount = value * unit(parameters.buyer_share, 0.5); amount = Math.min(finite(parameters.ceiling, amount), Math.max(finite(parameters.floor), amount)); components = { estimated_value: value, buyer_share: unit(parameters.buyer_share, 0.5) }; }
    else if (model === "pricing.usage_based") { const fixed = finite(parameters.fixed_fee); const recordCharge = records * finite(parameters.per_record); const queryCharge = finite(parameters.queries) * finite(parameters.per_query); const computeCharge = finite(parameters.compute_seconds) * finite(parameters.per_compute_second); amount = fixed + recordCharge + queryCharge + computeCharge; components = { fixed_fee: fixed, record_charge: recordCharge, query_charge: queryCharge, compute_charge: computeCharge }; }
    else if (model === "pricing.quality_freshness") { const quality = unit(parameters.quality); const freshness = unit(parameters.freshness); const weight = unit(parameters.quality_weight, 0.7); const factor = weight * quality + (1 - weight) * freshness; amount = finite(parameters.base_price) * factor; amount = Math.min(finite(parameters.ceiling, amount), Math.max(finite(parameters.floor), amount)); components = { base_price: finite(parameters.base_price), quality, freshness, adjustment_factor: rounded(factor) }; }
    else if (model === "pricing.tiered_usage") { const usage = Math.max(0, finite(parameters.usage)); const tiers = parameters.tiers || [{ upto: 100, unit_price: 30 }, { upto: 1000, unit_price: 20 }, { upto: Infinity, unit_price: 10 }]; let remaining = usage; let previous = 0; amount = finite(parameters.fixed_fee); const charges = []; for (const tier of tiers) { const limit = finite(tier.upto, Infinity); const units = Math.max(0, Math.min(remaining, limit - previous)); const charge = units * finite(tier.unit_price); charges.push({ units, unit_price: finite(tier.unit_price), charge }); amount += charge; remaining -= units; previous = limit; if (remaining <= 0) break; } components = { usage, tier_charges: charges }; }
    else if (model === "pricing.subscription") { const overage = Math.max(0, finite(parameters.usage) - finite(parameters.included_usage)); const overageCharge = overage * finite(parameters.overage_unit_price); const subtotal = finite(parameters.period_fee) + overageCharge; amount = subtotal * (1 - unit(parameters.commitment_discount)); components = { period_fee: finite(parameters.period_fee), included_usage: finite(parameters.included_usage), usage: finite(parameters.usage), overage_units: overage, overage_charge: overageCharge, commitment_discount: unit(parameters.commitment_discount) }; }
    else if (model === "pricing.risk_adjusted") { const basePrice = finite(parameters.estimated_value) * unit(parameters.buyer_share, 0.5); const penalty = 1.96 * Math.max(0, finite(parameters.std_error)); amount = (basePrice - penalty) * Math.max(0, finite(parameters.rights_factor, 1)); amount = Math.min(finite(parameters.ceiling, amount), Math.max(finite(parameters.floor), amount)); components = { estimated_value: finite(parameters.estimated_value), base_price: basePrice, uncertainty_penalty: penalty, rights_factor: finite(parameters.rights_factor, 1) }; }
    else if (model === "pricing.price_range") { const midpoint = Math.max(finite(parameters.cost_floor), finite(parameters.estimated_value) * unit(parameters.seller_share, 0.5)); const comparable = finite(parameters.comparable_price, midpoint); const weight = unit(parameters.comparable_weight, 0.25); amount = midpoint * (1 - weight) + comparable * weight; components = { value_midpoint: midpoint, comparable_price: comparable, comparable_weight: weight, lower: Math.max(finite(parameters.cost_floor), amount - 1.96 * finite(parameters.value_std_error)), upper: amount + 1.96 * finite(parameters.value_std_error) }; }
    else if (model === "pricing.comparable") { const candidates = (parameters.comparables || []).filter((item) => finite(item.price) >= 0); if (!candidates.length) throw new Error("no comparable prices"); const benchmark = mean(candidates.map((item) => finite(item.price))); amount = benchmark * Math.max(0, finite(parameters.quality_ratio, 1)) * Math.max(0, finite(parameters.freshness_ratio, 1)) * Math.max(0, finite(parameters.rights_ratio, 1)); components = { benchmark_price: benchmark, comparable_count: candidates.length, quality_ratio: finite(parameters.quality_ratio, 1), freshness_ratio: finite(parameters.freshness_ratio, 1), rights_ratio: finite(parameters.rights_ratio, 1) }; }
    else if (model === "pricing.rights_differentiated") { const rights = product.rights || {}; const premiums = (rights.commercial_use ? finite(parameters.commercial_premium, 0.2) : 0) + (rights.redistribution ? finite(parameters.redistribution_premium, 0.3) : 0) + (rights.exclusivity && !["none", "non_exclusive"].includes(rights.exclusivity) ? finite(parameters.exclusivity_premium, 0.5) : 0) + (rights.jurisdictions || []).length * finite(parameters.per_jurisdiction_premium, 0.02); const multiplier = 1 + Math.max(0, premiums); amount = finite(parameters.base_price) * multiplier; components = { base_price: finite(parameters.base_price), rights_multiplier: multiplier }; }
    else if (model === "pricing.freshness_tier") { const age = Math.max(0, finite(parameters.age_days)); const factor = age <= 1 ? 1.2 : age <= 7 ? 1 : age <= 30 ? 0.8 : 0.5; amount = finite(parameters.base_price) * factor; components = { base_price: finite(parameters.base_price), age_days: age, freshness_factor: factor }; }
    else if (model === "pricing.version_delta") { const factor = Math.max(0, 1 + finite(parameters.coverage_weight, 0.5) * unit(parameters.incremental_coverage) + finite(parameters.quality_weight, 0.3) * Math.max(-1, finite(parameters.quality_gain)) + finite(parameters.volume_weight, 0.2) * Math.max(-1, finite(parameters.volume_growth))); amount = finite(parameters.previous_price) * factor; components = { previous_price: finite(parameters.previous_price), version_factor: factor, incremental_coverage: unit(parameters.incremental_coverage), quality_gain: finite(parameters.quality_gain), volume_growth: finite(parameters.volume_growth) }; }
    else if (model === "pricing.expected_revenue") { const budget = Math.max(1, finite(parameters.buyer_budget, 100000)); const quality = unit(parameters.quality, 0.9); const freshness = unit(parameters.freshness, 0.85); const scored = (parameters.candidate_prices || []).map(Number).filter(Number.isFinite).map((price) => { const probability = 1 / (1 + Math.exp(5 * (price / budget - (0.55 + 0.25 * quality + 0.2 * freshness)))); return { price, probability, expected_revenue: price * probability }; }); if (!scored.length) throw new Error("candidate_prices must contain at least one price"); const selected = scored.sort((left, right) => right.expected_revenue - left.expected_revenue || left.price - right.price)[0]; amount = selected.price; components = { selected_probability: rounded(selected.probability), expected_revenue: rounded(selected.expected_revenue), candidate_count: scored.length }; }
    else throw new Error(`offline pricing model is not supported: ${model}`);
    const normalized = { ...parameters, model, currency: code, records };
    return { quote_id: identifier("quote"), product_id: product.product_id, pricing_model: model, price: money(amount, code), components, applied_constraints: [], normalized_parameters: normalized, trace: [{ step: "normalize_parameters", status: "succeeded", model }, { step: "quote", status: "succeeded", amount: rounded(amount), currency: code }], diagnostics: { engine: "offline.transparent_pricing" } };
  }

  function market(products, parameters) {
    const mechanism = String(parameters.mechanism || "mcafee_double_auction"); const known = new Set(products.map((item) => item.product_id)); const bids = copy(parameters.bids || []); const asks = copy(parameters.asks || []); const currencies = new Set([...bids.map((item) => item.currency || parameters.currency || "CNY"), ...asks.map((item) => item.currency || parameters.currency || "CNY")]); if (currencies.size > 1) throw new Error("market orders must use a single currency"); const code = [...currencies][0] || parameters.currency || "CNY";
    [...bids, ...asks].forEach((order) => { (order.product_ids || []).forEach((id) => { if (!known.has(id)) throw new Error(`unknown product id: ${id}`); }); });
    const allocations = []; const payments = []; const bundleMatches = []; const attributeMatches = [];
    const sortedBids = bids.sort((left, right) => finite(right.amount) - finite(left.amount)); const sortedAsks = asks.sort((left, right) => finite(left.reserve) - finite(right.reserve));
    const allocate = (bid, ask, price, quantity = 1) => { const productIds = bid.product_ids?.length ? bid.product_ids : ask.product_ids; allocations.push({ allocation_id: identifier("allocation"), buyer_id: bid.buyer_id, seller_id: ask.seller_id, product_ids: productIds, quantity, reported_value: money(finite(bid.amount), code), metadata: { unit_price: rounded(price) } }); payments.push({ payment_id: identifier("payment"), payer_id: bid.buyer_id, payee_id: ask.seller_id, product_ids: productIds, amount: money(price * quantity, code), reason: mechanism }); };
    if (["first_price_auction", "second_price_auction", "vcg"].includes(mechanism)) { if (!sortedBids.length || !sortedAsks.length) throw new Error("auction requires bids and asks"); const winner = sortedBids[0]; const ask = sortedAsks[0]; if (finite(winner.amount) >= finite(ask.reserve)) allocate(winner, ask, mechanism === "first_price_auction" ? finite(winner.amount) : Math.max(finite(ask.reserve), finite(sortedBids[1]?.amount, finite(ask.reserve)))); }
    else if (mechanism === "mcafee_double_auction") { const count = Math.min(sortedBids.length, sortedAsks.length); for (let index = 0; index < count && finite(sortedBids[index].amount) >= finite(sortedAsks[index].reserve); index += 1) allocate(sortedBids[index], sortedAsks[index], (finite(sortedBids[index].amount) + finite(sortedAsks[index].reserve)) / 2, Math.min(finite(sortedBids[index].quantity, 1), finite(sortedAsks[index].quantity, 1))); }
    else if (["budget_feasible_procurement", "budget_aware_procurement", "quality_aware_procurement"].includes(mechanism)) { let budget = Math.max(0, finite(parameters.budget)); const buyerId = parameters.buyer_id || sortedBids[0]?.buyer_id || "buyer"; let candidates = sortedAsks; if (mechanism === "quality_aware_procurement") candidates = [...sortedAsks].sort((left, right) => (finite(right.metadata?.quality, productQuality(products, right.product_ids)) / Math.max(1e-9, finite(right.reserve))) - (finite(left.metadata?.quality, productQuality(products, left.product_ids)) / Math.max(1e-9, finite(left.reserve)))); candidates.forEach((ask) => { const reserve = finite(ask.reserve); if (reserve <= budget) { const bid = { buyer_id: buyerId, product_ids: ask.product_ids, amount: budget }; allocate(bid, ask, reserve, finite(ask.quantity, 1)); budget -= reserve * finite(ask.quantity, 1); } }); }
    else if (mechanism === "multi_unit_uniform_price") { const count = Math.min(sortedBids.length, sortedAsks.length); const accepted = []; for (let index = 0; index < count && finite(sortedBids[index].amount) >= finite(sortedAsks[index].reserve); index += 1) accepted.push([sortedBids[index], sortedAsks[index]]); const clearing = accepted.length ? Math.max(...accepted.map((pair) => finite(pair[1].reserve))) : 0; accepted.forEach(([bid, ask]) => allocate(bid, ask, clearing, Math.min(finite(bid.quantity, 1), finite(ask.quantity, 1)))); }
    else if (mechanism === "bundle_matching") { let budget = Math.max(0, finite(parameters.budget)); sortedBids.forEach((bid) => { const compatible = sortedAsks.filter((ask) => (bid.product_ids || []).every((id) => (ask.product_ids || []).includes(id) || (ask.product_ids || []).length === 1 && (ask.product_ids || []).includes(id))); const selected = (bid.product_ids || []).map((id) => compatible.find((ask) => (ask.product_ids || []).includes(id))).filter(Boolean); const unique = [...new Map(selected.map((ask) => [ask.ask_id || `${ask.seller_id}:${ask.product_ids}`, ask])).values()]; const cost = unique.reduce((sum, ask) => sum + finite(ask.reserve), 0); if (unique.length && cost <= finite(bid.amount) && cost <= budget) { bundleMatches.push({ mode: bid.constraints?.bundle_mode || "and", buyer_id: bid.buyer_id, product_ids: bid.product_ids, seller_ids: unique.map((ask) => ask.seller_id), reported_value: money(finite(bid.amount), code), cost: money(cost, code), surplus: money(finite(bid.amount) - cost, code) }); unique.forEach((ask) => payments.push({ payer_id: bid.buyer_id, payee_id: ask.seller_id, product_ids: ask.product_ids, amount: money(finite(ask.reserve), code), reason: mechanism })); budget -= cost; } }); }
    else if (mechanism === "multi_attribute_matching") { sortedBids.forEach((bid) => { const matches = sortedAsks.filter((ask) => (ask.product_ids || []).some((id) => (bid.product_ids || []).includes(id)) && finite(ask.reserve) <= finite(bid.amount)); if (!matches.length) return; const ask = matches.sort((left, right) => attributeScore(products, right, parameters.match_weights) - attributeScore(products, left, parameters.match_weights))[0]; attributeMatches.push({ buyer_id: bid.buyer_id, seller_id: ask.seller_id, product_id: ask.product_ids[0], quantity: Math.min(finite(bid.quantity, 1), finite(ask.quantity, 1)), score: rounded(attributeScore(products, ask, parameters.match_weights)), price: money(finite(ask.reserve), code) }); payments.push({ payer_id: bid.buyer_id, payee_id: ask.seller_id, product_ids: ask.product_ids, amount: money(finite(ask.reserve), code), reason: mechanism }); }); }
    else throw new Error(`offline market mechanism is not supported: ${mechanism}`);
    const outcome = { mechanism, allocations, payments, diagnostics: { bids: bids.length, asks: asks.length, trades: allocations.length + bundleMatches.length + attributeMatches.length } };
    return { outcome, bundle_selection: mechanism === "bundle_matching" ? { matches: bundleMatches, method: "offline.greedy_bundle", diagnostics: { candidate_count: bids.length } } : null, multi_attribute_matches: attributeMatches, properties: { individually_rational: payments.every((payment) => finite(payment.amount.amount) >= 0), budget_feasible: true, weakly_budget_balanced: true }, audit: { status: "passed", findings: [], checked_allocations: allocations.length }, gaps: [], demand_segments: [], supply_segments: [], market_health: { status: allocations.length || bundleMatches.length || attributeMatches.length ? "active" : "no_trade", trade_count: allocations.length + bundleMatches.length + attributeMatches.length }, anomalies: [], order_book: { bids: sortedBids, asks: sortedAsks }, trace: [{ step: "normalize_orders", status: "succeeded", bids: bids.length, asks: asks.length, products: products.length }, { step: "clear_market", status: "succeeded", mechanism, allocations: allocations.length, payments: payments.length }, { step: "diagnostics", status: "succeeded" }] };
  }

  function productQuality(products, ids) { const selected = products.filter((product) => (ids || []).includes(product.product_id)); return selected.length ? mean(selected.map((product) => unit(product.metadata?.quality, 0.5))) : 0.5; }
  function attributeScore(products, ask, weights = {}) { const product = products.find((item) => (ask.product_ids || []).includes(item.product_id)) || {}; const normalized = { price: 1 / (1 + Math.max(0, finite(ask.reserve)) / 100000), quality: unit(product.metadata?.quality, 0.5), freshness: unit(product.metadata?.freshness, 0.5), reputation: unit(ask.metadata?.reputation, 0.9), rights: product.rights?.commercial_use === false ? 0.5 : 1 }; const effective = { price: 0.4, quality: 0.25, freshness: 0.15, reputation: 0.1, rights: 0.1, ...weights }; const total = Object.values(effective).reduce((sum, value) => sum + Math.max(0, finite(value)), 0) || 1; return Object.entries(effective).reduce((sum, [key, weight]) => sum + Math.max(0, finite(weight)) * normalized[key], 0) / total; }

  function execute(operation, products, parameters = {}) {
    if (!Array.isArray(products) || !products.length) throw new Error(`${operation} requires at least one product`);
    if (operation !== "market" && products.length !== 1) throw new Error(`${operation} accepts one product`);
    const product = products[0];
    if (operation === "governance") return { result: governance(product, parameters), producer: "offline.rights_policy_evaluator" };
    if (operation === "profile") return { result: profile(product, parameters), producer: "offline.basic_data_profiler" };
    if (operation === "evaluation") return { result: evaluate(product, parameters), producer: "offline.composite_evaluator" };
    if (operation === "valuation") { const method = String(parameters.method || "valuation.weighted_user_task"); return { result: valueProduct(product, parameters), producer: `offline.${method}` }; }
    if (operation === "pricing") { const model = String(parameters.model || "pricing.quality_freshness"); return { result: priceProduct(product, parameters), producer: `offline.${model}` }; }
    if (operation === "market") { const mechanism = String(parameters.mechanism || "mcafee_double_auction"); return { result: market(products, parameters), producer: `offline.${mechanism}` }; }
    throw new Error(`offline operation is not supported: ${operation}`);
  }

  function extractMetrics(operation, result, metrics) {
    if (operation === "governance") metrics.rights_decision = result.decision;
    if (operation === "profile") { metrics.record_count = result.record_count; metrics.field_count = result.fields.length; }
    if (operation === "evaluation") { const values = result.metrics.map((item) => item.direction === "lower_is_better" ? 1 - unit(item.value) : item.direction === "higher_is_better" ? unit(item.value) : null).filter((value) => value !== null); if (values.length) metrics.quality_score = rounded(mean(values), 4); }
    if (operation === "valuation" && result.estimates.length) { metrics.value = finite(result.estimates[0].value); metrics.value_currency = result.estimates[0].currency; }
    if (operation === "pricing") { metrics.price = finite(result.price?.amount); metrics.price_currency = result.price?.currency; }
  }

  function persistStage(workspace, batchId, productIds, operation, execution, startedAt, inputArtifactIds, inputRunIds) {
    const artifactId = identifier("artifact"); const runId = identifier("run"); const finishedAt = now();
    const artifact = { artifact_id: artifactId, kind: operation, producer: execution.producer, batch_id: batchId, product_id: productIds[0], product_ids: productIds, payload: execution.result, created_at: finishedAt };
    const run = { run_id: runId, batch_id: batchId, operation, product_id: productIds[0], product_ids: productIds, status: "succeeded", artifact_id: artifactId, producer: execution.producer, started_at: startedAt, finished_at: finishedAt, duration_ms: 0, input_artifact_ids: inputArtifactIds, input_run_ids: inputRunIds };
    workspace.artifacts.push(artifact); workspace.runs.push(run); return { artifactId, runId };
  }

  function executeBatch(workspace, request) {
    if (!request.product_ids?.length || !request.operations?.length) throw new Error("batch requires products and operations");
    const products = request.product_ids.map((id) => workspace.products.find((item) => item.product_id === id)); const missing = request.product_ids.filter((id, index) => !products[index]); if (missing.length) throw new Error(`products not found: ${missing.join(", ")}`);
    const batchId = identifier("batch"); const startedAt = now(); const selected = new Set(request.product_ids); const inputArtifactIds = request.include_related_content === false ? [...(request.input_artifact_ids || [])] : [...new Set([...(request.input_artifact_ids || []), ...workspace.artifacts.filter((item) => selected.has(item.product_id) || item.product_ids?.some((id) => selected.has(id))).map((item) => item.artifact_id)])]; const inputRunIds = request.include_related_content === false ? [] : workspace.runs.filter((item) => selected.has(item.product_id) || item.product_ids?.some((id) => selected.has(id))).map((item) => item.run_id);
    let succeeded = 0; let failed = 0;
    const items = products.map((product) => { const item = { product_id: product.product_id, title: product.title || product.product_id, status: "queued", metrics: { record_count: product.data?.record_count ?? product.records?.length ?? 0, quality_signal: product.metadata?.quality, freshness: product.metadata?.freshness, asking_price: product.metadata?.asking_price }, stages: [] }; let ok = 0; let errors = 0;
      for (const operation of request.operations.filter((name) => name !== "market")) { const stageStarted = now(); const parameters = copy(request.parameters?.[operation] || {}); if (operation === "valuation") { parameters.evaluation_vector ||= {}; (parameters.product_signals || []).forEach((name) => { if (product.metadata?.[name] !== undefined) parameters.evaluation_vector[`product_${name}`] = product.metadata[name]; }); }
        try { const execution = execute(operation, [product], parameters); const ids = persistStage(workspace, batchId, [product.product_id], operation, execution, stageStarted, inputArtifactIds, inputRunIds); item.stages.push({ operation, status: "succeeded", producer: execution.producer, run_id: ids.runId, artifact_id: ids.artifactId, duration_ms: 0, input_artifact_ids: inputArtifactIds, input_run_ids: inputRunIds, result: execution.result }); extractMetrics(operation, execution.result, item.metrics); ok += 1; succeeded += 1; }
        catch (error) { item.stages.push({ operation, status: "failed", duration_ms: 0, input_artifact_ids: inputArtifactIds, input_run_ids: inputRunIds, error: { code: "execution_error", message: error.message } }); errors += 1; failed += 1; if (request.fail_fast) break; }
      }
      item.status = errors ? ok ? "partial" : "failed" : "succeeded"; return item; });
    let marketStage = null;
    if (request.operations.includes("market") && !(request.fail_fast && failed)) { const stageStarted = now(); try { const execution = execute("market", products, request.parameters?.market || {}); const ids = persistStage(workspace, batchId, request.product_ids, "market", execution, stageStarted, inputArtifactIds, inputRunIds); marketStage = { operation: "market", status: "succeeded", producer: execution.producer, run_id: ids.runId, artifact_id: ids.artifactId, duration_ms: 0, input_artifact_ids: inputArtifactIds, input_run_ids: inputRunIds, result: execution.result }; succeeded += 1; } catch (error) { marketStage = { operation: "market", status: "failed", duration_ms: 0, input_artifact_ids: inputArtifactIds, input_run_ids: inputRunIds, error: { code: "execution_error", message: error.message } }; failed += 1; } }
    const status = failed ? succeeded ? "partial" : "failed" : "succeeded"; const values = items.map((item) => item.metrics.value).filter(Number.isFinite); const prices = items.map((item) => item.metrics.price).filter(Number.isFinite);
    const batch = { batch_id: batchId, label: String(request.label || "Untitled batch").trim() || "Untitled batch", scenario_id: request.scenario_id || null, status, seed: finite(request.seed), fail_fast: Boolean(request.fail_fast), input_artifact_ids: inputArtifactIds, input_run_ids: inputRunIds, operations: request.operations, product_ids: request.product_ids, started_at: startedAt, finished_at: now(), summary: { products: items.length, succeeded_items: items.filter((item) => item.status === "succeeded").length, partial_items: items.filter((item) => item.status === "partial").length, failed_items: items.filter((item) => item.status === "failed").length, succeeded_stages: succeeded, failed_stages: failed, total_value: rounded(values.reduce((sum, value) => sum + value, 0), 2), total_price: rounded(prices.reduce((sum, value) => sum + value, 0), 2) }, items, market_stage: marketStage };
    workspace.batches.push(copy(batch)); return batch;
  }

  function generateAgentOrders(workspace, request) {
    const participants = workspace.participants.filter((item) => request.participant_ids.includes(item.participant_id)); const products = workspace.products.filter((item) => request.product_ids.includes(item.product_id)); const orders = []; const skipped = [];
    participants.forEach((participant) => { const agent = participant.agent_config || {}; if (!agent.enabled) { skipped.push({ participant_id: participant.participant_id, reason: "代理未启用" }); return; } const applicable = agent.preferred_mechanisms || []; if (applicable.length && !applicable.includes(request.mechanism)) { skipped.push({ participant_id: participant.participant_id, reason: "机制不在代理适用范围" }); return; }
      const owned = participant.role === "seller" ? products.filter((product) => !participant.product_ids?.length || participant.product_ids.includes(product.product_id)) : products; if (!owned.length) { skipped.push({ participant_id: participant.participant_id, reason: "没有适用资产" }); return; }
      if (participant.role === "buyer") { const references = owned.map((product) => finite(product.metadata?.asking_price)); const reference = mean(references); const quality = mean(owned.map((product) => unit(product.metadata?.quality, 0.5))); const freshness = mean(owned.map((product) => unit(product.metadata?.freshness, 0.5))); const rationality = unit(agent.rationality, 1); const style = { conservative: 0.85, balanced: 1, aggressive: 1.12, exploratory: 1.05 }[agent.style] || 1; const amount = Math.min(finite(participant.budget), reference * (0.7 + 0.2 * quality + 0.1 * freshness) * (0.8 + 0.2 * rationality) * style); orders.push({ order_id: identifier("agent-bid"), side: "bid", participant_id: participant.participant_id, product_ids: owned.map((product) => product.product_id), amount: rounded(amount), quantity: 1, currency: participant.currency || owned[0].metadata?.currency || "CNY", bundle_mode: agent.bundle_mode || (owned.length > 1 ? "and" : "single"), agent_generated: true, explanation: { model: agent.model, style: agent.style, rationality, reference_price: rounded(reference), preference_score: rounded(0.5 * quality + 0.5 * freshness), price_basis: "注册参考价、质量、新鲜度、预算与代理风格" } }); }
      else if (participant.role === "seller") owned.forEach((product) => { const reference = finite(product.metadata?.asking_price); const rationality = unit(agent.rationality, 1); const style = { conservative: 1.08, balanced: 1, aggressive: 1.15, exploratory: 0.95 }[agent.style] || 1; const reserveTarget = finite(participant.strategy_parameters?.reserve_target, finite(participant.budget)); const amount = Math.max(reserveTarget, reference * (0.85 + 0.15 * rationality) * style); orders.push({ order_id: identifier("agent-ask"), side: "ask", participant_id: participant.participant_id, product_ids: [product.product_id], amount: rounded(amount), quantity: 1, currency: participant.currency || product.metadata?.currency || "CNY", bundle_mode: "single", agent_generated: true, explanation: { model: agent.model, style: agent.style, rationality, reference_price: reference, price_basis: "注册参考价、保留目标与代理风格" } }); });
    });
    return { orders, diagnostics: { generated: orders.length, skipped, mechanism: request.mechanism, participants: participants.length, products: products.length } };
  }

  return { execute, executeBatch, generateAgentOrders };
})();

if (typeof module !== "undefined" && module.exports) module.exports = OfflineExecutionEngine;
