# DataValor 示例

这里的代码按一条实际业务链来组织：先回答“数据对谁有用”，再回答“应该怎样报价和交易”，最后验证“买到以后能否在权利范围内使用”。示例使用仓库已有的公共模型和基线实现，不需要联网，也不要求安装可选依赖。

在仓库根目录执行：

```bash
PYTHONPATH=src python examples/00_unified_value_chain.py
PYTHONPATH=src python examples/01_task_value_and_shapley.py
PYTHONPATH=src python examples/02_auction_and_budget_procurement.py
PYTHONPATH=src python examples/03_governed_query_with_redaction.py
PYTHONPATH=src python examples/04_market_strategy_sensitivity.py
```

`00_unified_value_chain.py` 是阶段 0 的主链路示例：它读取
`configs/workflows/stage0_unified.json`，把一份数据产品依次送入治理、画像、评估、估值、定价、交易、查询、使用计量和分析阶段。每个阶段都会在 `outputs/stage0-unified/` 写出一个带 `parents`、`schema_version`、`producer`、`status` 和 `diagnostics` 的 JSON artifact；运行摘要写入 `summary.json`。如果中途失败，runner 会额外写出 `workflow.failure` artifact，摘要会标记 `failed_stage`，默认不会继续执行后续必需阶段。

四个脚本分别覆盖：

1. 统一主链路：治理、画像、评估、估值、定价、市场、查询、使用计量和分析；
2. 面向任务的效用估值与样本边际贡献（LOO、精确 Shapley、Monte Carlo Shapley）；
3. 将估值转成买方 bid，比较二价、McAfee 双边拍卖和预算可行采购；
4. 在查询前做用途/权利检查，查询后做字段脱敏和行数限制；
5. 在有限轮市场中比较真实出价、固定 shading 和预算 pacing 的成交与福利。

脚本输出 JSON，方便直接接入 notebook、CI 或后续的 artifact store。示例中的数据都是合成数据；接入真实数据时，应在 `DataReference` 中补充 schema、checksum、来源和许可证信息。

## 每个例子具体做了什么

### 01：任务效用和数据贡献

脚本把 5 条带有区域、标签和新鲜度的记录作为一个训练数据产品，定义一个透明的下游效用函数（覆盖率、区域多样性、标签平衡、新鲜度），再用同一函数跑四种估值口径。输出中的 `components`、`utility_calls`、`samples` 和 `std_error` 可直接用于采购排序或标注返工队列。把 `utility` 换成真实模型在留出集上的 AUC/损失，即可进行模型相关估值；样本超过 10 条时应使用 Monte Carlo 或 pyDVL adapter。

### 02：拍卖和预算采购

三个买方对同一气象产品提交支付意愿，三个供应方提交保留价。脚本分别运行二价拍卖、McAfee 双边拍卖和 500 元预算下的采购机制，并打印 allocation、payment、welfare（采购基线未定义买方价值时为 `null`）和 seller revenue。这个例子适合做机制对比和回放测试；生产化时还要增加多产品互补/替代约束、税费、结算失败和支付凭证。

### 03：受治理查询

查询请求先经过 `RightsQueryAuthorizer`，再由注入的 Vanna 风格 planner 生成 SQL，内存 executor 返回记录，最后由 `QueryResultGuard` 对 email 脱敏并限制最多 2 行。脚本同时展示允许和拒绝两条路径，拒绝时不会调用 executor。将 planner/executor 换成企业 SQL、DB-GPT 或 PySyft 后，仍可沿用相同的授权与审计结构。

### 04：市场策略敏感性

同一个买方价值 500 元、预算 600 元，连续 8 轮使用 first-price auction，分别比较 truthful、0.85 固定 shading 和 budget pacing。输出成交轮数、成交率、卖方收入和报告福利；它是实验观察，不是均衡证明。将 `rounds`、买方数量、卖方 ask、随机种子和策略参数放入 benchmark 配置，就能扩展成批量敏感性实验。

## 示例与真实部署的替换点

示例把“可替换的外部系统”集中在很小的函数里：效用函数可以换成训练集上的 AUC/损失下降，拍卖机制可以换成自定义 `PricingMechanism`，查询脚本中的 planner/executor 可以替换为 DB-GPT、Vanna、SQL 引擎或 PySyft executor。这样既能复现实验，也不会把某个供应商 SDK 写死在业务模型中。

更完整的行业背景、方法选择和能力边界见 [数据估值定价调研与 DataValor 能力地图](../docs/research/data_valuation_pricing_landscape.md)。
