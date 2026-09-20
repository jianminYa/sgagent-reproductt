# 任务：稳定 Claude-3.5 transport、完善完整 Trace、准备 no-N2D 消融

本阶段为正式 Full14 vs no-N2D 实验做准备。不要启动 SWE-Explore × Verified 全量实验。

模型继续使用 `ep-64pmfvfo`，API 配置继续从 `/workspace/proxy/.env` 安全加载。严格禁止查看、打印、记录或提交 API key/token；不得把 credential 写入命令参数、环境快照、HTTP trace、日志、异常或报告。

## 1. 增加请求级有限重试

在模型 transport 层对同一个 HTTP 请求进行重试，不要因为单次 502 从头重新运行整条 agent 轨迹。

- 只重试 HTTP 502/503/504 和明确的临时网络错误；
- 每个 logical LLM request 最多额外重试 3 次；
- 使用固定并可记录的退避策略，例如 15、30、60 秒；
- 400、401、403、模型名错误、解析错误不得自动重试；
- 每次重试必须使用完全相同的 request body；
- logical LLM call 与 HTTP attempt 分开计数；
- token 只统计成功响应实际返回的 usage；
- Full14 和未来 no-N2D arm 必须使用完全相同的重试策略。

先以 workers=1 重新运行以下三个失败样本，并保留此前所有失败尝试：

```text
matplotlib__matplotlib-26020
sympy__sympy-21379
sympy__sympy-21614
```

如果仍失败，判断失败发生在首个请求、普通小上下文请求还是大上下文请求，并保存证据。不得启用实验层 32,000 字符 guard，也不得截断、压缩或改写官方工具输出。

## 2. 完整 Trace 是正式实验硬性要求

正式实验中的每条轨迹必须能够完整重建 agent 的工作流。任何事件都应立即 flush，进程中断后仍可分析。

### Run 级元数据

记录：

- experiment/run/instance/arm/repeat ID；
- SGAgent commit、working-tree diff hash、目标 repo commit；
- 数据集名称、版本、manifest、sampling seed；
- requested/returned model、provider、protocol、temperature；
- 完整预算、timeout、recursion limit、retry policy、workers；
- prompt 文件、完整渲染后 prompt 或内容寻址引用及 SHA256；
- tool manifest、schema、tool 顺序；
- arm 配置和启用/禁用工具列表。

### 每个 LLM logical call

记录：

- phase、logical call index、时间戳；
- 发送给模型的完整有序 messages，包括 system/user/assistant/tool 内容；
- 完整 request body，但绝对不能记录认证 header；
- prompt/request hash；
- 每个 HTTP attempt 的 attempt index、开始/结束时间、HTTP 状态、延迟、脱敏错误类型；
- 成功响应的完整原始 response body、可见文本、request ID、returned model、stop reason；
- input/output/total/cache token usage；
- 模型生成的原始 `#TOOL_CALL` 文本及解析结果。

### 每个工具调用

记录：

- 工具名称、原始模型调用文本、解析后的完整参数；
- 开始/结束时间和耗时；
- 实际执行内容；对于 shell 工具记录 command、working directory、stdout、stderr、exit code；
- 完整原始返回值及序列化后返回给 agent 的内容；
- 字符数、字节数、SHA256；
- success/failure、异常类型和脱敏异常信息；
- 不得只保存摘要或前后片段。

若单条请求或工具结果过大，可以保存到独立 sidecar/blob 文件，并在 trajectory JSONL 中保存相对路径、SHA256、字符数和字节数，但 sidecar 必须完整存在且能够通过校验恢复，不能借此省略内容。

### 工作流事件

必须记录：

- router 决策和 graph node transition；
- summarizer 的完整输入、输出和 token；
- 所有嵌套 LLM 调用，包括 shell validation model 等隐藏调用；
- `INFO ENOUGH`、`PROPOSE LOCATION`、解析失败与反思轮次；
- KG 构建开始/结束及索引规模；
- 最终原始位置、标准化位置、终止原因；
- retry、resume、timeout、API error 和异常堆栈。

不得把 summarizer、嵌套验证模型或失败 HTTP attempt 漏出总调用统计。需要同时报告：

- logical LLM calls；
- HTTP attempts；
- successful responses；
- model calls by phase；
- tool calls by name；
- token by phase 和累计 token。

### Trace 校验

新增自动校验脚本和测试，至少检查：

- JSONL 事件序号连续且最终事件存在；
- 每个请求都有响应或错误；
- 每个工具调用都有执行结果或异常；
- 所有 sidecar 路径存在且 SHA256 一致；
- 汇总计数可从原始事件重新计算并与 summary 一致；
- trace 和报告中不存在 credential、认证 header 或 `/workspace/proxy/.env` 的内容；
- API key 不得通过测试夹具进入输出。

## 3. 完成并冻结 Claude-3.5 Full14 baseline

三个失败样本恢复后重新离线评估固定 45 样本，不重跑已成功样本，不覆盖旧尝试。报告同时给出：

- 全部样本 operational 指标；
- completed-only conditional 指标；
- 论文 File/Function Jaccard；
- completion 和 provider failure；
- mean/median/p25/p75/p95/max token；
- 极端 token 样本；
- 工具调用与返回体积分布。

如果请求级重试后 provider failure 仍高于 2%，停止，不进入 paired pilot，并给出证据化诊断。

## 4. 准备 no-N2D arm，但不运行正式实验

在同一官方 runner 中增加明确的 arm/feature flag：

- `full14`：完整 14 个工具；
- `no_n2d`：只移除 `find_methods_by_name` 和 `find_all_variables_named`。

no-N2D 必须同时从以下位置移除两个工具：

- system prompt 工具说明；
- tool registry/callable map；
- trajectory 中的 tool manifest。

其余 12 个工具、工具实现、prompt 内容和顺序、workflow、模型、temperature、summarizer、recursion limit、原始未截断输出、retry policy、evaluator、trace schema 必须完全一致。

增加自动 diff 测试，证明两个 arm 的唯一能力差异就是这两个工具。no-N2D 遇到相关名称时仍必须能够通过 `find_files_containing`、`search_code_with_context`、`analyze_file_structure`、`extract_complete_method`、`read_file_lines` 等多步路径完成定位。

只运行 fake/offline 测试验证 arm 配置和 trace，不运行正式付费 paired experiment。

## 输出

- transport retry 实现和测试；
- trace schema、trace validator 和测试；
- 三个失败样本的新尝试及诊断；
- 更新后的 45 样本 baseline 报告；
- Full14/no-N2D 配置 diff 报告；
- 不含密钥的复现命令与配置快照；
- 是否满足进入 10-instance paired smoke 的明确结论。

本阶段禁止：运行 45/90/全量 paired 消融、启用 32,000 guard、删除失败轨迹、发布 GitHub 仓库或记录任何 credential。
