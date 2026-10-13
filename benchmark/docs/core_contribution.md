# DataMechBench 核心贡献与技术主线

本文档是 DataMechBench 的权威定位说明。论文、README、报告和演示材料都应从这里派生主叙事，而不是分别发明新的 novelty 表述。

## 一句话定位

> DataMechBench is a claim- and constraint-aware benchmark for data-market mechanisms: it evaluates source-grounded mechanisms through complete outcome profiles, claim-aligned evidence, and structural stress tests that reveal when evaluation choices change mechanism admissibility and selection.

DataMechBench 不是“收集最多算法的榜单”，也不是通用数据市场仿真器。它要解决的问题是：**来自不同论文的数据估值、预算采购和双边交易机制，如何在不丢失支付、约束、假设和证据边界的前提下进行可复现比较。**

## 三项核心贡献

### C1. 完整机制 profile，而不是单一性能分数

每次运行首先记录机制输出，再计算指标：

\[
\text{profile}=(\text{score},\text{allocation},\text{payment},
\text{evaluator-held types},\text{constraints},\text{provenance}).
\]

三个轨道分别报告与其决策问题一致的主指标和守卫条件：

- 估值：任务效用、排名变化、奖励份额提取和分数膨胀；
- 采购：oracle-relative utility，以及预算、卖方 IR 和支付完整性；
- 交易：gain from trade 和成交数量，以及买卖双方 IR 与预算平衡。

不同轨道不生成总冠军，缺失 payment 或真值时也不把不可审计项记成零。`not_applicable`、`not_auditable` 和 coverage 是正式结果。

### C2. 与论文 claim 对齐的证据协议

benchmark 不把“代码跑通”当作论文结论成立。每个 headline 机制和结论都绑定：

1. 论文或上游仓库、算法位置、实现 fidelity 和已知偏差；
2. development、held-out 和 independent replication source blocks；
3. 与原 claim 一致的 estimand、随机性语义、假设和推断单位；
4. 可观测经济约束与有限域激励审计；
5. `confirmed`、`boundary`、`discrepant` 或 `not auditable` 判定。

统计上先在 case 内聚合 seed 和参数点，再以独立来源块为推断单位；预注册比较使用 block bootstrap、效应区间和多重比较校正。负结果、边界结果和反例不被删除。

### C3. 结构压力与 decision-impact 分析

benchmark 不只给排名，还通过三条具有机制含义的结构轴解释排名何时变化：

- owner replication：区分 rank、reward share、score magnitude 和 downstream utility；
- seller concentration：研究 largest-singleton share 与预算压力下的采购次序；
- trade geometry：区分成交容量损失和 selection/pricing residual。

随后用 decision-impact audit 比较不完整与完整评估协议的结论差异。核心问题不是“哪个方法平均最好”，而是：**如果忽略来源保真、支付、约束、统计单位或有限反例，机制准入和选择会改变多少。**

## 技术构件

