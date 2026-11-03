# Mac run status

- state: **failed**
- updated: 2026-11-03 14:05 CST
- machine: Mac16,13, 24 GB, macOS 26.3.1
- ollama: ollama version is 0.32.1
- model: qwen3:8b (as hb-qwen3-8b, num_ctx 16384), thinking: off (/no_think)
- eval salt sha256: bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e
- phases done: baseline

Stopped at: LLM smoke: the model calls failed (see log)

## Last 40 log lines

```
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
  /private/var/folders/3l/zjx6gqt12nsgcyvystl2nv3w0000gn/T/pip-build-env-xz62nqzv/overlay/lib/python3.12/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: BuildBackendWarning: `project.license` as a TOML table is deprecated
  !!
  
          ********************************************************************************
          Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).
  
          By 2027-Feb-18, you need to update your project and remove deprecated calls
          or your builds will no longer be supported.
  
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
  /private/var/folders/3l/zjx6gqt12nsgcyvystl2nv3w0000gn/T/pip-build-env-xz62nqzv/overlay/lib/python3.12/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: BuildBackendWarning: `project.license` as a TOML table is deprecated
  !!
  
          ********************************************************************************
          Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).
  
          By 2027-Feb-18, you need to update your project and remove deprecated calls
          or your builds will no longer be supported.
  
          See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
          ********************************************************************************
  
  !!
    corresp(dist, value, root_dir)
[11-03 14:05:14] eval salt sha256 bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e (salt stays in /Users/ju.l/code/horizon-bench/.hb, never committed)
99/480 runs succeeded
[11-03 14:05:34] pushed: Mac run: scripted baseline on this Mac's eval salt
FAIL smoke-qwen3-8b-nothink-llm-rich-h60-dev000  end=abort:llm_errors (HTTPStatusError: Server error '502 Bad Gateway' for url 'http://localhost:11434/v1/chat/completions'
For more information check: https://)  onset excursion@48  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/1 runs succeeded
[11-03 14:05:35] FAILED: LLM smoke: the model calls failed (see log)
```
