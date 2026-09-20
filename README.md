# SGAgent：Name-to-Definition 定位实验

本仓库包含 SGAgent 源码，以及截至 2026-09-20 已完成的 Name-to-Definition 实验：实验提示词、运行日志、完整 trace、离线评估结果、配对消融分析和复现实验脚本。

SGAgent 面向软件工程任务，结合代码知识图谱、检索工具和多阶段 agent workflow，对 SWE-bench Lite 问题进行代码位置定位，并进一步支持补丁生成。

## 当前实验进展

实验关注的问题是：在固定模型、数据集和评估器下，完整工具集与移除 N2D 专用工具后的定位效果有何差异。

| 阶段 | 实验 | 结果摘要 |
|---|---|---|
| Phase 1 | 官方 Locator reproduction | 45/45 完成，结果和复现差异报告已保存 |
| Phase 2 | Claude-3.5 Full14 baseline | 45/45 完成，provider failure 为 0 |
| Phase 3 | 完整 trace、请求级重试、no-N2D 准备 | 已加入 trace validator、sidecar 完整性校验和 arm diff 测试 |
| Paired smoke | Full14 vs no-N2D，固定 10 个实例 | 两组均 10/10 完成、provider failure 为 0、trace 均 10/10 有效 |

### 10-instance 配对 smoke 结果

运行使用相同的 10 个实例、模型别名 `ep-64pmfvfo`、协议、并行度、超时、重试策略和离线评估器。

| 指标 | Full14 | no-N2D |
|---|---:|---:|
| File accuracy | 1.0000 | 1.0000 |
| Class accuracy | 0.9000 | 0.9000 |
| Function accuracy | 0.4000 | 0.4000 |
| Line accuracy | 0.6000 | 0.6000 |
| Line IoU | 0.2533 | 0.3068 |
| Paper File Jaccard | 0.9250 | 0.9250 |
| Paper Function Jaccard | 0.6333 | 0.6250 |
| 平均总 token | 89,318 | 176,874.6 |

初步结论：no-N2D 在这 10 个实例上没有带来明确的离散定位指标提升；Line IoU 略高，但 Paper Function Jaccard 略低，且平均 token 消耗约为 Full14 的两倍。因此该结果目前属于 pilot-scale paired evidence，不应单独作为扩大正式全量消融实验的充分依据。

完整配对分析见 [`paired_comparison.md`](experiments/name_to_definition/reports/claude35_paired_smoke10/paired_comparison.md)。

## 主要实验产物

- [实验提示词](experiments/name_to_definition/)
- [45-instance Claude-3.5 baseline 报告](experiments/name_to_definition/reports/claude35_full14_baseline/)
- [10-instance Full14/no-N2D 配对报告](experiments/name_to_definition/reports/claude35_paired_smoke10/)
- [Full14 原始运行 trace](experiments/name_to_definition/runs/claude35_paired_smoke10/full14/)
- [no-N2D 原始运行 trace](experiments/name_to_definition/runs/claude35_paired_smoke10/no_n2d/)
- [Phase3 trace schema 说明](experiments/name_to_definition/reports/claude35_full14_baseline/trace_schema_phase3.md)
- [Phase3 readiness 与失败诊断](experiments/name_to_definition/reports/claude35_full14_baseline/)

每条正式 smoke 轨迹包含 `trajectory.jsonl`、`summary.json` 和必要的完整 sidecar/blob；trace validator 会检查事件序号、请求/响应配对、工具执行结果、sidecar SHA256、汇总计数和敏感信息。

## 目录结构

```text
sgagent/
├── agent/                         # agent 核心逻辑
├── kg/                            # 知识图谱构建
├── retriever/                     # 代码检索器
├── router/ workflow/              # workflow 与路由
├── tools/                         # agent 工具实现
├── experiments/name_to_definition/
│   ├── PROMPT_PHASE*.md           # 实验阶段说明
│   ├── official_locator.py        # 官方 Locator runner
│   ├── official_evaluate.py       # 离线评估器
│   ├── tracing.py                 # 完整 trace 写入
│   ├── trace_validator.py         # trace 校验
│   ├── runs/                      # 原始轨迹和 sidecar
│   └── reports/                   # 汇总结果和分析
├── tests/                         # 实验与输出安全测试
├── logs/                          # 历史运行日志
├── dataset/                       # 本地 SWE-bench Lite/Verified 数据
└── README.md
```

本地 `experiments/name_to_definition/repo_cache/` 仅用于构建知识图谱，已加入 `.gitignore`，不属于实验结果，也不上传第三方仓库的嵌套 Git 数据。

## 复现与验证

项目依赖见 `pyproject.toml` 和 `uv.lock`，建议使用 Python 3.12+ 与 `uv`。

### 运行测试

```bash
pytest -q tests/test_phase3_trace_and_arms.py \
  tests/test_output_guard.py \
  tests/test_name_to_definition.py
```

当前实验完成时测试结果为 `11 passed`。

### 验证已有 trace

```bash
python -m experiments.name_to_definition.trace_validator \
  experiments/name_to_definition/runs/claude35_paired_smoke10/full14/*/0/trajectory.jsonl
```

批量离线评估不需要调用模型。例如：

```bash
python -m experiments.name_to_definition.official_evaluate \
  --manifest experiments/name_to_definition/manifests/official_lite_45_seed_20260915.json \
  --runs experiments/name_to_definition/runs/claude35_paired_smoke10/full14 \
  --lite dataset/lite.parquet \
  --repo-cache experiments/name_to_definition/repo_cache \
  --source-root /path/to/source-root \
  --output /tmp/name-to-definition-evaluation \
  --experiment-id local_recheck
```

### 运行新的模型实验

模型 API 配置必须从本机安全环境加载，不要把 API key 写入命令行、配置快照、日志、trace 或 Git。实验脚本支持 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 等环境变量；本仓库上传的配置快照只记录安全的配置来源，不包含 credential。

完整 paid run 会产生大量模型请求和 trace，除非明确授权，不建议直接重新运行。已有 paid 结果可以通过上面的离线评估命令复核。

## 数据、隐私与限制

- 已上传的实验结果不包含 API key、认证 header 或本机安全配置文件内容；敏感信息扫描已覆盖源码、日志、报告和 smoke trace。
- 报告中的 `cost_usd` 没有伪造估算；当前未将 qtapi 价格写入实验配置。
- 45-instance baseline 中部分较早的成功轨迹属于 Phase2 legacy trace；新的 paired smoke 两个 arm 均使用完整 trace schema，并通过 validator。
- 10-instance 结果是小样本配对 smoke，不代表统计显著性，也不能替代更大规模正式实验。
- `dataset/` 中的数据文件是本地实验输入，第三方 repository cache 不随仓库提交。

## 原始项目说明

SGAgent 原始目标是自动定位、分析并修复 GitHub 仓库中的问题。Locator、Suggester 和 Fixer 分别负责问题定位、修复建议和补丁实现；知识图谱和检索工具用于提供代码结构与上下文。
