# DataMechBench

DataMechBench 是 DataValor 中相对独立的、面向**数据估值与定价机制设计**的 Python benchmark。它比较的不是孤立算法分数，而是论文机制在明确市场结构下产生的完整结果：

\[
(\text{score},\text{allocation},\text{payment},
\text{evaluator-held types},\text{constraints},\text{provenance}).
\]

一句话定位：**用来源保真的实现、与论文 claim 对齐的证据协议和有机制含义的结构压力测试，判断数据机制何时可比，以及评估选择何时会改变机制准入与推荐。**

- 核心贡献与技术主线：[`docs/core_contribution.md`](docs/core_contribution.md)
- 文档导航：[`docs/README.md`](docs/README.md)
- 核心复现入口：[`reproduction/README.md`](reproduction/README.md)

## 主要贡献

1. **完整机制 profile。** 同时保存性能、allocation、payment、真实类型、适用性和来源；不把缺失支付或不可审计约束记成零，也不生成跨轨道总冠军。
2. **Claim-aligned evidence。** 将论文/代码来源、实现 fidelity、假设、随机性 estimand、source-block 推断、经济约束和有限域激励证据绑定到同一个判定。
3. **Structural decision impact。** 围绕复制、采购集中度和交易几何构造压力轴，并量化忽略统计、支付、约束或反例时，机制 claim 与选择会如何改变。

扩展 catalog 的方法数量用于说明覆盖面和可扩展性，**不是 novelty 论据**。

## 这套系统评估能做什么

DataMechBench 将榜单转化为可执行的研究和选型流程：

- **开发新机制：**在固定 reference、case bank 和统计口径下判断增益，避免因更换数据或 estimand 获得虚假提升；
- **复核论文结论：**把 source claim、实现偏差、假设、随机性和有限反例放在同一证据链中，定位结论成立的边界；
- **诊断机制失效：**区分复制提取、卖方集中度、成交容量、随机分割与定价选择造成的损失；
- **辅助机制选型：**先看任务效用或福利，再按 payment、budget、IR、WBB/SBB 和 auditability 筛选候选，而不是直接部署 raw winner；
- **评估跨来源鲁棒性：**用 source-disjoint blocks、结构曲线、assumption transfer 和 minimax regret 判断推荐是否依赖单一数据源或类型插补；
- **持续扩展 benchmark：**通过 reference/open division 加入新方法和新 case，同时保留旧版本结论和负结果。

这些输出用于研究、工程预选和风险诊断；它们不构成自动采购决策、合规认证或部署许可。更完整的使用者—任务—决策映射见 [`docs/core_contribution.md`](docs/core_contribution.md)。

## 评估范围

reference suite 冻结 17 个 headline 机制族，并维护三个独立分榜。

| 轨道 | Headline scope | 核心结构轴 | 主指标与守卫条件 |
|---|---|---|---|
| V：owner-level valuation | 6 类：Shapley/TMC、Banzhaf、KNN-Shapley、Volume/RVSV | owner replication | utility、rank、reward share、score inflation |
| P：budget-feasible procurement | 6 类：proportional share、CGL、Jalaly--Tardos variants | largest-singleton share × budget pressure | oracle ratio + budget、payment、seller IR |
| T：two-sided trading | 5 类：McAfee、Trade Reduction、SBBA、Lottery-/Vickrey-MUDA | efficient trades × margin/asymmetry | GFT + buyer/seller IR、WBB、trade count |

三个轨道没有共同的加权总分。估值分数、采购效用和交易福利属于不同决策问题；预算、IR、WBB/SBB、覆盖率和运行时间是并列证据，不是用于掩盖失败的权重项。

### 当前规模

冻结的 v0.3 宽实验层包括：

- 161 个 cases、22 个 settings；
- 80 个被调度方法 ID、78 个机制族；
- 19,490 条逐运行结果：10,830 completed、8,660 transparent skips、0 failed；
- 2,027 个 paired comparisons；
- 1,603 条 claim expectations：1,393 met、102 not met、108 not applicable。

扩展 registry 当前有 80 个实现、78 个机制族。核心结论依赖 17 个 headline 机制和来源分离的证据，不用宽 catalog 的规模替代贡献。

### 数据与证据层级

| 层级 | 用途 | 当前内容 |
|---|---|---|
| T0 theorem sanity | 算法分支、退化例和性质检查 | 解析或小型有限实例 |
| T1 controlled structural | 隔离机制结构变量 | 复制、集中度、交易 margin/asymmetry |
| T2 open-data-backed | 测试来源迁移 | OpenML/UCI task utility、ChileCompra、Elexon |
| T3 market-calibrated | 现实支持与敏感性 | DaDaDa listed asks、CNIL aggregate anchors、deal/source audits |

v1 held-out core 每轨包含 3 个独立 source blocks，共 210 条完成结果；v2 每轨增加 2 个来源不重叠 blocks，共 140 条结果。两轮分别推断，不合并为更窄区间。DaDaDa 是挂牌价支持，ChileCompra/Elexon 是制度 proxy，均不解释为真实私有 reservation cost 或数据市场成交类型。

