# D001 收件回执实验

命令：`hb receipt-experiment --output <新目录>`。每格的 `verdict.json` 和 `process.json` 是稳定原始证据；SQLite/WAL 只在运行时存在。

| 策略 | 故障 | 目标收件数 | 本地状态 | 成功 | 初始进程 |
|---|---|---:|---|---:|---:|
| assume_success | ack | 1 | completed | 是 | 0 |
| wait_for_human | ack | 1 | completed | 是 | 0 |
| retry_new_key | ack | 1 | completed | 是 | 0 |
| reconcile_original_key | ack | 1 | completed | 是 | 0 |
| assume_success | request_lost | 0 | completed | 否 | 0 |
| wait_for_human | request_lost | 0 | pending_human | 否 | 0 |
| retry_new_key | request_lost | 1 | completed | 是 | 0 |
| reconcile_original_key | request_lost | 1 | completed | 是 | 0 |
| assume_success | receipt_lost_crash | 1 | completed | 是 | -9 |
| wait_for_human | receipt_lost_crash | 1 | pending_human | 否 | -9 |
| retry_new_key | receipt_lost_crash | 2 | completed | 否 | -9 |
| reconcile_original_key | receipt_lost_crash | 1 | completed | 是 | -9 |
