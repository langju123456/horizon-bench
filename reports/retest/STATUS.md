# Lever retest: run status

- state: **done**
- updated: 2026-11-16 13:58 CST
- code: 25c8497 on retest-levers
- machine: Mac16,13, 24 GB, macOS 26.3.1
- ollama: ollama version is 0.32.1
- model: qwen3:8b (as hb-qwen3-8b, num_ctx 16384), digest 500a1f067a9f, thinking: off
- eval salt sha256: bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e
- cells done: base, guard, tool, ctx, all

All cells finished. Summary: reports/retest/summary.md · walkthrough: reports/retest/walkthrough-eval007.md

## Last 40 log lines

```
FAIL retest-tool-llm-rich-h60-eval006  end=horizon  onset excursion@40  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-tool-llm-rich-h60-eval007  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-tool-llm-rich-h60-eval008  end=horizon  in control  failed=time_in_band,alarms_acked_in_time,report_matches_truth
FAIL retest-tool-llm-rich-h60-eval009  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
0/10 runs succeeded
wrote reports/retest/summary.md
wrote reports/retest/walkthrough-eval007.md
[11-16 12:52:40] pushed: Retest: cell tool done (qwen3:8b, 10 eval seeds, horizon 60)
[11-16 12:52:42] pushed: Retest: status
[11-16 12:52:42] cell retest-ctx starts (variant: ctx_rule)
FAIL retest-ctx-llm-rich-h60-eval000  end=horizon  onset excursion@48  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval001  end=horizon  onset excursion@46  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval002  end=horizon  in control  failed=time_in_band,alarms_acked_in_time,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval003  end=horizon  onset excursion@48  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval004  end=horizon  onset loop@50  failed=alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval005  end=horizon  onset excursion@42  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval006  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval007  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval008  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-ctx-llm-rich-h60-eval009  end=horizon  onset excursion@40  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/10 runs succeeded
wrote reports/retest/summary.md
wrote reports/retest/walkthrough-eval007.md
[11-16 13:21:40] pushed: Retest: cell ctx done (qwen3:8b, 10 eval seeds, horizon 60)
[11-16 13:21:44] pushed: Retest: status
[11-16 13:21:44] cell retest-all starts (variant: ctx_rule,tool_hint,guard)
FAIL retest-all-llm-rich-h60-eval000  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-all-llm-rich-h60-eval001  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-all-llm-rich-h60-eval002  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-all-llm-rich-h60-eval003  end=horizon  onset loop@46  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-all-llm-rich-h60-eval004  end=horizon  onset loop@18  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-all-llm-rich-h60-eval005  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-all-llm-rich-h60-eval006  end=horizon  onset excursion@34  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-all-llm-rich-h60-eval007  end=horizon  onset loop@34  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-all-llm-rich-h60-eval008  end=horizon  onset excursion@47  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-all-llm-rich-h60-eval009  end=horizon  onset loop@46  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/10 runs succeeded
wrote reports/retest/summary.md
wrote reports/retest/walkthrough-eval007.md
[11-16 13:58:54] pushed: Retest: cell all done (qwen3:8b, 10 eval seeds, horizon 60)
```
