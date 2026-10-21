# DataValor Workbench

`UI/` 是面向数据估值、定价和市场配置实验的本地工作台。它不是独立的演示页面：页面发起的治理、画像、质量评价、估值、定价与市场任务均由 DataValor 的 Python 实现执行，运行记录和产物保存在本地工作区。

## 启动

在仓库根目录运行：

```bash
python -m UI.run --port 8080
```

浏览器打开 `http://127.0.0.1:8080`。也可以在 `UI/` 目录执行 `python run.py --port 8080`。页面需要本地 API；直接打开 `index.html` 时会显示离线状态，不会用伪造计算替代 Python 实现。

## 工作方式

一次完整操作由四步组成：

1. 在左栏选择市场场景，主面板显示候选数据资产、权利、质量、新鲜度和参考报价。
2. 批量选择产品，按需启用 `Govern → Profile → Evaluate → Value → Price → Market` 环节。
3. 选择定价模型和市场机制，运行批次。每个产品独立保留阶段状态，单项失败默认不会丢失其他成功结果。
4. 在结果页比较任务估值、合同报价和质量信号，并下钻到生产者、耗时、产物和错误；批次可以导出为 JSON。

页面内置四组可重复加载的合成场景，共 13 个数据产品：

- AI 训练数据采购：法律问答、代码推理和工业视觉指令数据；
- 零售需求数据订阅：门店销量、促销、天气和匿名客流信号；
- 工业传感数据采购：振动、维修工单和设备能耗时序；
- 临床研究数据许可：实验室指标、影像标注和随访结局。

这些记录只用于验证工作流和接口，不是生产数据，也不代表真实个人、患者、设备或交易。

## 执行内容

工作台通过 `UI/services/operations.py` 调用仓库实现，包括或不限于：

- `RightsPolicyEvaluator`、`SensitiveFieldScanner` 和 `LocalMetadataExtractor`；
- `BasicDataProfiler`；
- `CompletenessMetric`、`DuplicateRateMetric`、`FieldValidityMetric` 与 `CompositeEvaluator`；
- `WeightedUserTaskValuator`；
- `pricing.subscription`、`pricing.quality_freshness`、`pricing.risk_adjusted`、`pricing.rights_differentiated` 等定价模型；
- `BundleDemandMatcher`、`QualityAwareProcurement`、`MultiUnitUniformPriceAuction`、`McAfeeDoubleAuction`、`VCGMechanism` 等市场机制。

场景默认值位于 `services/scenarios.py`。高级参数仍可在主面板以按 operation 分组的 JSON 修改。可执行方法和参数 Schema 由 `GET /api/workbench/schemas` 返回，前端不维护另一套算法实现。

## 批处理接口

```text
GET  /api/workbench/scenarios
POST /api/workbench/scenarios/{scenario_id}/load
POST /api/batches
GET  /api/batches
GET  /api/batches/{batch_id}
```

`POST /api/batches` 接收产品、环节和参数：

```json
{
  "product_ids": ["retail-pos-demand", "retail-local-weather"],
  "operations": ["governance", "evaluation", "valuation", "pricing"],
  "parameters": {
    "governance": {"operation": "analytics"},
    "valuation": {"base_value": 110000},
    "pricing": {"model": "pricing.subscription", "period_fee": 52000}
  },
  "label": "区域补货数据比较",
  "scenario_id": "retail-demand",
  "seed": 42,
  "fail_fast": false
}
```

返回的批次包含逐产品 `stages`、比较用 `metrics`、阶段产物引用、错误和可选的全局 `market_stage`。`UI/workspace/` 是运行时目录，不应作为样例数据提交。

## 交互设计参考

工作台借鉴了 [DataHub lineage](https://docs.datahub.com/docs/features/feature-guides/lineage) 的资产聚焦和溯源方式、[OpenMetadata Data Quality](https://docs.open-metadata.org/latest/how-to-guides/data-quality-observability/quality) 的状态汇总与下钻，以及 [Data-Juicer Quickstart](https://github.com/datajuicer/data-juicer/blob/main/docs/tutorial/QuickStart.md) 的 recipe 与批处理组织方式。界面的业务主线仍是 DataValor 自身的 `Data → Value → Market`。
