# 市场反馈与校准阶段扩展

本阶段补齐市场投入运行后的反馈能力，仍沿用 `UsageEvent`、`QueryResult`、`TaskUtilityResult`、`PricingObservation`、`PriceQuote`、`AnalysisRequest` 和 `AnalysisResult` 等公共协议，不引入新的主链路格式。

DataQuery 新增三类可直接使用的反馈处理：`UsageAggregator` 对事件编号去重并按产品、买方和操作等维度汇总用量、返回记录数、计算耗时与隐私预算；`QueryUtilityFeedback` 把查询成功、结果规模、延迟和显式满意度转成已有任务效用结果；`UsageAnomalyDetector` 标记重复事件、非法计量、配额超限与组内用量突增。异常是复核信号，不直接代表违规结论。

DataValue 新增分组校准、区间覆盖率和排序校准。分组校准可按买方、任务或版本分别估计既有校准参数，避免把不同使用场景混为一个总体；区间报告给出覆盖率、平均宽度和上下界偏离；排序报告检查采购优先级是否和实现价值顺序一致。这些结果用于诊断估值，不改变原估值结果结构。

DataPrice 新增可解释的成交概率逻辑模型与期望收入报价。模型只读取既有 `PricingObservation`，候选报价从 `QuoteRequest.market_context` 提供，并最大化“价格 × 接受概率”。`SafeExplorationPricingModel` 使用 Beta 平滑成交率、确定性随机种子、相邻报价变动上限和反馈去重，适合受控的小流量试价；它不是无限制动态涨价器，生产环境仍需价格门禁、人工审批和合规审计。

Toolkit 的 `ValueRealizationAnalyzer` 联合汇总估值、报价、是否成交和实现价值，输出成交率、报价估值比、实现价值估值比、估值偏差及分组统计。输入继续放在 `AnalysisRequest.options["observations"]`，输出继续使用 `AnalysisResult`，因此可以直接接入既有 benchmark、artifact store 或报表处理。

运行示例：

```bash
PYTHONPATH=src python examples/24_stage12_feedback_calibration.py
```

结果写入 `outputs/stage12-feedback-calibration/result.json`。推荐以固定观察窗口离线训练成交概率，以留出时间段检查校准和收入，并把安全探索限制在业务认可的候选价格及最大变动范围内。
