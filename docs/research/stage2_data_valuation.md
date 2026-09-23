# 任务效用、估值与数据单元贡献

DataValue 接收治理、画像和质量证据，并在给定买方、任务、成本和效用函数后估算任务价值及数据单元贡献。质量比例不会直接换算成价格。

## 运行

```bash
PYTHONPATH=src python examples/07_stage2_task_valuation.py
```

配置为 `configs/workflows/stage2_valuation.json`，输入为 `data/examples/stage2_valuation_records.jsonl`，输出写入 `outputs/stage2-valuation/`。链路按顺序生成 governance、profile、evaluation、valuation 和 contribution 五个 artifact；后两个 artifact 的父引用包含阶段 1 结果，可回溯估值使用的质量证据。

## 具体实现

### `TabularTaskUtility`

该 utility 接收稳定的样本 ID 到记录的映射，对任意 selection 计算 `[0, 1]` 的任务效用。默认由四项组成：

- coverage：样本数相对于目标样本量的覆盖程度；
- diversity：分组字段（默认 `segment`）的多样性；
- balance：二元标签接近 50/50 的程度；
- freshness：新鲜度字段（默认 `fresh`）的平均值。

权重经过绝对值归一化，零权重时明确返回 0。组件返回的是任务效用，不是货币；更换为留出集 AUC、损失下降或人工节省工时即可用于生产任务。

### `WeightedUserTaskValuator`

对 `EvaluationReport` 中的质量/效用向量按任务权重求加权质量，再乘买方偏好中的 `value_multiplier` 和权利约束中的 `multiplier`，最后扣除 `CostContext.adoption`。`ValueEstimate.components` 保存 weighted quality、raw value 和 adoption cost 等中间量，便于核对计算结果。没有买方或任务时使用代码中列出的默认值，不读取全局状态。

### 贡献度方法

- `LeaveOneOutValuator`：计算完整联盟效用减去移除该单元后的效用，复杂度为 O(n) 次联盟评估；
- `ExactShapleyValuator`：枚举 n! 个排列，默认最多 10 个单元，复杂度 O(n·n!)，超出上限直接报错；
- `MonteCarloShapleyValuator`：按固定 seed 抽样排列，默认 256 次，输出每个单元的 `std_error`、实际样本数和 utility 调用次数，适合较大数据集；
- `BanzhafValuator`：枚举每个单元的所有子联盟，默认最多 16 个单元，输出归一化 Banzhaf 贡献，复杂度 O(n·2ⁿ)。

所有方法都会拒绝重复的 unit ID，避免贡献结果无法对应真实样本。贡献值单位是 `utility`，可以为负，表示该单元降低了任务效用；这与后续如何分摊采购预算或生成价格是两个独立决策。

## registry 与扩展

默认组件已注册：

```python
from datavalor.data_value import CONTRIBUTION_VALUATORS, UTILITY_FUNCTIONS

utility = UTILITY_FUNCTIONS.create("utility.tabular_task")
shapley = CONTRIBUTION_VALUATORS.create("contribution.shapley_monte_carlo")
```

通过 registry 创建的 utility 使用空 records，实际运行时应注入真实映射，或在应用层构造带 records 的 `TabularTaskUtility`。pyDVL/OpenDataVal 适配器继续保留在 `datavalor.data_value.backends`，其结果转换成同一 `ContributionReport`/`ValuationReport` schema。

## 阶段边界与限制

该流程输出效用、估值、贡献度和不确定性，不负责 bid、quote、allocation、payment 或交易结算。金额估计依赖 buyer、task、rights 和 costs 假设，不能直接解释为市场成交价。

本地 utility 面向小型表格和可枚举样本；大规模训练任务应通过 `UtilityFunction` 注入模型训练与留出集评估，并用 Monte Carlo 或 pyDVL 后端控制计算预算。Shapley/Banzhaf 的理论性质（如效率、公平性或策略性质）需要在具体 utility 和采样方案下单独验证，不能仅凭一次运行结果宣称成立。
