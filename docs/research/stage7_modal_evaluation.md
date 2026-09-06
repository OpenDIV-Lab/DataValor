# 模态化 DataEval 扩展设计与实现

本轮扩展参考 DVMK `evaluation/text`、`evaluation/image`、`evaluation/audio`、`evaluation/video`、`evaluation/multimodal` 目录的职责划分，但将结果统一到 DataValor 的 `QualityMetric → MetricResult` 契约。每种模态使用独立源文件，避免把图像像素、音频波形和视频时序错误地当作同一种“质量分数”。

## 指标与实现边界

| 文件 | 主要指标 | 计算方法 | 生产替换点 |
|---|---|---|---|
| `tabular.py` | schema、数值统计、IQR 异常值、标签平衡 | 字段类型检查、描述统计、Tukey fences、归一化 Shannon entropy | Great Expectations、Evidently、数据质量平台 |
| `text.py` | lexical diversity、长度、重复率 | token type-token ratio、长度区间、token 频数 | tokenizer、语言识别、语义相似度模型 |
| `image.py` | 元数据、宽高比、像素有效性 | 尺寸/格式/通道校验、median ratio 偏差、像素范围 | PIL/OpenCV、模糊度和感知质量模型 |
| `audio.py` | 元数据、削波、静音 | 时长/采样率/通道校验、PCM clipping、振幅阈值 | librosa、torchaudio、VAD、响度标准 |
| `video.py` | 格式、运动、场景、时序、隐私 | ffprobe 字段、采样帧距离、边界排序、SSIM-like 值、检测计数 | ffmpeg/OpenCV、RAFT 光流、SSIM、YOLO/人脸检测 |
| `multimodal.py` | 包完整性、重复 ID、checksum、时间对齐 | 必需模态检查、SHA-256、timestamp spread | 对象存储 manifest、事件总线、跨模态 embedding |

所有指标都返回 dimension、scope、direction、unit、statistics、Evidence 和 diagnostics。`ScoreDirection.DESCRIPTIVE` 用于运动等不应直接解释成“越高越好”的描述性量；异常率、削波率、隐私风险使用 `LOWER_IS_BETTER`。

## 算法细节

- 表格标签平衡使用归一化熵 `H(p)/log(K)`，比只返回多数类占比更能区分多类别分布；异常值使用 IQR fences，避免均值/标准差被极端值拖动。
- 文本 lexical diversity 使用正则 token 化，并将“有效文本记录覆盖率”与 type-token ratio 加权，避免一条很长文本主导结果；repetition rate 返回每条记录的重复 token 比例并保存高重复证据。
- 图像宽高比一致性按 median ratio 标准化相对偏差；像素检查接受 0–255 的常见编码，同时保留非法像素行级证据。
- 音频 clipping rate 检查 `abs(sample) >= threshold`，silence rate 检查振幅阈值；没有样本时返回明确的空输入行为而不是伪造 0 分。
- 视频运动默认使用 manifest 提供的 sampled frame vectors 计算相邻欧氏距离；真实系统可由光流后端提供同样字段。时序 SSIM、场景边界和隐私检测均保留原始统计，不把后端依赖硬编码进核心包。
- 多模态 checksum 使用 canonical JSON + SHA-256；对齐指标使用 timestamp spread 与 tolerance，能够直接定位未对齐记录。

## 与 DataValue/DataPrice 的衔接

DataEval 只输出质量证据，不输出价值或价格。阶段 3 的 DataValue 可以选择 `quality`、`diversity`、`privacy_risk` 等指标作为 evaluation vector；阶段 4 的报价模型可以在明确业务规则下引用估值结果，但不能把某一个模态分数直接当成交价格。建议在实际项目中为每种下游任务注册指标权重，并保留原始 modality metrics 以便重新估值。

## 复杂度和数据规模

- 表格 schema/统计/文本指标：`O(N × F)` 或 `O(T)`，其中 N 为记录数、F 为字段数、T 为 token 数；IQR 排序为 `O(N log N)`。
- 图像/音频 manifest 指标：`O(N)`，像素/波形展开成本与采样规模线性相关。
- 视频采样帧运动：`O(N × K × D)`，K 为每条视频采样帧数，D 为 frame-vector 维度；默认 K ≤ 16。
- 多模态 integrity/alignment：`O(N × M)`，M 为模态字段数。

## 示例和生产边界

运行：

```bash
PYTHONPATH=src python examples/11_stage7_multimodal_evaluation.py
```

示例使用合成 manifest，输出六组独立报告到 `outputs/stage7-evaluation/result.json`。核心实现不依赖 PIL、OpenCV、ffmpeg、librosa 或深度模型；这些能力应通过 adapter 注入，并记录外部库版本、模型版本和采样参数。生产环境还需要处理版权/许可、个人信息检测误报、模型漂移、采样代表性、音视频解码失败和大文件分片执行。

