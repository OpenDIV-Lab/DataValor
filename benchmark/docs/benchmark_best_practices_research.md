# DataMechBench 创新性、研究意义与发展路线审计

> 调研日期：2026-09-29  
> 对象：DataMechBench 0.3.0 及其 17,788 条调度结果（9,678 completed）  
> 目的：判断它目前是否已经构成一个有研究价值的 benchmark，以及距离论文级、社区级 benchmark 还缺什么。

## 1. 结论先行

DataMechBench 已经超过“若干算法放在一起跑”的实验脚本阶段，形成了一个具有明确
研究主张的 **evidence-grade benchmark prototype**。它当前最值得保留的定位是：

> **A claim- and constraint-aware benchmark for data-market mechanisms.**  
> 它比较的不只是 valuation score 或 allocation welfare，而是机制在特定数据市场
> setting 下的性能、支付与约束、论文预期、统计证据和假设迁移。

这个定位有实际创新空间。现有工作通常分别覆盖 point-level 数据估值、预算数据获取、
通用拍卖仿真或模型性能评测；本轮调研没有发现一个成熟 benchmark 同时把
owner-level 数据效用、allocation、payment、真实类型、机制约束和论文 claim 纳入
同一个可审计协议。但“尚未发现”不是优先权证明，论文中应表述为系统调研下的空缺，
避免绝对声称“首个”。

当前成熟度更接近“可写 benchmark 论文的研究原型”，还不是社区可以长期依赖的基准。
阻碍其成为高价值 benchmark 的首要问题不是机制数量，而是：

1. 冻结 v0.3 的 76 个被调度方法 ID 中只有 61 个至少完成一次；当前 registry 已扩展为
   80 个实现、78 个机制族，其中有 17 个 `paper_exact`、13 个 `official_adapter`、
   28 个 `paper_variant`，而官方适配器当前多因
   可选依赖或 game-fidelity 条件透明跳过。17 个 headline 已完成显式 source/core parity，
   但 variant 的声明边界仍要求读者不能把实验结果直接当作完整论文机制定理。
2. 三个旗舰 setting 已扩展到 20--24 个 primary-eligible cases，完整 release 的 2,027 个
   成对比较中仍有 807 个因非平局 case 不足而无法检验，约占 39.8%；非旗舰 setting 的
   证据密度仍偏低。
3. 数据已从真实 ML 数据与跨制度 proxy 扩展到 DaDaDa 真实 marketplace 挂牌价支持，
   但挂牌 ask 仍不是成交价或私有 reservation cost，外部有效性只能部分闭合。
4. sampled misreport audit 有用但不是 truthfulness 证明，部分 mechanism profile 仍是
   `not_auditable`。
5. 已有 release manifest、锁定 CPU 环境、benchmark CI 和 submission checker；checker
   已 fail-closed 区分 reference/open identity namespace，并校验完整 case×seed coverage，
   但仍缺少真实外部提交、独立复现和公开托管后的社区采用证据。

因此接下来应“加深核心证据”，而不是继续横向堆很多 setting。

## 2. 典型优秀 benchmark 为什么有影响力

### 2.1 对照对象

