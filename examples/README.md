# DataValor 示例

示例统一使用 DataValor 的配置和公共接口，命令行入口为 `datavalor`：

```bash
datavalor profile --config configs/cli/profile.json --output outputs/profile.json
datavalor evaluate --config configs/cli/evaluate.json --output outputs/evaluation.json
```

示例数据放在 `data/examples/`，配置通过数据 URI 引用输入，并使用 DataValor 自己的 runner。
