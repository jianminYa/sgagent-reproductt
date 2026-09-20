# SGAgent Name-to-Definition 第一阶段实验：Codex 工作提示词

你正在 `/workspace/projects/agentlab/sgagent` 中工作。请直接完成下面的工程实现、验证和第一阶段 pilot；不要只给方案或停留在代码审查。当前研究仓库应固定并记录上游基线 commit：

```text
33a2cfe61d56494ab2d20a2b0c48c1f43e37b452
```

## 最终目标

构建并运行一个可复现的、仅覆盖 Locator 阶段的配对 A/B 实验，检验：给 SGAgent 增加纯粹的 name-to-definition 能力后，是否能够：

1. 减少 Locator 的总 token 消耗；
2. 减少 Locator 的 LLM 调用轮数和工具调用次数；
3. 提高文件级、函数级和行级定位表现。

第一阶段默认使用固定随机种子 `20260915`，在 SWE-Explore 与 SWE-bench Verified 的交集上选取 45 个样本，所有实验组必须运行完全相同的实例。45 个样本属于 pilot，不得将其描述为最终统计结论。如果环境和预算允许，可通过参数扩展到 90 个，但不得擅自改变默认样本清单。

实验必须保存逐事件 trajectory，使后续能够重建每一次 LLM 请求、模型响应、工具调用、工具结果和最终位置。不要记录或请求模型的隐藏思维链；只保存 API 实际返回、模型可见文本和工具 I/O。

## 已知代码问题：先核实，再修复

在动手前检查相关代码，不要盲目相信下面的行号仍然准确：

- `main.py` 的 tool map 注册了 KG 工具，但 `agent/core.py:create_agent()` 没有 bind tools；当前工具能力主要依赖 `prompts/system.py` 中手写的工具说明。
- 当前生效 system prompt 只列出基础工具；包含 KG/name 工具的完整清单处于注释状态。因此只从 tool map 删除 name 工具可能是 no-op。
- `DISABLE_KG` 会同时移除多个 KG 工具，不能用作本实验的 A/B 开关。
- `tools/retriever_tools.py` 在模块导入时立即执行 `get_retriever()`，即使 baseline 不使用名称工具也可能构建 KG。改成真正的 lazy initialization。
- `main.py` 当前硬编码读取 `dataset/lite.parquet`。实验数据集必须由 CLI/配置明确指定，Verified 实例不能错误读取 Lite。
- `main.py` 会输出 API key。必须删除该输出，并确保日志、异常、manifest、命令行都不泄漏密钥。
- 未注册工具目前会被静默忽略。实验模式下应当记录为明确错误并终止该 run，避免 Agent 空转。
- 现有 `_api_stats.json` 不足以作为完整 trajectory，而且 provider 的 token 字段可能位于 `usage_metadata` 或 `response_metadata.token_usage`。需要兼容并验证两者；token 缺失必须显式标记，不能当作 0。

## 实验范围

主实验只运行 Locator：从 issue 输入开始，到 Locator 第一次成功输出可解析、按相关性排序、最多 5 个代码位置时结束。不要进入 Suggester、Fixer、补丁生成或 reranking，否则会污染定位阶段的 token 和轮数。

定义并分别记录：

- `locator_llm_calls`：Locator 的模型调用次数；
- `tool_calls`：成功提交到工具执行器的调用次数；
- `failed_tool_calls`：未知工具、参数错误和执行异常；
- `reflection_turns`：没有工具调用、也没有完成定位的模型响应次数；
- `summarizer_llm_calls`：如果发生 summarization，单独计数；
- `total_llm_calls`：包括 Locator 和 summarizer；
- `termination_reason`：`completed`、`budget_exhausted`、`timeout`、`parse_error`、`tool_error`、`api_error` 等。

所有超时、预算耗尽、解析失败都保留在结果中并按定位失败处理，不得从结果中删除。

## A/B 的唯一处理差异

至少实现两个 arm：

### A：`baseline`

不向 Locator 暴露任何全仓 name-to-definition 工具。保留正常的多步搜索路径，至少包括：