| 构件 | 技术作用 | 避免的错误 |
|---|---|---|
| Outcome-first runner | 在指标层之前保存 score/allocation/payment 和状态 | 报告层修补或隐藏机制失败 |
| Capability-routed metrics | 只对机制真实支持的输出计算指标 | 把缺失能力当作零或通过 |
| Source/fidelity contract | 绑定论文、代码版本、算法位置和偏差 | 将松散 baseline 冒充原论文机制 |
| Case-bank separation | 隔离 development、held-out 和 replication wave | 看过结果后改阈值或重复使用样本 |
| Claim-aligned inference | 以 source block 为单位，保留 effect、CI、worst block 和 coverage | 把 seed 当独立市场、只看均值方向 |
| Constraint qualification | 将性能与 IR、预算、WBB/SBB、支付完整性并列 | 让不可部署的 raw winner 自动获胜 |
| Finite incentive audit | 保存 profitable-deviation witness 和 estimand 边界 | 把有限实验误写成 DSIC/BIC 定理 |
| Structural decomposition | 分解复制、集中度和交易几何造成的差异 | 用一个宽泛“鲁棒性/厚度”指标解释所有现象 |
| Controlled semantic gold | 在 evaluator 已知诱导类型上重放 allocation/payment 与指标 | 用现实 proxy 冒充可验证的私有类型与真实机制结果 |
| Benchmark metrology | 对全部 17 个 headline 机制执行 56 个科学破坏与 34 个良性控制，并按来源块枚举榜单稳定性 | 用少量探针或测试通过就假定测量有效，或把 seed 当独立市场 |
| Prospective selection | 只在 v1 选型，在独立 v2 报告资格保持与 regret | 看过复现数据后重选方法并称为外部泛化 |
| Track-native resource diagnostics | 估值报告 utility calls；采购报告机制执行期 oracle calls；交易报告消息、清算轮次和随机事件向量 | 用运行时间替代机制成本，或把不可比单位压成跨轨总分 |
| Prospective boundary challenge | 在执行前按理论分支、阈值、tie 与薄市场条件冻结小面板，并与 held-out 推断隔离 | 将低分辨率误写成机制等价，或看到榜单后挑选能拉开差距的 case |
| Exact oracle certificates | 独立枚举每个冻结采购子集与双边市场成交基数，并将最优配置、目标值和原始结果哈希绑定 | evaluator 与 oracle 共用错误路径，导致整个市场轨道的比率分母系统性偏差 |
| Resolution sensitivity envelope | 在固定 `[0,.005,.01,.02,.05]` 网格上报告所有 headline 方法对，保留 0.01 为主口径 | 只展示有利阈值，或把阈值脆弱的分离误写成稳定区分能力 |
| Conjunctive external-asset gate | 分别审计真实类型语义/权利/隐私/转换与作者代码身份/许可/结构/输出 parity | 用“真实”或“作者代码”标签绕过不可复现、不可再分发或语义不完整的证据 |

## 系统评估带来的用途与价值

DataMechBench 的贡献不止是提供一组统一表格。它把“实现一个机制—验证论文 claim—判断约束—选择部署候选”连接为可复现流程，使评估结果能够被后续研究和应用直接使用。

| 使用者与任务 | benchmark 提供什么 | 能支持的决策 |
|---|---|---|
| 新机制研究 | 固定 case banks、reference mechanisms、结构轴和 claim-aligned statistics | 判断改进来自真实机制差异，还是数据、estimand、seed 或比较口径变化 |
| 理论与论文复核 | 来源位置、fidelity/deviation、有限反例和假设迁移记录 | 定位 theorem assumptions 与有限实现之间的边界，生成可复核反例，而不是笼统宣布“理论失效” |
| 算法与系统开发 | outcome schema、capability routing、golden/parity cases 和 open division | 快速接入新机制，发现 allocation/payment 缺失、随机性语义错误和退化分支问题 |
| 数据采购与市场设计 | raw performance 与 budget、IR、WBB/SBB、payment completeness 并列 | 在给定制度约束下形成候选集合，避免直接部署 raw-metric winner |
| 鲁棒选型 | 分层证据 blocks、结构曲线、minimax regret 和 assumption transfer | 判断推荐依赖日期、数据集、来源族、机构、单点类型插补或特定市场结构中的哪一层 |
| 风险与治理审查 | participant impacts、coverage、`not_auditable` 和禁止用途 | 识别证据缺口及受益/受损角色；不能自动生成安全、合规或部署许可 |
| benchmark 社区扩展 | reference/open division、方法与 case submission contract、版本规则 | 在不改写既有冻结结论的情况下加入新方法、新来源块和新压力设置 |

因此，系统级价值可以概括为三个动作：

1. **筛选：**从性能可用的方法中筛出支付和制度约束可审计的候选；
2. **诊断：**解释结论为何随来源、市场结构、随机性或假设发生变化；
3. **积累：**让新机制和新证据进入同一版本化合同，而不覆盖历史结果。

它提供的是研究与设计决策支持，而不是自动采购、合规认证或无人监督的市场部署工具。

## 核心研究范围

reference suite 冻结 17 个 headline 机制族：估值 6 个、预算采购 6 个、交易 5 个。扩展 registry 用于覆盖面和后续接入，不构成 novelty 论据。

真实市场证据不被压成一个“realism”标签。机器可读的 semantic-alignment
层将六种不可替代的证据分开：真实任务效用、跨域类型 proxy、数据商品挂牌价、
聚合接受度锚点、公开数据许可交易披露，以及尚未满足发布条件的链上数据访问结算
候选。78 条 CC BY 4.0 数据许可交易记录可以支持角色、计价方式、金额披露和交易
集中度分析，但其中只有 7 条属于 reported deal amount、2 条为高置信金额，且买方
前两名占 50% 的记录；因此它们不作为 IID 观察，也不生成保留价、买方价值或机制
重放结果。该层的价值是量化每个结论究竟得到 direct、proxy、aggregate-stress 或
unsupported 哪一级支持，而不是伪造一个“真实交易榜”。

