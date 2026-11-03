# Mac run status

- state: **running**
- updated: 2026-11-03 14:31 CST
- machine: Mac16,13, 24 GB, macOS 26.3.1
- ollama: ollama version is 0.32.1
- model: qwen3:8b (as hb-qwen3-8b, num_ctx 16384), thinking: off (/no_think)
- eval salt sha256: bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e
- phases done: baseline, smoke

Phase: LLM, horizon 60, bare and rich, 10 eval seeds each

## Last 40 log lines

```
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
  /private/var/folders/3l/zjx6gqt12nsgcyvystl2nv3w0000gn/T/pip-build-env-21f6phn0/overlay/lib/python3.12/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: BuildBackendWarning: `project.license` as a TOML table is deprecated
  !!
  
          ********************************************************************************
          Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).
  
          By 2027-Feb-18, you need to update your project and remove deprecated calls
          or your builds will no longer be supported.
  
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
  /private/var/folders/3l/zjx6gqt12nsgcyvystl2nv3w0000gn/T/pip-build-env-21f6phn0/overlay/lib/python3.12/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: BuildBackendWarning: `project.license` as a TOML table is deprecated
  !!
  
          ********************************************************************************
          Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).
  
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
```
