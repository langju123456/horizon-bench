# D006: 精确证据页初轮协议

## 首轮结果（2026-11-24）

8条原始运行均完成，44次真实模型调用；8条轨迹独立重放全部一致。基线 fields 严格通过1/4、金额正确4/4、引用页正确1/4；候选 evidence 严格通过1/4、金额正确3/4、引用页正确1/4。调用数25→19，模型时间89.359→73.195秒，但不能用省时掩盖新增金额错误。严格成功的配对修好0、退化0，金额分项退化1。

决定：不采用此提示词候选。它没有改善引用精度；仍需其他修复机制和未用于开发的文档验证。两个文档家族已用于D005，本轮不构成独立泛化证据。详见 `reports/evidence-pages/D006/summary.json`、`report.md` 与8份原始轨迹。

本轮只完成实验与采用判断，不宣称已经修好严格完成率。后续不能通过放宽原判定、挑选重跑或删除失败来改变本轮结论。

冻结时间：2026-11-24 Asia/Shanghai。目标是验证模型会不会把已经读过的背景页误列为 `source_pages`；D005 的严格判定、任务数据、schema 和预算均不改。

## 预登记

比较两臂：`fields`（D005 中全部提交的基线）与 `evidence`（同一交稿字段说明，加一条通用规则：`source_pages` 仅列直接支撑数据格、表头或单位所需的页；已读不等于应引；跨页表头/数据才引两页）。候选不包含公司、答案、目标期间或预期页码。

每臂固定运行 CATL 与中国铝业各两题，共 4 条；总计 8 条。每条使用相同的 `handoff_full`、rich Unicode 工具观察、Qwen3-8B、本地 Ollama、温度 0、12 步、每调用 384 输出 token、16,000 总 token、8,000 context token、240 秒模型时间、`/no_think`。不覆盖已有 run；第一份终态为该 trial 的计分终态。

开始前以 catalog 规则策略验证四题仍可解。主终点是原有所有严格 checks；同时逐题记录提交、`correct_source_pages`、模型调用、输入/输出 token、模型耗时与失败 checks。报告 fields 相对 evidence 的修好与退化。无外部 API 或模型下载。

仓内只有 D005 已使用的 CATL 和中国铝业两份公开表；没有第三份已经准备好且从未用于开发的文档。因此本轮不把这两个复用文档伪称为未用开发集；新文档泛化仍是后续人类提供/冻结资料的卡点。

## 命令

```bash
for arm in fields evidence; do
  for doc in catl transfer; do
    env -u HB_API_KEY -u OPENAI_API_KEY hb --runs-dir runs/D006 run \
      --family annual_handoff --policy llm --name "D006-$arm-$doc" --tools rich --variant handoff_full \
      --handoff-doc "$doc" --submission "$arm" --seeds 2 --horizon 12 --session-len 12 \
      --max-steps 12 --max-tokens-per-call 384 --max-total-tokens 16000 --context-budget 8000 \
      --wall-time 240 --temperature 0 --model qwen3:8b --base-url http://127.0.0.1:11434/v1 \
      --no-think --tool-observation unicode || exit 1
  done
done
python scripts/handoff_archive.py dump runs/D006/hb.sqlite reports/evidence-pages/traces \
  D006-fields-catl D006-fields-transfer D006-evidence-catl D006-evidence-transfer --study D006
python scripts/handoff_archive.py check reports/evidence-pages/traces --study D006 --reports-dir reports/evidence-pages
```
