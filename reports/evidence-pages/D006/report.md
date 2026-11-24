# D006

| 环境 | 策略 | 任务 | 交付 | 未通过项 | 模型调用 | 输入 / 输出 token |
|---|---|---|---|---|---:|---:|
| annual_handoff | llm:qwen3:8b+unicode+evidence+handoff_full | annual-to-q4 | 成功 | — | 4 | 3819 / 139 |
| annual_handoff | llm:qwen3:8b+unicode+evidence+handoff_full | q4-to-annual | 失败 | correct_source_pages | 5 | 5116 / 209 |
| annual_handoff | llm:qwen3:8b+unicode+evidence+handoff_full | chalco-annual-to-q4 | 失败 | opened_required_source, correct_amount, correct_source_pages | 6 | 5820 / 267 |
| annual_handoff | llm:qwen3:8b+unicode+evidence+handoff_full | chalco-q4-to-annual | 失败 | correct_source_pages | 4 | 3758 / 132 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | annual-to-q4 | 成功 | — | 4 | 3579 / 139 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | q4-to-annual | 失败 | correct_source_pages | 6 | 6155 / 242 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | chalco-annual-to-q4 | 失败 | correct_source_pages | 4 | 3527 / 133 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | chalco-q4-to-annual | 失败 | correct_source_pages | 11 | 14618 / 369 |