| Benchmark | 值得借鉴的核心设计 | 不应机械照搬的部分 |
|---|---|---|
| HELM | 先给 scenario/metric taxonomy，再按 coverage、value、feasibility 选择具体任务；多指标而非单一总分；公开原始输出；living benchmark | DataMechBench 不需要追求宽泛覆盖，也不需要把每个数据市场问题都纳入 |
| OpenML Suites | task 同时固定 dataset、target、split、procedure 和 metric；机器可读元数据与可复用 runs | 不需要建设完整在线实验平台才能采用 task contract |
| MLPerf | Closed/Open division、reference implementation、强制覆盖、结构化日志、自动 checker、评审与发布轮次 | 当前不需要复杂委员会和企业级基础设施 |
| DataPerf | 冻结模型和训练超参以隔离“数据”的贡献；开放挑战、baseline、长期组织维护 | DataMechBench 的对象是机制，不能冻结掉机制需要访问的信息或支付规则 |
| DataComp | 固定训练代码与算力尺度，允许参与者只优化数据；多 downstream tests；明确不同参与轨道 | 暂时不需要大规模 GPU competition，但应借鉴 compute tier 与隐藏测试 |
| WILDS | 用真实应用中的自然分布偏移定义 benchmark；提供标准 loader、默认模型和 leaderboard；版本更新保持旧结果可比 | 数据市场没有现成的统一真实标签，不能为了“真实”而混入不可解释案例 |
| OpenDataVal | 统一 11 类数据估值方法、4 个 downstream tasks、公开 leaderboard；展示没有方法在所有任务都占优 | 主要是 point-level 估值质量，不评价 allocation/payment/IR/budget balance |
| DataPerf DAM | 隐藏 seller data、预算合法性检查、固定下游模型、面向提交的购买策略 | 核心是 acquisition performance，不横向验证 truthful mechanism 及支付性质 |
| AuctionGym | 可配置竞争强度、bidder behavior 与重复拍卖；保留逐轮原始日志，便于离线策略评测 | 面向在线广告与 learning-to-bid，不是数据效用或静态机制定理 benchmark |
| DaDaDa | 16,147 个真实 data-product listings、九个平台，支持价格预测/分类/检索，并区分 subscription、one-off、usage-based 价格语义 | 不评价 allocation/payment/IR/budget，也不含成交价或私有 reservation cost；本 benchmark 仅把其用于描述性 price-support transfer stress |
| BetterBench | 从设计、实现、文档、维护到退役的完整生命周期；46 项质量实践；强调统计和可复现性 | 其 checklist 是最低质量保障，不等于具体领域的 construct validity |
| BenchmarkCards | 用统一结构说明目标、数据、协议、限制和适用范围，帮助用户判断 benchmark 是否适合自己的问题 | 文档完整不能替代真实数据、正确机制或统计功效 |

### 2.2 共同成功模式

优秀 benchmark 通常同时做到以下六点。

1. **测量对象清楚。** 用户能够用一句话说明“这个 benchmark 测什么、不测什么”。
2. **任务协议冻结。** 数据、split、输入可见性、预算、随机性、metric 和聚合方式共同
   构成 task，而不只是一个数据文件。
3. **构造具有现实或理论依据。** WILDS 使用自然发生的 shift；DataPerf 冻结模型以隔离
   数据贡献；HELM 解释 concrete tasks 如何从 taxonomy 中选择。
4. **比较公平且可复现。** 统一接口、reference implementation、固定 seed、原始结果、
   环境版本和自动 checker 是基础，不是论文卖点本身。
5. **结果产生新认识。** 好 benchmark 论文不会只报排行，而会总结稳定规律、trade-off、
   rank reversal、失败模式和未解决问题。
6. **能被别人持续使用。** 安装简单、运行成本合理、提交路径清楚、有维护者、版本策略和
   反馈渠道。

BetterBench 特别指出，许多流行 benchmark 没有报告统计不确定性，也难以复现；其质量
框架将设计、实现、文档、维护和退役视为完整生命周期。DataMechBench 已经覆盖不少
设计与文档要求，但社区维护和外部可复现性仍基本未经验证。

## 3. 典型优秀 benchmark 论文的“写法”

### 3.1 推荐的问题叙事

Benchmark 论文的开头不应从“我们实现了 63 个算法”开始，而应采用以下逻辑：

1. **现实/科学决策问题：** 数据市场研究提出大量估值、采购和交易机制，但论文的
   utility model、private information、market thickness 和 payment assumptions 不同。
2. **现有评测缺口：** 现有数据估值 benchmark 主要评价 downstream ML utility；
   acquisition benchmark 主要评价预算下准确率；auction simulator 主要评价通用广告策略。
3. **由此造成的不可比性：** 同名指标、不同可见信息、未验证支付规则和未披露实现偏差
   会让横向结果无法解释，也不能判断理论假设离开后是否仍有效。
4. **核心研究问题：** 如何在不制造跨问题总分的前提下，系统比较数据市场机制的性能、
   约束、论文 claim 和结构性稳健性？
5. **benchmark 回答方式：** mechanism profile + paper-grounded setting axes +
   constraint qualification + paired evidence + assumption transfer。

### 3.2 推荐的论文结构

1. **Introduction：** 一句话 construct、现有空缺、三项贡献、三条 headline finding。
2. **Landscape and taxonomy：** 只建立支撑 benchmark 边界的机制分类，不写成泛化综述。
3. **Benchmark design：** evaluation unit、可见信息、case contract、setting 选择准则、
   primary/guardrail metrics、fidelity tiers。