`outputs/kdd_market_semantics/` 进一步把真实语义拆成六个不可替代的证据层。
其中 78 条可再发布的数据许可 deal 记录用于角色、计价方式、金额披露与集中度分析；
它们不用于机制排名，也不被转换为卖方保留价或买方价值。这样，benchmark 可以明确
回答“哪类现实证据支持哪类结论”，而不是用一个含混的真实性标签掩盖证据缺口。

所有完成运行都保留标准化 `outcome`（估值分数，或 allocation/payment）；reference
结果的常规指标由 evaluator 从这些 outcome 和冻结 case 独立复算。v1 的 210 行复算
3,810 个指标值、v2 的 140 行复算 2,540 个指标值，均为零不一致；全量完成结果复算
207,522 个指标值，也为零不一致。需要额外反事实运行的策略指标被显式列为
execution-dependent，而不是伪称可从单次 outcome 恢复。

## 主要发现

### 1. 完整协议会改变哪些结论被接受

- 只看效应方向会接纳 3/6 个确认性比较；完整 block-level 协议只确认 1/6；
- 只看 primary performance 会接纳 11/11 个采购和交易 headline 机制；加入可审计约束后只保留 10/11；

这些 incomplete screens 是诊断性反事实，不是新的 literature baselines。

### 2. 机制次序随来源和市场结构变化

v1 中唯一确认的比较是 RVSV 相比 VSV 将复制 rank gain 降低 0.1746，95% block-bootstrap CI 为 `[0.0952, 0.2857]`。独立 v2 为 0/6 confirmed、6/6 boundary，RVSV 效应衰减为零，Banzhaf 对照变号。采购轨中，CGL-randomized 与 proportional-share 的相对次序也在不同 concentration blocks 间变号。

因此可支持的结论是来源/结构异质性，而不是总体优越性或通用阈值。

### 3. 厚度、容量和选择质量不可互换

4,626-run 受控交易几何研究固定 16 买方、16 卖方和 8 笔有效交易。count-matched frontier 将效率损失拆为容量损失和 selection/pricing residual：Trade Reduction 的 residual 为 0；Lottery- 和 Vickrey-MUDA 的容量损失同为 0.3703，但 residual 相差 0.0301，恰好解释其宏观 GFT 差距。

### 4. Raw winner 不等于合格机制

CNIL aggregate-type envelope 保持 12 个公开接受度锚点不变，只改变九种组内类型配置。5 个 headline references 出现两组排序翻转；VCG 的 GFT 为 1，但 WBB 通过 0/9。单一 profile 选择的最坏迁移 regret 是 minimax 的 6.133 倍。合取 source fidelity、IR/WBB/SBB 和对应有限域激励审计后，当前 5 个 headline 交易机制中通过数为 0。

该空交集是冻结实验域中的 benchmark 结果，不是不可能性定理，也不自动反驳原论文定理。

资格分解进一步表明，这不是一个无法解释的“0/5”：McAfee、Trade Reduction 和
SBBA 各只被一个要求阻断；Lottery-MUDA 与 Vickrey-MUDA 各有两个阻断要求。失败
分为来源 fidelity 缺口、观测 guardrail 失败和有限域反例；`not_auditable` 单独记录，
不会当作失败。最小放宽路径只是诊断，不构成新的综合排名或部署建议。

## 安装与快速运行

DataMechBench 使用原生 Python，不需要 Docker 或虚拟机镜像。根包 `datavalor` 提供可复用机制实现，`benchmark/src/datamechbench` 提供 setting、评估、证据和榜单。

```bash
pip install -e . -e ./benchmark
PYTHONPATH=src:benchmark/src python -m datamechbench.cli run \
  --config benchmark/configs/mvp.yaml
```

运行冻结的完整配置：

```bash
PYTHONPATH=src:benchmark/src python -m datamechbench.cli run \
  --config benchmark/configs/full.yaml
```

从已有 raw results 重建报告，不重跑机制：

```bash
PYTHONPATH=src:benchmark/src python -m datamechbench.cli render \
  --results benchmark/outputs/full/raw_results.jsonl \
  --output benchmark/outputs/full \
  --config benchmark/configs/full.yaml
```

验证冻结 reference core（脚本保留历史兼容文件名）：

```bash
PYTHONPATH=benchmark/src python benchmark/scripts/reproduce_kdd_core.py \
  --verify-only \
  --report /tmp/datamechbench-kdd-reproduction-report.json
```

`--verify-only` 证明当前 release 的内部完整性，不等于外部 clean-room reproduction。公开 DOI 和两名非实现者复现仍是发布 gate。

## 如何阅读输出

输出按证据层分开，不能只看一张总榜。

