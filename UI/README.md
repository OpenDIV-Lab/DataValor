# DataValor Workbench

DataValor Workbench 用于批量登记数据资产和参与者，运行治理、画像、质量评估、估值、定价与市场配置任务，并在页面中查看运行结果、报价、订单、支付和产物谱系。服务模式调用 DataValor 的 Python 实现；单文件模式可以离线完成一套轻量流程。两种模式都会保存配置、运行记录和环节产物。

## 一分钟产品导览

服务启动后访问 `http://127.0.0.1:8080/tour/`，可通过金融投研、电力调度、临床 RWE 和城市交通四个来源可核验案例，快速查看 DataValor 如何连接数据治理、质量证据、任务估值、报价、市场配置与使用反馈。该导览页位于 `UI/tour/`，与执行任务的工作台相互独立。

需要基于实际工作台界面的无配音动图或视频时，使用 [`demo/`](demo/) 中的可重复录制脚本。操作顺序、字幕、高亮位置和停留时间均由 `demo/tour.json` 配置，便于在界面更新后重新生成。

## 启动

在仓库根目录运行：

```bash
python -m UI.run --port 8080
```

浏览器打开 `http://127.0.0.1:8080`。也可以在 `UI/` 目录执行 `python run.py --port 8080`。

## 多账号与独立工作区

远程或多人使用时启用应用内账号认证。首次启动通过环境变量创建管理员；密码不会写入命令行或配置文档：

```bash
export DATAVALOR_ADMIN_USERNAME="admin"
export DATAVALOR_ADMIN_PASSWORD="<至少 10 个字符的初始密码>"
python -m UI.run --host 127.0.0.1 --port 8080 --auth \
  --auth-root /var/lib/datavalor/auth \
  --workspace-root /var/lib/datavalor/workspaces
```

管理员登录后可从工作台右上角进入“账号管理”，创建普通账号或其他管理员，并可停用账号、重新启用或重置密码。每个账号使用不可变账号 ID 对应到独立目录；数据产品、参与者、批次、运行记录与产物不会跨账号读取或写入。产品导览 `/tour/` 保持公开，工作台与业务 API 需要登录。

部署在 HTTPS 反向代理之后时增加 `--secure-cookie`。首次成功启动后可以从服务环境中移除 `DATAVALOR_ADMIN_PASSWORD`；账号文件只保存 PBKDF2-HMAC-SHA256 密码哈希，后续账号均由管理员界面创建。`--auth-root` 和 `--workspace-root` 必须位于 `UI/` 静态目录之外并限制为服务账号读写，应用会拒绝不安全的目录配置。失败登录同时按来源地址和账号限速。

## 单文件离线版

在仓库根目录生成可复制、可直接双击打开的单文件工作台：

```bash
python -m UI.build_standalone
```

输出文件为 `UI/datavalor-standalone.html`，其中已经内嵌界面样式、交互代码、场景、方法目录和参数 Schema，不依赖 CDN 或其他本地文件。通过 `file://` 打开时，场景载入、资产与参与者注册、CSV/TSV/JSON/JSONL 预览、各环节任务、代理订单和市场清算均可使用，工作区保存在浏览器的 `localStorage` 中。

离线执行器提供透明、确定性的常用实现，便于断网演示和案例复现；需要完整 Python 方法目录或扩展组件时使用本地服务模式。

## 工作方式

一次完整操作由四步组成：

1. 在左栏选择市场场景，主面板显示候选数据资产、权利、质量、新鲜度和参考报价。
2. 批量选择产品，按需启用 `Govern → Profile → Evaluate → Value → Price → Market` 环节。
3. 选择定价模型和市场机制，运行批次。每个产品独立保留阶段状态，单项失败默认不会丢失其他成功结果。
4. 在结果页比较任务估值、合同报价和质量信号，并下钻到生产者、耗时、产物和错误；批次可以导出为 JSON。

页面内置四组可重复加载的合成场景，以及四组来源可核验的具体应用：

- AI 训练数据采购：法律问答、代码推理和工业视觉指令数据；
- 零售需求数据订阅：门店销量、促销、天气和匿名客流信号；
- 工业传感数据采购：振动、维修工单和设备能耗时序；
- 临床研究数据许可：实验室指标、影像标注和随访结局。

来源可核验应用包括 NYC 出行需求数据采购、PJM 小时负荷数据订阅、临床 RWE 数据许可，以及基于 SEC 点时财务事实与 FRED 利率观测的金融投研数据采购。它们分别给出官方记录、衍生产品、买卖方、业务需求、评价维度、估值/定价方法与市场过程；商业报价明确标记为案例假设。完整数据来源和设计依据见 [`REAL_WORLD_CASES.md`](REAL_WORLD_CASES.md)。

合成场景用于验证工作流和接口；来源可核验应用保留官方样本的记录级出处，并以规模受控的复现实例展示完整过程。生产项目可在相同接口下接入完整数据源和尽调材料。

## 执行内容

工作台通过 `UI/services/operations.py` 调用仓库实现，包括或不限于：

- `RightsPolicyEvaluator`、`SensitiveFieldScanner` 和 `LocalMetadataExtractor`；
- `BasicDataProfiler`；
- `CompletenessMetric`、`DuplicateRateMetric`、`FieldValidityMetric` 与 `CompositeEvaluator`；
- `WeightedUserTaskValuator`；
- `pricing.subscription`、`pricing.quality_freshness`、`pricing.risk_adjusted`、`pricing.rights_differentiated` 等定价模型；
- `BundleDemandMatcher`、`QualityAwareProcurement`、`MultiUnitUniformPriceAuction`、`McAfeeDoubleAuction`、`VCGMechanism` 等市场机制。

合成场景默认值位于 `services/scenarios.py`，真实应用位于 `services/real_world_scenarios.py`。参数可在各环节主面板修改。服务模式的可执行方法和参数 Schema 由 `GET /api/workbench/schemas` 返回；离线文件从同一构建载荷取得场景与 Schema。

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