| 轨道 | 主要机制 | 结构轴 | 主决策量 |
|---|---|---|---|
| Valuation | Shapley/TMC、Banzhaf、KNN-Shapley、Volume/RVSV | owner replication | utility、rank、reward share、inflation |
| Procurement | proportional share、CGL、Jalaly--Tardos variants | largest-singleton share × budget pressure | oracle ratio + budget/payment/IR |
| Trading | McAfee、Trade Reduction、SBBA、Lottery-/Vickrey-MUDA | efficient trades × margin/asymmetry | GFT + IR/WBB/trade count |

冻结 v0.3 的宽实验层包括 161 cases、22 settings 和 19,490 条逐运行结果（10,830 completed）；核心结论主要依赖 17 个 headline 机制、来源分离的 held-out blocks 和单独冻结的结构研究。完成运行保留标准化 outcome，常规指标可由 evaluator 复算；需要额外反事实运行的策略指标明确排除在单次 outcome 复算之外。方法总数用于说明可扩展性，不能代替贡献论证。

## 已得到的十一个有决策意义的发现

1. **评估协议会改变 claim 接纳。** 只看方向会接纳 3/6 个确认性比较，完整协议只确认 1/6；只看 primary performance 会接纳 11/11 个采购与交易 headline 机制，而完整约束协议只保留 10/11。
2. **机制次序具有来源和结构异质性。** v1 仅确认 RVSV 对复制 rank gain 的改善；独立 v2 为 0/6 confirmed，并出现效应衰减和方向翻转。采购机制次序也随 concentration block 变号。
3. **市场厚度、容量和选择质量不可互换。** Lottery- 和 Vickrey-MUDA 的宏观容量损失相同，但 selection/pricing residual 相差 0.0301；Trade Reduction 的该残差为零。
4. **raw winner 不等于合格机制。** 在 CNIL aggregate-type envelope 中，VCG 的 GFT 为 1 但 WBB 通过 0/9；单 profile 选择的最坏迁移 regret 是 minimax 的 6.133 倍；合取 fidelity、IR/WBB/SBB 和有限审计后，5 个 headline 交易机制的当前通过数为 0。资格分解显示其中 3 个是一条件 near miss、2 个需要放宽两个条件，并分别标注 fidelity 缺口、观测 guardrail 失败、有限域反例和证据缺失。
5. **测量有效性不能由三个探针机制代表整张榜。** method-complete mutation matrix 覆盖全部 17 个 headline 机制：56 个逐方法科学破坏全部被检出，34 个逐方法 runtime/serialization 良性控制全部被接受；其结论仅限于声明的 90 个 cell。累计五来源块的留一块冠军集合恢复率在采购、交易为 1，在估值仅为 0.8，进一步说明“代码可复现”“评测器能检错”和“结论对来源删减稳定”是三种不同证据。
6. **回顾性冠军与前瞻选型不是同一证据。** raw、constraint-aware 和 worst-block robust 三类策略均只用 v1 选型并在 v2 上评估。mean-based 估值选择的 rank-change regret 为 0.0357，而 robust 策略在 v1 保留三个并列方法，它们在 v2 的 regret 从 0 到 0.1429；采购和交易三种策略在当前低区分度支持上均产生相同并列选择。与此同时，17 个 headline 虽全部具有本地 parity，只有 5 个有外部实现比较且采购轨为零。选型迁移、setting 区分度和实现独立性是三种不同证据。
7. **运行规模不能替代区分能力，区分能力也不能替代排序迁移。** 固定容差审计显示 v2 采购主榜 15 个方法对中 10 对完全相等，交易两轮均有 40% 方法对完全相等。完整的 40-pair 前瞻迁移审计进一步表明：采购仅有的 5 个可分方法对和交易仅有的 6 个可分方法对均在 v2 保持，但估值的 15 个 v1 可分方法对只有 9 个保持，4 个反转、2 个衰减为并列，排序分离保持率仅 0.6。因此采购/交易的主要问题是低分辨率，而估值的主要问题是跨波次排序不稳定；二者不能由同一个“榜单稳定”数字替代。该审计包含所有 headline 方法对，不在看到 v2 后挑 pair 或 case。
8. **held-out 并列不等于机制等价。** 独立于 held-out 排名冻结的理论边界面板，在采购 4 个 case 上使 14/15 个 headline 方法对至少分离一次，在交易 5 个 case 上使 10/10 分离；采购 threshold-boundary 单个 case 即分离 14/15。结合第 7 点可知，采购/交易主榜低分辨率主要来自当前来源支持没有充分激活机制分支，而不是实现都产生相同映射。该面板只用于诊断未来 setting 设计，不增加总体推断样本。
9. **机制成本需要原生向量，不能由运行时间或统一分数替代。** 冻结 v1 中，采购效用接近的 CGL-deterministic（oracle ratio 0.9855）与 generalized proportional share（0.9834）分别需要平均 289 和 1,317 次机制执行期 utility calls；交易 direct mechanisms 在同为 24 条报告和一次清算下达到约 0.9063 GFT ratio，而两个 MUDA 变体使用两次清算及平均 24 个随机事件、当前 ratio 为 0.1667。该结果不是复杂度定理，但证明同一质量附近存在可测的资源差异，且不同轨道必须保留不同资源语义。
10. **主指标分母现在可逐案例验证，而不是信任同一实现。** 对 v1、v2 和理论边界面板中的 29 个市场案例，独立证书穷举 14 个采购案例的 2,624 个子集候选，并重算 15 个交易案例的 150 个成交基数候选；所有持久化 `budget_optimum` 与 `efficient_clearing` 配置和目标值均一致。该结果认证的是这些有限案例，不是一般复杂度或最优性定理。
11. **“低分辨率”至少包含阈值脆弱和结构性并列两种不同现象。** 采购自然面板在 0.01 下 v1/v2 均分离 5/15 对，但 v1 在 0.05、v2 在 0.02 即降为 0；交易两轮的 6/10 个可分对一直保持到 0.05。与此同时，理论边界面板的采购 14/15 和交易 10/10 对也都保持到 0.05。因而采购自然面板的弱区分主要依赖小效应尺度，而交易自然面板同时包含稳定可分组与精确等价组；challenge 的作用是定位机制分支，不是替代自然面板。