- `explore_directory`
- `search_code_with_context`
- `find_files_containing`
- `analyze_file_structure`
- `extract_complete_method`
- `get_code_relationships`
- `find_variable_usage`
- `show_file_imports`
- `read_file_lines`

Locator 阶段不要暴露 `execute_shell_command_with_validation`，否则 Agent 可以通过 `grep`/`rg "def name"` 自己重建单步 name-to-definition 捷径。

### B：`n2d`

拥有与 baseline 完全相同的公共工具，并额外暴露纯 name-to-definition 工具。可以保留以下名称，也可以用统一包装器，但 manifest 中必须记录最终接口：

- `find_methods_by_name`
- `find_all_variables_named`

这两个实验版工具只能返回紧凑的“定义候选元数据”，不能返回完整实现或图关系。建议统一返回结构化 JSON：

```json
{
  "query": "save",
  "match_mode": "exact",
  "total_candidates": 12,
  "candidates": [
    {
      "candidate_id": "pkg/model.py:User.save",
      "kind": "method",
      "file_path": "pkg/model.py",
      "full_qualified_name": "User.save",
      "start_line": 120,
      "end_line": 148,
      "signature": "save(self, update_fields=None)"
    }
  ],
  "next_cursor": null
}
```

要求：

- 默认严格名称匹配；若提供 substring fallback，必须由显式参数启用，并在结果中标注 `match_mode`。
- 方法和变量使用一致的字段、repo-relative path 和稳定排序。
- 支持 `top_k` 和 `cursor`，不能把所有同名候选拼接后按字符截断。
- 不能返回 method body、variable content、CALLS、REFERENCES 或其他自动关系展开。
- 获取候选内容必须继续使用与 baseline 共享的 `extract_complete_method` 或 `read_file_lines`，从而隔离 name-to-definition 本身的贡献。
- 不要直接删除原生实现；可以保留为 legacy/native 函数，但实验 prompt 和 tool manifest 只能暴露当前 arm 允许的接口。

除上述名称工具外，两个 arm 的 Locator prompt、模型、temperature、token/turn budget、代码快照、索引内容、完成条件和公共工具必须完全相同。工具说明应从实际 tool registry 动态生成或至少由同一个配置源生成，禁止再次出现“prompt 声明与 tool map 不一致”。

注意：`find_class_constructor(class_name)` 和 `list_class_attributes(class_name)` 也具有全仓按类名解析能力。为了让第一阶段只研究 method/variable name-to-definition，应从两个 arm 的 Locator 公共工具中同时移除，或者在 manifest 中明确禁用其全仓名称查找能力。不要只在一个 arm 中保留。

## 可选诊断 arm

如果实现成本很低，可增加 `native_n2d`，使用 SGAgent 原生的“名称搜索 + 完整代码 + 关系”复合行为，仅作生态对照。它不能替代 `n2d`，也不能用 `native_n2d - baseline` 声称纯 name-to-definition 的因果效果。

## 样本清单

创建确定性的采样脚本和冻结的 manifest，例如：

```text
experiments/name_to_definition/manifests/pilot_45_seed_20260915.json
```

manifest 至少记录：

- 数据集名称、来源 URL/Hugging Face ID、revision/hash；
- 精确交集数量和排序规则；
- sampling seed；
- 选中的 45 个 `instance_id`；
- 每个实例的 repo、base commit；
- `name_eligible` 和 ambiguity bucket。

`name_eligible` 必须用 pre-treatment 信息定义：Issue 中存在 identifier-like token，且该 token 在对应 base commit 的索引中精确匹配至少一个 method 或 variable。不能用某个 arm 是否实际调用名称工具来定义 eligibility，也不能把 gold patch 内容输入 Agent。

pilot 尽量分层：

- name-eligible 与 non-eligible 都要有；
- eligible 中覆盖候选数 `1`、`2-5`、`>5`；
- 避免单一 repository 占据绝大多数样本。

如果无法在 45 个样本中满足理想配比，保留确定性选择，记录实际分布和原因，不要手工挑选有利案例。两个 arm 必须使用同一冻结清单，并随机/交替 arm 执行顺序以减轻服务时间漂移和缓存偏差。

