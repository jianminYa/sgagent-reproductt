# 任务：使用 Claude-3.5-Sonnet 完成 Full14 baseline

本阶段使用现有 API 服务，调用方式和 API 地址不变。模型请求名称固定为：

```text
ep-64pmfvfo
```

该名称由用户确认对应 Claude-3.5-Sonnet。API 地址和认证配置位于：

```text
/workspace/proxy/.env
```

## 绝对安全要求

严格禁止查看、显示或记录 API key/token 的内容。

- 禁止使用 `cat`、`less`、`head`、`tail`、`grep`、`sed`、`awk`、`printenv`、`env`、`set`、shell tracing、调试器或脚本输出 `.env` 的密钥值。
- 禁止输出密钥的长度、前缀、后缀、哈希或任何部分字符。
- 禁止把密钥写入代码、命令参数、进程参数、日志、异常、trajectory、配置快照、报告、测试或 Git 文件。
- 只能直接将 `/workspace/proxy/.env` 加载到当前进程环境，并以布尔 `set/unset` 状态确认所需变量存在，不得回显变量值。
- HTTP authentication header 必须在进程内部从环境变量构造，不能在可见 shell 命令中展开。
- 不得修改或提交 `/workspace/proxy/.env`。
- 如果现有脚本可能打印 credential，必须先阻止该输出，之后才能发起请求。

## 执行顺序

### 1. 首先进行最小 API 联通测试

这是最高优先级，成功前不得运行 smoke 或 45 样本实验。

1. 安全加载 `/workspace/proxy/.env`。
2. 沿用其中的 API base URL、认证方式和协议，但在当前进程中将 requested model 设置为 `ep-64pmfvfo`，不要改写 `.env`。
3. 发起一次最小请求，让模型只返回简短固定文本，并记录脱敏元数据：
   - requested model：`ep-64pmfvfo`；
   - returned model；
   - request ID；
   - stop reason；
   - input/output token usage；
   - HTTP 状态和延迟。
4. 用户提供的映射“`ep-64pmfvfo` 对应 Claude-3.5-Sonnet”应标记为 user-provided mapping；不得在 API 未返回底层版本时虚构具体日期版本。
5. 结果保存到：

```text
experiments/name_to_definition/reports/claude35_full14_baseline/connectivity_report.json
```

如果联通、认证或模型调用失败，只允许对明确的临时网络/5xx 错误进行至多 2 次有限重试。仍失败则停止所有后续付费运行，保存脱敏诊断，不得自动切换模型。

### 2. 恢复官方未截断的工具输出行为

正式复现与后续主消融必须遵循公开 SGAgent 的原始工具行为。此前实验层新增的统一 32,000 字符 output guard 不属于论文或公开仓库配置，因此本阶段不得启用该 guard。

- 从本阶段正式运行路径中移除或禁用 `protect_tool_output`，工具返回内容应与原始工具实现完全一致；
- 不得截断、压缩、重排或改写工具结果；
- 可以在不改变返回内容的前提下记录原始返回字符数和估算 token，供诊断使用；
- 之前带 32,000 guard 的运行必须标记为 diagnostic，不得与未截断正式结果混合；
- 新 API 下重新运行单样本和 smoke，验证此前 HTTP 400 是否属于旧 API/代理问题；
- 如果超大结果再次导致 HTTP 400 或上下文错误，应保留失败轨迹并如实报告，不得在主实验中临时开启截断后重跑成功结果；
- 如后续需要 guarded 方案，只能作为单独命名的 sensitivity experiment，不能替代主实验；
- 不覆盖此前 faithful reproduction 或 diagnostic 运行结果。

### 3. Claude-3.5 Full14 smoke

保持以下配置：

- 完整 14-tool prompt；
- 官方文本 `#TOOL_CALL` 协议；
- 官方 Locator workflow；
- `INFO ENOUGH -> PROPOSE LOCATION`；
- summarizer；
- `recursion_limit=150`；
- temperature 0；
- Locator-only，在首次可解析定位结果后停止。

先运行一个样本，成功后再运行固定 8 样本：

```text
experiments/name_to_definition/manifests/full14_smoke_8_seed_20260915.json
```

输出使用独立目录，例如：

```text
experiments/name_to_definition/runs/claude35_full14_smoke/
experiments/name_to_definition/reports/claude35_full14_smoke/
```

要求 8/8 完成，token、request ID、requested/returned model 和 stop reason 完整。失败时保留全部尝试，并执行固定、对称的有限重试策略。

### 4. 固定 45 样本 Claude-3.5 Full14 baseline

Smoke 通过后，复用完全相同的 manifest：

```text
experiments/name_to_definition/manifests/official_lite_45_seed_20260915.json
```

输出到新的独立目录，不得覆盖 Claude Sonnet 5 或旧 5-tool 结果，例如：

```text
experiments/name_to_definition/runs/claude35_full14_baseline/
experiments/name_to_definition/reports/claude35_full14_baseline/
```

使用官方 evaluator 和论文 Jaccard 口径，报告：

- completion 与所有终止原因；
- File/Class/Function/Line Accuracy 和 Line IoU；
- File/Function Jaccard；
- 平均值、中位数、分位数及 bootstrap CI；
- input/output/total token；
- Locator、summarizer、总 LLM 调用和工具调用；
- 各工具调用次数和原始返回体积，并确认实验层 32,000 guard 未启用；公开工具自身原有的返回逻辑保持不变；
- `find_methods_by_name`、`find_all_variables_named` 的调用实例和次数；
- 延迟、API 错误、重试和完成率；
- requested model、returned model、request ID 和 stop reason 完整率。

将结果与论文的 File 81.2%、Function 52.4% 作带有限制说明的比较。可以与现有 Claude Sonnet 5 Full14 结果作描述性比较，但不能把跨模型差异解释为 N2D 因果效果。

特别复查 `sympy__sympy-15609`，观察更换 API 后，未经实验层截断的超大工具结果是否仍会导致 HTTP 400 或上下文错误。

## 最终产物

- 脱敏 connectivity report；
- 配置快照和无密钥运行命令；
- 未截断官方工具行为的核验说明，以及超大输出/API 错误诊断；
- 单样本、8-sample smoke 和 45-sample baseline 的完整 trajectory；
- 逐实例 JSONL/CSV；
- 聚合报告与 reproduction gap report；
- 是否满足进入 Full14 vs no-N2D 正式配对实验的明确结论。

## 本阶段禁止事项

- 不运行 no-N2D arm；
- 不运行正式 N2D 消融；
- 不运行 SWE-Explore × Verified 全量实验；
- 不创建或推送 GitHub 仓库；
- 不删除、覆盖或篡改此前任何成功或失败轨迹。
