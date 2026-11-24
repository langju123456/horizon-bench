# D007：已观察单元格绑定引用页

冻结于首次模型运行之前。D006只增加提示没有提高严格通过率；本轮改为Harness证据绑定，与fields基线保持同样模型提示、工具集合和预算。模型仍决定期间、金额、单位和审阅备注；在发出finish前，程序只用此前成功open_source返回的文本，寻找唯一匹配的期间列、金额格、表头及单位，修改source_pages。找不到或有歧义时保留原提交，交给原judge判定。原模型页码及绑定依据写入动作note。

不读取Case、required_pages、desired_amount、种子对应答案或judge。支持当前公开摘录的管道表格及显式跨页续表，不是通用PDF表格解析。新的页码/金额合成样例覆盖跨页、同页、歧义、错数、错年、缺单位及跨文档；不是新文档泛化证据。

预登记：fields/grounded两臂，CATL和中国铝业各2题，共8次首答；Qwen3-8B、temp0、rich Unicode、handoff_full、12步、384输出token、16000总token、8000上下文、240秒模型预算、no_think均与D006相同。判定以原全部strict checks为准；逐题报告修好/退化与用量。候选至少修好一题且严格成功不退化才保留为开发集候选；仍需未用于开发的新文档验证。首答不覆盖、不择优重跑。

原评分模块 `src/horizon_bench/env/annual_handoff.py` 不修改。该改进若有效，是执行端的证据绑定，不宣称基础模型或后训练改善。
