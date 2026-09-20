# SGAgent：Name-to-Definition 定位实验

本仓库记录 SGAgent 在 SWE-bench Lite 上开展的 Name-to-Definition 代码定位实验，包括源码、实验提示词、运行日志、完整轨迹、评估结果和分析报告。

SGAgent 结合代码知识图谱、检索工具和多阶段 agent workflow，对 issue 描述对应的文件、类、函数和代码行进行定位，并支持后续补丁生成。项目依赖见 [`pyproject.toml`](pyproject.toml)。

## 一、实验目标与实验口径

本阶段主要研究两个问题：

1. 使用完整 14 个工具时，SGAgent Locator 在固定 SWE-bench Lite 样本上的定位效果；
2. 移除 `find_methods_by_name` 和 `find_all_variables_named` 两个 N2D 相关工具后，定位质量和资源消耗是否发生变化。

实验使用本地 SWE-bench Lite 数据集，共 300 条 issue；正式 baseline 使用固定的 45 条样本，配对消融 smoke 使用相同的 10 条样本。模型请求使用 Claude-3.5-Sonnet ，保留官方 Locator workflow、文本 `#TOOL_CALL` 协议、summarizer 和 `recursion_limit=150`。

报告同时保留两类指标：

- **官方仓库指标**：File/Class/Function/Line containment accuracy，以及 Line IoU；
- **论文口径指标**：逐实例 File/Function 集合 Jaccard，分别记为 Paper File Jaccard 和 Paper Function Jaccard。

两类指标不能混用。论文口径的 File/Function Jaccard 是本文与论文结果进行比较时使用的主要指标。

## 二、45-instance Claude-3.5 Full14 baseline

这是当前最完整的 Full14 baseline：45/45 条轨迹完成，provider failure 为 0。

### 2.1 定位质量

| 指标 | 本实验结果 |
|---|---:|
| File accuracy（官方 containment） | 0.9111 |
| Class accuracy | 0.8222 |
| Function accuracy（官方 containment） | 0.3556 |
| Line accuracy | 0.3333 |
| Line IoU | 0.2235 |
| Paper File Jaccard | **0.8593** |
| Paper Function Jaccard | **0.5204** |
| Completion rate | 45/45 = 1.0000 |
| Provider failure | 0/45 = 0 |

### 2.2 资源消耗

| 统计量 | 总 token |
|---|---:|
| Mean | 270,819.4 |
| Median | 98,078 |
| P25 | 61,481 |
| P75 | 179,865 |
| P95 | 1,226,416.4 |
| Maximum | 3,660,622 |

平均每个实例产生 10.80 次 logical LLM call、8.49 次工具调用。最高 token 消耗来自 `sympy__sympy-21379`，达到 3,660,622，说明长上下文工具返回是该实验的主要资源风险。

## 三、与论文结果的比较

论文报告的 File Accuracy 为 **81.2%**，Function Accuracy 为 **52.4%**。本实验采用论文定义的 File/Function Jaccard 后，45-instance Full14 baseline 为：

| 结果来源 | File Jaccard | Function Jaccard |
|---|---:|---:|
| 论文报告值 | 81.20% | 52.40% |
| 本实验 45-instance Full14 | **85.93%** | **52.04%** |
| 差值 | **+4.73 个百分点** | **-0.36 个百分点** |

从数值上看，本实验的文件级定位略高于论文报告值，函数级定位基本持平、略低于论文值。这个比较只能作为描述性参照，不能视为严格复现论文结果，原因包括：

- 论文结果是完整 SWE-bench Lite 上的端到端修复实验；本实验测量的是 Locator 输出；
- 论文使用完整 300 条数据并描述了每个 issue 的四组定位结果；本实验使用固定 45 条样本、每个 issue 一条主要轨迹；
- 论文与本实验在完成条件、样本规模和 evaluator adapter 上并非完全一致。

因此，当前结果支持“文件级定位与论文量级接近、函数级定位也基本接近”的判断，但不支持宣称已经完成论文级别的严格数值复现。

## 四、10-instance Full14 vs no-N2D 配对 smoke

两组使用完全相同的 10 个实例和运行配置。两组均 10/10 完成，provider failure 均为 0，完整 trace 均通过校验。

### 4.1 定位指标