4. **Datasets and case generation：** 数据来源、owner 分组、经济类型构造、split、license、
   leakage 和现实校准。
5. **Methods：** reference/official/paper-variant 分层；具体偏差放附录或机器可读表。
6. **Protocol：** seed、预算、计算资源、失败/N/A、宏平均、统计检验和 submission rules。
7. **Results：** 先回答研究问题，再给榜单；核心图应是结构轴上的曲线和 constraint-aware
   rank reversal，而不是几十列大表。
8. **Validity and limitations：** construct、internal、external、statistical 和
   implementation validity 分开讨论。
9. **Lifecycle：** release、版本兼容、维护、反馈、退役和扩展规则。

### 3.3 推荐的三类核心图

- **Benchmark contract 图：** data owners / sellers / traders → mechanism →
  score/allocation/payment → evaluator-held truth → evidence layers。
- **机制结构曲线：** replication factor、largest-singleton share、efficient trade count
  横轴上的性能与约束变化；它比静态总榜更能体现机制研究价值。
- **profile/rank-reversal 图：** 同一机制在 theorem-friendly 与 assumption-stress
  setting 下的性能、约束状态和名次变化。

论文主文只应保留少量稳定结论。完整 63-method 榜单、来源、N/A 和 claim 对照应由
artifact 提供，避免正文变成目录打印件。

## 4. DataMechBench 当前真正的创新性

### 4.1 可以作为论文核心贡献的部分

#### 创新 A：机制 profile，而不是单分数排行榜

每个方法结果同时保留 valuation score、allocation、payment、真实成本/价值及机制能力，
再分成 performance、constraint、statistical evidence 和 assumption transfer 四层。
这比只比较准确率或 welfare 更贴近 mechanism design 的决策对象。

**创新强度：高。** 这是最清晰的核心贡献，也应成为标题和摘要中心。

#### 创新 B：论文 claim 与实现 fidelity 的机器可读连接

benchmark 为每个方法记录论文、repo、算法位置、`paper_exact` / `official_adapter` /
`paper_variant`、实现偏差和条件化理论预期；`not_met` 仍保留为结果。

**创新强度：中高。** 单独做 provenance catalog 不新，但将其与每次运行、setting
assumptions 和 expectation result 连接，在机制 benchmark 中很有意义。

#### 创新 C：机制论文驱动的结构性 setting 轴

复制倍数、largest-singleton share、efficient trade count 不是任意数据增强，而分别对应
复制操纵、大市场条件和有限交易损失。结果形成可解释曲线：RVSV 压制复制膨胀，
best-singleton 分支随集中度改变相对价值，trade-reduction/SBBA/MUDA 在厚市场中改善。

**创新强度：高。** 这是把理论机制研究转成可比较实验协议的关键。

当前实现已进一步把这项主张落成 block-aware structural profile：每条轴先在 nuisance
block 内归一化和计算 AUC/slope/endpoint，再跨 block 宏平均，并同时报告最差 case、
相邻点不退化率和设计覆盖。它把“性能水平”与“对市场结构的敏感性”分开，避免新的复合
总分；协议和扩展门槛见 `structural_response_protocol.md`。

在此基础上，benchmark 还增加了版本化 discovery layer，把 paired evidence、约束赢家
变化、mean-to-worst gap、结构响应、assumption transfer 和 claim boundary 转成带效应值、
分母、限制与 next test 的机器可读发现。由于规则是在查看 v0.3 结果后形成，当前发现明确
标为探索性；其真正研究价值将在下一版本冻结规则并使用 held-out blocks 后得到检验。详见
`discovery_protocol.md`。

该层现已明确降级为高召回 screening：24 张卡片不是 24 个独立结论。当前正文价值由四个
跨证据 deep dive 承担，分别连接 constraint status 与效率缺口、GFT 曲线与交易容量、复制
rank 与 reward/score magnitude、以及 run-level failure 与论文 claim 的聚合 estimand。
每个专题都保留竞争解释和可证伪实验，完整结果见 `outputs/full/deep_dive_report.md`。

#### 创新 D：owner-level 数据效用与市场机制结果统一

