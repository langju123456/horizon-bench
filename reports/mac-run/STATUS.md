# Mac run status

- state: **running**
- updated: 2026-11-03 15:48 CST
- machine: Mac16,13, 24 GB, macOS 26.3.1
- ollama: ollama version is 0.32.1
- model: qwen3:8b (as hb-qwen3-8b, num_ctx 16384), thinking: off (/no_think)
- eval salt sha256: bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e
- phases done: baseline, smoke, llm h60

Phase: LLM, horizon 120, bare and rich, 10 eval seeds each

## Last 40 log lines

```
  
          By 2027-Feb-18, you need to update your project and remove deprecated calls
          or your builds will no longer be supported.
  
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
[11-03 14:26:29] eval salt sha256 bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e (salt stays in /Users/ju.l/code/horizon-bench/.hb, never committed)
skip mac-baseline-random-rich-h240-eval019: done (use --overwrite to run it again)
[11-03 14:26:35] pushed: Mac run: scripted baseline on this Mac's eval salt
preflight: {"id":"chatcmpl-197","object":"chat.completion","created":1793687195,"model":"hb-qwen3-8b","system_fingerprint":"fp_ollama","choices":[{"index":0,"message":{"role":"assistant","content":"OK."},"finish_reason":"stop"}],"usage":{"prompt_tokens":20,"completion_tokens":3,"total_tokens":23}}
FAIL smoke-qwen3-8b-nothink-llm-rich-h60-dev000  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
0/1 runs succeeded
[11-03 14:31:09] smoke: model calls, median completion tokens, median seconds per call = 60 20 2.9
[11-03 14:31:12] pushed: Mac run: status
[11-03 14:31:12] LLM phase: horizon 60
FAIL qwen3-8b-nothink-llm-rich-h60-eval000  end=horizon  onset excursion@42  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval001  end=horizon  onset excursion@50  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval002  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval003  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval004  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval005  end=horizon  onset excursion@40  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval006  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval007  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval008  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-rich-h60-eval009  end=horizon  onset excursion@45  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval000  end=horizon  onset excursion@48  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval001  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval002  end=horizon  in control  failed=time_in_band,alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval003  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval004  end=horizon  in control  failed=alarms_acked_in_time,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval005  end=horizon  onset excursion@40  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval006  end=horizon  onset excursion@44  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval007  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval008  end=horizon  onset excursion@35  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL qwen3-8b-nothink-llm-bare-h60-eval009  end=horizon  onset excursion@47  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/20 runs succeeded
[11-03 15:48:01] pushed: Mac run: qwen3:8b at horizon 60 (bare and rich, 10 eval seeds)
```
