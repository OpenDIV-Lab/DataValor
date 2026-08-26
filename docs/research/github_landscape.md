# DataValor GitHub 开源项目调研

## 一、筛选标准

候选项目至少满足以下条件之一：

- 提供可以直接导入的数据估值或数据贡献度算法；
- 提供可复用的数据质量、数据画像、数据治理、市场、定价或智能问数能力；
- 仓库结构适合多模块研究工具箱参考，例如具有稳定接口、registry、插件、benchmark、文档、示例和测试；

复用方式需要区分两类：DVMK 是实验室已有、明确纳入本项目范围的代码基础，将按文件和算法筛选，保留 MIT 归属并重构为 `datavalor.*` 原生代码；本报告列出的其他第三方项目原则上仍通过依赖、adapter、API 或服务边界接入，除非后续完成单独的许可证与源码迁移评审。

## 二、直接相关的数据估值项目

| 项目 | 调研快照 | 值得学习或复用的内容 | 建议 |
|---|---|---|---|
| [aai-institute/pyDVL](https://github.com/aai-institute/pyDVL) | 约 145 stars；LGPL-3.0；仍活跃，最近推送于 2026-04 | 稳定的 `pydvl.valuation` API，覆盖 Data Shapley、semivalue、least core、Data-OOB 和 influence function；`src/`、文档、notebook、测试的组织也很成熟 | **A 级优先**：作为模型相关数据估值的可选后端。通过动态链接/导入依赖使用，不把 LGPL 实现源码复制进 Apache-2.0 核心 |
| [opendataval/opendataval](https://github.com/opendataval/opendataval) | 约 103 stars；MIT；最近推送于 2025-02 | NeurIPS 2023 统一 benchmark；公共 `DataEvaluator`；包含 AME、DVRL、Influence、KNN-Shapley、LAVA、Data-OOB、Volume 等实现，并具有数据集、噪声和实验层 | **A 级优先**：作为 benchmark 参考和兼容适配目标；在把它作为大范围依赖前，重新检查维护状态和版本约束 |
| [ZJU-DIVER/OpenSV](https://github.com/ZJU-DIVER/OpenSV) | 较新的项目，约 8 stars；Apache-2.0；2026 年仍活跃 | Shapley 系列方法、game 抽象、benchmark 脚本，以及许可证较宽松的实现接口 | **B 级/观察**：适合补充算法覆盖，但需独立验证 API 稳定性、算法正确性和规模性能 |
| [reds-lab/LAVA](https://github.com/reds-lab/LAVA) | 约 54 stars；MIT；最近推送于 2024-06 | 不需要预先指定学习算法的最优传输数据估值方法 | **B 级**：作为专门方法和论文实现参考；若维护更好的统一库已提供等价实现，优先从统一库接入 |
| [p-lambda/wilds](https://github.com/p-lambda/wilds) | 约 602 stars；MIT；最近推送于 2024-01 | 真实世界分布偏移、官方数据划分、数据加载器和评估器 | **B 级**：作为 benchmark 和数据分布参考，不把它视为数据估值引擎 |
| [mlcommons/dataperf](https://github.com/mlcommons/dataperf) | 约 25 stars；Apache-2.0；最近推送于 2024-05 | data-centric benchmark 的任务设计和可复现提交方式 | 作为 `toolkit.benchmark` 的结构参考；不能假定项目仍处于高频维护状态 |

### 为什么同时保留 pyDVL 和 OpenDataVal

两者主题接近，但侧重点不同。pyDVL 更强调可复用、经过测试的算法库，以及可扩展的估值与 influence 接口；OpenDataVal 更强调在统一数据、模型、污染方式和下游指标下进行可比实验。DataValor 应定义一个小型内部估值结果 schema，并分别编写适配器，而不是把任一项目的原生对象直接设为全局公共 API。

## 三、价值发现：治理、画像与评估

| 项目 | 调研快照 | 对应模块 | 建议的复用方式 |
|---|---|---|---|
| [cleanlab/cleanlab](https://github.com/cleanlab/cleanlab) | 约 11.6k stars；Apache-2.0；活跃 | DataEval | **A 级优先**：作为标签和样本问题检测、Datalab 报告的可选算子；保留样本级证据，而不是只保留汇总分数 |
| [fivetran/great_expectations](https://github.com/fivetran/great_expectations) | 约 11.7k stars；Apache-2.0；活跃 | DataGov、DataEval | expectation、checkpoint 和 connector 概念值得复用；将其作为外部验证引擎集成，不作为核心强制依赖 |
| [evidentlyai/evidently](https://github.com/evidentlyai/evidently) | 约 7.8k stars；Apache-2.0；活跃 | DataEval、Toolkit/Web UI | 指标、测试、报告快照和监控交互设计很有参考价值；适配器默认不应加载 Web UI 相关重型依赖 |
| [awslabs/deequ](https://github.com/awslabs/deequ) | 约 3.6k stars；Apache-2.0；活跃 | DataGov、DataEval | 成熟的 Spark 规模约束验证和指标仓库；其主要生态是 JVM/Spark，适合通过服务或文件产物边界接入 |
| [Data-Centric-AI-Community/fg-data-profiling](https://github.com/Data-Centric-AI-Community/fg-data-profiling) | 约 13.7k stars；MIT；活跃 | DataProf | 一行式 DataFrame 画像和报告结构值得参考；旧 `ydataai/ydata-profiling` 地址当前会重定向到此项目，集成前必须重新确认发行包身份和版本关系 |
| [datahub-project/datahub](https://github.com/datahub-project/datahub) | 约 12.6k stars；Apache-2.0；活跃 | DataGov | 元数据图、血缘、领域、所有权和可扩展 ingestion；应通过 API 或事件集成，不把这个大型平台嵌入算法包 |
| [open-metadata/OpenMetadata](https://github.com/open-metadata/OpenMetadata) | 约 15.0k stars；Apache-2.0；活跃 | DataGov、DataQuery | 目录、血缘、治理和 Data/AI context；适合作为 API 级集成对象，不作为 Python 算法依赖 |
| [Lightning-AI/torchmetrics](https://github.com/Lightning-AI/torchmetrics) | 约 2.5k stars；Apache-2.0；活跃 | DataEval、Toolkit | 小型 metric 协议、状态与聚合、指标集合、测试和可选领域依赖的优秀结构参考 |

DataValor 不宜重新实现一个完整的数据目录平台。DataGov 应定义便携的治理和血缘产物，以及 DataHub/OpenMetadata 适配器。以实验室工具箱的投入规模，很难合理替代这些平台已经具备的数据摄取、身份管理、检索和政策能力。

## 四、价值流通：隐私、市场与仿真

| 项目 | 调研快照 | 对应模块 | 建议的复用方式 |
|---|---|---|---|
| [OpenMined/PySyft](https://github.com/OpenMined/PySyft) | 约 10.0k stars；Apache-2.0；活跃 | DataGov、DataMarket | 支持数据保留在所有者侧的远程数据科学和权限控制；适合作为架构参考或服务集成，不适合作为轻量核心依赖 |
| [oceanprotocol/ocean.py](https://github.com/oceanprotocol/ocean.py) | 约 173 stars；Apache-2.0；最近推送于 2025-08 | DataMarket | 覆盖数据资产发布、发现、消费、service 和隐私交换流程；**B 级**：用于参考市场生命周期和资产元数据，因协议和区块链耦合较强，只通过适配器接入 |
| [data-dot-all/dataall](https://github.com/data-dot-all/dataall) | 约 257 stars；Apache-2.0；活跃 | DataGov、DataMarket | AWS 上较贴近真实业务的数据市场、目录、访问申请和共享流程；很好的产品和工作流参考，但基础设施绑定较强，不作为核心可导入算子 |
| [mesa/mesa](https://github.com/mesa/mesa) | 约 3.8k stars；Apache-2.0；活跃 | DataMarket/Simulation | 可导入的 agent-based modeling、调度器、数据采集和可视化；**A 级优先**：当 DVMK 的轻量模拟器不足以表达复杂参与者行为时，作为可选仿真后端 |
| [salesforce/ai-economist](https://github.com/salesforce/ai-economist) | 约 113 stars；BSD-3-Clause；**已归档** | DataMarket/Simulation | 模块化 agent、component、scenario 和经济政策实验；只作为仓库结构和研究方法参考，不作为新运行时依赖 |

本次调研没有发现一个成熟的 Python 库能够同时完整覆盖“数据产品估值 + 通用拍卖/采购定价 + 市场 benchmark”。因此，DataValor 初期应从 DVMK 中筛选机制、registry、市场 benchmark 和仿真实现，经过拆分、去耦、重命名和性质复核后直接迁入 DataPrice、DataMarket 与 Toolkit；DVMK 不成为 DataValor 的运行时依赖。每一种迁入机制仍须分别对照原始文献和性质测试进行验证。

## 五、价值实现与仓库工程结构

| 项目 | 调研快照 | 对应模块 | 建议的复用方式 |
|---|---|---|---|
| [eosphoros-ai/DB-GPT](https://github.com/eosphoros-ai/DB-GPT) | 约 19.8k stars；MIT；活跃 | DataQuery | 数据应用/智能体架构、connector、Text-to-SQL 和服务化；整体技术栈较大，优先通过 connector 或服务适配器集成 |
| [vanna-ai/vanna](https://github.com/vanna-ai/vanna) | 约 23.8k stars；MIT；在核验快照中**已归档** | DataQuery | RAG-to-SQL API 和交互体验的历史参考；项目处于归档状态时不建立新的核心依赖，后续重新检查维护者给出的 successor 或迁移建议 |
| [kedro-org/kedro](https://github.com/kedro-org/kedro) | 约 11.0k stars；活跃 | Toolkit、全部模块 | 模块化 pipeline、catalog/config 分离、项目模板、hooks 和可复现性；借鉴其边界和工程约定，初期不需要整体引入 Kedro 框架 |
| [microsoft/FLAML](https://github.com/microsoft/FLAML) | 约 4.4k stars；MIT；活跃 | Toolkit/Benchmark | 可插拔 estimator、调优和实验接口；将来出现自动算法选择需求时再参考，不属于第一阶段范围 |

DataQuery 的政策约束必须发生在真正执行查询之前，不能只写进 prompt。查询轨迹至少应记录：目录对象、认证主体、获批用途与权利、生成的查询、执行目标、结果脱敏过程，以及输出产物的下游血缘。

## 六、值得采用的仓库设计模式

在成熟度较高的候选项目中，可以反复观察到以下有效模式：

1. 使用小型可导入核心，并把领域能力和后端放入可选依赖；
2. 使用明确的基础协议和结果对象，不把脚本本身当作公共 API；
3. 为算法、数据集、指标和模型提供 registry 或插件机制；
4. benchmark runner 与具体算法实现分离；
5. 同时维护 `src/`、测试、示例/notebook、文档和引用信息；
6. 输出有版本、可检查的产物，并显式记录确定性随机种子；
7. 后端缺失时执行明确的能力检查和错误提示，不静默降级或假装成功。

同样需要避免几种问题：不保留来源就内嵌论文仓库源码；把 stars 数量当作算法验证；强迫只需要算法的用户安装数据目录或 Web UI；以及把市场模拟观察描述为经济学证明。

## 七、建议的集成优先级

### 第一批

1. 固定 DVMK 源码快照，从中选择性迁移 DataEval、DataValue、DataMarket、DataPrice 和 Toolkit 代码，改造为不依赖 `dvmk` 的 DataValor 原生实现，并保留 MIT 来源及逐文件迁移记录。
2. 实现 OpenDataVal benchmark 适配器和 pyDVL 估值后端。
3. 接入 Cleanlab 数据问题和标签质量算子，并保留证据。
4. 根据实际部署环境，在 DataHub 与 OpenMetadata 中选择一个元数据治理适配器。
5. 为 DataQuery 实现带显式政策闸门的 DB-GPT connector 实验。

### 第二批

1. 使用 Mesa 支持更复杂的市场参与者和 agent-based simulation。
2. 增加 Great Expectations 和 Evidently 产物适配器。
3. 对照 Ocean 与 data.all，整理注册、发现、访问申请和交换的完整工作流。
4. 建设 WILDS/DataPerf 风格的 benchmark suite。

### 观察名单或仅作参考

- OpenSV：项目较年轻，需要继续观察接口和 benchmark 稳定性；
- LAVA：较窄的单一研究方法实现；
- AI Economist、Vanna：核验时已经归档；
- 旧 DataScope 或 `ydata-profiling` 链接：当前无法在不经过迁移或重定向的情况下确认和旧论文中完全相同的仓库身份。

这些项目在真正进入实现计划前都需要重新核验。
