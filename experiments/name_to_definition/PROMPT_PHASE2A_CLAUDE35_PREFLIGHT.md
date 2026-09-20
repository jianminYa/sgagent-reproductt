# 任务：Claude-3.5 API 联通测试与正式实验预检

本阶段只完成 API 验证和小规模预检，不运行 45/90/完整样本实验，也不运行 N2D 消融。

## 最高优先级：先验证 Claude API

API 配置位于：

```text
/workspace/proxy/.env
```

### API 密钥安全红线

严格禁止查看 API key/token 的内容。不得使用 `cat`、`less`、`head`、`tail`、`grep`、`sed`、`awk`、`printenv`、`env`、`set`、调试器或任何脚本输出 `.env` 中的密钥值，也不得在终端、日志、测试输出、异常、trajectory、报告、进程参数或提交内容中显示其全部或部分字符。

只能将 `/workspace/proxy/.env` 直接加载到当前进程环境，并以 `set/unset`、布尔值或变量名列表的形式确认必要变量是否存在；不得回显变量值。HTTP header 必须在进程内部从环境变量构造，禁止把密钥展开到可见命令行。如果任何现有脚本可能打印 credential，必须先阻止该输出，再进行 API 请求。

必须先执行以下工作，成功后才能继续其他任务：

1. 安全加载该 `.env` 中的 API base URL、credential 和模型配置。不得查看、打印、记录或提交 API key/token，也不得把密钥放入报告、trajectory、命令参数或错误信息。
2. 先发起一次最小化 API 请求，只要求模型返回简短固定文本，验证：
   - 网络和认证可用；
   - Anthropic/OpenAI-compatible 协议类型；
   - requested model；
   - API 实际 returned model；
   - request ID；
   - stop reason；
   - input/output token usage。
3. 必须确认实际返回的是可识别的 Claude-3.5-Sonnet 模型或其明确版本。如果请求别名与返回模型不同，要如实记录。
4. 将脱敏结果保存到：

```text
experiments/name_to_definition/reports/claude35_preflight/connectivity_report.json
```

5. 如果认证、协议、模型名称或请求失败，立即停止后续付费运行，保存脱敏错误类型和诊断结论，不要反复无限重试，也不要自行改用其他模型。

## API 联通成功后

1. 检查 Full14 工具输出过大的问题。已知 `extract_complete_method` 曾返回约 123 万字符并导致 HTTP 400。
2. 为正式实验增加统一、可审计的工具输出保护：
   - 对所有实验 arm 使用完全相同的限制；
   - 尽量保留方法主体和定位信息，限制过大的关系数据；
   - trajectory 记录 `original_chars`、`returned_chars` 和 `truncated`；
   - 不修改 N2D 工具的排序或语义；
   - 保留此前 faithful reproduction 结果，不覆盖旧目录。
3. 补充并运行单元测试，覆盖正常输出、截断输出和必要定位字段保留。
4. 使用 API 返回确认过的 Claude-3.5-Sonnet，运行一次单样本端到端 Locator 测试，确认官方文本 `#TOOL_CALL` 协议、summarizer、`INFO ENOUGH -> PROPOSE LOCATION` 和 `recursion_limit=150` 正常。
5. 单样本成功后，运行固定的 8 个 Full14 smoke 样本。使用现有 smoke manifest，不进行 no-N2D arm：

```text
experiments/name_to_definition/manifests/full14_smoke_8_seed_20260915.json
```

## 输出与验收

使用新的独立目录，例如：

```text
experiments/name_to_definition/runs/claude35_full14_preflight/
experiments/name_to_definition/reports/claude35_preflight/
```

输出以下内容：

- 脱敏 API 联通报告；
- 配置快照与不含密钥的复现命令；
- 工具输出保护的代码 diff 说明；
- 单元测试结果；
- 单样本及 8-sample smoke 的完整 trajectory；
- completion、token、LLM/tool/summarizer 调用、工具返回体积、终止原因和模型元数据汇总；
- 是否满足进入 45 样本 Claude-3.5 baseline 的明确结论。

验收条件：

- API 最小请求成功，真实 returned model 已记录并确认；
- 密钥未泄露；
- 超大工具输出不会再次导致上下文 HTTP 400；
- 8 个 smoke 样本完成率不低于 95%，即应完成 8/8；
- token usage 和 request ID 记录完整；
- 本阶段不得运行正式 N2D 消融或完整规模实验。