OpenDataVal 的主要对象是 point-level ranking；DataPerf DAM 的主要对象是购买策略；
DataMechBench 把 owner bundle 对下游任务的效用连接到采购和交易的 allocation/payment。

DaDaDa 进一步提供 direct marketplace listing support。本 benchmark 对八个
platform-by-price-mode cohort 分别归一化，保留 ask 的支持几何而不跨价格模式混合原始
金额，并发现 CGL-randomized 相对 proportional share 在八个 cohort 中方向一致，
JT-DEOM 则仍有符号异质性。这缩小了“完全合成经济类型”的缺口，但不构成真实成交或
私有成本证据。

**创新强度：中高。** 需要更多真实或可信校准案例才能把潜力变成强证据。

#### 创新 E：不把不可比问题压成总分

V/P/T 与各 setting 有自己的 primary metric；constraint qualification 和 companion
metrics 不被任意加权。这个选择牺牲了一个容易传播的总榜，但提高了解释有效性。

**创新强度：中。** 不是新算法，却是正确且重要的 benchmark 设计原则。

### 4.2 有价值但不应包装成核心创新的部分

- YAML catalogs、CSV 报告、CLI、manifest、SHA-256、submission checker；
- “包含 76 个被调度方法”本身；
- bootstrap/Wilcoxon/Holm 等标准统计技术；
- 常见 baseline 的重新实现；
- 自动生成 README、metric card 和 setting card。

这些是可信 benchmark 的必要工程和证据基础，但单独不足以支撑研究创新 claim。

## 5. 当前 benchmark 的实际意义

### 5.1 对机制设计研究者

- 快速发现一个 mechanism 的理论优势依赖哪些 assumptions；
- 在同一 case 上同时查看 welfare/utility 与 budget、IR、balance、deviation guardrail；
- 将不满足论文预期的实例保留为可复现 discrepancy，而不是隐藏为实现噪声；
- 为新机制提供可横向扩展、来源清楚的对比对象。

### 5.2 对数据估值和数据市场研究者

- 避免把“数据贡献高”直接等同于“应该支付更多”或“市场配置更好”；
- 将 point/owner valuation、预算采购和交易清算放进同一信息流，但不混为同一任务；
- 用复制、噪声、互补、集中度和厚度揭示不同机制的适用边界。

### 5.3 对实践者

- 不是直接给出“部署哪个机制”的答案，而是帮助筛选候选机制并识别不可审计约束；
- 能区分 performance winner、constraint-qualified winner 和 paper-fidelity winner；
- 提供透明 case 和原始输出，允许使用者替换自己的数据效用与类型分布。

### 5.4 对 benchmark 社区

它探索了一个比“数据集 + accuracy”更适合经济机制的评估单元：

```text
case information structure
  + mechanism outcome (score/allocation/payment)
  + evaluator-held true types
  + observable constraints
  + conditional paper claims
```

如果这一单元经过外部验证，它本身可以成为论文的重要方法论贡献。

## 6. 当前差距审计

### 6.1 科学有效性

| 缺口 | 当前证据 | 风险 | 优先级 |
|---|---|---|---|
| Headline fidelity 回归风险 | 17 个 headline 已有 parity evidence；28 个 catalog 方法仍是 paper variants，完整 run 中 official adapters 多为 capability skip | 后续代码变化或读者忽略 variant 边界时，排名仍可能被误解为原论文完整机制 | 已通过当前 P0；持续 regression gate |
| 非旗舰 case 数与统计功效不足 | 三个旗舰轴已达 20--24 cases，但全局仍有 39.8% pairwise comparisons insufficient | 非旗舰排名容易受少数构造影响，难以形成稳健论文结论 | P0 |
| construct validity 未完全闭合 | 例如复制榜允许负 score 方法以负 share gain 排前 | 指标可能奖励不可比较的 score semantics | P0 |
| truthfulness 只能有限审计 | 固定离散误报网格，随机机制按有限 seeds | 不能支撑 DSIC/BIC 等理论 claim | P0 |
| 真实市场外部有效性弱 | ML 数据真实，但 costs/values 多为透明合成 | 难以说明结论能迁移到真实数据交易 | P0/P1 |
| 约束能力仍缺失 | 402 个约束行中 60 not_auditable | 部分机制无法进入有意义的 constraint-qualified 比较 | P1 |

