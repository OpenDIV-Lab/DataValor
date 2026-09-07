# DataProf 增量：统计画像、抽样与漂移

本轮扩展保持 `DataProfiler`、`ProfileMetric`、`ProfileComparator` 和现有 `DatasetProfile` 格式不变，新增可独立注册的描述性算子。它们输出可复核统计事实，不直接判定质量、价值或价格。

## 数值画像

`RobustStatisticsMetric` 计算 q01/q05/q25/median/q75/q95/q99、方差、标准差、变异系数、IQR 以及 Tukey `Q1-1.5*IQR`/`Q3+1.5*IQR` 围栏和异常数量。分位数采用线性插值，方差按总体口径计算，结果中保留样本数；没有有限数值时返回空 statistics 和原因诊断。该结果可用于下游选择截尾均值、winsorization 或 DataEval 异常指标，但本身不把异常数解释成“不合格”。

## 类别集中度与相关性

`CategoricalConcentrationMetric` 返回 distinct 数、基数比、Shannon entropy（bit）、最大熵、Gini 集中度、top-10 频率和覆盖率，适合识别长尾类别、标签塌缩和高基数键。`PairwiseCorrelationMetric` 对两个字段计算 Pearson r、样本协方差及两侧方差，少于两组有效数值时返回 `None` 并写入诊断；常量列不会被强行设为 0。

## 可复现分层抽样

`stratified_sample(records, strata_fields, sample_size, seed)` 按分层比例分配样本，使用 largest-remainder 修正余数，并在样本容量允许时保证每层至少一行。每层内部和最终结果都使用独立的确定性随机顺序；同一 seed、输入和分层字段产生相同结果。它适合将抽样结果注入已有 `ProfileRequest.options["records"]`，不会修改原始数据。

## 漂移报告

`DriftAnalyzer` 对数值字段使用 Population Stability Index（按参考分位数切成最多 10 个桶），对类别字段使用 Jensen–Shannon divergence；每个字段保留 method、statistic、threshold、两侧有效计数以及数值 PSI 的分桶贡献。默认 PSI 阈值 0.2、JS 阈值 0.1 可由调用方覆盖，`DriftReport.summary` 提供漂移字段数和比例。缺失或无有效值时 statistic 为 `None`，不会误报漂移。

漂移阈值只是研究/监控参数：DataProf 不把 `drifted=True` 直接转换为质量分数。应用方可依据业务规则触发 DataEval 重算、DataGov 审核或 DataValue 重新估值。示例见 `examples/13_dataprof_statistics_drift.py`。

