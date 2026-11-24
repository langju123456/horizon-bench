# D007

| 环境 | 策略 | 任务 | 交付 | 未通过项 | 模型调用 | 输入 / 输出 token |
|---|---|---|---|---|---:|---:|
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | annual-to-q4 | 成功 | — | 4 | 3579 / 139 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | q4-to-annual | 失败 | correct_source_pages | 6 | 6155 / 242 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | chalco-annual-to-q4 | 失败 | correct_source_pages | 4 | 3527 / 133 |
| annual_handoff | llm:qwen3:8b+unicode+fields+handoff_full | chalco-q4-to-annual | 失败 | correct_source_pages | 11 | 14618 / 369 |
| annual_handoff | llm:qwen3:8b+unicode+grounded+handoff_full | annual-to-q4 | 成功 | — | 4 | 3579 / 139 |
| annual_handoff | llm:qwen3:8b+unicode+grounded+handoff_full | q4-to-annual | 成功 | — | 6 | 6155 / 242 |
| annual_handoff | llm:qwen3:8b+unicode+grounded+handoff_full | chalco-annual-to-q4 | 成功 | — | 4 | 3527 / 133 |
| annual_handoff | llm:qwen3:8b+unicode+grounded+handoff_full | chalco-q4-to-annual | 成功 | — | 11 | 14618 / 369 |
