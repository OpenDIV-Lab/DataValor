# DataMechBench 0.3 Setting、指标与机制扩展调研

## 结论

本轮没有继续横向铺开隐私、联邦学习、多物品交易等新市场，而是选择三个能让
现有机制产生可解释差异的论文问题轴：数据复制激励、采购市场集中度和双边市场
厚度。这样每个新榜仍有至少十个可比机制，同时新增方法来自具体论文而不是为了
填榜自造规则。

## 纳入的方法

| 轨道 | 方法 | 原始工作/代码 | 本实现位置 | fidelity 与边界 |
|---|---|---|---|---|
| V | Volume Shapley Value | Xu et al., NeurIPS 2021；官方 `VolumeBased-DataValuation` | `valuation_model_based.py` | Eq. 3 的精确 owner Shapley + Vol characteristic；owner/PCA adaptation，`paper_variant` |
| V | Robust Volume Shapley Value | 同上 | `valuation_model_based.py` | cube mean、omega=0.1、alpha=1/(10N)、精确 Shapley；`paper_variant` |
| P | Greedy-TM(0.5) | Jalaly--Tardos, WINE 2018 | `procurement_truthful.py` | 论文停止条件；数值临界支付，`paper_variant` |
| P | Random-TM(0.5) | 同上 | `procurement_truthful.py` | 3/5 greedy、2/5 singleton；分支先由 seed 固定，再算支付 |
| P | Random-EOM(0.5) | 同上 | `procurement_truthful.py` | 1/2 exact-oracle greedy、1/2 singleton；仅小规模 case |
| P | Deterministic-EOM | 同上 | `procurement_truthful.py` | `(sqrt(17)-3)/4` 判断与 exact subset oracle |

直接来源：

- Volume paper: https://proceedings.neurips.cc/paper/2021/hash/59a3adea76fadcb6dd9e54c96fc155d1-Abstract.html
- Volume official repo: https://github.com/ZhaoxuanWu/VolumeBased-DataValuation
- Jalaly--Tardos: https://arxiv.org/abs/1703.10681

## 新 setting 为什么有实际意义

### `V-REPLICATION-ROBUSTNESS`

论文把 inflation 定义为 `nu(replicate(X,c))/nu(X)`，最优 robustness 为 1，并对
beta=10 的 robust volume 给出 1.1 上界。benchmark 同时报告：

1. characteristic inflation：最贴近该理论定义，只适用于显式 characteristic；
2. owner score inflation：攻击者自己的绝对分数是否膨胀；
3. reward-share gain：如果分数被用来分配固定奖励池，攻击者实际多拿多少；
4. rank change：复制是否改变采购/奖励优先级。

主榜选 reward-share gain，因为它跨不同分数量纲仍有决策含义；理论 claim 只标在
characteristic inflation 上，避免把 RV 定理错误移植成 RVSV 支付定理。

### `P-MARKET-CONCENTRATION`

Jalaly--Tardos 的 large-market 分析依赖单个 item 相对 OPT 可忽略。有限 benchmark
不能证明“趋于零”，因此公开记录 `largest_singleton_share=max_i v({i})/OPT`，用
diffuse/moderate/dominant 三档观察每个机制的 oracle ratio 和 efficiency loss。
论文 5、4、4.56 近似保证作为条件化 expectation 保存；随机机制的 guarantee 是
期望福利，而逐 seed claim 检查是刻意保守的，报告中必须同时查看 seed 聚合值。

### `T-MARKET-THICKNESS`

McAfee 最多损失一笔有效交易；MUDA/SBBA 的效率论述也依赖市场变厚。只报告
`trade_count_loss=1` 会掩盖规模效应，所以增加 `(k*-k)/k*`，并把有效交易数
1/3/6/12 固定为 setting 轴。`participant_surplus_ratio` 进一步区分“总 GFT 高”与
“福利被平台留存”，避免只看 allocation efficiency。

直接来源：

- McAfee: https://doi.org/10.1016/0022-0531(92)90091-U
- SBBA: https://arxiv.org/abs/1607.05139
- MUDA: https://ojs.aaai.org/index.php/AAAI/article/view/11450

## 与已有 benchmark 的差异化

OpenDataVal 已经系统比较 point-level data valuation 的污染检测、addition/removal
和运行成本，但不评估 owner 复制带来的支付激励，也不连接采购支付与双边交易约束。
DataPerf DAM 评估预算数据获取，但核心是 acquisition performance，并非多种 truthful
budget-feasible mechanism 的 allocation/payment/IR 横评。DataMechBench 的差异不是
“更多数据集”，而是同一机制 profile 中同时保留：setting 性能、可审计约束、论文
claim、实现 fidelity、paired statistics 和 assumption transfer。

- OpenDataVal paper/repo: https://arxiv.org/abs/2306.10577 and https://github.com/opendataval/opendataval
- DataPerf DAM: https://github.com/facebookresearch/Data_Acquisition_for_ML_Benchmark

## 调研后仍延后的方法

延后不等于不相关，而是当前 case contract 无法忠实复现：

- TRAK、DAVINZ：需要 checkpoint/神经特征协议；
- LAVA：需要 owner-level optimal transport 聚合与 geomloss fidelity；
- DVRL：RL 训练预算与当前 native 协议不可比；
- Information-Gain Shapley：需要共享 Bayesian/GP prior；
- GJLZ additive optimal 与统计估计最优数据获取：需要 cost/data distribution prior；
- MIDA：需要多物品需求与 demand oracle。

这些对象保存在 `catalog/research_candidates.yaml`，不会以不完整近似混入正式榜。