这些结论描述冻结实验域中的证据，不是总体最优性、机制不可能性或对原定理的自动反证。

## 与相邻 benchmark 的差异边界

在直接审计的 OpenDataVal、DataPerf/DAM、AuctionGym、AuctionNet、SATS 和 DaDaDa 等相邻工作中，没有一个同时覆盖以下交集：

- owner-level valuation、budget-feasible procurement 和 two-sided trading；
- score、allocation、payment 与 evaluator-held types；
- 来源 fidelity、经济约束、有限策略审计和 held-out source-block inference。

这是一项限定在已审计集合内的交集差异，不是“首个/唯一”式无边界优先权声明。DataMechBench 与上述项目是互补关系：它牺牲通用市场仿真规模，换取论文机制、经济结果和证据边界的一致评估。

## 不应扩写的主张

- 不称为所有数据定价算法的统一总榜；
- 不把 DaDaDa listed ask 当作成交价或私有 reservation cost；
- 不把 ChileCompra/Elexon proxy 当作真实数据市场私有类型；
- 不把有限 report grid 的零 witness 写成 strategyproofness 证明；
- 不把三个或五个来源块写成总体抽样；
- 不用 registry 规模、运行数或代码量代替 novelty；
- 不把本机重跑写成独立 clean-room reproduction。
- 不把公开 deal amount、listing ask 或 executed settlement 外推成未观测私有类型；
- 不把重复交易记录当作相互独立的市场样本。

## 面向不同读者的价值

- 机制研究者：可复现原 claim 的 estimand、假设和失败边界；
- benchmark 研究者：得到适用于部分可审计机制的非复合评估合同；
- 数据市场设计者：避免选择高 raw utility 但支付或预算性质不合格的机制；
- 后续贡献者：可在 reference/open division 中增加方法，而不改写冻结论文结论。

当前范围和复现入口见 [`../README.md`](../README.md)，文档导航见 [`README.md`](README.md)。论文稿件、venue-specific claim mapping、投稿材料以及复用本 benchmark 的独立论文研究均维护在代码库之外。
