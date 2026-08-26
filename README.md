# DataValor

**A Toolkit for Data Valorization**

数据智能与价值化实验室（Data Intelligence and Valorization Laboratory, DIV Lab）发起的开源研究工具箱。

> 当前状态：`pre-alpha / repository scaffold`。本仓库目前定义模块边界、参考项目和复用路线，不代表各模块已经具有生产能力。

DataValor 面向数据从“可管理”到“可使用、可交易、可定价”的完整价值链，将研究对象分成三个阶段：

1. **价值发现（Value Discovery）**：DataGov、DataProf、DataEval、DataValue；
2. **价值流通（Value Circulation）**：DataMarket、DataPrice；
3. **价值实现（Value Realization）**：DataQuery。

## 仓库结构

```text
DataValor/
├── src/datavalor/
│   ├── data_gov/                 # DataGov：治理、标准、清洗、安全、元数据
│   ├── data_prof/                # DataProf：统计画像、属性与指标
│   ├── data_eval/                # DataEval：数据质量评估
│   ├── data_value/               # DataValue：数据估值
│   ├── data_market/
│   │   └── simulation/           # DataMarket：市场与参与者仿真
│   ├── data_price/               # DataPrice：定价与机制设计
│   ├── data_query/               # DataQuery：智能问数与数据智能体
│   └── toolkit/
│       ├── benchmark/
│       ├── analysis/
│       └── webui/
├── data/
│   ├── examples/
│   └── dataflow_data/
├── tests/
├── outputs/                      # 默认不纳入版本控制
└── docs/
    └── research/                 # GitHub 调研与 DVMK 复用分析
```

目录采用 Python 可导入命名。例如方案中的 `DataValue` 对应 `datavalor.data_value`；展示顺序和阶段信息可从 `datavalor.MODULES` 读取。没有采用 `0_DataGov` 作为包名，因为数字开头不能成为正常的 Python import 路径。

## 快速检查

仓库当前没有运行时依赖；开发环境可安装轻量测试依赖：

```bash
python -m pip install -e ".[dev]"
python -c "from datavalor import MODULES; print([m.display_name for m in MODULES])"
pytest -q
```

## 已整理的研究资料

- [架构与模块契约](docs/architecture.md)
- [GitHub 项目调研与选型](docs/research/github_landscape.md)
- [机器可读参考项目清单](docs/research/reference_projects.yaml)
- [data_value_market_kit 复用建议](docs/research/dvmk_reuse.md)

参考项目只作为调研对象列出，不表示 DIV Lab 或 DataValor 对其背书。仓库当前尚未迁移这些项目的代码、模型或数据；真正接入前仍需复核版本、许可证、数据权利与安全边界。DVMK 是实验室已有代码基础，将采用“筛选源码、保留 MIT 归属、按 DataValor 模块重构后直接纳入”的方式迁移，而不是作为运行时依赖调用。

## 开发原则

- 质量评估、估值与定价是不同语义层，不把质量分数直接当作价格；
- 算法通过稳定协议和 registry 接入，benchmark 与算法实现解耦；
- 运行产物包含配置、随机种子、版本、输入摘要和 provenance；
- 一般第三方能力优先采用 optional dependency 或 adapter，不直接复制研究仓库源码；
- DVMK 作为已有内部代码基础按文件和算法选择性迁移，迁移后成为 `datavalor.*` 原生实现，并保留完整来源、许可证和改造记录；
- 原始数据、受限数据和大体积输出默认不提交到 Git。

## License

Apache License 2.0。第三方依赖和数据保持各自的许可证与使用条款。
