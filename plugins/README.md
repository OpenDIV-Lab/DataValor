# DataValor 本地插件

本目录用于放置实验性扩展。插件通过 `datavalor.cli.load_plugin` 按文件加载，组件实现
`datavalor.core.BaseComponent` 及对应模块接口后，再显式注册到 DataValor registry。

插件统一使用 DataValor 的包名、命令行协议和输出约定。
