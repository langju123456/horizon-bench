# Lever retest: run status

- state: **running**
- updated: 2026-11-16 12:07 CST
- code: 67689f2 on retest-levers
- machine: Mac16,13, 24 GB, macOS 26.3.1
- ollama: ollama version is 0.32.1
- model: qwen3:8b (as hb-qwen3-8b, num_ctx 16384), digest 500a1f067a9f, thinking: off
- eval salt sha256: bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e
- cells done: base, guard

Finished retest-guard. Summary: reports/retest/summary.md

## Last 40 log lines

```
  
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
[11-16 10:43:25] eval salt sha256 bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e (same seeds as the 2026-11-03 run)
FAIL retest-smoke-llm-rich-h20-dev000  end=horizon  in control  failed=report_matches_truth
0/1 runs succeeded
[11-16 10:44:54] pushed: Retest: status
[11-16 10:44:54] cell retest-base starts (variant: none)
FAIL retest-base-llm-rich-h60-eval000  end=horizon  onset excursion@42  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-base-llm-rich-h60-eval001  end=horizon  onset excursion@50  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-base-llm-rich-h60-eval002  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-base-llm-rich-h60-eval003  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-base-llm-rich-h60-eval004  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-base-llm-rich-h60-eval005  end=horizon  onset excursion@40  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-base-llm-rich-h60-eval006  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-base-llm-rich-h60-eval007  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-base-llm-rich-h60-eval008  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-base-llm-rich-h60-eval009  end=horizon  onset excursion@45  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/10 runs succeeded
wrote reports/retest/summary.md
wrote reports/retest/walkthrough-eval007.md
[11-16 11:26:32] pushed: Retest: cell base done (qwen3:8b, 10 eval seeds, horizon 60)
[11-16 11:26:35] pushed: Retest: status
[11-16 11:26:35] cell retest-guard starts (variant: guard)
FAIL retest-guard-llm-rich-h60-eval000  end=horizon  onset excursion@42  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval001  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval002  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval003  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval004  end=horizon  in control  failed=time_in_band,alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval005  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval006  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval007  end=horizon  in control  failed=time_in_band,alarms_acked_in_time,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval008  end=horizon  onset excursion@44  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL retest-guard-llm-rich-h60-eval009  end=horizon  onset excursion@45  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/10 runs succeeded
wrote reports/retest/summary.md
wrote reports/retest/walkthrough-eval007.md
```
