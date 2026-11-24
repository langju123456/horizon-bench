# D007 首轮结果：仅将引用绑定到实际读过的单元格

8次完整任务、50次真实Qwen3-8B调用；两臂均提交4/4，原严格判定fields 1/4、grounded 4/4。金额均4/4，引用页1/4→4/4；配对修好3、退化0。8份原始轨迹全部重放一致，实验前冻结的实现与原评分模块哈希均匹配。

两臂每题调用数、输入输出token和模型原提议引用页一致。程序在提交前，只根据成功open_source返回的文本建立“金额格→期间表头→单位→引用页”的关系：CATL全年移除p12，中国铝业第四季度移除p10，中国铝业全年移除p11。CATL季度跨页表头需要p11+p12，保留两页。原提议页码和绑定依据保存于每条提交动作note；不读取任务答案、判定器或种子答案映射。

两个arm的中国铝业全年任务均曾提交单位“千元，人民币”，被原schema拒绝；模型在同一次12步预算内改成“千元”，随后形成首份有效终态。失败调用保留在原轨迹中，不是删掉失败另开trial。绑定模块不会纠正单位、金额或期间；没有证据或匹配有歧义时也不改页码。

模型调用总时长分别90.340秒、76.752秒。输入均27,879token、输出均883token、调用均25次；顺序执行、缓存及运行噪声未控制，因此不将时差解释为加速收益。

采用判断：满足预登记的开发候选门槛，保留grounded作为可选策略，默认策略未改。这是Harness修复，不是模型能力或后训练改进。只支持当前管道表格摘录、单一文档、固定现金流指标；没有证明一般PDF解析或未见文档泛化。两个文档早已用于开发，仍需独立冻结的新文档任务验证。

审阅入口：`reports/cell-bound-citations/D007/review.html`。逐题金额、引用页、首次提议和最终提交、用量及修好/退化见同目录`summary.json`；原始记录位于`../traces/`。

复验（离线、不调用模型）：

```bash
PYTHONPATH=src python scripts/handoff_archive.py check reports/cell-bound-citations/traces --study D007
PYTHONPATH=src python scripts/citation_summary.py
PYTHONPATH=src python -m pytest tests/test_llm_agent.py tests/test_annual_handoff.py tests/test_handoff_cli.py tests/test_submission.py tests/test_citation_support.py -q
```

最后一项40例通过，包含缺证据、歧义、错金额、跨页单位、原提议不变、恢复状态和新session必须重新取证。D006提示词失败结果另行保留；不以本轮成功覆盖它。