## Trajectory 与运行产物

逐 run 保存 append-only JSONL，建议路径：

```text
experiments/name_to_definition/runs/{experiment_id}/{arm}/{instance_id}/{repeat}/trajectory.jsonl
```

每条事件至少包含：

- `schema_version`
- `run_id`、`experiment_id`、`instance_id`、`arm`、`repeat`、`sampling_seed`
- `sgagent_commit`、当前工作树 diff/hash、`repo_commit`
- `dataset_id`、`dataset_revision`
- `model`、`provider`、`temperature`、所有预算设置
- `prompt_hash`、`tool_manifest`、`tool_manifest_hash`、`index_hash`
- `seq`、UTC timestamp、`phase`、`event_type`
- 对 LLM 事件：实际发送的 role/content、可见响应、token usage、latency；若不能获得 system prompt 的实际渲染内容，必须说明
- 对工具事件：`tool_name`、原始参数、结果、结果字符数/可计算 token 数、latency、异常
- 最终事件：ranked locations、termination reason、aggregate counters

事件应在每一步后立即 flush，保证崩溃后仍可分析。允许额外生成便于聚合的 `summary.json`，但不得代替原始 trajectory。

不要记录环境变量值、API key、Authorization header 或其他凭据。可以记录 provider/base URL 的脱敏主机名。

## Token 计量

优先使用 provider 返回的真实 usage。兼容：

- `response.usage_metadata.input_tokens/output_tokens/total_tokens`
- `response.response_metadata.token_usage.prompt_tokens/completion_tokens/total_tokens`
- provider 可用的 cached/reasoning token 明细。

缺失值写 `null` 并将 run 标为 `token_usage_incomplete=true`，禁止把缺失值转为 0 后参与主分析。

主结果使用包含静态工具说明开销的端到端 token 总量，因为这代表真实使用成本。同时补充诊断指标：首轮 token、后续轮 token、累计工具结果字符/token，以区分“多了工具 schema”和“少了搜索轮次”的影响。

KG/index 构建时间和工具 wall-clock latency 单独记录，不计入 LLM token，但应进入总耗时指标。索引应按 repo commit 缓存，并验证 hash；避免一个 arm 总是冷启动、另一个 arm 总是热启动。

## 定位输出与评价

Locator 的最终输出必须是按相关性排序的最多五个 repo-relative 位置：

```json
{
  "locations": [
    {"file_path": "pkg/model.py", "start_line": 120, "end_line": 148}
  ]
}
```

不要依赖当前从最终 patch 反推位置的 evaluator；实现直接评价 Locator 输出的 evaluator。至少产生：

- file-level hit/accuracy；
- function-level hit/accuracy；
- line-level overlap/IoU；
- 若 SWE-Explore 官方 scorer 可复用，调用其官方实现计算 `HitFile`、`nDCG@500`、Precision、Context Efficiency；不要自行创造同名但不同定义的指标。

另外记录机制指标：

- issue 中可解析的名称数量；
- 名称索引候选总数；
- gold 定义是否出现在候选中；
- gold candidate rank；
- `Recall@1/3/5`；
- Agent 读取的错误同名候选数；
- 首次到达 gold 文件/函数之前的 token、LLM calls 和 tool calls。

Gold 只能用于离线采样标注和评价，不能出现在 Agent prompt、工具返回或在线排序中。

## 第一阶段执行流程

1. 阅读 README、相关 agent/workflow/tool/prompt/logging/evaluation 代码并记录当前行为。
2. 建立独立实验目录，尽量避免破坏默认 SGAgent 的端到端入口。
3. 实现配置化 arm、locator-only runner、动态一致的工具说明、纯 N2D 工具、结构化 tracer、采样器和 evaluator。
4. 为 N2D 精确/模糊匹配、排序分页、arm 工具隔离、trajectory schema、token 解析、定位输出解析编写测试。
5. 运行格式检查、单元测试和一个不调用付费模型的 deterministic/fake-LLM integration test。该测试必须证明：
   - baseline 无法调用 N2D；
   - n2d 可以调用 N2D；
   - baseline 的多步搜索和内容读取仍然可用；
   - 两个 arm 都能到达统一的 locator-only 完成状态；
   - trajectory 可完整重放事件顺序。
