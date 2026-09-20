# 任务：复现论文中的完整 14-tool SGAgent Locator

当前 45 样本复现已经实现 100% 完成率，但公开仓库激活的 system prompt 只向模型描述了 5 个通用工具，导致 `find_methods_by_name`、`find_all_variables_named` 等图工具从未被调用。请先修正这一复现差异，暂时不要进行 N2D 消融。

要求：

1. 依据论文、公开仓库的 14 个工具实现，以及 `prompts/system.py` 中被注释的完整工具说明，构造论文一致的 14-tool system prompt。
2. 保留原始文本 `#TOOL_CALL` 协议、Locator workflow、`INFO ENOUGH -> PROPOSE LOCATION` 终止协议、summarizer 和 `recursion_limit=150`；不要改用自定义固定轮次 runner。
3. 除 qtapi 和 `claude-sonnet-5` 外，其余数据、prompt、工具实现、参数和评价方式尽量与官方一致。
4. 所有 14 个工具必须同时注册并在 prompt 中可见。不得修改工具语义，也不得只对 N2D 工具做额外引导。
5. 先用 5～10 个具有明确函数/方法名称的样本做 smoke test，确认图工具能够被模型调用且轨迹完整。
6. smoke test 通过后，复用完全相同的 45 样本 manifest：
   `experiments/name_to_definition/manifests/official_lite_45_seed_20260915.json`
7. 保存每条完整 trajectory，并记录输入/输出 token、LLM 调用、summarizer 调用、工具调用、终止原因、耗时、requested model、API 返回的真实 model、request ID 和 stop reason。不得记录 API key。
8. 使用现有官方 evaluator 和论文 Jaccard 口径评估 File/Function Accuracy，同时保留 Class、Line Accuracy 和 Line IoU。
9. 汇总每种工具的调用次数，重点确认 `find_methods_by_name` 和 `find_all_variables_named` 是否真实可见、可调用；如果仍为 0，先分析 prompt、解析或模型行为，不要直接进入消融。
10. 保留现有 5-tool 结果，不覆盖原目录。新运行使用独立名称，例如 `official_locator_full14_reproduction`。

输出：

- 完整配置快照与可复现命令；
- 逐实例结果和聚合报告；
- 完整轨迹；
- 5-tool 与 14-tool 的指标、token、轮次及工具分布对比；
- 更新后的 reproduction gap report；
- 所有必要代码改动的 diff 说明。

验收标准：45 个正式样本完成率不低于 95%，token 记录完整、工具调用无系统性错误，并确认完整工具集确实暴露给模型。达到这些条件后再提出后续 no-N2D 消融方案，但本阶段不要运行消融实验。
