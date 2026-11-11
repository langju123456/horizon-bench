# Prompt-cache run status

- state: **running**
- updated: 2026-11-11 10:16 CST
- model: qwen3:8b

Arm budget 4000, keep 24: 3 dev seeds, horizon 120

```
FAIL cache-keep24-llm-rich-h120-dev002  end=horizon  onset excursion@39  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/3 runs succeeded
[11-11 09:35:03] pushed: Mac cache run: status
[11-11 09:35:03] arm keep8
FAIL cache-keep8-llm-rich-h120-dev000  end=horizon  onset excursion@74  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL cache-keep8-llm-rich-h120-dev001  end=terminated  onset excursion@30  failed=no_trip,time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
FAIL cache-keep8-llm-rich-h120-dev002  end=horizon  onset excursion@39  failed=time_in_band,alarms_acked_in_time,no_lost_control,report_matches_truth
0/3 runs succeeded
[11-11 10:01:18] pushed: Mac cache run: qwen3:8b, keep 24 vs keep 8 (3 dev seeds, horizon 120)
[11-11 10:01:18] ==== done ====
[11-11 10:16:41] ==== prompt-cache run starts (5b02e2f) ====
[?2026h[?25l[1Gpulling manifest ⠋ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠙ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠹ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠸ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠼ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠴ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠦ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠧ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠇ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠏ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠋ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest ⠙ [K[?25h[?2026l[?2026h[?25l[1Gpulling manifest [K
pulling a3de86cd1c13: 100% ▕██████████████████▏ 5.2 GB                         [K
pulling ae370d884f10: 100% ▕██████████████████▏ 1.7 KB                         [K
pulling d18a5cc71b84: 100% ▕██████████████████▏  11 KB                         [K
pulling cff3f395ef37: 100% ▕██████████████████▏  120 B                         [K
pulling 05a61d37b084: 100% ▕██████████████████▏  487 B                         [K
verifying sha256 digest [K
writing manifest [K
success [K[?25h[?2026l
[?2026h[?25l[1Ggathering model components [K
using existing layer sha256:a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f [K
using existing layer sha256:ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4 [K
using existing layer sha256:d18a5cc71b84bc4af394a31116bd3932b42241de70c77d2b76d69a314ec8aa12 [K
using existing layer sha256:1011c5c86b1c40138cc215ccb25c690251c8c434f790426ee67fad7bb480dd0f [K
writing manifest [K
success [K[?25h[?2026l

[notice] A new release of pip is available: 26.1.2 -> 26.3
[notice] To update, run: /Users/ju.l/code/horizon-bench-cache/.venv/bin/python -m pip install --upgrade pip
```