| 证据层 | 主要产物 | 回答的问题 |
|---|---|---|
| Performance | `leaderboard_*`、`summary_*` | 在给定 setting 的主决策量上谁更好？ |
| Constraint | `constraint_leaderboard.csv`、`mechanism_profiles.csv` | 必要支付/预算/IR/WBB 是否可审计且通过？ |
| Statistical | `pairwise_comparisons.csv`、confirmatory artifacts | common cases 上的差异是否稳定？ |
| Transfer | `assumption_transfer.csv`、direct-market studies | 放宽一个命名假设或替换支持后结果如何变化？ |
| Incentive | finite-audit artifacts | 声明的有限类型/报告域内是否观察到 profitable deviation？ |
| Decision impact | `outputs/kdd_decision_impact/` | 不完整 screen 会改变哪些判定？ |

随机机制先在 case 内聚合 seed，再对独立 cases/source blocks 比较；seed 不被当作独立市场样本。`not_met` 保留在结果中，但不等于理论反证；`not_auditable` 也不等于通过。

## 代码与配置入口

```text
benchmark/
├── catalog/                 # 方法、指标、claim、来源与发布合同
├── configs/                 # MVP、完整实验与冻结研究配置
├── data/                    # 可发布输入、held-out manifest 与校准数据
├── docs/                    # 主线、证据、协议和扩展研究文档
├── evidence/                # hash-bound fidelity/protocol records
├── reproduction/           # 核心复现说明、lock 与 manifest
├── scripts/                 # 构建、运行和验证入口
├── src/datamechbench/       # benchmark runner、settings、metrics、reports
├── submission_template/     # 新方法结果提交模板
├── case_submission_template/# 开放 development case 模板
└── tests/                   # 契约、机制、统计与 artifact 测试
```

算法放置遵循一个简单规则：可被 DataValor 其他组件复用的通用机制放在 `src/datavalor`，benchmark 特有适配器、setting、评估和报告放在 `benchmark/src/datamechbench`。

## 增加一个横向方法

新方法需要：

1. 实现对应 `ValuationMethod`、`ProcurementMethod` 或 `TradingMethod` 协议；
2. 声明 `MethodSpec`、`family_id`、capabilities 和 fidelity；
3. 在 catalog 中绑定论文/repo、算法位置、版本、许可证和显式偏差；
4. 提供 golden/parity case；
5. 只在支持的 setting 上运行，不支持的观测量返回明确 N/A。

runner 和报告不按算法名分支。第三方实现也可以只提交标准结果包：

```bash
PYTHONPATH=src:benchmark/src python -m datamechbench.cli validate-submission \
  --submission path/to/submission \
  --output path/to/submission-validation.json

PYTHONPATH=src:benchmark/src python -m datamechbench.cli evaluate-submission \
  --submission path/to/submission \
  --output path/to/trusted-evaluation.json
```

提交包 1.1 必须包含原始 `scores` 或 `allocation/payment` outcome。提交者附带的
`metrics` 只用于本地诊断；正式榜单读取 `evaluate-submission` 在评测端重算的结果，
从而避免自报分数成为权威来源。

`reference` division 固定论文机制及证据；`open` division 接受新适配器，但在来源、覆盖和守卫条件通过前不会替代 reference 结果。开放 case 通过 `case_submission_template/` 提交，只进入 development，不自动进入 held-out 或正式榜单。

## 与现有 benchmark 的关系

OpenDataVal 聚焦 point-level valuation，DataPerf/DAM 聚焦预算数据获取，AuctionGym/AuctionNet 聚焦竞价策略与大规模环境，SATS 聚焦拍卖实例生成，DaDaDa 提供数据商品挂牌信息。DataMechBench 的限定差异是它们在已审计范围内尚未共同覆盖的交集：

- valuation、procurement、trading 三类数据机制；
- score、allocation、payment 和 evaluator-held types；
- 来源 fidelity、经济约束、有限策略审计和 held-out source-block inference。

这是互补定位，不是无边界的“首个”声明。详细矩阵和审计范围见 [`docs/benchmark_best_practices_research.md`](docs/benchmark_best_practices_research.md)。

## 当前边界

- held-out 核心尚无真实数据卖方私有 reservation cost 或可比成交类型；
- 每轨累计 5 个 held-out source blocks，不能支持总体级最优性；
- 外部作者代码路径覆盖 5/17 个 headline 核心、2/3 个轨道，其余依赖本地 source/core parity；
- 本地 release candidate 尚不能替代公开归档 DOI、社区提交或两名非实现者 clean-room 复现；
- 有限域激励审计是经验反例/未见反例记录，不是 DSIC/BIC 证明。

发布状态和外部复现边界由 `catalog/kdd_public_release.yaml` 与 `reproduction/` 中的机器可读合同记录；KDD benchmark 稿件、venue checklist 和投稿管理位于独立目录 `/root/yusen/datamechbench_kdd2027`，不属于本代码库。其他基于 benchmark 的研究工作也不属于该 KDD 稿件主线。

贡献规范、版本变化与维护政策分别见 [`CONTRIBUTING.md`](CONTRIBUTING.md)、
[`CHANGELOG.md`](CHANGELOG.md) 和 [`MAINTAINERS.md`](MAINTAINERS.md)。
