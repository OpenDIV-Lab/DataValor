(() => {
  "use strict";

  const STAGES = {
    govern: {
      id: "govern", code: "01 / DATA", accent: "#52d5da", label: "注册与治理",
      title: "把原始记录注册为带权利与来源的数据产品",
      summary: "DataValor 先保留数据引用、版本、所有者、允许用途和来源证据，再判断目标任务是否符合权利约束。",
      inputs: ["原始记录、schema 与内容校验", "所有者、版本、来源与用途条款", "目标任务和商业使用上下文"],
      method: "RightsPolicyEvaluator", formula: "eligible = rights ⊨ requested_use",
      methodNote: "来源、用途、商业使用、地域、期限与再分发条件分别保留。",
      outputs: ["DataProduct 与 RightsBundle", "GovernanceReport 与准入决定", "来源、版本和上游引用"],
      metrics: [{ label: "用途准入", value: "ALLOW" }, { label: "来源记录", value: "2+" }, { label: "版本身份", value: "tracked" }],
      artifact: "DataProduct"
    },
    evaluate: {
      id: "evaluate", code: "02 / EVIDENCE", accent: "#6ba8ff", label: "画像与评估",
      title: "把数据特征与任务适用性变成可检查证据",
      summary: "质量指标保留维度、方向、单位、统计量和诊断；任务效用与通用数据质量分开记录。",
      inputs: ["已准入的数据产品与记录", "数据模态和关键字段要求", "下游任务、基线和评价指标"],
      method: "CompositeEvaluator", formula: "evidence = metric(data, task, modality)",
      methodNote: "支持表格、文本、图像、音频、视频和多模态指标；higher/lower/target-is-best 方向显式保存。",
      outputs: ["DatasetProfile 与字段统计", "EvaluationReport 与 MetricResult", "TaskUtilityResult 与置信信息"],
      metrics: [{ label: "完整性", value: "0.97" }, { label: "字段有效性", value: "0.95" }, { label: "任务覆盖", value: "0.91" }],
      artifact: "EvaluationReport"
    },
    value: {
      id: "value", code: "03 / VALUE", accent: "#a78bfa", label: "任务估值",
      title: "估计数据对指定决策任务的增量价值",
      summary: "估值消费质量证据、任务表现、基线、成本和风险上下文，但不会把通用质量分数直接当作成交价。",
      inputs: ["已通过权利检查的数据产品", "候选数据与基线任务表现", "买方任务、成本、风险和预算上下文"],
      method: "CounterfactualValuator", formula: "ΔU = U(task | data) − U(task | baseline)",
      methodNote: "保留 evaluation vector、baseline vector、metric weights、币种和不确定性假设。",
      outputs: ["ValuationReport 与 ValueEstimate", "按任务指标分解的价值依据", "producer、输入引用和 diagnostics"],
      metrics: [{ label: "增量效用", value: "+0.12" }, { label: "任务覆盖", value: "0.94" }, { label: "不确定性", value: "tracked" }],
      artifact: "ValuationReport"
    },
    price: {
      id: "price", code: "04 / PRICE", accent: "#f3bd62", label: "形成报价",
      title: "把价值、成本与商业条款转化为可解释报价",
      summary: "报价模型明确使用了成本、价值、质量、时效、用量、权利或需求中的哪些依据，并保留每个价格组件。",
      inputs: ["估值报告、质量与新鲜度证据", "服务成本、用量和交付周期", "许可范围、价格上下限与币种"],
      method: "SubscriptionPricingModel", formula: "quote = period_fee + overage − discount",
      methodNote: "PriceQuote 是卖方或平台报价，不等于机制清算后买方实际支付。",
      outputs: ["PriceQuote 与报价组件", "订阅、用量或权利条款", "模型、参数和约束诊断"],
      metrics: [{ label: "计费形态", value: "subscription" }, { label: "报价依据", value: "4 signals" }, { label: "币种", value: "USD" }],
      artifact: "PriceQuote"
    },
    market: {
      id: "market", code: "05 / MARKET", accent: "#f08a91", label: "配置与支付",
      title: "让多个参与者和数据产品进入同一个机制",
      summary: "买卖方可由代理依据预算、偏好、质量和保留价生成订单；机制再决定配置、支付、收入与可行性。",
      inputs: ["买方预算、偏好和组合需求", "卖方报价、保留价和可供产品", "市场机制、供给与约束"],
      method: "BundleDemandMatcher", formula: "allocation = argmax Σ reported_value(bundle)",
      methodNote: "支持拍卖、双边市场、预算采购、AND/XOR 组合需求和多属性匹配。",
      outputs: ["PricingOutcome 与配置结果", "支付、收入和订单簿", "预算、个体理性与机制审计"],
      metrics: [{ label: "参与者", value: "4" }, { label: "数据产品", value: "3" }, { label: "约束", value: "AND" }],
      artifact: "PricingOutcome"
    },
    realize: {
      id: "realize", code: "06 / OUTCOME", accent: "#70d9a6", label: "审计与反馈",
      title: "把市场决定、运行证据和实际使用反馈留在同一链路",
      summary: "最终 artifact 不只写“已完成”，而是保留配置、支付、机制性质、输入谱系和后续使用信号，供下一轮校准。",
      inputs: ["配置、支付与机制诊断", "实际查询、交付和使用记录", "任务表现、接受率与续约反馈"],
      method: "audit_pricing_outcome", formula: "next_model ← calibrate(outcome, usage_feedback)",
      methodNote: "观测到的实际使用与场景假设分开保存，避免把模拟结果误写成市场事实。",
      outputs: ["机制审计与 MarketSnapshot", "UsageAggregate 与反馈信号", "可复现运行记录和完整 lineage"],
      metrics: [{ label: "审计检查", value: "enabled" }, { label: "反馈状态", value: "tracked" }, { label: "谱系", value: "complete" }],
      artifact: "UsageAggregate"
    }
  };

  function previewRow(label, value, detail = "", tone = "") {
    return { label, value, detail, tone };
  }

  function buildStageScenes(config) {
    const demo = config.demo;
    const run = (stage, selection, status = "ready") => ({
      id: `${demo.runId}-${stage.toUpperCase()}`,
      operator: demo.operator,
      selection,
      status
    });
    const pane = (title, meta, rows, artifact = "") => ({ title, meta, rows, artifact });
    const evidenceRows = config.evidence.map((metric) => previewRow(metric.label, metric.value, "通过质量门槛", "positive"));
    const signalRows = config.signals.map((metric) => previewRow(metric.label, metric.value, "任务效用输入", "accent"));

    return {
      govern: {
        run: run("govern", `${demo.assets.length} 个候选资产`),
        action: { label: "Run rights check", detail: "policy evaluation" },
        input: pane("候选资产与来源", "资产注册队列 · 原始内容保持只读", demo.assets),
        config: pane("治理策略", config.methods.govern, [
          previewRow("requested_use", config.rights, "当前研究任务申请"),
          previewRow("commercial_use", demo.commercialUse, "合同用途约束"),
          previewRow("version_policy", "immutable + PIT", "保留可复现快照")
        ]),
        output: pane("准入与权利报告", "来源、许可和版本逐项留证", demo.governance, "GovernanceReport")
      },
      evaluate: {
        run: run("evaluate", `${demo.sample.length} 条可展开样本`, "running preview"),
        action: { label: "Run quality evaluation", detail: "profile + metric suite" },
        input: pane("数据采样预览", `${demo.modality} · 从已准入资产抽样`, demo.sample),
        config: pane("质量评估配置", config.methods.evaluate, [
          previewRow("modality", demo.modality, "选择对应模态指标"),
          previewRow("sample_policy", demo.samplePolicy, "固定种子，可复现"),
          previewRow("quality_gate", demo.qualityGate, "不合格资产停止流转")
        ]),
        output: pane("质量证据", "指标方向、单位和诊断均被保存", evidenceRows, "EvaluationReport")
      },
      value: {
        run: run("value", demo.valueSelection, "model configured"),
        action: { label: "Run valuation", detail: "counterfactual task utility" },
        input: pane("基线与候选表现", "同一任务、同一时间切分", demo.baseline),
        config: pane("估值器与权重", config.methods.value, demo.valueConfig),
        output: pane("增量价值分解", "估值不等于报价或支付", demo.valuation.length ? demo.valuation : signalRows, "ValuationReport")
      },
      price: {
        run: run("price", demo.priceSelection, "quote draft"),
        action: { label: "Generate quote", detail: "pricing model + terms" },
        input: pane("报价依据", "价值、质量、成本和权利分别输入", demo.priceBasis),
        config: pane("价格模型参数", config.methods.price, demo.priceConfig),
        output: pane("可解释报价", "场景商业条款 · 非来源方公开售价", demo.quote, "PriceQuote")
      },
      market: {
        run: run("market", `${config.participantCount} 个代理 · ${demo.assets.length} 个产品`, "clearing preview"),
        action: { label: "Clear market", detail: "agents + allocation + payment" },
        input: pane("参与者与代理订单", "买卖方策略自动生成订单", demo.orders),
        config: pane("市场与清算约束", config.methods.market, demo.marketConfig),
        output: pane("配置与支付", "配置、报价与实际支付分开记录", demo.allocation, "PricingOutcome")
      },
      realize: {
        run: run("realize", demo.outcomeSelection, "observed window"),
        action: { label: "Audit & calibrate", detail: "outcome + usage feedback" },
        input: pane("交付与使用事件", "仅记录场景中可观测的后验信号", demo.usage),
        config: pane("审计与反馈窗口", config.methods.realize, [
          previewRow("window", demo.feedbackWindow, "固定观测周期"),
          previewRow("audit", "budget · IR · lineage", "机制与数据证据联合审计"),
          previewRow("update_policy", "evidence only", "不把模拟结果写成事实")
        ]),
        output: pane("结果与下一轮校准", "历史属性变化被绑定到同一资产", demo.feedback, "UsageAggregate")
      }
    };
  }

  function withStageMetrics(config) {
    const common = {
      govern: [{ label: "权利适配", value: config.rights }, { label: "来源", value: String(config.sourceCount) }, { label: "版本", value: "tracked" }],
      evaluate: config.evidence,
      value: config.signals,
      price: [{ label: "价格形态", value: config.priceShape }, { label: "报价依据", value: config.priceBasis }, { label: "币种", value: "USD" }],
      market: [{ label: "参与者", value: String(config.participantCount) }, { label: "产品", value: "3" }, { label: "机制约束", value: config.marketConstraint }],
      realize: [{ label: "决策证据", value: "retained" }, { label: "使用反馈", value: "tracked" }, { label: "谱系", value: "complete" }]
    };
    return { ...config, stageMetrics: common, scenes: buildStageScenes(config) };
  }

  const CASES = {
    "real-sec-fred-investment": withStageMetrics({
      name: "金融投研数据采购", domain: "资产管理与风险研究", buyer: "多资产研究与风险团队", sellers: "3 类数据服务商",
      task: "构建无未来信息泄漏的 point-in-time 研究面板",
      products: "SEC 公司事实 · FRED 利率 · 派生时点信号",
      valuation: "CounterfactualValuator", pricing: "SubscriptionPricingModel", market: "BundleDemandMatcher",
      decision: "哪些互补数据值得在预算内联合采购？",
      outcome: "输出估值报告、订阅报价、组合匹配结果及完整来源链路。", budget: "预算假设 · USD 260,000",
      sources: "SEC EDGAR XBRL Company Facts · FRED Effective Federal Funds Rate",
      signalsText: "Rank IC 改善 · 下行预警召回 · Point-in-time coverage", shape: "1 个买方 · 3 类卖方 · 互补数据 AND 组合",
      sourceNote: "原始事实保留 filing date、accession 与 observation date；场景价格不代表 SEC 或 FRED 的数据售价。",
      rights: "research use", sourceCount: 2, participantCount: 4, priceShape: "subscription", priceBasis: "usage + SLA", marketConstraint: "AND bundle",
      evidence: [{ label: "时点完整性", value: "0.97" }, { label: "申报可追溯", value: "100%" }, { label: "字段有效性", value: "0.95" }],
      signals: [{ label: "Rank IC improvement", value: "+0.032" }, { label: "Downside alert recall", value: "+0.08" }, { label: "Point-in-time coverage", value: "0.97" }],
      methods: { govern: "RightsPolicyEvaluator", evaluate: "CompositeEvaluator", value: "CounterfactualValuator", price: "SubscriptionPricingModel", market: "BundleDemandMatcher", realize: "audit_pricing_outcome" },
      methodDetails: {
        value: { method: "CounterfactualValuator", formula: "ΔU = U(task | data) − U(task | baseline)", note: "比较候选数据和无候选数据的影子研究表现，并按任务指标权重形成价值依据。" },
        price: { method: "SubscriptionPricingModel", formula: "quote = period_fee + overage − commitment_discount", note: "周期费、包含用量、超额使用和承诺折扣分别进入报价组件。" },
        market: { method: "BundleDemandMatcher", formula: "bundle* = argmax Σ reported_value(bundle), subject to budget", note: "SEC、FRED 与派生时点信号按 AND 关系作为互补组合参与匹配。" }
      },
      demo: {
        runId: "FIN-PIT-042", operator: "research-data@northstar", commercialUse: "internal research", modality: "tabular / time-series",
        samplePolicy: "stratified · seed 42 · n=10,000", qualityGate: "PIT coverage ≥ 0.95", valueSelection: "baseline vs. 3-asset bundle",
        priceSelection: "annual research subscription", outcomeSelection: "90-day post-allocation window", feedbackWindow: "90 days",
        assets: [
          previewRow("SEC Company Facts", "2.4M point-in-time facts", "CIK 0000320193 · 10-K filed 2024-11-01", "data"),
          previewRow("FRED DFF", "daily rate observations", "observation 2024-10-31 · vintage tracked", "data"),
          previewRow("PIT Signal Pack", "48 derived features", "only information available at decision time", "data")
        ],
        governance: [
          previewRow("SEC Company Facts", "ALLOW", "source + accession + filing date retained", "positive"),
          previewRow("FRED DFF", "ALLOW", "observation date and series ID retained", "positive"),
          previewRow("PIT Signal Pack", "ALLOW WITH LINEAGE", "upstream SEC/FRED references required", "warning")
        ],
        sample: [
          previewRow("0000320193 · Revenues", "USD 391.0B", "FY2024 · filed 2024-11-01 · 10-K"),
          previewRow("DFF · 2024-10-31", "4.83%", "FRED observation · known before rebalance"),
          previewRow("AAPL · earnings_yield_pit", "0.0362", "as_of 2024-11-04 · lineage complete")
        ],
        baseline: [
          previewRow("0000320193 · Revenues", "USD 391.0B", "prior EvaluationReport · filed 2024-11-01", "data"),
          previewRow("Rank IC", "0.041 → 0.073", "+0.032 with candidate bundle", "positive"),
          previewRow("Downside alert recall", "0.63 → 0.71", "+0.08 at fixed false-positive rate", "positive"),
          previewRow("Point-in-time coverage", "0.82 → 0.97", "leakage guardrail satisfied", "positive")
        ],
        valueConfig: [
          previewRow("method", "CounterfactualValuator", "same walk-forward folds"),
          previewRow("metric weights", "IC .45 · recall .35 · PIT .20", "buyer task preferences"),
          previewRow("uncertainty", "block bootstrap · 500", "95% interval retained")
        ],
        valuation: [
          previewRow("Rank IC contribution", "USD 94,000", "+0.032 · weight 0.45", "accent"),
          previewRow("Recall contribution", "USD 62,000", "+0.08 · weight 0.35", "accent"),
          previewRow("PIT coverage contribution", "USD 39,000", "+0.15 · weight 0.20", "accent"),
          previewRow("Bundle value estimate", "USD 195,000", "95% interval: 171k–216k", "positive")
        ],
        priceBasis: [
          previewRow("value ceiling", "USD 195,000", "from ValuationReport"),
          previewRow("service cost", "USD 118,000", "normalization + lineage + delivery"),
          previewRow("quality / SLA", "0.97 / 99.5%", "PIT coverage and availability")
        ],
        priceConfig: [
          previewRow("period_fee", "USD 150,000 / year", "base subscription"),
          previewRow("included_usage", "1.2M API calls", "USD 0.025 overage"),
          previewRow("commitment_discount", "8%", "12-month commitment")
        ],
        quote: [
          previewRow("base + SLA", "USD 176,000", "150k period fee + 26k SLA tier"),
          previewRow("commitment discount", "− USD 14,080", "8% annual commitment"),
          previewRow("annual quote", "USD 161,920", "176k subtotal − 14.08k discount", "positive")
        ],
        orders: [
          previewRow("Northstar buyer agent", "budget USD 260,000", "rational · AND bundle · value ceiling 195k"),
          previewRow("Filings service seller", "reserve USD 96,000", "SLA-first · no partial allocation"),
          previewRow("Macro stream seller", "reserve USD 34,000", "volume discount after 1M calls"),
          previewRow("Signal pack seller", "reserve USD 28,000", "requires upstream bundle")
        ],
        marketConfig: [
          previewRow("mechanism", "BundleDemandMatcher", "complementary AND demand"),
          previewRow("buyer budget", "USD 260,000", "hard feasibility constraint"),
          previewRow("tie break", "higher PIT coverage", "then lower total payment")
        ],
        allocation: [
          previewRow("winning bundle", "SEC + FRED + PIT Signals", "all three products allocated", "positive"),
          previewRow("buyer payment", "USD 161,920", "below value ceiling and budget", "positive"),
          previewRow("estimated buyer surplus", "USD 33,080", "195k value − 161.92k payment"),
          previewRow("mechanism checks", "budget ✓ · IR ✓ · lineage ✓", "audit passed", "positive")
        ],
        usage: [
          previewRow("API delivery", "684,230 calls", "99.72% availability · 2.1h p95 lag"),
          previewRow("research adoption", "3 portfolios · 14 notebooks", "SEC and macro joined in 91% of runs"),
          previewRow("realized task signal", "Rank IC +0.029", "90-day shadow evaluation")
        ],
        feedback: [
          previewRow("task outcome", "recall +0.07", "close to configured +0.08 expectation", "positive"),
          previewRow("value calibration", "USD 189,000", "revised from 195k using observed usage"),
          previewRow("asset history", "evaluation 0.95 → 0.97", "PIT repair released in v2024.11"),
          previewRow("next action", "renewal_candidate", "review overage tier before renewal", "accent")
        ]
      },
      sourceDisclaimer: "任务效用、预算、保留价与订阅费是可编辑案例假设，不构成投资建议。"
    }),
    "real-pjm-energy": withStageMetrics({
      name: "PJM 负荷数据订阅", domain: "电力调度与交易", buyer: "日前负荷决策团队", sellers: "3 类负荷服务商",
      task: "为日前负荷决策选择连续、低延迟的数据服务",
      products: "EIA 小时负荷 · 爬坡特征 · 滚动窗口服务",
      valuation: "UpdateStreamValuator", pricing: "ExpectedRevenuePricingModel", market: "QualityAwareProcurement",
      decision: "哪些更新流在预算内带来更高的质量成本比？",
      outcome: "输出更新流价值、候选价格比较、质量感知采购和 SLA 证据。", budget: "预算假设 · USD 190,000",
      sources: "U.S. EIA Hourly Grid Monitor · PJM Data Miner terms",
      signalsText: "MAPE 改善 · 峰值捕获 · Delivery reliability", shape: "1 个买方 · 3 类卖方 · 质量感知采购",
      sourceNote: "场景对接官方负荷实测记录；价格表示接入、加工、更新和 SLA 服务，并非 EIA/PJM 报价。",
      rights: "energy trading", sourceCount: 2, participantCount: 4, priceShape: "expected revenue", priceBasis: "quality + demand", marketConstraint: "fixed budget",
      evidence: [{ label: "时间连续性", value: "0.99" }, { label: "数值有效性", value: "0.97" }, { label: "交付可靠性", value: "0.96" }],
      signals: [{ label: "Update value", value: "159k" }, { label: "Peak capture", value: "+0.11" }, { label: "Delivery probability", value: "0.96" }],
      methods: { govern: "RightsPolicyEvaluator", evaluate: "CompositeEvaluator", value: "UpdateStreamValuator", price: "ExpectedRevenuePricingModel", market: "QualityAwareProcurement", realize: "analyze_market_health" },
      methodDetails: {
        value: { method: "UpdateStreamValuator", formula: "PV = Σ marginal_value_t × delivery_probability_t × quality_t / (1 + r)^t", note: "把每期边际价值、交付概率、质量和折现率显式写入更新流价值。" },
        price: { method: "ExpectedRevenuePricingModel", formula: "p* = argmax_p p × P(accept | p, quality, freshness)", note: "在候选价格上估计接受概率，并选择期望收入最高的可行报价。" },
        market: { method: "QualityAwareProcurement", formula: "rank_i = quality_i / reserve_i; accept while Σ cost_i ≤ budget", note: "按质量成本比排序，并在固定采购预算内依次接受服务。" }
      },
      demo: {
        runId: "GRID-DA-018", operator: "dispatch-data@gridops", commercialUse: "operations + trading", modality: "time-series",
        samplePolicy: "rolling 28 days · 5-minute checks", qualityGate: "continuity ≥ 0.98", valueSelection: "baseline vs. live update stream",
        priceSelection: "12-month low-latency feed", outcomeSelection: "30-day delivery window", feedbackWindow: "30 days",
        assets: [previewRow("EIA hourly load", "18 balancing areas", "hour ending timestamps"), previewRow("PJM ramp features", "24 derived ramps", "15–180 minute horizons"), previewRow("Rolling window API", "5-minute refresh", "SLA instrumented")],
        governance: [previewRow("EIA load", "ALLOW", "source and timestamp retained", "positive"), previewRow("PJM features", "ALLOW", "derivation lineage required", "positive"), previewRow("Live API", "ALLOW WITH SLA", "redistribution disabled", "warning")],
        sample: [previewRow("PJM · 17:00", "112,438 MWh", "2026-07-15 · observed"), previewRow("ramp_60m", "+4,821 MWh", "peak transition"), previewRow("delivery_lag_p95", "74 sec", "rolling 24h")],
        baseline: [previewRow("MAPE", "4.8% → 3.9%", "−0.9 pp", "positive"), previewRow("Peak capture", "0.76 → 0.87", "+0.11", "positive"), previewRow("Delivery probability", "0.93 → 0.96", "SLA-adjusted", "positive")],
        valueConfig: [previewRow("method", "UpdateStreamValuator", "daily marginal update value"), previewRow("discount rate", "8% annualized", "service horizon"), previewRow("delivery model", "empirical p(on-time)", "30-day window")],
        valuation: [previewRow("forecast gain", "USD 101,000", "MAPE and peak capture"), previewRow("timeliness value", "USD 58,000", "delivery-adjusted"), previewRow("update stream PV", "USD 159,000", "scenario estimate", "positive")],
        priceBasis: [previewRow("stream PV", "USD 159,000", "valuation ceiling"), previewRow("delivery", "96% on-time", "SLA evidence"), previewRow("demand", "4 active desks", "acceptance model feature")],
        priceConfig: [previewRow("candidates", "120k · 138k · 152k", "annual price grid"), previewRow("acceptance model", "logit", "quality + freshness + price"), previewRow("min margin", "18%", "seller constraint")],
        quote: [previewRow("selected annual quote", "USD 138,000", "candidate price maximizing the objective", "positive"), previewRow("expected revenue", "USD 97,980", "USD 138,000 × P(accept)=0.71", "accent"), previewRow("SLA credit", "5% / breach", "monthly cap 15%"), previewRow("refresh tier", "5 minute", "12-month term")],
        orders: [previewRow("Dispatch buyer", "budget USD 190,000", "quality-first agent"), previewRow("Base load seller", "reserve USD 72,000", "continuity 0.99"), previewRow("Ramp seller", "reserve USD 41,000", "peak capture 0.87"), previewRow("API seller", "reserve USD 25,000", "delivery 0.96")],
        marketConfig: [previewRow("mechanism", "QualityAwareProcurement", "quality / reserve ranking"), previewRow("budget", "USD 190,000", "hard cap"), previewRow("minimum quality", "0.94", "reject below gate")],
        allocation: [previewRow("selected", "load + ramp + API", "all quality gates passed", "positive"), previewRow("payment", "USD 138,000", "within procurement budget", "positive"), previewRow("quality / cost", "0.00696", "normalized winner score")],
        usage: [previewRow("delivered windows", "8,640", "30 days · 5-minute cadence"), previewRow("late windows", "326", "3.77%"), previewRow("dispatch runs", "60", "day-ahead + intraday")],
        feedback: [previewRow("realized MAPE", "4.0%", "close to 3.9% shadow estimate"), previewRow("SLA credit", "USD 0", "monthly threshold not breached"), previewRow("next action", "retain_and_monitor", "recheck summer peak", "accent")]
      },
      sourceDisclaimer: "更新边际价值、需求、预算和候选报价均为实验配置，不是电力交易建议。"
    }),
    "real-mimic-rwe": withStageMetrics({
      name: "临床 RWE 数据许可", domain: "临床研究与药物安全", buyer: "药物安全 RWE 研究组", sellers: "3 类临床数据服务商",
      task: "选择适配研究方案且许可可审计的住院、诊断与检验数据",
      products: "MIMIC-IV 住院 · ICD 诊断 · 检验事件",
      valuation: "RiskAdjustedValuator", pricing: "RightsDifferentiatedPricingModel", market: "MultiAttributeMarketMatcher",
      decision: "哪组数据在质量、权利和不确定性之间最适合研究？",
      outcome: "输出 fit-for-purpose 证据、风险调整价值、权利报价和多属性匹配。", budget: "预算假设 · USD 280,000",
      sources: "PhysioNet MIMIC-IV Demo 2.2 · FDA RWE guidance",
      signalsText: "关键元素完整性 · 跨表链接 · Rights fit", shape: "1 个买方 · 3 类卖方 · 多属性匹配",
      sourceNote: "页面使用去标识的 MIMIC-IV Demo 官方记录；场景价格并非 PhysioNet 报价。",
      rights: "protocol fit", sourceCount: 2, participantCount: 4, priceShape: "rights tiers", priceBasis: "rights + risk", marketConstraint: "multi-attribute",
      evidence: [{ label: "关键元素完整性", value: "0.91" }, { label: "跨表链接率", value: "0.94" }, { label: "时间有效性", value: "0.92" }],
      signals: [{ label: "Risk-adjusted quality", value: "0.91" }, { label: "Std. error", value: "0.08" }, { label: "Rights fit", value: "audited" }],
      methods: { govern: "RightsMatrixEvaluator", evaluate: "CompositeEvaluator", value: "RiskAdjustedValuator", price: "RightsDifferentiatedPricingModel", market: "MultiAttributeMarketMatcher", realize: "audit_pricing_outcome" },
      methodDetails: {
        value: { method: "RiskAdjustedValuator", formula: "V_risk = E[V | task] − λ × σ", note: "从任务价值中扣除由标准误和风险厌恶系数决定的不确定性折减。" },
        price: { method: "RightsDifferentiatedPricingModel", formula: "quote = base_price × rights_factor(commercial, redistribution, exclusivity, term)", note: "商业使用、再分发、独占、地域和期限分别形成权利溢价。" },
        market: { method: "MultiAttributeMarketMatcher", formula: "score = w_price·s_price + w_quality·s_quality + w_rights·s_rights + …", note: "价格、质量、新鲜度、信誉和权利适配共同决定供需匹配分数。" }
      },
      demo: {
        runId: "RWE-SAFETY-011", operator: "rwe-governance@biopharma", commercialUse: "protocol-bound analysis", modality: "relational tabular",
        samplePolicy: "subject-level stratified · n=8,000", qualityGate: "linkage ≥ 0.90", valueSelection: "protocol baseline vs. linked bundle",
        priceSelection: "24-month protocol license", outcomeSelection: "study execution window", feedbackWindow: "180 days",
        assets: [previewRow("MIMIC-IV admissions", "100-patient demo subset", "Demo v2.2 · de-identified relational schema"), previewRow("ICD diagnoses", "demo-coded events", "subject + admission linkage"), previewRow("Lab events", "demo time-stamped results", "unit normalization")],
        governance: [previewRow("Admissions", "ALLOW", "credentialed protocol", "positive"), previewRow("Diagnoses", "ALLOW", "no redistribution", "positive"), previewRow("Lab events", "ALLOW WITH AUDIT", "minimum-cell suppression", "warning")],
        sample: [previewRow("subject 10000032", "admission 29079034", "anchor-safe dates"), previewRow("ICD I50.9", "heart failure", "linked to admission"), previewRow("creatinine", "1.4 mg/dL", "unit normalized")],
        baseline: [previewRow("key element completeness", "0.84 → 0.91", "+0.07", "positive"), previewRow("cross-table linkage", "0.81 → 0.94", "+0.13", "positive"), previewRow("standard error", "0.11 → 0.08", "lower is better", "positive")],
        valueConfig: [previewRow("method", "RiskAdjustedValuator", "expected task value − risk"), previewRow("risk λ", "0.35", "buyer preference"), previewRow("bootstrap", "1,000 subject blocks", "95% interval")],
        valuation: [previewRow("expected task value", "USD 238,000", "protocol utility"), previewRow("uncertainty deduction", "− USD 28,000", "λ × σ"), previewRow("risk-adjusted value", "USD 210,000", "scenario estimate", "positive")],
        priceBasis: [previewRow("risk-adjusted value", "USD 210,000", "valuation report"), previewRow("rights scope", "protocol only", "no redistribution"), previewRow("term", "24 months", "audited access")],
        priceConfig: [previewRow("base license", "USD 144,000", "non-exclusive"), previewRow("audit tier", "+ USD 24,000", "quarterly evidence"), previewRow("term factor", "1.18", "24-month access")],
        quote: [previewRow("license subtotal", "USD 168,000", "base + audit"), previewRow("term adjustment", "+ USD 30,240", "factor 1.18"), previewRow("protocol quote", "USD 198,240", "scenario terms", "positive")],
        orders: [previewRow("RWE buyer", "budget USD 280,000", "rights-sensitive agent"), previewRow("Admission seller", "score 0.91", "price + completeness"), previewRow("Diagnosis seller", "score 0.89", "linkage + rights"), previewRow("Lab seller", "score 0.86", "validity + audit")],
        marketConfig: [previewRow("mechanism", "MultiAttributeMarketMatcher", "weighted score"), previewRow("weights", "price .25 · quality .35 · rights .40", "protocol priorities"), previewRow("rights gate", "mandatory", "no compensating tradeoff")],
        allocation: [previewRow("matched bundle", "admission + ICD + labs", "rights-compatible", "positive"), previewRow("payment", "USD 198,240", "below value and budget", "positive"), previewRow("match score", "0.892", "all mandatory gates pass")],
        usage: [previewRow("approved researchers", "8", "credentialed access"), previewRow("audited queries", "12,804", "zero export violations"), previewRow("linked cohort", "82 demo subjects", "after protocol filters")],
        feedback: [previewRow("realized standard error", "0.081", "aligned with estimate"), previewRow("rights incidents", "0", "audit complete", "positive"), previewRow("next action", "extend_protocol", "retain audit tier", "accent")]
      },
      sourceDisclaimer: "研究价值、预算和许可报价为演示配置，不构成临床判断或真实合同。"
    }),
    "real-nyc-mobility": withStageMetrics({
      name: "NYC 出行需求数据采购", domain: "城市交通与运力", buyer: "城市运力规划团队", sellers: "3 类出行数据服务商",
      task: "采购能够改善分区小时需求预测的数据组合",
      products: "TLC 行程 · Taxi Zone 主数据 · 需求特征",
      valuation: "CounterfactualValuator", pricing: "SubscriptionPricingModel", market: "BundleDemandMatcher",
      decision: "哪些互补记录和特征值得作为一个完整组合订阅？",
      outcome: "输出行程质量证据、预测增益价值、订阅报价和组合选择。", budget: "预算假设 · USD 220,000",
      sources: "NYC TLC Yellow Taxi 2024 · Taxi Zone Lookup",
      signalsText: "WMAPE 改善 · Peak recall · Zone coverage", shape: "1 个买方 · 3 类卖方 · 互补数据 AND 组合",
      sourceNote: "TLC 记录由官方公开来源提供；预算和订阅费用于复现采购过程，不是城市或厂商报价。",
      rights: "forecasting", sourceCount: 2, participantCount: 4, priceShape: "subscription", priceBasis: "usage + cadence", marketConstraint: "AND bundle",
      evidence: [{ label: "必填完整性", value: "0.96" }, { label: "有效行程率", value: "0.92" }, { label: "区域覆盖", value: "0.98" }],
      signals: [{ label: "WMAPE improvement", value: "+0.16" }, { label: "Peak recall gain", value: "+0.09" }, { label: "Zone coverage", value: "0.98" }],
      methods: { govern: "RightsPolicyEvaluator", evaluate: "CompositeEvaluator", value: "CounterfactualValuator", price: "SubscriptionPricingModel", market: "BundleDemandMatcher", realize: "UsageAggregator" },
      methodDetails: {
        value: { method: "CounterfactualValuator", formula: "ΔU = U(forecast | trip + zone + features) − U(forecast | history)", note: "以历史需求预测为基线，估计加入行程、区域和派生特征后的预测增益。" },
        price: { method: "SubscriptionPricingModel", formula: "quote = period_fee + overage − commitment_discount", note: "按更新周期、包含用量、超额使用和承诺折扣形成订阅报价。" },
        market: { method: "BundleDemandMatcher", formula: "bundle* = argmax Σ reported_value(bundle), subject to budget", note: "行程、区域主数据和需求特征作为互补 AND 组合进入匹配。" }
      },
      demo: {
        runId: "MOBILITY-ZONE-027", operator: "planning-data@cityops", commercialUse: "service planning", modality: "tabular / geospatial",
        samplePolicy: "zone-hour stratified · n=20,000", qualityGate: "valid trips ≥ 0.90", valueSelection: "history vs. trip-zone-feature bundle",
        priceSelection: "monthly planning subscription", outcomeSelection: "12-week planning window", feedbackWindow: "12 weeks",
        assets: [previewRow("TLC yellow trips", "12.8M rows / month", "pickup/dropoff zones"), previewRow("Taxi Zone lookup", "265 zones", "borough geometry keys"), previewRow("Demand features", "36 zone-hour features", "weather + calendar joins")],
        governance: [previewRow("Trip records", "ALLOW", "public-source lineage", "positive"), previewRow("Zone lookup", "ALLOW", "version pinned", "positive"), previewRow("Demand features", "ALLOW WITH LINEAGE", "derived sources retained", "warning")],
        sample: [previewRow("zone 161 → 236", "1 passenger · USD 18.40", "2024-05-06 08:14"), previewRow("zone 132 → 230", "2 passengers · USD 62.10", "airport origin"), previewRow("zone 79 · 18:00", "demand 184", "feature window")],
        baseline: [previewRow("WMAPE", "0.31 → 0.26", "−0.05", "positive"), previewRow("Peak recall", "0.68 → 0.77", "+0.09", "positive"), previewRow("Zone coverage", "0.91 → 0.98", "+0.07", "positive")],
        valueConfig: [previewRow("method", "CounterfactualValuator", "fixed forecast folds"), previewRow("weights", "WMAPE .50 · peak .30 · coverage .20", "planning priorities"), previewRow("uncertainty", "week-block bootstrap", "500 draws")],
        valuation: [previewRow("WMAPE contribution", "USD 86,000", "largest task gain"), previewRow("peak + coverage", "USD 74,000", "weighted contribution"), previewRow("bundle estimate", "USD 160,000", "scenario value", "positive")],
        priceBasis: [previewRow("value ceiling", "USD 160,000", "valuation report"), previewRow("monthly rows", "12.8M", "usage driver"), previewRow("refresh", "weekly", "cadence tier")],
        priceConfig: [previewRow("period fee", "USD 10,500 / month", "base subscription"), previewRow("included rows", "15M / month", "USD 0.001 overage"), previewRow("annual discount", "6%", "12-month term")],
        quote: [previewRow("annual base", "USD 126,000", "12 monthly periods"), previewRow("annual discount", "− USD 7,560", "6%"), previewRow("annual quote", "USD 118,440", "overage excluded", "positive")],
        orders: [previewRow("Planning buyer", "budget USD 220,000", "AND-bundle agent"), previewRow("Trip seller", "reserve USD 68,000", "volume tier"), previewRow("Zone seller", "reserve USD 12,000", "master-data license"), previewRow("Feature seller", "reserve USD 31,000", "weekly refresh")],
        marketConfig: [previewRow("mechanism", "BundleDemandMatcher", "complementary inputs"), previewRow("budget", "USD 220,000", "hard cap"), previewRow("bundle rule", "trip AND zone AND features", "no partial award")],
        allocation: [previewRow("winning bundle", "Trips + Zones + Features", "complete forecast inputs", "positive"), previewRow("payment", "USD 118,440", "below value and budget", "positive"), previewRow("buyer surplus", "USD 41,560", "scenario estimate")],
        usage: [previewRow("forecast runs", "1,272", "265 zones × rolling weeks"), previewRow("rows consumed", "38.1M", "three monthly partitions"), previewRow("peak alerts used", "418", "planning review events")],
        feedback: [previewRow("realized WMAPE", "0.265", "close to shadow estimate"), previewRow("zone coverage", "0.982", "stable", "positive"), previewRow("next action", "renewal_candidate", "consider daily refresh", "accent")]
      },
      sourceDisclaimer: "预测增益、预算、保留价和订阅费是可编辑实验假设。"
    })
  };

  const FINANCIAL_WORKBENCH_SCREENS = {
    govern: {
      config: "assets/workbench/governance-config.png",
      result: "assets/workbench/governance-result.png",
      title: "注册与治理",
      input: "三个资产：SEC 点时财务事实、FRED DFF、发行人—利率点时信号。",
      configuration: "计划用途设为 investment_research，并开启严格权利检查；来源、许可和版本逐资产保存。",
      output: "治理结果逐项给出 allowed、违规项、敏感字段和 GovernanceReport。",
      configCaption: "左侧选中三个资产；右侧设置投研用途和严格权利检查。",
      resultCaption: "结果页显示 3/3 个资产执行成功，并可展开每份治理报告。",
      alt: "DataValor 工作台的注册与治理界面"
    },
    evaluate: {
      config: "assets/workbench/evaluation-config.png",
      result: "assets/workbench/evaluation-result.png",
      title: "质量评估",
      input: "同一批三个金融资产；每条记录保留 source_record_id 和来源日期。",
      configuration: "模态选择 tabular；计算完整性、重复率、字段有效性、schema consistency、数值统计和异常率。",
      output: "EvaluationReport 显示各质量维度的数值、方向和统计依据，而不是只给一个总分。",
      configCaption: "右侧选择表格模态和质量指标；左侧保持同一批金融资产。",
      resultCaption: "结果页逐资产展示质量指标、方向、统计依据和完整 artifact。",
      alt: "DataValor 工作台的表格数据质量评估界面"
    },
    value: {
      config: "assets/workbench/valuation-config.png",
      result: "assets/workbench/valuation-result.png",
      title: "数据估值",
      input: "选中 SEC 点时财务事实、FRED DFF 和发行人—利率点时信号。",
      configuration: "使用 valuation.counterfactual；基础价值 260,000 USD，并填写 evaluation / baseline vectors 和指标权重。",
      output: "执行结果展示逐资产估值、价值分解、状态与完整 ValuationReport artifact。",
      configCaption: "左侧选中三个金融数据资产；右侧设置反事实估值方法和价值参数。",
      resultCaption: "结果页给出每个资产的估值、币种、价值依据和可展开 artifact。",
      alt: "DataValor 工作台的数据估值界面"
    },
    price: {
      config: "assets/workbench/pricing-config.png",
      result: "assets/workbench/pricing-result.png",
      title: "定价与报价",
      input: "三个已带有质量报告和估值记录的数据资产。",
      configuration: "使用 pricing.subscription；period_fee=68,000 USD、included_usage=1,200、usage=1,400、overage=12、discount=5%。",
      output: "报价结果并列显示参考报价、模型报价、差额、价格组件和执行轨迹。",
      configCaption: "为同一批资产配置订阅费、包含用量、超额单价和折扣。",
      resultCaption: "结果页比较参考价与模型价，并展开每份 PriceQuote 的组件。",
      alt: "DataValor 工作台的订阅定价与报价界面"
    },
    market: {
      config: "assets/workbench/market-config.png",
      result: "assets/workbench/market-result.png",
      title: "市场配置与支付",
      input: "一个预算 260,000 USD 的买方、三个卖方和三个数据产品。",
      configuration: "使用 bundle_matching；买方提交 240,000 USD 的 AND 组合需求，三笔卖方要价为 72,000、38,000 和 94,000 USD。",
      output: "组合匹配结果展示中标数据包和申报盈余；该机制不直接生成支付，报价仍保留在前一环节。",
      configCaption: "在真实订单簿中配置一个买方、三个卖方和互补 AND 组合。",
      resultCaption: "结果页显示一个 AND 组合被选中、申报盈余为 36,000 USD；支付为 0，并列出诊断与异常。",
      alt: "DataValor 工作台的多参与者组合市场界面"
    },
    realize: {
      config: "assets/workbench/resources-config.png",
      result: "assets/workbench/resources-result.png",
      title: "运行记录与产物",
      input: "前五个环节生成的 batches、runs、reports、quotes 和 PricingOutcome。",
      configuration: "每次运行保存输入引用、标准化参数、producer、时间戳和 lineage。",
      output: "资源页只保留本次金融案例生成的治理、评估、估值、报价、市场结果和原始 artifacts。",
      configCaption: "资源总览按资产和批次汇总运行状态、产物数量与最近更新时间。",
      resultCaption: "产物视图列出本次金融流程的 report、quote 与 outcome；点击条目可展开输入、参数和 JSON。",
      alt: "DataValor 工作台的资源与运行产物界面"
    }
  };

  Object.entries(FINANCIAL_WORKBENCH_SCREENS).forEach(([stageId, screen]) => {
    CASES["real-sec-fred-investment"].scenes[stageId].screen = screen;
  });

  function nextTabIndex(current, length, key) {
    if (!length) return -1;
    if (key === "Home") return 0;
    if (key === "End") return length - 1;
    if (key === "ArrowLeft" || key === "ArrowUp") return (current - 1 + length) % length;
    if (key === "ArrowRight" || key === "ArrowDown") return (current + 1) % length;
    return current;
  }

  function screenState(scene, mode = "config") {
    if (!scene?.screen) return null;
    const normalizedMode = mode === "result" ? "result" : "config";
    const isResult = normalizedMode === "result";
    return {
      mode: normalizedMode,
      modeLabel: isResult ? "执行结果" : "配置界面",
      src: scene.screen[normalizedMode],
      title: `真实工作台 · ${scene.screen.title}${isResult ? "结果" : "配置"}`,
      caption: isResult ? scene.screen.resultCaption : scene.screen.configCaption,
      alt: `${scene.screen.alt}（${isResult ? "执行结果" : "配置界面"}）`,
      input: scene.screen.input,
      configuration: scene.screen.configuration,
      output: scene.screen.output
    };
  }

  const api = { model: { cases: CASES, stages: STAGES }, nextTabIndex, selectCase, selectStage, screenState };
  globalThis.DataValorTour = api;

  if (typeof document === "undefined") return;

  let activeCaseId = "real-sec-fred-investment";
  let activeStageId = "value";
  let activeScreenMode = "config";
  const byId = (id) => document.getElementById(id);
  const setText = (id, value) => { const node = byId(id); if (node) node.textContent = value; };

  function selectScreenMode(mode) {
    const scene = CASES[activeCaseId]?.scenes?.[activeStageId];
    const state = screenState(scene, mode);
    if (!state) return;
    activeScreenMode = state.mode;
    const image = byId("workbenchScreen");
    const link = byId("workbenchScreenLink");
    if (image) {
      image.src = state.src;
      image.alt = state.alt;
    }
    if (link) link.href = state.src;
    setText("workbenchProofTitle", state.title);
    setText("screenCaption", state.caption);
    setText("screenInputText", state.input);
    setText("screenConfigText", state.configuration);
    setText("screenOutputText", state.output);
    document.querySelectorAll("[data-screen-mode]").forEach((button) => {
      const active = button.dataset.screenMode === state.mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function selectCase(caseId, options = {}) {
    const selected = CASES[caseId];
    if (!selected) return;
    activeCaseId = caseId;
    document.querySelectorAll("[data-case]").forEach((tab) => {
      const active = tab.dataset.case === caseId;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    setText("receiptTitle", selected.name);
    setText("receiptBuyer", selected.buyer);
    setText("receiptSellers", selected.sellers);
    setText("receiptTask", selected.task);
    setText("receiptProducts", selected.products);
    setText("receiptValuation", selected.valuation);
    setText("receiptPricing", selected.pricing);
    setText("receiptMarket", selected.market);
    setText("receiptDecision", selected.decision);
    setText("receiptOutcome", selected.outcome);
    setText("receiptBudget", selected.budget);
    setText("caseSources", selected.sources);
    setText("caseSignals", selected.signalsText);
    setText("caseShape", selected.shape);
    setText("caseSourceNote", selected.sourceNote);
    selectStage(activeStageId, { focus: false });
    if (options.focus) document.querySelector(`[data-case="${caseId}"]`)?.focus();
  }

  function selectStage(stageId, options = {}) {
    const stage = STAGES[stageId];
    const selectedCase = CASES[activeCaseId];
    if (!stage || !selectedCase) return;
    activeStageId = stageId;
    document.querySelectorAll("[data-stage]").forEach((tab) => {
      const active = tab.dataset.stage === stageId;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    const panel = byId("stagePanel");
    if (panel) {
      panel.className = `stage-panel stage-panel-${stageId}`;
      panel.style.setProperty("--stage-accent", stage.accent);
    }
    setText("stageCode", stage.code);
    setText("stageTitle", stage.title);
    setText("stageSummary", `${stage.summary} 当前案例：${selectedCase.task}。`);
    activeScreenMode = "config";
    selectScreenMode(activeScreenMode);
    const stageIndex = Object.keys(STAGES).indexOf(stageId);
    document.querySelectorAll("#lineageItems li").forEach((item, index) => item.classList.toggle("active", index === stageIndex));
    if (options.focus) document.querySelector(`[data-stage="${stageId}"]`)?.focus();
  }

  function bindTabs(selector, dataKey, activate) {
    const tabs = [...document.querySelectorAll(selector)];
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => activate(tab.dataset[dataKey]));
      tab.addEventListener("keydown", (event) => {
        const next = nextTabIndex(index, tabs.length, event.key);
        if (next === index && !["Home", "End"].includes(event.key)) return;
        event.preventDefault();
        activate(tabs[next].dataset[dataKey], { focus: true });
      });
    });
  }

  async function enrichDashboard() {
    try {
      const response = await fetch("../api/dashboard", { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const payload = await response.json();
      const count = Number(payload?.data?.summary?.components);
      if (Number.isFinite(count) && count > 0) setText("componentCount", String(count));
    } catch (_) {
      // Static and offline use intentionally keep the curated fallback count.
    }
  }

  bindTabs("[data-case]", "case", selectCase);
  bindTabs("[data-stage]", "stage", selectStage);
  document.querySelectorAll("[data-screen-mode]").forEach((button) => {
    button.addEventListener("click", () => selectScreenMode(button.dataset.screenMode));
  });
  selectCase(activeCaseId);
  enrichDashboard();
})();
