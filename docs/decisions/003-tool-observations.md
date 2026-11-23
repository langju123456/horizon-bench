# 同一张中文表，怎么传给模型？

D002 全历史组的第一个实际运行中，Qwen3‑8B 打开了印刷页 11、12，最后仍交全年数，还把审阅原话中的“千元”写为“千万元”。运行器把工具返回再次做 JSON 序列化；默认把中文写成一串 Unicode 转义，例如“元”会变成六个可见字符。模型有时仍能读对。改成直读中文能否增加最终交付，需要另做比较。

| 我可以选择怎样传递原表和审阅意见 | 代价或疑问 | 首轮 |
|---|---|---|
| 1. 保留当前 ASCII 转义 JSON | 兼容已有结果，中文变长 | 实测 |
| 2. JSON 结构相同，直接保留中文字符 | 改动最小，原样保留工具边界与全部信息 | 实测 |
| 3. 直接保留中文，并只发业务值或明确工具错误 | 可去掉重复外层状态；会少传置信度、陈旧度和延时等线索 | 实测 |
| 4. 用 Markdown 表格加表下注释 | 对人可读，需要保证行列还原正确 | 未测 |
| 5. 原样传业务字段，重复来源用短编号 | 少发长网址，需要稳定引用字典 | 未测 |
| 6. 审阅原话保存在只读字段，最后按引用拼装 | 能保留字面内容，引入产品侧字段绑定 | 未测 |
| 7. 将表头与金额行预联结为带页组的单元格 | 跨页更容易读，增加工具的抽取责任 | 未测 |
| 8. 由模型先摘要，再将摘要传给下一步 | 多一次调用，可能改写财务单位 | 未测 |
| 9. 返回表格图片并调用视觉模型 | 需要图像输入、相应模型和新的成本比较 | 未测 |
| 10. 以数值协议传输，最后按确定性模板展示 | 数字便于验证，模板表达范围有限 | 未测 |

**实验条件。** Codex 代做。固定 D002 的全历史，使用同一份宁德时代年报、同两个反向修改、同版模型、提示、可用工具、独立验收和每任务预算。第一组直接复用已登记的 D002 全历史两条原始轨迹；另两组从任务开始，各执行两条真实模型运行。这比只让模型重抄正确答案更接近使用者的工作。第三组只改变成功工具结果的外层包装，保留原页、业务值和错误。它的结论限于本环境的稳定本地资料。

逐题列终态通过、实际取证页、审阅原话、输入/输出 token、工具次数与累计模型时间。候选方案先看修好与退化，再看所需输入。原始记录可用相同独立判据回放。这里使用公开开发题，重复观察同一份年报，结论保留这个边界。

**怎样复跑。** 先按[交接实验](002-handoff-memory.md)生成本地的 D002 基线。保持同一个输入库、模型和设置，执行下面两组。归档时只从 D002 取全历史的两条原始运行。

```bash
for view in unicode business; do
  env -u HB_API_KEY -u OPENAI_API_KEY hb --runs-dir runs/D002 run \
    --family annual_handoff --policy llm --name "D003-$view" --tools rich --variant handoff_full \
    --seeds 2 --horizon 12 --session-len 12 --max-steps 12 --max-tokens-per-call 384 \
    --max-total-tokens 16000 --context-budget 8000 --wall-time 240 --temperature 0 \
    --model qwen3:8b --base-url http://127.0.0.1:11434/v1 --no-think --tool-observation "$view" || break
done
python scripts/handoff_archive.py dump runs/D002/hb.sqlite runs/D003-published D002 D003-unicode D003-business --study D003
python scripts/handoff_archive.py check runs/D003-published --study D003 --reports-dir reports
```
