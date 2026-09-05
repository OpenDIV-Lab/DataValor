# 阶段 3 实现说明：符号估值、学习型估值与贡献分摊

阶段 3 在阶段 2 的任务效用基础上，补充可解释的符号估值、质量调整和情景估值、可训练的线性估值模型、分类/回归/排序任务指标、Group Shapley、Banzhaf/精确 Shapley 包装器、交互贡献、Bootstrap 稳定性，以及把总价值按贡献分摊到样本单元的会计函数。仍然使用既有 `ValuationRequest`、`ValueEstimate`、`ContributionReport` 和 `UnifiedWorkflowRunner`，不引入第二套估值协议。

## 运行入口

```bash
PYTHONPATH=src python examples/08_stage3_advanced_valuation.py
```

配置为 `configs/workflows/stage3_advanced_valuation.json`，结果位于 `outputs/stage3-valuation/`。示例依次执行治理、画像、质量评估、符号估值、模型训练、学习型估值、精确 Shapley 和贡献价值分摊，所有阶段均产生带父引用和 checksum 的 artifact。

当前示例还会执行 quality-adjusted valuation、保守/基准/乐观情景、按 `segment` 的 Group Shapley、两两 synergy 和 Bootstrap LOO 稳定性分析；这些是独立 artifact，不会覆盖基础估值或贡献报告。

## 组件细节

### `SymbolicValuator`

采用受限 AST 解释器而不是 Python `eval`，只允许数字常量、变量名和 `+ - * / **` 运算；函数调用、属性访问、下标和任意代码都会拒绝。结果中的 `explanation.expression` 和 `components` 保存公式及每个变量值，便于审计和敏感性分析。除以零返回 0，幂指数限制在 [-10, 10]，最终价值下限为 0。

### `LearnedLinearValuator`

提供 `fit → value` 生命周期。训练阶段从 `ValuationRequest.options["evaluation_vector"]` 提取特征，使用带 ridge 正则的正规方程和高斯消元求解系数；输出 `TrainingReport`，包含样本数、特征名、ridge 和训练 RMSE。未训练直接调用 `value` 会明确报错。预测阶段保留截距、系数和输入特征。

### 任务指标

`datavalor.data_value.task_metrics` 提供不依赖第三方库的 `classification_scores`、`binary_roc_auc`、`regression_scores`、`ranking_scores` 和 `incremental_gain`。它们返回混淆矩阵、balanced accuracy、F1、AUC、MAE、RMSE、R²、NDCG@k 和基线增益，可作为真实模型适配器的评估函数。

### 贡献度包装器

`ExactShapleyValuator` 和 `MonteCarloShapleyValuator` 将函数式算法封装为统一 `ContributionValuator`，从 `ContributionRequest.method_options` 读取规模、采样数和 seed。`BanzhafValuator` 枚举子联盟并输出归一化贡献，默认最多 16 个单元。所有贡献算法拒绝重复 unit ID；精确算法超过规模上限直接失败。

`GroupShapleyValuator` 把供应商、批次或区域作为联盟单位；`pairwise_interactions` 计算互补/替代效应；`bootstrap_loo_values` 对 LOO 贡献进行重采样并给出标准误和 95% 区间。三者都保留 utility 调用次数和随机种子，适合采购排序和供应商分摊。

### `allocate_value_by_contribution`

这是透明的会计分摊，不是新的估值算法。给定总金额和 utility 单位贡献报告，默认将负贡献视为 0，再按正贡献比例分配；`negative_policy="signed"` 可保留负权重。返回的 `ValueEstimate.unit` 为 `monetary_allocation`，并保留原始贡献和总金额。零贡献时所有分摊为 0。

## 复杂度与适用边界

- 符号估值：表达式节点数线性计算；
- 线性模型：特征数为 p 时求解约 O(p³)；
- 精确 Shapley：O(n·n!)，默认 n≤10；
- Monte Carlo Shapley：O(samples·n)，输出标准误；
- Banzhaf：O(n·2ⁿ)，默认 n≤16；
- Group Shapley：O(g·g!)，默认 g≤8；
- 两两交互：O(n²) 次效用评估；
- Bootstrap LOO：O(samples·n)；
- 贡献分摊：O(n)。

训练型估值需要历史观测价值，观测值的来源、货币口径和选择偏差应由业务方单独记录；本地实现不声称因果识别或市场均衡。`ValuationReport` 仍与 `PriceQuote`、`Payment` 分离，后续 DataPrice 才能根据市场规则把估值转成报价或清算结果。