6. 生成并冻结 pilot-45 manifest。
7. 如果本机已经安全配置模型凭据、目标 repo snapshots 和必要依赖，执行完整 paired pilot。不要打印密钥，不要在没有确认价格/预算上限的情况下无限重试。
8. 如果缺少凭据、数据或 repo snapshots，不要伪造结果，也不要停在口头说明：完成所有不依赖这些资源的实现、测试、dry-run、manifest 和运行命令，并在报告中精确列出剩余阻塞项。
9. 从 trajectory 自动生成逐实例结果 CSV/JSONL 和聚合报告。

## 聚合报告

至少输出：

- 每组成功、失败、超时和 token usage 缺失数量；
- token、Locator LLM calls、tool calls 的 mean、median、P25、P75；
- file/function/line 指标；
- 同一实例上的 paired delta；
- bootstrap 95% CI；准确率可补充 McNemar 检验；
- name-eligible、non-eligible 和 ambiguity bucket 分组结果；
- 每种工具调用频次和典型路径模式；
- 至少 3 个 trajectory 对照案例：明显减少调用、无改善、发生退化。

第一阶段只报告“pilot evidence”，不能使用“已经证明”这种措辞。若真实 pilot 未运行，报告必须清楚标记为 infrastructure-only，不得把 fake/dry-run 指标混入真实结果。

## 推荐 CLI

实现等价的非交互 CLI；具体文件名可以调整，但接口应能表达：

```bash
python -m experiments.name_to_definition.sample \
  --seed 20260915 --size 45 --output experiments/name_to_definition/manifests/pilot_45_seed_20260915.json

python -m experiments.name_to_definition.run \
  --manifest experiments/name_to_definition/manifests/pilot_45_seed_20260915.json \
  --arms baseline,n2d \
  --locator-only \
  --resume

python -m experiments.name_to_definition.evaluate \
  --runs experiments/name_to_definition/runs/<experiment_id>
```

支持 `--resume`，已完成的 `(instance_id, arm, repeat)` 不得重复计费；失败重试必须产生新的 attempt 标识并保留旧 trajectory。

## 验收标准

完成工作时必须满足：

- A/B 只差 N2D 能力，tool manifest 可机器验证；
- baseline 的多步定位路径仍然存在并有 integration test；
- 实验版 N2D 不返回代码正文或图关系；
- Locator-only 有明确统一停止点；
- Verified 问题描述按选定 dataset 正确加载；
- API key 不会输出或进入日志；
- 每个 run 都有结构化 trajectory 和 summary；
- token 缺失不会静默变成 0；
- 采样清单确定、冻结、可复现；
- 所有测试通过；
- 若资源齐备，真实 paired pilot 跑完并生成报告；若不齐备，给出一条可直接继续执行的命令和精确阻塞项。

## 工作约束

- 保留用户已有修改，不进行 destructive git 操作。
- 不使用 `git reset --hard` 或 `git checkout --` 清理工作树。
- 不把 gold patch 暴露给 Agent。
- 不为了得到预期结论修改样本、丢弃失败或改变两组预算。
- 不把完整 KG 消融当作 N2D 消融。
- 不用 SGAgent 原生复合 name 工具的结果直接声称纯 N2D 效果。
- 不提交或上传任何凭据、trajectory 或实验数据到外部服务，模型 API 的正常请求除外。

## 最终交付说明

最终回复应先说明第一阶段是否真正跑完；然后列出：

1. 实现和修改的文件；
2. 测试及其结果；
3. manifest 的精确样本数和分层分布；
4. trajectory、逐实例结果和聚合报告路径；
5. 真实 pilot 的主要 paired 结果，或未运行的精确阻塞原因；
6. 尚存的实验威胁和进入 90/全量实验前需要处理的事项。

不要只展示总体均值；必须保留逐实例结果，使研究者可以检查具体工具调用路径。