### 6.2 可复现性和软件发布

| 缺口 | 当前状态 | 应达到的状态 |
|---|---|---|
| 版本单一来源 | release catalog 与 `benchmark/pyproject.toml` 已对齐为 0.3.0 | 保持自动对账，并在 schema/metric 破坏性变更时拒绝生成 release |
| Benchmark CI | Python 3.10/3.12 matrix 已运行 benchmark tests，并直接验证随包模板 | 持续保持并在真实外部提交出现后加入兼容性回归样本 |
| 环境冻结 | 精确 CPU lockfile、Python≥3.10 gate、clean-room 命令和确定性发布包已存在 | 由非实现者在独立环境验证 lockfile 与 setup 时间 |
| 一键复现 | release CLI 可重建 held-out、replication、审计、扩展与论文产物并核对科学摘要 | 取得两份真实外部 machine-readable reproduction records |
| 外部复现 | 当前结果均由同一实现者与环境生成 | 至少一个 clean-room / external reproduction |
| 结果托管 | 仓库内 CSV/Markdown | 可下载的 versioned release bundle 与静态 leaderboard 页面 |

### 6.3 社区可用性和生命周期

- 没有 benchmark 专用 `CONTRIBUTING.md`、`CITATION.cff`、changelog、维护者和反馈 SLA；
- submission checker 已隔离 reference/open identity namespace、要求完整 canonical
  case×seed 网格并审计 N/A/failure，但尚无真实外部包进入独立 open leaderboard；
- submission checker 仍只验证离线结果包，没有公共或半隐藏 evaluator；
- 没有明确新增/修改/弃用 setting 的治理流程，也没有 saturation/retirement 规则；
- 没有真实外部 submission，扩展接口的易用性尚未被第三方验证。

### 6.4 论文叙事风险

1. **范围过宽。** 如果平均用力描述 V/P/T，读者可能看不出一个统一研究问题。
2. **方法很多但 reference-grade 少。** 数量容易被 reviewer 追问为“是否严格复现”。
3. **真实数据标签容易被高估。** 使用 sklearn 数据集不等于真实数据市场。
4. **统计文件很多但 headline evidence 少。** 需要预先选定少量核心 hypotheses。
5. **工程贡献压过科学贡献。** manifest、checker 和 YAML 不应占据主文贡献列表中心。

## 7. 建议的发展路线

路线应分成四个小阶段。前一阶段不达标，不扩展后一阶段。

### 阶段 A：把核心实验变成可信 reference benchmark（最高优先）

#### A1. 冻结三个 flagship axes

主论文只以以下三条结构轴为核心：

- replication robustness；
- seller/value concentration；
- market thickness。

其他 setting 保留为扩展结果，但不继续无边界增加。新增 setting 必须同时满足：明确机制
问题、至少 5 个论文机制、不能由已有轴回答、有可验证的 primary/guardrail metric。

#### A2. 建立 reference implementation gate

优先对象不是更多方法，而是 headline 方法：VSV/RVSV、Shapley/Banzhaf、Jalaly--Tardos、
CGL/Singer、McAfee、SBBA、MUDA。

每个 headline family 至少满足以下一种：

1. 官方 repo adapter；
2. 逐公式/逐伪代码复现，并通过论文 toy example；
3. 与独立实现做相同输入的 outcome parity test。

验收目标：每条 flagship axis 至少有 2 个 reference-grade paper families；主结果表中
所有结论都可追溯到 paper exact、official adapter 或经过独立 parity 的 variant。

#### A3. 扩充 case，不扩充问题轴

- 每条 flagship axis 至少 20 个独立 cases，而不是把同一个 case 多跑 seeds 当样本；
- 来自至少 3 个数据来源或参数生成族；
- 在看结果前固定 case generator、范围和排除规则；
- 对 headline pair 做 power/sensitivity analysis；
- 将核心 pair 的 `insufficient_cases` 比例降到 20% 以下。

#### A4. 修正 construct 与 metric eligibility

- 复制榜按 score semantics 分组：nonnegative reward mechanisms 使用 reward-share gain；
  signed attribution methods 使用 rank/attack benefit；volume family 单列 characteristic
  inflation，不能由无 characteristic 的方法“赢得”该 claim。
- P 榜同时报告 allocation efficiency 与 constraint-qualified efficiency，明确付款缺失的
  方法不能进入机制合格结论。
