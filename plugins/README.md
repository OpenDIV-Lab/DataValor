# DataValor 本地插件

本目录用于放置实验性扩展。插件通过 `datavalor.cli.load_plugin` 按文件加载，组件本身应实现
`datavalor.core.BaseComponent` 及对应模块接口，再显式注册到 DataValor registry。

插件不得导入旧项目包名，也不得依赖旧项目的命令行协议或输出目录约定。
