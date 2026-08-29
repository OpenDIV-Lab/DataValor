# DataValor 示例

示例统一使用 DataValor 的配置和公共接口。命令行入口为 `datavalor`：

```bash
datavalor profile --config configs/cli/profile.json --output outputs/profile.json
datavalor evaluate --config configs/cli/evaluate.json --output outputs/evaluation.json
```

示例数据放在 `data/examples/`，配置只引用数据 URI，不绑定固定的源项目 runner。