- T 榜把 GFT、participant surplus、IR/WBB/SBB 分开，不用 tie-breaking 总分。
- 每个 primary metric 增加“什么机制有资格比较”的 capability contract。

#### A5. 增加小域穷举机制审计

对具有 truthfulness claim 的机制，在小离散类型空间穷举单边偏报；随机机制比较期望效用
并报告 Monte Carlo error。它仍不是通用定理证明，但比五点误报网格更有鉴别力。

### 阶段 B：增加现实性和可迁移性

#### B1. 建立三层 case 来源

1. **Axiom/toy：** 用于精确性质和 paper parity；
2. **Open-data calibrated：** 使用 OpenML/WILDS/DataPerf 可复现数据与自然 group；
3. **Market-calibrated stress：** 依据公开采购/拍卖统计拟合 costs、values、correlation，
   同时公开拟合过程和不确定性。

不建议立即追求不可公开的“真实交易日志”。半合成但可校准、可审计的数据优于无法复现的
私有真实性。

#### B2. 设置 public development 与 held-out challenge

- public core：全部公开，服务机制理解与论文复现；
- held-out challenge：隐藏 case seed/实例，防止对公开 case 手工调参；
- reference division：严格输入、实现披露和全 setting 覆盖；
- open division：允许替换模型、外部数据或新机制，但单独排行。

这借鉴 MLPerf Closed/Open、OpenDataVal 隐藏 noise 和 DataPerf 多轮 challenge，同时保留
本项目的开放研究价值。

#### B3. 增加 compute-aware profile

保留 runtime 和 utility calls，并定义 small/standard/extended 三个预算档。不要把成本与
性能加权为一个总分，而是报告 Pareto frontier，避免昂贵 exact 方法和轻量近似被不公平
混排。

### 阶段 C：把原型变成社区可用 release

1. 统一 package/release/schema 版本来源；
2. benchmark 独立 CI：Python matrix、catalog parity、full smoke、submission validation；
3. 发布精确 lockfile、clean-venv 步骤和 CPU reference command；
4. 增加 `CONTRIBUTING.md`、`CITATION.cff`、changelog、维护者与反馈渠道；
5. 定义 setting admission、breaking change、deprecation 和 retirement policy；
6. 生成静态网站，允许下载 raw rows、查看 case curve、constraint status 和方法来源；
7. 邀请至少两个外部方法提交，记录 onboarding 时间和失败点。

阶段 C 的成功标准不是网页是否漂亮，而是一个未参与开发的人能在干净环境中：

- 10 分钟内运行 MVP；
- 一条命令复现 reference summary；
- 按模板提交一个外部方法；
- 得到与官方相同的 validation 和排名结果。

### 阶段 D：形成论文级外部证据，再谨慎扩展

#### D1. 预注册少量研究问题

建议主论文只回答：

1. 只看 performance 是否会选择违反/不可审计机制约束的方法？
2. 论文机制的相对表现是否随 replication、concentration、thickness 出现可预测变化？
3. theorem-friendly setting 的排名能否迁移到 measured ML utility 或 assumption stress？

#### D2. 做必要 ablation

- setting case cohort sensitivity；
- score aggregation 与 owner partition；
- payment/constraint qualification 是否改变名次；
- paper exact/official 与 benchmark-native variant 的差异；
- seeds、type grid 和 compute budget 稳定性。

#### D3. 独立验证

- 至少一个外部研究者 clean-room 重跑；
- 至少一个 headline mechanism 独立重实现；
- 对错误、差异和不利结果公开 issue/erratum；
- 由机制设计和真实数据市场两个方向的领域专家分别审查 construct validity。

只有完成上述步骤后，才优先纳入 deferred candidates：LAVA/TRAK/DVRL、distributional
procurement（如 GJLZ）以及真正多单位 MIDA。新方法必须进入已有研究问题，而不是为了
扩大数字而新增榜单。

## 8. 建议的优先级清单

### 现在最值得做的五件事

1. **Reference fidelity sprint：** 先核对并升级 8--10 个 headline paper mechanisms。
2. **Case-bank sprint：** 将三个 flagship settings 扩到每个至少 20 个独立 cases。
3. **Metric eligibility sprint：** 修正复制榜等 signed/nonnegative semantics 不一致问题。
4. **Reproducibility sprint：** 统一版本、独立 benchmark CI、lockfile/clean venv、clean run。
5. **External validation sprint：** 找一个外部实现者和一个独立复现者实际使用 submission。