| 指标 | Full14 | no-N2D | no-N2D - Full14 |
|---|---:|---:|---:|
| File accuracy | 1.0000 | 1.0000 | 0.0000 |
| Class accuracy | 0.9000 | 0.9000 | 0.0000 |
| Function accuracy | 0.4000 | 0.4000 | 0.0000 |
| Line accuracy | 0.6000 | 0.6000 | 0.0000 |
| Line IoU | 0.2533 | **0.3068** | **+0.0535** |
| Paper File Jaccard | 0.9250 | 0.9250 | 0.0000 |
| Paper Function Jaccard | **0.6333** | 0.6250 | **-0.0083** |

### 4.2 资源指标

| 指标 | Full14 | no-N2D | no-N2D - Full14 |
|---|---:|---:|---:|
| 平均总 token | 89,318.0 | 176,874.6 | **+87,556.6** |
| 总 token 中位数 | 61,977.5 | 102,265.0 | +40,287.5 |
| 平均 logical LLM call | 8.2 | 7.9 | -0.3 |
| 平均工具调用 | 6.2 | 6.7 | +0.5 |

### 4.3 配对分析

no-N2D 没有改变 File/Class/Function/Line 这些离散命中指标；Line IoU 在小样本上提高了 0.0535，但 Paper Function Jaccard 下降了 0.0083。更明显的变化是资源消耗：no-N2D 平均总 token 接近 Full14 的两倍，说明移除两个专用工具后，模型倾向于通过更多上下文搜索和间接工具链完成定位。

因此，当前 smoke 结果没有显示 no-N2D 在定位质量上具有稳定优势；它更像是以显著增加上下文成本换取相近的定位效果。该结果属于小样本 pilot evidence，不能单独推出更大规模的因果结论。

## 五、实验阶段与产物

| 阶段 | 实验内容 | 当前状态 |
|---|---|---|
| Phase 1 | 官方 Locator reproduction | 已完成 45-instance 结果与差异分析 |
| Phase 1B | Full14 工具和 prompt reproduction | 已完成并保留工具使用统计 |
| Phase 2A | Claude-3.5 API preflight | 已完成，模型请求正常 |
| Phase 2 | Claude-3.5 Full14 baseline | 已完成 45/45，provider failure 为 0 |
| Phase 3 | 请求级重试、完整 trace、no-N2D arm | 已完成 |
| Paired smoke | Full14 与 no-N2D 的 10-instance 对照 | 已完成，两组均 10/10 |

主要产物：

- [45-instance baseline 汇总报告](experiments/name_to_definition/reports/claude35_full14_baseline/aggregate_report.md)
- [baseline 与论文口径差异分析](experiments/name_to_definition/reports/claude35_full14_baseline/reproduction_gap_report.md)
- [Full14/no-N2D 配对汇总](experiments/name_to_definition/reports/claude35_paired_smoke10/paired_comparison.md)
- [Full14 配对结果](experiments/name_to_definition/reports/claude35_paired_smoke10/full14/aggregate_report.json)
- [no-N2D 配对结果](experiments/name_to_definition/reports/claude35_paired_smoke10/no_n2d/aggregate_report.json)
- [完整 Full14 trace](experiments/name_to_definition/runs/claude35_paired_smoke10/full14/)
- [完整 no-N2D trace](experiments/name_to_definition/runs/claude35_paired_smoke10/no_n2d/)
- [实验阶段提示词](experiments/name_to_definition/)

每条正式配对轨迹都保留 `trajectory.jsonl`、`summary.json` 和完整 sidecar/blob；45-instance baseline、10-instance smoke 以及历史运行日志均保存在仓库中。

## 六、项目结构

```text
sgagent/
├── agent/                         # agent 核心逻辑
├── kg/                            # 知识图谱构建
├── retriever/                     # 代码检索器
├── router/ workflow/              # workflow 与路由
├── tools/                         # agent 工具实现
├── experiments/name_to_definition/
│   ├── PROMPT_PHASE*.md           # 实验阶段说明
│   ├── official_locator.py        # Locator runner
│   ├── official_evaluate.py       # 离线评估器
│   ├── tracing.py                 # trace 写入
│   ├── trace_validator.py         # trace schema 校验
│   ├── runs/                      # 原始轨迹和 sidecar
│   └── reports/                   # 汇总结果和分析
├── tests/                         # 实验相关测试
├── logs/                          # 历史运行日志
├── dataset/                       # SWE-bench Lite/Verified 数据
└── README.md
```

## 七、原始项目简介

SGAgent 原始目标是自动定位、分析并修复 GitHub 仓库中的问题。Locator、Suggester 和 Fixer 分别负责问题定位、修复建议和补丁实现；知识图谱与检索工具用于提供代码结构、依赖关系和上下文信息。
