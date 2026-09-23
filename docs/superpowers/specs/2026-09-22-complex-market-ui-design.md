# DataValor 复杂输入、定价与市场工作台设计

## 目标

在不增加左侧导航项、不改变现有工作流格式和 API envelope 的前提下，把仓库已有的复杂输入、定价、市场机制与市场分析能力映射到现有 UI。每个可见配置都必须参与真实请求或确定性的离线执行；每个执行结果都必须能追溯到输入、方法、参数和中间步骤。

## 兼容性约束

- 保留 `datavalor.ui-workflow/v1alpha1`、现有节点类型、连线结构和导入导出格式。
- 保留 `/api/operations/{operation}` 及 `{ok,data,warnings,meta}` envelope。
- 原有 `product_id` 单产品请求继续有效；复杂市场通过 `parameters.product_ids`、订单和合同配置扩展。
- 不新增左侧导航项。复杂功能只进入数据产品、定价与市场以及工作流节点的内部视图。
- 不新增前端框架或强制外部依赖，继续使用当前 HTML、CSS、JavaScript 和 FastAPI 服务。

## 输入工作区

数据产品页面和工作流手动输入详情共享统一的输入描述，但保持各自现有存储结构。支持：

1. 内联 JSON 数组、JSON Lines、CSV、TSV 和键值表单。
2. 浏览器文件选择和拖放；文本文件在浏览器解析，二进制或大型文件保存为文件描述而非直接读取。
3. URI、HTTP(S)、对象存储 URI、数据库表引用及自定义 catalog URI。
4. 已登记数据产品、历史产物和上游节点输出引用。
5. 手动 Schema、自动字段推断、字段类型覆盖、编码、分隔符、表头、采样和批次参数。
6. 原始输入、标准化记录、字段推断和解析错误的独立预览。

标准化输出保持现有产品 payload：`data` 保存引用和解析元数据，`records` 保存能够内联的标准化记录，额外输入配置进入 `metadata.input_config`。无效 JSON、行列不一致、未知编码和缺失引用必须在提交前显示字段级错误。

## 定价与市场工作台

现有“定价与市场”页面改为模块内标签工作区：

- 场景：单产品拍卖、多产品组合需求、双边市场、竞争采购、订阅授权和按量交易预设。
- 产品与输入：选择一个或多个数据产品，并展示质量、权利、版本和输入来源。
- 参与方与订单：编辑买方、卖方、预算、数量、Bid、Ask、任务、约束及元数据；支持批量 JSON/CSV 导入订单。
- 定价合同：选择报价模型并渲染模型专属字段。
- 市场机制：选择清算或采购机制并渲染机制专属字段。
- 执行过程：显示标准化、校验、报价、筛选、排序/组合搜索、清算、支付和性质检查步骤。
- 结果与诊断：显示报价、订单簿、分配、支付、收入、福利、供需缺口、市场健康、异常信号和下载入口。

## 定价能力映射

界面从组件目录和一份明确的参数 Schema 生成配置，不根据组件名字猜参数。首批覆盖仓库已注册模型：成本加成、价值分成、基础用量、阶梯用量、订阅与超额、质量与新鲜度、风险调整、价格区间、可比产品、权利差异、新鲜度分层、版本增量和期望收入优化。

报价响应除 `PriceQuote` 外增加工作台 Trace：模型选择、归一化参数、计算分量、约束投影和警告。Trace 作为结果 payload 的附加字段，不修改核心 `PriceQuote` 类型。

## 市场能力映射

市场执行支持一价、二价、VCG、McAfee 双边拍卖、预算可行采购，以及仓库已注册的多单位统一价、预算感知采购和质量感知采购。复杂分析接入：

- `MultiAttributeMarketMatcher`
- `BundleDemandMatcher` 的 AND/XOR 组合需求
- `DemandClusterAnalyzer` 与 `SupplySegmentAnalyzer`
- `MarketGapAnalyzer`
- `analyze_market_health`
- `detect_market_anomalies`
- `evaluate_pricing_properties`
- `audit_pricing_outcome`

多产品订单中的 `product_ids` 必须引用请求中存在的产品。所有金额必须使用同一币种，除非未来显式配置换汇模块。数量、预算和供给不得为负；机制不支持的输入组合在执行前拒绝。

## API 与执行服务

保持通用操作端点，扩展 `OperationPayload`：原有 `product_id` 保留，增加可选 `product_ids`。服务端解析所有产品并交给定价或市场执行器。输入解析采用独立纯函数，定价参数 Schema、市场参数 Schema 和 Trace 生成采用独立服务文件，避免继续扩大 `operations.py`。

建议职责：

- `UI/services/input_parsing.py`：输入格式解析、Schema 推断和错误定位。
- `UI/services/pricing_workbench.py`：模型 Schema、报价请求和报价 Trace。
- `UI/services/market_workbench.py`：订单解析、机制执行、组合撮合和市场诊断。
- `UI/services/operations.py`：保持现有操作分派入口。
- `UI/server/app.py`：保持 HTTP 校验、workspace 读写和 envelope。

## 工作流节点

Price 和 Market 节点详情保持下方面板位置，增加内部标签：输入、方法、参数、参与方/订单、执行 Trace、输出、错误与诊断。节点配置继续保存在 `config`、`components` 和 `parties`；新增订单、合同与 Trace 字段必须有缺省值，使旧工作流可以直接导入。

API 在线时节点运行调用真实操作端点；离线时使用相同输入 Schema 和字段校验，结果明确标记 `execution_mode: offline`，不得伪装成真实仓库算法结果。

## 错误处理

错误分为输入解析、产品引用、定价参数、订单、机制兼容性和执行异常。API 返回既有 HTTP 错误码并在 detail 中携带可定位字段；前端把错误显示在所属标签和控件附近，同时在执行 Trace 中保留失败步骤。币种冲突、空订单簿、无可比产品、组合产品缺失和预算/容量违反分别显示，不合并为泛化的“运行失败”。

## 测试与验收

- 输入解析测试覆盖 JSON、JSONL、CSV、TSV、键值输入、空输入、坏行和 Schema 覆盖。
- 定价测试覆盖每个暴露模型至少一个有效场景，以及缺少必要参数的错误。
- 市场测试覆盖单产品、多产品、AND/XOR bundle、多单位、预算采购、币种冲突和未知产品。
- API 测试证明旧单产品 payload 仍可执行，多产品 payload 能生成产物和 Trace。
- 前端契约测试证明复杂功能在现有页面内部渲染，左侧导航未增加。
- JavaScript 语法、Ruff 和全量 Pytest 必须通过；根目录和 `UI/` 目录启动方式继续有效。

## 非目标

- 不引入实时交易所、外部支付、真实文件上传存储或数据库连接器。
- 不实现货币兑换、身份认证和多租户隔离。
- 不改变 DataValor 核心 dataclass 和 registry 协议。
- 不为尚无仓库实现的方法创建只有名称的占位入口。