### 暂时不值得做的事情

- 继续增加大量没有论文机制支撑的 market scenarios；
- 建设复杂账号系统或动态在线平台；
- 制作跨 V/P/T 的总分；
- 用更多 common baselines 替代缺少的 paper methods；
- 把 sampled regret 改名为 truthfulness；
- 在 reference fidelity 和 case power 未解决前追求几十个新方法。

## 9. 何时可以称为“有价值、有意义的 benchmark”

建议以以下 release gate 判断，而不是以代码量或方法数判断。

### 科学 gate

- 三个 flagship axes 的 construct、primary metric、eligibility 和限制经过领域审查；
- 每轴至少 20 个独立 cases、3 个来源/生成族和 2 个 reference-grade paper families；
- headline comparisons 有足够 common-case evidence；
- 约束缺失不会被当作通过；关键机制的小域偏报审计完整；
- 至少三条结果是新的、稳定的、对机制选择有指导意义的发现。

### 复现 gate

- benchmark/package/release 版本一致；
- benchmark CI、锁定环境和 reference command 通过；
- clean-room 重跑与官方摘要一致；
- raw result、case hash、catalog、环境和统计产物都可追溯。

### 社区 gate

- 外部研究者能够添加方法而无需改 runner；
- 至少两个外部 submission 或独立复现；
- 有维护者、反馈渠道、贡献规范和版本/退役政策；
- 结果页面能清楚解释“为什么这个方法排在这里”，而不只是显示名次。

达到科学 gate 和复现 gate 后，它就是有说服力的论文 benchmark；再达到社区 gate，才是
有持续影响力的 community benchmark。

## 10. 参考资料

- [HELM: Holistic Evaluation of Language Models](https://arxiv.org/abs/2211.09110)
- [OpenML Benchmarking Suites](https://docs.openml.org/benchmark/)
- [MLPerf submission rules](https://github.com/mlcommons/policies/blob/master/submission_rules.adoc)
- [MLPerf Inference submission guide](https://docs.mlcommons.org/inference/submission/)
- [DataPerf](https://proceedings.neurips.cc/paper_files/paper/2023/file/112db88215e25b3ae2750e9eefcded94-Paper-Datasets_and_Benchmarks.pdf)
- [DataComp](https://arxiv.org/abs/2304.14108)
- [WILDS](https://proceedings.mlr.press/v139/koh21a.html)
- [OpenDataVal](https://papers.nips.cc/paper/2023/file/5b047c7d862059a5df623c1ce2982fca-Paper-Datasets_and_Benchmarks.pdf)
- [DataPerf DAM](https://github.com/facebookresearch/Data_Acquisition_for_ML_Benchmark)
- [AuctionGym](https://github.com/amazon-science/auction-gym)
- [DaDaDa](https://arxiv.org/abs/2607.08785)
- [BetterBench](https://proceedings.neurips.cc/paper_files/paper/2024/file/26889e8359e7ef8a7f5d77457364ca55-Paper-Datasets_and_Benchmarks_Track.pdf)
- [BenchmarkCards](https://openreview.net/pdf?id=b2IJBWhGFu)
- [Statistical Comparisons of Classifiers over Multiple Data Sets](https://www.jmlr.org/papers/v7/demsar06a.html)
- [A Survey on Data Markets](https://arxiv.org/abs/2411.07267)

## 11. 与当前产物的对应关系

- 当前实验规模与新 setting 发现：`benchmark/outputs/full/analysis.md`；
- 原始机制来源与 fidelity：`benchmark/outputs/full/method_sources.md`；
- constraint 状态：`benchmark/outputs/full/constraint_leaderboard.csv`；
- common-case statistics：`benchmark/outputs/full/pairwise_comparisons.csv`；
- assumption transfer：`benchmark/outputs/full/assumption_transfer.csv`；
- benchmark lifecycle card：`benchmark/outputs/full/benchmark_card.md`；
- 后续候选机制：`benchmark/catalog/research_candidates.yaml`。

本文件给出发展判断和优先级，不替代这些机器可读证据。
