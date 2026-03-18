SWE 轨迹分析引擎迭代

启动方式：/loop 10m swe轨迹分析引擎迭代，读 sessions/swe.md 比较脚本内容与目标差距 执行当前任务，提升脚本质量

理解意图、设计方案、写代码、跑测试

核心思想：迭代一个分析 navworld 轨迹分析器，要求从多个角度 例如但是不限于 1.是否overfitting 2. winning/loss 的轨迹规律/pattern 提炼出任何不对称或者通过RL reasoning 或得的能力或者规律  4. 提出建议优化环境的方案

1. 独立创造一个脚本来分析 swe环境的轨迹，可参已有的脚本
2. 支持 任意uid，在当前1. active sampling list 和 2. 所有历史数据的查询 3. 以及最近N 条的查询
3. 数据获取的方式请看 scripts/FETCH_TRAJECTORIES.md 务必遵守

纬度分析
1. 统计不同类型 任务获得分数值
2. 要把自己每个种类剥离出来独立分析，，是否有可能hack 任意source 的reward
3. 是否有overfitting 或者 memorization 的pattern 自行 搜索决定 如何判断这点
4. 需要给一个总体的描述
5. 如果有任何 失败/成功的 pattern 深入分析
6. 根据 sft 提出可能得分的策略 以及对应数据合成的策略
7. 环境相关代码的提升点 理解环境背后设计意图 要求多角度充分论证，不得给出不扎实的意见

每次迭代工作流
0. 阅读最新 SWE 题目构建代码 https://github.com/AffineFoundation/affine-swe-infinite.git 以及相关环境设置评测代码
https://github.com/AffineFoundation/affinetes.git 目录下 environments/SWE-SYNTH 或者 environments/SWE-INFINITE （两种模式下都有可能存在轨迹）对应分析
1. 理解目标 + 问题区问题 并思考背后意图后 深度思考，提出待办计划 记录在待办工作去
2. 根据待办的工作深度思考完成工作
3. 脚本更新完后 完整的跑一次脚本 针对当前排名比较好的的miner 的采样列表跑一次分析（每次随机选一个尽量不重复），并且针对输出每个token 阅读，提出至少1条不足 写入本文件的待办区。不得不写入，或者说已经很好。要用对抗性思维去提出需要解决问题。并把问题记录在问题区
4. 根据想法 更新 markdown, 要求保留每次迭代记录
5. 要求每次的报告需要精炼但是一定包含重点，自动审查 删掉冗余&无价值信息
6. 最开始给我 top findings 要求根据我分析报告背后的意图给出最优价值的 top findings
7. 重点寻找下是否由于环境设计，基建设等问题导致轨迹失败/甚至评分有偏差的问题，重点分析，反复论证 给出可疑的轨迹&原因

待办工作区

1. [x] ~~**conversation质量评分/循环检测**~~: 已用 n-gram Jaccard similarity 替代 prefix 匹配。UID 248 检出 13/23（旧方法在 UID 162 上检出 0/21）
2. [x] ~~**per-bug-type失败阶段交叉分析**~~: 已实现 BUG TYPE × FAILURE STAGE CROSS-ANALYSIS 表
3. [x] ~~**patch diff语义分析**~~: 已实现 PATCH SEMANTIC ANALYSIS，分类 functional/import_only/config_only/comment_only/brute_force/test_only
4. [x] ~~**explore_only 深入剖析**~~: 已实现 EXPLORE-ONLY DEEP ANALYSIS，分类为 analysis_paralysis/cant_locate/wrong_direction/tool_struggling
5. [x] ~~**analysis_paralysis 细分**~~: 已细分为 wide_scatter（高文件多样性）和 deep_stuck（低文件多样性），通过文件路径去重率区分
6. [x] ~~**跨miner一致性分析增强**~~: 已实现 per-task difficulty labels (easy/medium/hard-/hard) + TASK DIFFICULTY DISTRIBUTION
7. [x] ~~**near-win 跨 miner 一致性**~~: 已实现 NEAR-WIN CROSS-MINER CONSISTENCY 段落。检测 >=80% 测试通过的跨 miner 一致性，标记 target test 可能过严的任务
8. [x] ~~**failure mode 迁移分析**~~: 已实现 FAILURE MODE MIGRATION ANALYSIS。包含一致/分歧分类、migration matrix（pairwise co-occurrence）、MODEL WEAKNESS SIGNATURES（每个 miner 的主导失败模式）
9. [x] ~~**language distribution 应计入无 patch 任务**~~: 已修复。通过 project map 推断无 patch 任务的语言，并显示 "X from patch, Y inferred from project"。扩展了 `_PROJECT_LANG_MAP` (新增 qutebrowser, NodeBB)
10. [x] ~~**conversation 命令解析精度**~~: 已改进。区分 sed -n (读) vs sed -i (编辑), echo >file (编辑), ls/find/tree (导航 vs 读取)。添加更多 test command 关键词。
11. [x] ~~**env_blocked 分类恢复**~~: 新版本缺失 env_blocked 阶段，已恢复。通过检测 user 消息中的高频环境错误关键词实现
12. [x] ~~**tool_use JSON 格式兼容**~~: 已验证 5 个 UID (242,30,60,162,55) 的 conversation 格式，全部使用 agent=miniswe 纯文本格式（str content），无 tool_use JSON。当前正则完全兼容。
13. [x] ~~**SFT 数据候选的 memorization 检测**~~: 已实现 contamination flagging — 标记 <=3 lines + 100% tests + edit<15% into conv + no testing 的 wins 为潜在 memorization。当前 miniswe 的 explore ratio 均 >=0.64，暂无触发。
14. [x] ~~**跨 UID 同 task patch 对比**~~: 已实现 CROSS-MINER PATCH SIMILARITY 段落。使用 n-gram Jaccard 比较同 task 的 normalized patch，分为 IDENT(>95%)/SIM(50-95%)/DIFF(<50%)。输出 SFT 含义：identical = low value (pattern match), different = high value (unique problem-solving)
15. [x] ~~**_count_conversation_stats edit 检测严重 overcounting bug**~~: 修复了 "edit" 作为 substring 匹配导致讨论文本中的 "edit" 被误计为 edit command 的 bug。改为仅在 ```bash blocks 中检测实际命令。UID 162: edit_churn 94%→0%, explore_only 0%→44%
16. [x] ~~**explore_only 任务中 tool_struggling 过高**~~: 修复。改为需要 non-zero returncode + 特定严重错误关键词。UID 162 tool_struggling 86%→0%
17. [x] ~~**test 行为描述模板不准确**~~: 当 test-free wins <=50% 时改为 "Testing is key differentiator"
18. [x] ~~**identity_confusion 模式覆盖不足**~~: 新增 "unable to access the file" 等变体，修复 task 2790 误分类
19. [x] ~~**resource-leak × edit_no_test 高关联**~~: 已泛化为 BUG-SPECIFIC SFT RECOMMENDATIONS 段落。自动检测 bug_type × failure_stage 高关联对（>=60%, >=3 例），按 stage 分组避免重复建议，100% 关联标记 ⚠ CAPABILITY GAP
20. [x] ~~**near-win 的 target test 部分通过分析**~~: 已实现 TARGET TEST PROXIMITY 子段落。将 near-wins 分为 target-close (target pass>50%, patch 几乎正确) 和 target-far (target pass<=50%, 需要不同修复策略)。UID 248: 1 target-close (2807, 73%) vs 4 target-far。UID 55: 4/4 全部 target-far (0%)
21. [x] ~~**跨 UID 汇总报告**~~: 已增强 --compare 的 OVERVIEW 表，新增 DomFailure 和 Gaps 列。新增 MINER PROFILES 段落，自动生成每个 UID 的 strengths/weaknesses 摘要（highest win rate, near-win count, bottleneck, capability gaps）
22. [x] ~~**fetch 性能优化**~~: 已实现双层并行：(1) 多 UID 并行 fetch via asyncio.gather，(2) 单 UID 内部 task 并行 fetch via Semaphore(20)。5 UIDs ~1600 tasks: 15 秒（原串行估计 >60 秒）。DB 连接安全共享（singleton + Lock init）
23. [ ] **`--all --recent N` 仍需全量扫描 DB**: 虽然并行化大幅加速，但 `--recent 30` 仍然先 fetch 全部再取最后 30 条。理想方案是 DB 层支持 reverse timestamp query + limit。
24. [x] ~~**报告冗余精简**~~: 报告从 364→315 行（-13.5%）。移除二元分数时的 SCORE DISTRIBUTION 段落、near-win 三重展示合并为单表（含 proximity tag）、bug co-occurrence 过滤 count<2、priority ranking 过滤 count<2、移除冗余 project-language mapping 子段落。
25. [x] ~~**SFT near-win 建议分化**~~: SFT 数据合成建议现在根据 target-close/far 给出不同 action：close→"synthesize minor corrections"，far→"re-read problem and try different fix direction"
26. [x] ~~**SCORING ANOMALIES 检测范围扩大**~~: 从仅检测 target_passed_count==0 的 wins 扩大到 target_pass_rate<50% 的 wins。捕获了 task 2953 (1/49=2%) 和 2936 (1/4=25%)
27. [x] ~~**target+regress regression 深入分析**~~: 已新增 REGRESSION DETAIL 段落。显示 regression severity（avg/median/max broken tests）、catastrophic vs minor 分类、patch size 与 regression 相关性、per-project 分布。UID 228: avg 346 tests broken/regression, 14/15 catastrophic, 2-4 line patches 就能破坏 2984 个测试
28. [x] ~~**regression-prone code area 分析**~~: 已实现 patch 文件路径分析。对比 regressing patches vs winning patches 的修改文件路径，标记 "NEVER in wins" 的危险文件。UID 228: `src/posts/uploads.js` (3x, never in wins) 和 `src/database/redis/hash.js` (2x) 是 regression 陷阱
29. [ ] **SFT 生成：regression avoidance trajectory**: 基于 regression-prone areas 的发现，可以为 SFT 合成 "检测到修改危险文件时先跑测试" 的 trajectory。这是 agent 策略层的改进。
30. [x] ~~**TEMPORAL TREND ANALYSIS 时序分析**~~: 已实现时序分批分析，包含趋势检测（STABLE/IMPROVING/DEGRADING）、overfitting 信号、memorization 检测、per-project 趋势。修复 timestamp 毫秒阈值。
31. [x] ~~**explore_only 新增 identified_no_action 子类型**~~: 检测模型声称找到 bug 但从未编辑的情况。UID 162: 50% explore_only 是 identified_no_action。
32. [x] ~~**目录层级累积风险聚合**~~: regression-prone areas 自动选择 depth-2/3 中信息量最大的聚合深度
33. [x] ~~**identified_no_action turn-of-claim 指标**~~: 已实现 `_find_claim_turn()` + `claim_position`。IDENTIFIED-NO-ACTION DETAIL 段落按 early/late diagnosis 分类。Sample tasks 显示 `claim@X%`。UID 242 task 3104: claim@3% 但 wide_scatter — 早期诊断后遗忘
34. [x] ~~**"false_completion" 子类型**: 已实现。检测 bash blocks 中无重定向的 echo/printf 声称完成的命令（"completed", "fixed", "implemented" 等）。UID 242 task 3111 正确检出。新增 FALSE-COMPLETION DETAIL 子段落显示具体命令~~
35. [x] ~~**Sample explore_only 的 last_msg 格式泄露**: 已修复。在提取 last_msg 时用 `re.sub` 剥离 ` ```bash`/` ``` ` 标记，将换行替换为空格，合并连续空格。UID 60 验证通过，每个 sample task 只占 2 行~~
36. [x] ~~**BUG-SPECIFIC SFT RECOMMENDATIONS 遗漏高损低浓度 bug type**: 已实现 [SYSTEMIC] 绝对数量触发——>=5 losses AND <=20% win rate 时，即使 stage 分散也生成建议，并显示 per-stage 分布。跳过已被浓度触发器覆盖的 bug types。UID 228 正确检出 off-by-one(0/5, 0%) 和 logic-inversion(0/7, 0%)~~
37. [x] ~~**[SYSTEMIC] SFT 建议缺乏具体行动指导**: 已实现 stage-proportional composite advice。[SYSTEMIC] 触发器现在根据 loss 的 stage 分布百分比生成复合建议（如 "43% target+regress → cautious edit patterns; 29% target_fail_only → include target test names"），替代了笼统的 "dedicated SFT curriculum"~~
38. [x] ~~**TEMPORAL TREND 的 "STABLE" 标签掩盖末批崩溃**: 已实现 LATE COLLAPSE 检测。当最后 batch win rate 为 0% 且任何前序 batch >=30% 时，标记 "LATE COLLAPSE" 信号并显示峰值 batch 编号和 win rate~~
39. [x] ~~**`partial` 分类逻辑可能掩盖 target-test-passed-but-regression 的重要信号**~~: 已实现 `target_pass+minor_regress` 和 `partial_progress` 细分。tasks 2843/2848 正确从 `partial` → `target_pass+minor_regress`。新增 SFT section 3 (TARGET-PASS + MINOR-REGRESS) 和 ★ Side-effect correction 建议。所有描述映射表同步更新
40. [x] ~~**PATCH-TARGET ALIGNMENT 分析**~~: 已实现。利用 `target_tests` 和 `patch_files` 比较 patch 模块与 target 测试模块的对齐度（match/related/mismatch）。跨 UID 一致发现 45-58% mismatch。含 MISMATCH DETAIL、SFT 自动推断、near-win 表 align 列
41. [x] ~~**--compare 模式的跨 miner alignment 汇总**~~: 已实现。per-UID alignment 分布表 + ALIGNMENT DIVERGENCE 子段落。发现跨 miner alignment 高度一致（同一 task 上所有 miner 通常相同 alignment）
42. [x] ~~**目录匹配深度自适应**~~: 已实现浅层项目结构 fallback。NodeBB mismatch 从 50%→11%。UID 228 的 7 个假 mismatch 正确升级为 related
43. [x] ~~**缺 target_tests 时从 missing_tests 推断**~~: 经验证 recent 30 中所有 UID 的 no_data 率为 0%，问题不存在于近期数据中
44. [x] ~~**阅读环境评分源码确认评分机制**~~: 已读 `env.py`。score = 1.0 当且仅当 `all_required` 全部通过。target_tests 仅为 informational。新增 OPT-9(scoring gap)/OPT-10(localization gap)
45. [x] ~~**TEST SUITE SIZE vs WIN RATE 分析**~~: 已实现。tiny(1-10) 67% win vs large(201+) 19% win。Losses 的测试套件平均 1.4x 更大
46. [ ] **--compare 模式的 suite size 效应对比**: 不同 miner 在不同 suite size 上的表现差异
47. [x] ~~**TOP FINDINGS 段落**~~: 已实现。在 EXECUTIVE SUMMARY 之后自动生成 3-5 个最高价值洞察（REWARD GAMING, LOCALIZATION/FIX QUALITY, NEAR-WINS, BOTTLENECK, PATTERN MATCHING, SCORING GAP）

问题区

1. [x] ~~**环境混淆(env_confusion)未被归类到no_patch_stage**~~: 已解决，新增 `identity_confusion` stage
2. **TypeScript表现与项目强相关**: UID 55 在 element-hq/element-web(TypeScript) 上 47% 胜率，但 UID 120/162/248 在 protonmail/webclients(TypeScript) 上 0%。说明不是 TypeScript 通用问题，而是 protonmail 项目特有困难。
3. [x] ~~**LANGUAGE WIN RATES 之前严重低估Python失败数**~~: 已修复
4. [x] ~~**task 2225 评分异常**~~: **已确认根因**。阅读 `env.py:576` 确认评分逻辑是 `if all_passed: return 1.0`。score 完全基于 `all_required = f2p | p2p` 全部通过，target_passed 仅为 informational。task 2225 WIN 因为 all=2984/2984（全通过），尽管 target=0/46。target_tests 在评分中不起决定作用。
5. **NodeBB near-win 率极高**: UID 30 在 NodeBB/NodeBB 上 5/10 losses 是 near-wins (>=80% all tests pass)。task 2931 (424/425 pass, target 0/3) 和 task 2937 (257/258 pass, target 0/1)。现已确认：env 评分基于 ALL tests（非 target），所以这些 near-wins 失分是因为 1-2 个非 target test 回归，不是因为 target test 问题。
6. **环境评分机制确认（迭代 30 读源码确认）**: `env.py` 行 576: `if all_passed: return 1.0, else: return 0.0`。评分完全是二元的（1.0 or 0.0），基于 `all_required = fail_to_pass ∪ pass_to_pass` 全部通过。`target_tests` 仅记录在 test_stats 中不影响评分。`missing_tests` = `all_required - passed_tests`（所有未通过的测试列表）。任务生成时 `max_failed_ratio: 0.2`（bug 注入不能让超过 20% 的测试失败，否则重试）。

---

迭代记录

### 迭代 1 — 2026-03-14

**分析对象**: UID=120, SWE-SYNTH, limit=30

**本次改进**:
1. 扩展 `_PROJECT_LANG_MAP` 增加 protonmail/webclients→TypeScript
2. 新增 **NEAR-MISS DETAIL** 段落 — 展示近胜任务的具体失败测试名
3. 新增 **ENVIRONMENT CONFUSION** 检测 — 识别模型自认为无法执行命令的情况（task 2790）
4. 扩大 ALL TASKS 表中 bug_types 截断长度 30→50，减少信息丢失
5. 以上改进使 LANGUAGE GAP suggestion 被正确触发（TypeScript 0%胜率）

**关键发现**:
- UID 120 在 SWE-SYNTH 上 13% 胜率 (4/30), 所有胜利均在 internetarchive/openlibrary (Python)
- protonmail/webclients (TypeScript) 7 tasks 全部失败，其中 1 task (2790) 是环境混淆
- 3个近胜任务 (2777, 2783, 2796) 通过 ≥80% 测试但target test失败
- 73% 失败命中 max_iterations=30, 7/26 losses 陷入循环

**提出不足**: 当前 `no_patch_stage` 分类体系缺少 `identity_confusion` 阶段——模型认为自己是纯文本AI无法执行命令，这是与 explore_only 完全不同的根因，应该单独追踪。

### 迭代 2 — 2026-03-14

**分析对象**: UID=162, SWE-SYNTH, limit=30

**本次改进**:
1. 新增 `identity_confusion` 作为独立的 `no_patch_stage` 类别（解决问题区#1）
2. 新增 **BUG TYPE × FAILURE STAGE CROSS-ANALYSIS** 交叉分析表（解决待办#2）
3. 修复 **LANGUAGE WIN RATES** 严重bug — 之前只统计有patch任务的语言，Python胜率从75%→39%（真实值），TypeScript从不可见→0%可见

**关键发现**:
- UID 162 胜率 30% (9/30), 显著高于 UID 120 的 13%
- 两个UID在protonmail/webclients(TypeScript)上都是0%胜率 — 跨miner一致性说明是环境/语言问题而非miner能力
- UID 162 的 explore_only 占比 50%（vs UID 120 的 20%）但 stuck-in-loop 检出 0/21 — 循环检测灵敏度不足
- 交叉分析揭示：`resource-leak` 4/6 卡在 explore_only（找不到泄漏位置），`logic-inversion` 3/4 卡在 edit_no_test（改了但不验证）
- **UID 162 的 explore-before-edit ratio: wins=0.38 vs losses=0.64** — 失败任务花 64% 预算在纯读代码上
- 67% 的 wins 是 TEST-FREE（不跑测试就提交）— 模型靠模式匹配而非验证

**提出不足**: explore_only 占比高达 50% 但没有回答 "为什么不编辑"。需要对 explore_only 任务的最后几条 assistant 消息做内容分析，区分 "不知道改什么" vs "找不到文件" vs "在错误方向探索"。

### 迭代 3 — 2026-03-14

**分析对象**: UID=248, SWE-SYNTH, limit=30

**本次改进**:
1. 新增 **EXPLORE-ONLY DEEP ANALYSIS** — 分类 explore_only 卡住原因为 analysis_paralysis/cant_locate/wrong_direction/tool_struggling，展示最后 assistant 消息片段
2. **循环检测升级为 n-gram Jaccard similarity** — 阈值 ≥50% 相似度，窗口扩大到 last 10 条。UID 248 检出 13/23 stuck（旧 prefix 方法在 UID 162 上 0/21）
3. 修复 stuck_tasks 输出中 backtick 字符导致的格式破损

**关键发现**:
- UID 248 胜率 23% (7/30), 所有胜利均在 Python/openlibrary
- **100% 的 wins 没有跑过任何测试**（avg test cmds: 0.0）— 三个 UID 中最极端
- explore_only 占比 62.5% (10/16), 其中 90% 是 analysis_paralysis（30次调用全在读代码）
- task 2784 是极端案例：174行patch, 60/61测试通过(98%), 但target test失败
- protonmail/webclients 5任务全部 explore_only — 模型在 TypeScript 项目中完全无法定位目标
- 跨三个 UID 的 protonmail/webclients 总计 0/19 胜率，已确认为系统性问题

**提出不足**: analysis_paralysis 分类过于笼统（90% 都归入此类）。需要通过分析读取文件路径的去重率来细分"广度探索"和"深度卡死"——前者说明模型找不到入口，后者说明模型在错误区域打转。

### 迭代 4 — 2026-03-14

**分析对象**: UID=55, SWE-SYNTH, limit=30（首次覆盖非 openlibrary/webclients 项目池）

**本次改进**:
1. **analysis_paralysis 细分为 wide_scatter + deep_stuck** — 通过文件路径去重率区分。UID 55 的 4 个 explore_only 任务 2:2 split
2. **PATCH SEMANTIC ANALYSIS** — 分类 patch 为 functional/brute_force 等。捕获 task 2314 的 770 行 brute_force patch
3. **SCORING ANOMALIES 检测** — 发现 task 2225 (WIN, score=1.0, target=0/46, all=2984/2984)
4. **修复 _detect_languages** — 过滤未知扩展名（如 .backup），不再产生垃圾语言标签

**关键发现**:
- UID 55 胜率 40% (12/30) — 四个 UID 中最高
- **首次见到 TypeScript 胜利**：element-hq/element-web 47% 胜率 (7/15)。证明 TypeScript 不是通用难题，protonmail/webclients 的 0% 是项目特有问题
- 8 个 near-wins (44% of losses) — 最大的提升空间
- task 2314: 770 行 brute_force patch, 0/5 tests — 模型在 ansible 上生成了巨大无效 patch
- task 2225 评分异常: 0/46 target tests 但 score=1.0 — 评分系统与 target_passed 不完全对应
- **所有 UID 的 wins 都是 0 test commands** — 模型从不验证就提交，100% pattern-matching

**提出不足**: explore_only 的 wide_scatter 阈值 (unique_files>=8 OR diversity>=0.6) 可能需要校准——task 2347 有 8 unique files 但 33% diversity，归入 wide_scatter 是否合理？33% diversity 意味着大量重复读取同一文件，更接近 deep_stuck。

### 迭代 5 — 2026-03-14

**分析对象**: --compare 120,162,248 (28 shared tasks)

**本次改进**:
1. **修复 wide_scatter 阈值** — OR→AND (unique>=8 AND diversity>=0.5)。task 2347 正确从 wide_scatter→deep_stuck
2. **per-task difficulty labels** — 在 --compare head-to-head 矩阵中增加 easy/medium/hard-/hard 列
3. **TASK DIFFICULTY DISTRIBUTION** — 统计各难度级别的任务数量及其 bug type 分布

**关键发现 (跨 miner 比较)**:
- 28 shared tasks: 2 easy (7%), 4 medium (14%), 6 hard- (21%), 16 hard (57%)
- **57% 任务对所有三个 miner 都不可解** — 这些 hard 任务的 top bug types: wrong-constant(5), exception-swallow(4), resource-leak(4)
- protonmail/webclients 全部 4 个 shared tasks 都是 hard — 跨 miner 一致确认
- **Winner vs Loser 行为差异**：winner 用更少调用(-5.6)，更少读取(-5.9)，更早开始编辑(-2.8 turns)
- winner 100% submit vs loser 44% submit — loser 耗尽预算不提交
- UID 120 的 failure mode 以 edit_churn(32%) + edit_no_test(42%) 为主；UID 162/248 以 explore_only(44%/53%) 为主 — 模型差异显著

**提出不足**: 同一 task 在不同 miner 上的 failure stage 不同（如 task 2790: identity_confusion/edit_no_test/explore_only），head-to-head 矩阵展示了结果但没有分析这种"失败模式迁移"意味着什么——不同模型的能力瓶颈在哪里。

### 迭代 6 — 2026-03-17

**分析对象**: --compare 242,228 (21 shared tasks, --all --limit 30)

**本次改进**:
1. **完整重建 analyze_swe.py** — 原 .pyc 意外被覆盖，从字节码内省结果完整重建了 ~700 行分析脚本，包含迭代 1-5 的所有功能
2. **NEAR-WIN CROSS-MINER CONSISTENCY (#7)** — 检测多个 miner 在同一 task 上都 >=80% 测试通过的情况。输出 per-task 表格、by-project 汇总、high-confidence 候选（avg >=95%）
3. **FAILURE MODE MIGRATION ANALYSIS (#8)** — 分析共享失败任务的 failure mode 一致性/分歧。包含：consistent/divergent 分类统计、divergent task 明细表、migration matrix（pairwise co-occurrence 对称矩阵）、MODEL WEAKNESS SIGNATURES（每个 miner 的主导失败模式描述）
4. **修复 model_calls 读取** — 从 `extra.model_calls` 正确读取（原代码从 top-level 读导致全为 0）
5. **修复 swe_instance_id 解析** — 剥离 `instance_` 前缀（如 `instance_ansible__ansible-xxx` → `ansible/ansible`）
6. **修复 task difficulty 计算** — 修正 present 列表生成中 `tid` 与 `uid` 的混淆 bug

**关键发现 (UID 242 vs 228)**:
- 21 shared tasks: 3 easy (14%), 3 medium (14%), 0 hard-, 15 hard (71%)
- 71% 任务对双方都不可解 — top bug types: logic-inversion(4), wrong-constant(4), missing-edge-case(3)
- task 2750 跨双 miner 均 near-win (98% pass rate) — target test 可能过严
- Failure mode: 60% 一致（target+regress 4, edit_churn 3, env_blocked 2），40% 分歧
- Migration pattern: edit_churn ↔ target+regress 是最常见的迁移路径（2次），说明两个模型能力差异在于 "是否能跳出编辑循环产出 patch"
- Winner 行为: 平均 edit cmd 36.7 vs loser 9.3 — winner 编辑量显著更多（但都不跑测试）

**提出不足**: language distribution 仅统计有 patch 的任务。无 patch 任务（55%+ 的 loss）的语言只能通过 project map 推断，但这些任务未被计入语言分布统计。这可能导致低估 TypeScript 等语言的任务占比。

### 迭代 7 — 2026-03-17

**分析对象**: UID=30, SWE-SYNTH, --all --limit 30（首次覆盖 NodeBB/JavaScript 项目池）

**本次改进**:
1. **修复 `_extract_project` 多 hash 解析** — 正确处理 `instance_org__repo-<commit_hash>-v<version_hash>` 和 `-vnan` 等异常后缀。通过逐段 split + hex 检测替代 rfind 方法
2. **扩展 `_PROJECT_LANG_MAP`** — 新增 `qutebrowser/qutebrowser`→Python, `NodeBB/NodeBB`→JavaScript
3. **恢复 `env_blocked` 失败阶段分类** — 检测 user 消息中高频环境错误关键词（permission denied, command not found, traceback 等），>=3 次则归为 env_blocked
4. **细化 `edit_no_test` vs `edit_churn` 边界** — edit_cmd>5 归 edit_churn（无目的重复），<=5 归 edit_no_test（尝试了但未验证）
5. **Language distribution 现在统计所有任务** — 无 patch 任务通过 project map 推断语言。UID 30 从 17/30 tasks→30/30 tasks，Python 真实胜率从 35%→20%

**关键发现 (UID 30)**:
- 26.7% 胜率 (8/30)，横跨 3 个项目：qutebrowser(Python), NodeBB(JavaScript), ansible(Python)
- **首次观察到 JavaScript 项目(NodeBB)**: 23.1% 胜率 (3/13)，低于 Python 29.4% (5/17)
- **9/22 losses 是 near-wins (>=80% tests passing)** — 其中 6 个 >=95% pass rate，target test 可能过严
- task 2931: 424/425 all tests pass (100%) 但 target 0/3 — 最极端的 target test mismatch
- No-patch: edit_churn 60%, identity_confusion 20%, env_blocked 20%
- **100% test-free wins** (8/8) — 所有 UID 一致的 pattern
- Patched failures: 67% target_fail_only — 说明 patch 质量不差，target test 定义可能有问题

**提出不足**: 当前的 `_count_conversation_stats` 对 edit command 的判定精度未验证。SWE 环境中的 agent 可能使用 tool_use JSON 格式而非 bash code blocks 来执行命令。如果 conversation 中的 tool calls 是结构化 JSON（如 `{"type":"tool_use", "name":"str_replace_editor"}`），当前的纯文本正则会完全漏检。需要检查多个 UID 的 conversation 格式来确认。

### 迭代 8 — 2026-03-17

**分析对象**: UID=60, SWE-SYNTH, --all --limit 30（首次覆盖 element-hq/element-web TypeScript 项目的大量任务）

**本次改进**:
1. **验证 conversation 格式一致性** — 检查 5 个 UID 的 conversation 格式，确认全部使用 agent=miniswe 纯文本（str content），无 tool_use JSON。#12 关闭
2. **SFT memorization/contamination 检测** — 新增 contamination flagging，标记：patch<=3 lines + 100% tests + edit<15% conv + no testing 的 wins。使用 `explore_before_edit_ratio` 替代绝对 call count（miniswe 始终 >=9 turns）
3. **SFT 数据推荐精细化** — 将 clean wins 分为 genuine（推荐 SFT）和 suspicious（需验证），不再盲目推荐 "as-is"

**关键发现 (UID 60)**:
- 33.3% 胜率 (10/30)，横跨 ansible(40%) 和 element-hq/element-web(30%)
- **85% 的 losses 没有 patch** — 所有 UID 中最高的 no-patch 率
- **edit_churn 主导 (59%)**, 45% losses 检出循环 — 模型在 TypeScript 编辑中打转
- **只有 2 个 near-wins** (vs UID 30 的 9 个) — 说明 element-hq 的 losses 是真正的 "远离胜利" 而不是 "差一点"
- Losses 平均 28.9 turns vs wins 19.8 turns — losses 耗尽预算
- **80% test-free wins** (8/10)，但 2 个 wins 使用了 test commands — 首次观察到 SWE 环境中有 miner 在 winning 时跑测试
- explore_before_edit_ratio: wins=0.90 vs losses=1.05 — 所有 wins 的 explore ratio 均 >=0.64，表明 miniswe 总是做大量探索
- Memorization flagging: 0 suspicious wins（ratio 全部 >=0.64，远高于 0.15 阈值）
- task 2996: 119 lines patch, WIN — 跨 UID 最大的 winning patch

**提出不足**: 当前分析器对同一 task 在不同 miner 间的 patch 内容没有做语义对比。如果多个 miner 在同一 task 上产出 near-identical 的 2-line patch，这说明该 fix 是 "显而易见的"（pattern match 即可解决），在 SFT 训练中的价值较低。需要实现跨 miner 同 task patch diff 相似度分析。

### 迭代 9 — 2026-03-17

**分析对象**: UID=162, SWE-SYNTH, --all --recent 30 + --compare 242,60

**本次改进**:
1. **CROSS-MINER PATCH SIMILARITY (#14)** — 在 compare 报告中新增 patch 相似度对比段落。使用 n-gram Jaccard(n=3) 比较 normalized patches（仅保留 +/- 行的内容）。分类为 IDENT(>95%)/SIM(50-95%)/DIFF(<50%)，标注 SFT 训练价值
2. **修复 `_count_conversation_stats` 严重 bug** — 旧逻辑用 `"edit"` 作为 substring 匹配整个 assistant 消息内容，导致任何提到 "edit" 一词的对话都被计为 edit command。改为仅在 ```bash code blocks 内检测实际命令（sed -i, cat >, echo > 等）
3. **修复 `t.patch_raw` → `t.fix_patch` 属性名引用** — 旧名称在新代码中不存在

**关键发现**:

**Bug 修复影响（UID 162）**:
- edit_churn: 94% → **0%**, explore_only: 0% → **44%**, edit_no_test: 6% → **56%**
- 修复前的 edit_churn 94% + loop 0% 矛盾已消除 — 实际上模型根本没在执行 edit commands，而是在讨论 editing
- explore_only 44% 与迭代 2 的发现（50%）一致，证实修复后的分类准确

**Bug 修复影响（UID 60）**:
- edit_churn: 59% → **6%**, explore_only: 18% → **53%**, edit_no_test: 18% → **35%**
- 真正的主导失败模式是 explore_only（53%），不是 edit_churn

**跨 miner patch 相似度（UID 242 vs 60, 7 shared patched tasks）**:
- 3 IDENTICAL (100% sim): tasks 3088, 3089, 3062 — 两个 miner 产出完全相同的 2-line fix
- 1 SIMILAR (57%): task 3068 — 相似但结果不同（一个 WIN 一个 LOSE）
- 3 DIFFERENT (<50%): tasks 3070, 3072, 3069 — 完全不同的修复策略
- **SFT 含义**: 3 个 identical wins 是 pattern-match（低 SFT 价值），3 个 different wins 是 unique solving（高 SFT 价值）

**提出不足**: explore_only 子分类中 tool_struggling 占比过高（UID 162 为 86%）。当前 tool_struggling 通过检测 user 消息中的 "error"/"not found" 关键词触发，但正常的命令输出（如 `grep ... | no results found`）也包含这些词。需要更精确地区分真正的工具错误 vs 正常的空结果输出。

### 迭代 10 — 2026-03-17

**分析对象**: UID=120, SWE-SYNTH, --all --recent 30

**本次改进**:
1. **修复 tool_struggling 误判 (#16)** — 改为仅在 non-zero returncode + 特定严重错误关键词（permission denied, traceback, command not found, modulenotfounderror 等）时计数。阈值从 >=5 降到 >=3。UID 162: tool_struggling 86%→0%, wide_scatter 0%→86%
2. **修复 test 行为描述不准确** — 当 test-free wins <=50% 且 winner test 频率 >2x loser 时，输出 "Testing is key differentiator" 而非 "pattern matching without testing"。>=80% 才说 "predominantly pattern matching"
3. **扩展 identity_confusion 模式** — 新增 "unable to access the file", "i can't access the file", "i'm unable to run" 等变体。task 2790 正确从 explore_only/deep_stuck → identity_confusion
4. **修复 `t.patch_raw` 引用** — 上一迭代遗留的属性名不一致问题

**关键发现 (UID 120, recent 30)**:
- 20% 胜率 (6/30)，所有胜利在 internetarchive/openlibrary (Python)
- **protonmail/webclients: 0% (5 tasks)** — 持续确认为系统性项目问题
- **首次发现 "测试是关键区分因素" 的 UID**：wins avg 1.5 test cmds vs losses 0.2。50% test-free wins（所有其他 UID 为 80-100%）
- edit_no_test 59%, explore_only 12%, edit_churn 12%, env_blocked 12%, identity_confusion 6% — 5 个阶段全部覆盖
- **target_fail_only: 100% of patched losses** — 所有提交 patch 的 loss 都通过了非 target 测试，仅 target test 失败
- 3 near-wins (83-91% pass rate)，全部在 openlibrary
- Explore-before-edit ratio wins=losses=0.64 — 探索行为一致，胜负差异在测试验证

**提出不足**: BUG TYPE × FAILURE STAGE 交叉表中 `resource-leak` 在 `edit_no_test` 列有 5 个，远超其他 bug type。这暗示 resource-leak 类 bug 的模型会尝试编辑但不验证——可能是因为 leak fix 需要 runtime 验证（跑测试才能确认是否修复），但模型缺乏这个认知。SFT 数据中应专门为 resource-leak 类 bug 合成 "编辑后必须测试" 的 trajectory。

### 迭代 11 — 2026-03-17

**分析对象**: UID=248, SWE-SYNTH, --all --recent 30

**本次改进**:
1. **BUG-SPECIFIC SFT RECOMMENDATIONS 泛化 (#19)** — 自动检测 bug_type × failure_stage 高关联对（>=60% + >=3 例），按 stage 分组输出避免重复建议，100% 关联标记 ⚠ CAPABILITY GAP
2. **分组去重** — UID 248 原本输出 5 条独立建议（4 条相同 action），现合并为 2 条：`[target_fail_only]` 12 losses 合并 4 个 bug type，`[explore_only]` 3 losses 标记 exception-swallow 为能力缺口

**关键发现 (UID 248, recent 30)**:
- 23.3% 胜率 (7/30)，4 个项目覆盖（含 gravitational/teleport Go 项目）
- **explore_only: 58% (7/12 no-patch)**，wide_scatter:4 vs deep_stuck:3 — 模型在定位目标文件上存在困难
- **exception-swallow → explore_only: 3/3 (100%) ⚠ CAPABILITY GAP** — 模型完全无法处理异常吞没类 bug，从未尝试编辑。需要专门的 SFT 数据教模型识别和定位异常吞没 pattern
- **target_fail_only: 91% of patched losses** — 模型的 patch 质量不差（通过了 91%+ 非 target 测试），但精确命中 target test 能力不足
- explore ratio: wins=0.54 vs losses=0.84 → 30% gap — losses 花过多时间探索
- task 2738: gravitational/teleport 229 行 brute_force patch → target+regress — Go 项目完全失败
- 5 near-wins 全在 openlibrary (83-93% pass rate)

**提出不足**: near-win 分析只看 `all_pass_rate >= 80%`，忽略了 target test 的部分通过率。task 2807 通过 8/11 target tests (73%) 但 score=0.0 — 这比 target 0/4 (0%) 的 task 2786 离胜利近得多。SFT 策略应该区分 "target 部分通过" 和 "target 完全失败"。

### 迭代 12 — 2026-03-17

**分析对象**: UID=248+55, SWE-SYNTH, --all --recent 30

**本次改进**:
1. **TARGET TEST PROXIMITY 子段落 (#20)** — 在 NEAR-WIN ANALYSIS 中新增。将 near-wins 按 target test 通过率分为：
   - **target-close** (target pass >50%): patch 几乎正确，仅需微调
   - **target-far** (target pass <=50%): patch 通过了其他测试但未命中 target，需要不同修复策略
   标注 SFT 优先级：target-close 有最高校正价值

**关键发现**:
- **UID 248**: 5 near-wins 中仅 1 个 target-close (task 2807, 8/11=73%)，4 个 target-far (0-50%)
  → task 2807 是最有价值的 SFT 校正候选：只需修复 3 个剩余 target test
- **UID 55**: 4 near-wins 全部 target-far (0% target pass, 但 94-99% all pass)
  → 这些 patch 完全没有命中 target test，是 "wrong fix" 而非 "almost right fix"
  → SFT 策略应该是重新审视问题理解，而非微调 patch
- **跨 UID 规律**: target-far 远多于 target-close（约 4:1 比例），说明大多数 near-win 不是 "差一点" 而是 "改对了别的东西"。这挑战了 "near-win = 接近胜利" 的假设

**提出不足**: 当前分析器只能逐个 UID 分析或两两 compare。缺少 "全景汇总" 模式：输入多个 UID，输出一张汇总表（win rate, dominant failure, near-win count, capability gaps per UID），用于快速筛选最优/最差 miner 和识别跨 UID 一致的全局模式。

### 迭代 13 — 2026-03-17

**分析对象**: --compare 120,248,60 --all --recent 30 (3-way panoramic)

**本次改进**:
1. **OVERVIEW 表增强 (#21)** — 新增 DomFailure（主导失败模式）和 Gaps（能力缺口 bug type）两列。全景视图一目了然
2. **MINER PROFILES 段落** — 自动生成每个 UID 的 strengths/weaknesses 一句话摘要，包含：highest win rate, near-win 数量, bottleneck（>=40% 集中度的失败模式），capability gaps
3. **修复 `utm` UnboundLocalError** — `utm` 在 `if shared:` 块内定义但在外部引用，移至块外

**关键发现 (3-way: UID 120 vs 248 vs 60)**:
- **UID 60 (46.7%)** > UID 248 (23.3%) > UID 120 (20.0%)
- 三个 UID 的 bottleneck 完全不同：
  - UID 60: explore_only (40%) — 找不到目标文件
  - UID 120: edit_no_test (42%) — 编辑但不验证
  - UID 248: target_fail_only (43%) — patch 通过非 target 测试但不中 target
- **protonmail/webclients: 0% 跨 UID 120/248 一致** — 持续确认
- **Python vs TypeScript**: Python 24-47% 胜率 vs TypeScript 0% — 语言差距全局一致
- UID 248 唯一检出 capability gap (exception-swallow)

**提出不足**: `--compare` 多 UID 模式需要全量扫描每个 UID 的 DB（如 UID 162 有 683 条），--recent 30 也需要先扫描全部才能取最近 30 条。应支持并行 fetch 或 DB 层 limit 查询以提升性能。

### 迭代 14 — 2026-03-17

**分析对象**: --compare 120,162,248,60,242 --all --recent 20 (5-way panoramic)

**本次改进**:
1. **双层并行 fetch (#22)** — (1) 多 UID 用 `asyncio.gather` 并行 fetch，(2) 单 UID 内部 task 用 `Semaphore(20)` 并行 fetch。5 UIDs ~1600 tasks: 15 秒
2. **DB 连接安全共享** — 用 `asyncio.Lock` 确保 `init_client()` 只调用一次，`close_client()` 统一在 main 结束时调用
3. **修复 `utm` UnboundLocalError** — 上一迭代遗留：`utm` 只在 `if shared:` 内定义但外部引用

**关键发现 (5-way panoramic: UID 60/120/162/242/248)**:
- **UID 60=162=40% > 242=30% > 248=25% > 120=20%** — win rate 差距显著
- **target_fail_only 是 4/5 UID 的主导失败模式** — 系统性问题：模型的 patch 通过了大部分测试但精确不中 target test
- **UID 120 是唯一 edit_no_test 主导的 UID** — 其他 UID 都已进化到 "能提交 patch 但不精确" 阶段
- **UID 242 检出 wrong-default capability gap** — 新发现
- **protonmail/webclients: 跨 UID 120/248 一致 0%** — 持续确认
- **Near-wins**: UID 242 最多 (6 个)，说明 patch 质量高但差 "最后一英里"
- 双层并行将 5-UID 对比从估计 >60 秒降至 15 秒

**提出不足**: `--all --recent N` 仍需要先全量扫描 DB（如 UID 162 的 689 条），然后才在 Python 层取最近 N 条。DB 层面（DynamoDB）应支持 reverse scan + limit 来避免全量扫描，但这需要 DAO 层修改，超出分析脚本范围。

### 迭代 15 — 2026-03-17

**分析对象**: UID=242, SWE-SYNTH, --recent 30 (质量审查)

**本次改进 (报告精简)**:
1. **移除二元分数 SCORE DISTRIBUTION** — 当 score 只有 0.0 和 1.0 时，柱状图和百分比分布无信息量。Executive Summary 已覆盖
2. **Near-win 三重展示合并为单表** — 原来的 near-win table + HIGH-CONFIDENCE 列表 + TARGET PROXIMITY 列表合并为一张带 proximity tag 的表 + 单行汇总（`11 near-wins | 10 high-conf | 0 close | 11 far`）
3. **Bug co-occurrence 过滤 count<2** — 移除只出现 1 次的配对（随机噪声），只保留 >=2 次的有统计意义的配对
4. **Priority ranking 过滤 count<2** — 移除 "1 tasks stuck reading code" 等单例优先级
5. **移除冗余 Project-language mapping** — project 表和 language 表已经清楚地展示了这个映射

**效果**: 报告从 **364 → 315 行** (-13.5%)，信息密度提升

**关键发现 (UID 242, recent 30)**:
- 26.7% 胜率 (8/30)，几乎全在 element-hq/element-web (TypeScript)
- **11/22 losses 是 near-wins (50%!)** — 最高比例，说明 UID 242 的 patch 质量高但不精确
- **11/11 near-wins 全部 target-far (0% target pass)** — 确认 "wrong fix" 模式：patch 通过了 94-100% 非 target 测试，但完全没命中 target test
- wrong-default → target_fail_only: 5/6 (83%) — 最强的 bug-specific 信号
- 100% test-free wins — 持续一致的 pattern

**提出不足**: 当前 SFT 数据合成建议对 near-win 统一推荐 "synthesize corrected trajectories by fixing the target test issue"。但迭代 12 已证实绝大多数 near-wins 是 target-far（wrong fix），不是 target-close（almost right）。对 target-far 来说，"修正 target test issue" 的建议不准确——实际需要的是 "重新理解问题并尝试不同修复方向"。SFT 建议应根据 close/far 分类给出不同 action。

### 迭代 16 — 2026-03-17

**分析对象**: UID=228, SWE-SYNTH, --all --recent 30（纯 NodeBB/JavaScript 项目）

**本次改进**:
1. **SFT near-win 建议分化 (#25)** — 对 target-close 推荐 "synthesize minor corrections"，对 target-far 推荐 "re-read problem and try different fix direction"。UID 228 正确输出 2 close + 2 far 的差异化建议
2. **SCORING ANOMALIES 范围扩大 (#26)** — 从仅检测 `target_passed_count==0` 扩大到 `target_pass_rate<50%`。新检出 task 2953 (1/49=2% target pass, WIN) 和 task 2936 (1/4=25% target pass, WIN)

**关键发现 (UID 228, 纯 NodeBB/JavaScript)**:
- 16.7% 胜率 (5/30) — 分析过的 UID 中最低
- **target+regress: 78% of patched losses (14/18)** — 远高于其他 UID（通常 <20%）。UID 228 的 patch 不仅没修对，还破坏了其他测试
- 这与其他 UID 的 target_fail_only 模式（patch 没破坏其他测试）形成鲜明对比：NodeBB 项目的测试可能有强耦合性，一处修改容易引发连锁回归
- task 2944: target=0/93, all=2924/2925 — 极端 wrong fix（完全不同的 bug）
- task 2956: all=0/2984 — 灾难性 patch，2984 个测试全部失败
- **2 个 scoring anomalies**: task 2953 (1/49 target, WIN) 和 2936 (1/4 target, WIN) — 评分系统可能基于 `all_passed` 而非 `target_passed`
- `incomplete-update → target+regress: 100%` ⚠ CAPABILITY GAP — 模型的 incomplete-update fix 总是造成回归
- Explore-before-edit ratio wins=0.66 vs losses=0.69 — 几乎无差异，暗示探索行为不是此 UID 的瓶颈

**提出不足**: target+regress 在 NodeBB 上占 78%，远高于其他项目（element-hq ~10%, openlibrary ~20%）。这是否因为 NodeBB 的测试套件有特殊的耦合结构（如全局 state 依赖）？当前分析器没有能力分析 regression 的具体测试失败模式（哪些测试被破坏、是否有共同的 test fixture）。这可能需要解析 test result 详情。

### 迭代 17 — 2026-03-17

**分析对象**: UID=228 + 5-way panoramic (228,242,120,60,248)

**本次改进**:
1. **REGRESSION DETAIL 段落 (#27)** — 新增于 FAILURE ANALYSIS 中 PATCHED FAILURE CATEGORIES 之后（>=2 regress tasks 时显示）。内容：
   - Regression severity distribution（avg/median/max tests broken）
   - Catastrophic（<10% pass）vs Minor（>=80% pass）分类 + per-task detail
   - Patch size 与 regression 的相关性（regressing vs wins vs non-regressing）
   - Per-project regression 分布

**关键发现 (REGRESSION DETAIL, UID 228)**:
- **avg 346 tests broken/regression, median 192, max 2984** — 灾难级
- **14/15 regressions are catastrophic** (<10% tests pass)
- **Patch size 无差异**: regressing=3L, wins=2L — 同样大小的 patch，一个能赢一个能破坏 2984 个测试。差异在于 *理解* 而非 *复杂度*
- task 2956: 4-line patch → 0/2984 tests — NodeBB 测试套件对小改动极度脆弱
- **5-way panoramic**: UID 228 是唯一以 target+regress 为主导的 UID (57%)，其他 4 个 UID 都是 target_fail_only/edit_no_test 为主。NodeBB 项目的测试耦合是 UID 228 低胜率 (16%) 的核心原因

**提出不足**: REGRESSION DETAIL 显示 catastrophic regression 中 patch size 与 win patch size 相同（都是 2-3 lines）。这意味着区分 "正确 fix" 和 "灾难 fix" 不在于 patch 大小而在于 patch *位置*（哪个文件/函数被修改）。当前分析器不解析 patch 的文件路径来判断高危修改区域。可以通过分析 patch 中 `diff --git a/PATH` 行来识别 "regression-prone code areas"。

### 迭代 18 — 2026-03-17

**分析对象**: UID=228 + UID=30 对比验证

**本次改进**:
1. **Regression-prone code area 分析 (#28)** — REGRESSION DETAIL 新增文件路径对比：
   - 统计 regressing patches 修改的 top directories
   - 对比 win patches 的修改路径，标记 "NEVER in wins" 的危险区域
   - 标记 regression-only files（仅在 regression 中出现，从未在 win 中出现的文件）

**关键发现**:

**UID 228 (NodeBB) regression-prone areas:**
- `src/database/redis`: 5 regressions（also in wins）— Redis 操作是高风险但有时必要的修改
- `src/posts/uploads.js`: 3 regressions, **NEVER in wins** — 碰此文件必回归，是明确的 regression trap
- `src/database/redis/hash.js`: 2x regression-only — Redis hash 操作特别危险
- **SFT 含义**: 可以合成 "检测到修改 uploads.js/hash.js 时先跑测试" 的 cautious trajectory

**UID 30 (qutebrowser) 对比:**
- avg 8 tests broken/regression（vs NodeBB 的 346）— 回归规模小两个数量级
- Regression 与 **大 patch** 相关：regressing=184L vs wins=3L — 与 NodeBB 完全相反（NodeBB 是小 patch 大回归）
- 这证实 regression pattern 是项目特定的，不是通用模式

**提出不足**: regression-prone areas 分析目前按完整文件路径匹配。但更有价值的是按 *目录层级* 聚合（如 `src/database/` 包含多个危险文件），当前实现已用 top-3 path segments 做了初步聚合，但未考虑同一目录下不同文件的累积风险。

### 迭代 19 — 2026-03-17

**分析对象**: UID=162, SWE-SYNTH, --all --recent 30（element-hq/element-web TypeScript 为主）

**本次改进**:
1. **TEMPORAL TREND ANALYSIS 新增 (#overfitting检测)** — 将轨迹按时间排序分批，展示 win rate 变化趋势。包含：
   - 时序分批 win rate/patch rate/avg turns/near-win 表
   - 自动趋势检测（STABLE/IMPROVING/DEGRADING，基于前后半段对比）
   - Overfitting 信号检测（peak then decline >20pp）
   - 单调递增 memorization 检测
   - Per-project 时序趋势（>=5 tasks 的项目）
   - 智能时间格式：同一天内显示 HH:MM，跨天显示 MM-DD HH:MM
2. **修复 timestamp 毫秒阈值** — `1e15` → `1e12`，修复 year 58176 out of range 错误
3. **explore_only 新增 "identified_no_action" 子类型** — 检测模型最后 3 条 assistant 消息中是否声称找到了 bug（"I found the bug", "the issue is", "root cause" 等），但从未执行编辑。这与 wide_scatter/deep_stuck 有本质区别：不是定位能力问题，而是行动决策能力问题
4. **目录层级累积风险聚合优化 (#18 fix)** — regression-prone areas 分析现在在 depth-2 和 depth-3 中自动选择信息量最大的聚合深度（top-3 dirs 覆盖 >=70% regressions 时选择浅层），并显示每个目录下涉及的文件数

**关键发现 (UID 162, recent 30)**:
- 36.7% 胜率 (11/30)，element-hq/element-web 40% (10/25)，Python 25% (1/4)
- **TEMPORAL: 02:59-12:26 同一天内完成 30 tasks**。Win rate 从 batch 1 的 17% 提升到 batch 4 的 50%（delta=+5.6pp），轻微 IMPROVING 趋势
- **TypeScript(element-hq) 40% 胜率** — 与 UID 55 的发现一致，证明 TypeScript 不是通用难题
- **探索不行动: identified_no_action 50% (3/6) explore_only** — 模型明确声称"I found the bug"但从未编辑。这是全新发现：
  - task 3106: 声称找到 openlibrary 的 import_author bug，但耗尽所有 turns 读代码
  - task 3096: 声称找到 createRoom.ts 的 JoinRule.Knock bug，但没有编辑
  - 这不是定位失败，是 **行动决策失败** — 模型有能力诊断但缺乏编辑信心
- **7/19 near-wins 全部 target-far (0% target pass)** — 持续确认 "wrong fix" 模式
- **Token 效率**: wins avg 158K vs losses avg 319K — losses 用 2 倍 token，说明 loss 的代价不仅是分数还有计算资源
- **wrong-default 6 tasks 0% win rate** — bug type 中最差，但不触发 SFT recommendation（各 failure stage 分散）
- **wrong-operator → edit_no_test: 3/5 (60%)** — 唯一触发 SFT recommendation 的 bug-stage 高关联

**提出不足**: identified_no_action 是一个重要发现，但当前只检查最后 3 条 assistant 消息中的关键词。更准确的方法是检测整个 conversation 中 *最早出现* "found the bug" 声称的时间点，然后计算声称后 remaining turns 中 edit 命令的比例。如果模型在第 5 turn 就声称找到 bug 但接下来 25 turns 都没有编辑，这比在第 28 turn 声称找到 bug 严重得多。turn-of-claim 指标可以区分 "早期诊断但不行动" vs "最后才诊断来不及行动"。

### 迭代 20 — 2026-03-17

**分析对象**: UID=242, SWE-SYNTH, --all --recent 30（element-hq/element-web TypeScript + Python + NodeBB）

**本次改进**:
1. **Turn-of-claim 指标实现 (#33)** — `_find_claim_turn()` 扫描整个 conversation 找到模型最早声称找到 bug 的 assistant turn。计算 `claim_position`（0.0=很早, 1.0=很晚）。在 EXPLORE-ONLY DEEP ANALYSIS 中新增 IDENTIFIED-NO-ACTION DETAIL 子段落：
   - Early diagnosis (claim <50%): 有预算但不行动 → 需要 AGENCY 训练
   - Late diagnosis (claim >=50%): 来不及行动 → 需要 EFFICIENCY 训练
   - 每个任务显示 `claim at turn X/Y (Z%), N turns unused after diagnosis`
   - Sample explore_only tasks 现在显示 `claim@X%` 标注（即使是 wide_scatter 等其他子类型）
2. **claim_turn 属性添加到 TrajectoryData** — 可在 compare 报告中使用

**关键发现 (UID 242, recent 30)**:
- 30% 胜率 (9/30)，所有胜利在 element-hq/element-web (TypeScript 36%)
- **Python 0% (4 tasks)** — 与早期分析中 UID 242 有 Python wins 不同，可能是新任务更难
- **10/21 near-wins (48%) 全部 target-far** — 最高 near-win 比例（near 半数 loss）。task 3094: 217/218 (100%) all pass 但 target 0/1
- **100% test-free wins** — 持续一致
- **TEMPORAL: IMPROVING (+8.3pp)**，element-hq 25%→46% (+21pp ↑)
- **task 3104 claim@3%**: 模型在 conversation 3% 处声称找到 bug，但之后散射到 wide_scatter（读取大量不同文件）。这与 identified_no_action 不同 — 模型早期诊断后 *忘记* 了诊断结果，而非 *不敢* 行动
- **task 3111 "假完成"**: 模型运行 `echo 'Completed code review and implemented fix...'` 而非实际编辑代码。是一种 analysis_paralysis 变体 — 模型模拟完成行为代替真正编辑
- **target_fail_only 83% patched losses + 3 个 bug type 都 >=60%**: wrong-default, missing-edge-case, incomplete-update 全部集中在 target_fail_only
- **Token 效率**: wins avg 99K vs losses avg 211K — 2.1 倍差距，与 UID 162 的发现一致

**提出不足**: task 3111 的 "假完成" 模式（`echo 'Completed...'`）是一个未被当前分类系统捕获的行为。模型运行一个 echo 命令来 "宣告完成"，但实际上什么都没改。当前分类逻辑把 echo 识别为 edit command（因为 `echo >` 匹配），但这种声明性 echo 没有重定向符号，不应该被计为 edit。需要检查 `_count_conversation_stats` 是否正确处理了无重定向的 echo 命令（当前正则 `(echo|printf)\s+.*>` 要求 > 符号，所以纯 `echo 'Completed...'` 不会被误计 — 这是正确的）。但 analysis_paralysis 分类也不太准确 — 应考虑新增 "false_completion" 子类型检测模型声称完成但没有实际 patch 的情况。

### 迭代 21 — 2026-03-17

**分析对象**: UID=120, SWE-SYNTH, --all --recent 30（internetarchive/openlibrary Python + protonmail/webclients TypeScript）

**本次改进**:
1. **"false_completion" 子类型实现 (#34)** — 在 `_classify_explore_only()` 中新增检测，扫描 assistant 消息的 ```bash blocks 中无文件重定向的 echo/printf 命令，匹配 "completed", "fixed", "implemented", "resolved" 等完成声称关键词。新增：
   - `_extract_false_completion_cmds()` 辅助函数提取具体命令文本
   - `TrajectoryData.false_completion_cmds` 属性存储检出的命令
   - `FALSE-COMPLETION DETAIL` 子段落在 EXPLORE-ONLY DEEP ANALYSIS 中，显示每个 false_completion 任务的具体 echo 命令和 SFT 含义
   - `_explore_subtype_description` 和 `_LABEL_ABBREV` 同步扩展
   - 验证：UID 242 task 3111 正确从 analysis_paralysis → false_completion，显示 3 条 `echo 'Completed code review...'` 命令
2. **修复 near-win 全 target-far 注释不准确** — 当 target-far 任务中有部分 target pass（如 1/2=50%）时，注释从 "0% target pass" 改为 "<=50% target pass"。UID 120 的 task 2783 (1/2) 和 2796 (1/2) 现在被准确描述

**关键发现 (UID 120, recent 30)**:
- 20% 胜率 (6/30)，全部胜利在 internetarchive/openlibrary (Python 24%)
- **protonmail/webclients: 0% (5 tasks)** — 跨迭代持续确认为系统性项目问题
- **edit_no_test 主导 (59%, 10/17)** — UID 120 的核心瓶颈是"编辑但不验证"，与其他 UID 的 explore_only/target_fail_only 不同
- **target_fail_only: 100% patched losses (7/7)** — 所有提交 patch 的 loss 都通过了非 target 测试，仅 target test 失败
- **Testing is key differentiator**: wins avg 1.5 tests vs losses 0.2，50% test-free wins — UID 120 是唯一测试行为区分胜负的 UID
- **explore_only 仅 2 个 (12%)，均为 wide_scatter** — 无 false_completion 检出（该模式目前仅在 UID 242 task 3111 确认）
- **Temporal: DEGRADING (-8.3pp)**，从 batch 1-2 的 25% 到 batch 4-5 的 25%，但 batch 3 跌至 0% 拉低整体趋势
- **Token 效率**: wins avg 182K vs losses avg 288K — 1.6 倍差距
- **resource-leak → edit_no_test: 5/7 (71%)** — resource-leak bug 的模型会编辑但不跑测试验证，这是因为 leak fix 需要 runtime 验证

**提出不足**: Sample explore_only tasks 的 `last_msg` 显示存在格式泄露问题。当 assistant 最后一条消息包含 ```bash 代码块时，`[:120]` 字符截断会保留换行符和 markdown 代码块标记（如 ` ```bash`），导致报告输出中出现多行原始 markdown（报告第 127-134 行）。应将 `last_msg` 中的换行符替换为空格，并剥离 ``` 标记，确保每个 sample task 只占 2 行（task 信息 + last msg 预览）。

### 迭代 22 — 2026-03-17

**分析对象**: UID=60, SWE-SYNTH, --all --recent 30（element-hq/element-web TypeScript 为主 + openlibrary + NodeBB）

**本次改进**:
1. **修复 last_msg 格式泄露 (#35)** — 在 EXPLORE-ONLY DEEP ANALYSIS 的 Sample tasks 中，提取 assistant 最后一条消息时：
   - 用 `re.sub(r'```\w*', '', raw)` 剥离 ` ```bash`、` ```python` 等开放代码块标记
   - 用 `raw.replace('```', '')` 剥离闭合 ` ``` ` 标记
   - 将 `\n` 和 `\r` 替换为空格
   - 用 `re.sub(r'  +', ' ', raw).strip()` 合并连续空格
   - 验证：UID 60 的 3 个 sample tasks 每个只占 2 行（task 信息 + last msg 预览），无 markdown 泄露

**关键发现 (UID 60, recent 30)**:
- 40% 胜率 (12/30)，横跨 NodeBB(100%, 1/1)、openlibrary(50%, 2/4)、element-hq(36%, 9/25)
- **⚠ OVERFITTING SIGNAL**: win rate 在 batch 2 达到 67% 峰值后持续下降到 33%。element-hq 项目从 50%→23% (-27pp)。这是跨迭代首次检出 overfitting 信号
- **100% target_fail_only among patched losses (8/8)** — 所有提交 patch 的 loss 都通过了大部分测试但 target test 失败。8 个 near-wins 全部 target-far (0% target pass)，确认 "wrong fix" 模式
- **wrong-default 是最弱 bug type: 1/8 (12.5%) win rate** — 7 个 losses 分散在 edit_no_test(2), explore_only(2), target_fail_only(3) 三个 stage，但当前 BUG-SPECIFIC RECOMMENDATIONS 未能捕获（因为无单个 stage >=60%）
- **explore_only 分类精细化后的全新视角**: 6 个 explore_only 中 5 个是 deep_stuck（83%），仅 1 个 wide_scatter。模型在 TypeScript 项目中反复读取同一区域文件，不是定位失败而是理解失败
- **Token 效率**: wins avg 157K vs losses avg 294K — 1.9 倍差距，与 UID 162/242 的 ~2x 差距一致
- **75% test-free wins** (9/12)，但 3 个 wins 使用了 test commands — UID 60 是少数有部分 winning 时跑测试的 UID（与迭代 8 观察一致）
- **Patch size 反常**: losses avg 1.9L vs wins avg 4.3L — losses 的 patch 反而更小，说明 loss 不是因为 "改太多" 而是 "改的位置不对"

**提出不足**: BUG-SPECIFIC SFT RECOMMENDATIONS 仅靠 stage 浓度（>=60%）触发，遗漏了 `wrong-default` 这种高总量低浓度的 bug type（8 tasks, 12.5% win rate, 7 losses 分散在 3 个 stage）。应增加绝对数量触发条件：当某 bug type 有 >=5 losses 且 win rate <=20% 时，即使没有单一 stage 达到 60%，也生成 "systemic weakness" 类建议（如 "this bug type has systemically low win rate across all failure stages — consider dedicated SFT curriculum"）。

### 迭代 23 — 2026-03-17

**分析对象**: UID=228, SWE-SYNTH, --all --recent 30（纯 NodeBB/JavaScript，第二次分析此 UID）

**本次改进**:
1. **[SYSTEMIC] 绝对数量触发器实现 (#36)** — BUG-SPECIFIC SFT RECOMMENDATIONS 新增第二触发条件：当 bug type 有 >=5 losses AND <=20% win rate 时，即使 losses 分散在多个 failure stages，也生成 `[SYSTEMIC]` 建议。实现细节：
   - 统计每个 bug type 的全局 win count 和 total count（遍历所有 parsed tasks，不仅 losses）
   - 用 `concentrated_bts` 集合跳过已被浓度触发器（>=60%）覆盖的 bug types，避免重复建议
   - 输出格式：`[SYSTEMIC] bug_type: X/Y wins (Z%) — N losses spread across stages (stage:count, ...)`
   - 按 win rate 升序排序（最弱 bug type 优先）
   - 验证：UID 228 正确检出 `off-by-one` (0/5, 0%) 和 `logic-inversion` (0/7, 0%)，两者的 losses 分散在 3-4 个不同 stages

**关键发现 (UID 228, recent 30, 第二次分析)**:
- 16.7% 胜率 (5/30) — 与迭代 16 一致，持续为分析过的 UID 中最低
- **⚠ OVERFITTING SIGNAL**: win rate 从 batch 2 的 33% 峰值下降到 batch 5 的 17%（delta=-13.9pp）。与 UID 60 一同为仅有的两个检出 overfitting 信号的 UID
- **[SYSTEMIC] 新发现**:
  - `logic-inversion`: 0/7 (0%) — 7 losses 分散在 target+regress(3), target_fail_only(2), regression_only(1), edit_no_test(1)。模型完全无法修复逻辑反转类 bug，失败方式多样化
  - `off-by-one`: 0/5 (0%) — 5 losses 分散在 target+regress(2), target_fail_only(1), edit_no_test(1), explore_only(1)。与 logic-inversion 类似的全面失败
- **`src/user` 目录新增为高风险区域**: 4 regressions across 4 files, NEVER in wins — 与迭代 17-18 发现的 `src/posts/uploads.js` (3x) 和 `src/database/redis/hash.js` (2x) 并列为 regression traps
- **target+regress 持续主导**: 14/18 patched losses (78%)，14/15 catastrophic (<10% pass)。avg 346 tests broken — NodeBB 测试套件的强耦合性持续确认
- **Token 效率**: wins avg 86K vs losses avg 252K — 2.9 倍差距，比其他 UID 的 ~2x 更极端
- **0% loop detection**: 尽管有 14 个 catastrophic regressions，模型没有在重复循环中浪费时间 — 失败模式是 "一次错误编辑就灾难" 而非 "反复尝试"

**提出不足**: `[SYSTEMIC]` 触发器的建议仅为笼统的 "dedicated SFT curriculum for X bugs"，缺乏 stage-specific 行动指导。浓度触发器通过 stage_advice 字典提供具体行动（如 "run tests after editing"），但 SYSTEMIC 建议因 losses 分散在多个 stage 而无法选择单一建议。改进方向：根据 stage 分布比例生成复合建议（如 "43% in target+regress → cautious edit patterns; 29% in target_fail_only → re-read problem; 14% in explore_only → file-scope hints"），提供可执行的多阶段 SFT 策略。

### 迭代 24 — 2026-03-17

**分析对象**: UID=248, SWE-SYNTH, --all --recent 30（internetarchive/openlibrary Python + gravitational/teleport Go + protonmail/webclients TypeScript，第二次分析此 UID）

**本次改进**:
1. **[SYSTEMIC] stage-proportional composite advice 实现 (#37)** — 替换了笼统的 "dedicated SFT curriculum for X bugs" 建议。现在根据 loss 在各 failure stage 的分布比例，生成多条 stage-specific 行动建议。实现细节：
   - 遍历 `stage_breakdown` 计算每个 stage 占总 loss 的百分比
   - 使用已有的 `stage_advice` 字典获取对应 stage 的具体行动
   - 输出格式：`Action (composite): 40% stage1 → advice1; 30% stage2 → advice2; ...`
   - 验证 UID 248: `resource-leak` 输出 "40% target_fail_only → include target test names; 40% explore_only → provide file-scope hints; 20% env_blocked → provide project-specific setup instructions"
   - 验证 UID 228: `logic-inversion` 输出 "43% target+regress → cautious edit patterns; 29% target_fail_only → include target test names; 14% regression_only → investigate root cause; 14% edit_no_test → run tests after editing"

**关键发现 (UID 248, recent 30, 第二次分析)**:
- 23.3% 胜率 (7/30) — 与迭代 11-12 一致（23.3%），模型性能稳定
- **末批崩溃**: batch 5 (03-13 09:54-10:58) 跌至 0% win rate，avg turns 27.8（全批最高）。batch 2-4 稳定在 33%，趋势检测报 STABLE（delta=-2.8pp），掩盖了最后 6 tasks 全部失败的事实
- **exception-swallow → explore_only: 3/3 (100%) CAPABILITY GAP 持续确认** — 与迭代 11 一致，模型完全无法处理异常吞没类 bug，跨时间稳定的能力缺口
- **[SYSTEMIC] resource-leak: 1/6 (17%)** — 5 losses 分散在 target_fail_only(2), explore_only(2), env_blocked(1)。新增的 composite advice 正确输出三条 stage-specific 建议
- **identified_no_action 分化**: task 2789 (claim@0%, 29 turns unused) vs task 2787 (claim@96%, 0 turns left) — 完美展示了 early vs late diagnosis 的对比，前者需要 AGENCY 训练（有预算不行动），后者需要 EFFICIENCY 训练（定位太慢）
- **wrong-variable 0% (5 tasks) 但未触发 SYSTEMIC** — 因为 3/5 (60%) 集中在 target_fail_only，已被浓度触发器正确捕获。`concentrated_bts` 去重机制工作正常
- **openlibrary 下降趋势**: per-project 从 33%→17% (-17pp)，与整体 STABLE 标签矛盾。暗示 openlibrary 的后期任务更难或模型在该项目上退化
- **Patch size 异常**: losses avg 28.9L vs wins avg 2.1L — 14 倍差距。loss 的 patch 过大（含 229L brute_force），与 UID 228 (NodeBB 小 patch 大回归) 的 pattern 完全相反
- **Token 效率**: wins avg 213K vs losses avg 255K — 仅 1.2 倍差距，比其他 UID (1.6-2.9x) 显著更小。说明 UID 248 的 loss 不是因为耗尽预算（explore_only 的 token 消耗较低），而是方向错误

**提出不足**: TEMPORAL TREND ANALYSIS 的 "STABLE" 标签可以掩盖末批崩溃。UID 248 batch 5 从 33% 跌至 0%（avg turns 27.8，最高），但前后半段对比的 delta 仅 -2.8pp（因 batch 1 的 16.7% 拉低了前半段均值）。应增加 "末批 vs 峰值" 检测：当最后 batch win rate 为 0% 且任何前序 batch >=30% 时，应标记 "LATE COLLAPSE" 信号，区分于整体趋势。这与 UID 228/60 的 overfitting signal（peak then decline >20pp）不同——那里是持续下降，这里是骤降。

### 迭代 25 — 2026-03-17

**分析对象**: UID=30, SWE-SYNTH, --all --recent 30（qutebrowser/Python + NodeBB/JavaScript，第二次分析此 UID）

**本次改进**:
1. **LATE COLLAPSE 检测实现 (#38)** — 在 TEMPORAL TREND ANALYSIS 的 overfitting signal 检测之后新增。逻辑：当最后 batch win rate 为 0% 且任何前序 batch >=30% 时，标记 "LATE COLLAPSE" 并显示峰值 batch 编号和 win rate。区别于 overfitting signal（peak then sustained decline >20pp）——LATE COLLAPSE 捕获的是骤降而非渐降。UID 30 最后 batch 为 33.3%（非 0%），正确未触发

**关键发现 (UID 30, recent 30, 第二次分析)**:
- 26.7% 胜率 (8/30)，与迭代 7 一致（26.7%），模型性能稳定
- **qutebrowser 剧烈下降**: 50% → 12% (-38pp)，是跨迭代观察到的最大单项目跌幅
- **TEMPORAL: DEGRADING (-11.1pp, 33%→22%)**，但 NodeBB 反向 IMPROVING (+12pp: 17%→29%)，两个项目趋势完全相反
- **`partial` 分类的新发现**: tasks 2843 (target 4/4, all 80/86) 和 2848 (target 2/2, all 50/54) 通过了全部 target tests 但因 all tests 少量失败被分类为 `partial`。这些是 "修对了 target bug 但引入轻微回归" — 与 target_fail_only 有本质区别，是 SFT 高价值候选
- **order-dependency: 0/5 (0%) [SYSTEMIC]** — 新增发现：UID 30 完全无法修复顺序依赖类 bug，5 losses 分散在 4 个 stage。composite advice 正确输出四条 stage-specific 建议
- **9/22 near-wins (41%)**: 2 target-close (tasks 2843, 2848) + 7 target-far。NodeBB 5/10 losses 是 near-wins（50%）— 与迭代 7 的发现一致
- **Scoring anomaly 持续确认**: task 2936 (target 1/4=25%, WIN) — 评分系统可能基于 all_passed 而非 target_passed
- **explore ratio wins=0.62 vs losses=0.59** — 几乎无差异且 loss 甚至更低，说明 UID 30 的失败不是因为过度探索（与 UID 248 的 0.54 vs 0.84 gap 完全不同）

**提出不足**: `partial` 分类逻辑过于模糊。tasks 2843 和 2848 通过了 100% target tests 但 all tests 有少量失败（80/86 和 50/54），被归为 "some progress but incomplete"。这实际是 "target bug 修复成功但引入轻微副作用"（target_pass+minor_regress），与 target_fail_only（未命中 target）是完全不同的失败模式。前者只需学习避免副作用（高 SFT 价值），后者需要不同修复方向。应细分 partial 为 target_pass+minor_regress vs partial_progress。

### 迭代 26 — 2026-03-17

**分析对象**: UID=30, SWE-SYNTH, --all --recent 30（验证 partial 细分）+ UID=248 回归验证

**本次改进**:
1. **`partial` 细分为 `target_pass+minor_regress` 和 `partial_progress` (#39)** — 在 `_classify_patched_failure()` 中，原 else 分支（target_ok AND non_target_rate >= 0.9）改为：
   - `target_pass+minor_regress`: target 全部通过但仍为 loss（可能 all_tests 有少量失败 / 评分系统差异）
   - `partial_progress`: target 部分通过
   - 无测试数据时从 `partial` → `partial_progress`
2. **新增 SFT section "3. TARGET-PASS + MINOR-REGRESS"** — 在 NEAR-WINS 之后、EXPLORE-ONLY 之前，显示每个 target_pass+minor_regress 任务的 target/all 结果和 broken test 数量
3. **新增 IMPROVEMENT PRIORITY "Fix side effects"** — 在 near-win conversion 之前
4. **新增 SFT SYNTHESIS "★ Side-effect correction"** — 标注为 HIGHEST SFT correction value
5. **所有描述映射表同步更新** — `_LABEL_ABBREV`, `_category_description`, `_mode_consistency_suffix`, `_mode_weakness_description`, `stage_advice` 均新增对应条目

**关键发现 (UID 30, partial 细分验证)**:
- **tasks 2843 和 2848 正确重分类**: `partial` → `target_pass+minor_regress`
  - task 2843: target 4/4 OK, all 80/86 (93%), 6 broken — 修对了 target bug (logic-inversion, off-by-one) 但引入 6 个副作用
  - task 2848: target 2/2 OK, all 50/54 (93%), 4 broken — 修对了 target bug (timing-error, type-error) 但引入 4 个副作用
- **这两个任务是 qutebrowser 项目中最高 SFT 校正价值的候选**：只需教模型在提交前跑完整测试套件来捕获副作用
- **UID 248 无 target_pass+minor_regress** — 回归验证通过，原有 target_fail_only 和 target+regress 分类不受影响
- **compare 模式 (30 vs 228)** — target_pass+minor_regress 在两个 UID 各检出 1 个，正确显示在失败分布表中

**提出不足**: `target_pass+minor_regress` 目前只区分了 "target 全过 + 非 target 有少量失败" 的情况。但未分析这些 minor regressions 的具体模式——是否集中在某些 test fixtures 或特定模块？如果 2843 和 2848 的 broken tests 有共同模式（如都在 `tests/unit/config/` 下），这可能暗示 qutebrowser 项目的 config 模块有隐式依赖。分析 broken test names 可以为 SFT 提供更精确的 "避免副作用" 指导。

### 迭代 27 — 2026-03-17

**分析对象**: UID=162, SWE-SYNTH, --all --recent 30 + UID=228, UID=242 交叉验证

**本次改进**:
1. **PATCH-TARGET ALIGNMENT 分析 (#40 新增)** — 在 FAILURE ANALYSIS 的 PATCHED FAILURE CATEGORIES 之后新增段落。利用 `target_tests` 和 `patch_files` 数据，计算每个 patched loss 的 patch-target 对齐度：
   - `match`: 模块名匹配（修了正确文件但逻辑错误）→ 需要 fix quality 训练
   - `related`: 同一子系统/目录但不同文件（正确区域但错误文件）→ 需要更精确定位
   - `mismatch`: 完全不同的模块（修了错误位置）→ 需要 bug localization 训练
2. **MISMATCH DETAIL 子段落** — 显示 top-5 mismatch 任务的具体 patch 模块 vs target 测试模块对比
3. **SFT 含义自动推断** — >=30% mismatch 时推荐 localization 训练，>=50% match 时推荐 fix quality 训练
4. **Near-win 表新增 `align` 列** — 每个 near-win 任务显示其 patch-target 对齐度
5. **`_extract_module_name()` 函数** — 从文件路径提取归一化模块名，处理 test_ 前缀/后缀、多种扩展名
6. **`_extract_parent_dir()` 函数** — 提取完整父目录路径（剥离 src/test/lib 等公共根），用于精确的目录级匹配
7. **目录匹配精度改进** — 初版使用 depth-2 目录匹配导致 element-hq 的 `components/views` 过于宽泛（DeviceDetails vs Notifications 被误判为 related）。改为要求 >=3 段共享路径或 parent/child 关系

**关键发现**:

| UID | match | related | mismatch | SFT 建议 |
|-----|-------|---------|----------|---------|
| 162 | 36% | 18% | 45% | localization 训练 |
| 242 | 33% | 8% | 58% | localization 训练 |
| 228 | 50% | 0% | 50% | localization 训练 |

- **跨 UID 一致发现: 45-58% mismatch** — 近半数 patched losses 修了完全错误的文件。这是最大的 SFT 改进机会
- **UID 228 (NodeBB) 无 related** — NodeBB 项目结构扁平，不存在 "接近但不完全正确" 的情况，要么修对文件要么完全错
- **UID 162 的 near-wins**: 10 个中 3 个 match + 2 个 related + 5 个 mismatch — 即使在 "接近胜利" 的任务中，一半也修了错误文件
- **UID 228 target-close near-wins (2951, 2960) 显示 mismatch** — 这些任务通过了 target test 但 patch 是在错误模块中。暗示 target test 评判标准可能不依赖 patch 位置（可能是功能测试而非 unit test）

**提出不足**: PATCH-TARGET ALIGNMENT 仅在 single-UID 报告中显示。在 `--compare` 多 UID 模式中，应该有跨 miner 的 alignment 汇总表，展示不同 miner 在同一 task 上的对齐度差异——如果 miner A 对 task X 是 match 但 miner B 是 mismatch，说明 miner A 的 localization 能力更强。这种跨 miner 对齐度对比可以精确衡量不同模型的定位能力差距。

### 迭代 28 — 2026-03-17

**分析对象**: --compare 60,162,242 --all --recent 30 (3-way) + --compare 55,162,242 + UID=60 单独分析

**本次改进**:
1. **--compare 模式的 PATCH-TARGET ALIGNMENT COMPARISON (#41)** — 在 FAILURE MODE COMPARISON 之后、HEAD-TO-HEAD 之前新增段落。包含：
   - Per-UID alignment 分布表（match/related/mismatch 百分比并列对比）
   - ALIGNMENT DIVERGENCE 子段落：检测同一 task 上不同 miner 的 alignment 差异
   - 每个 divergent task 显示 "UID_X=match vs UID_Y=mismatch"
   - 统计哪个 UID 在 divergent tasks 中 localization 更好
   - Consistent alignment 计数（所有 miner 同一任务上的 alignment 相同）
2. **目录匹配精度修复** — 从 depth-2 改为 `_extract_parent_dir()` 全路径匹配，要求 ≥3 段共享路径前缀或 parent/child 关系。修复了 element-hq 中 `components/views` 过于宽泛的误分类

**关键发现 (3-way: UID 60 vs 162 vs 242)**:

| UID | match | related | mismatch | 定位能力排名 |
|-----|-------|---------|----------|------------|
| 60  | **57%** | 14% | 29% | 最好 |
| 162 | 36% | 18% | 45% | 中等 |
| 242 | 33% | 8% | **58%** | 最差 |

- **UID 60 定位能力最强**: 57% match（修了正确文件），仅 29% mismatch。SFT 建议自动切换为 "fix quality" 训练（而非 "localization" 训练）
- **UID 242 定位能力最弱**: 58% mismatch（修了错误文件），仅 33% match
- **跨 miner alignment 一致性**: 6/6 shared patched-loss 任务的 alignment 完全一致——说明 alignment 差异来自不同任务分布，而非同一任务上的能力差异。同一个困难任务对所有 miner 都同样难以定位
- **UID 55 (仅 9 tasks) 83% mismatch** — 最小样本但最高 mismatch 率，可能是因为全部在 element-hq 且只有 6 个 losses

**UID 60 独特发现**:
- **100% explore_only 是 deep_stuck**（8/8）— 其他 UID 通常有 wide_scatter 和 identified_no_action 混合。UID 60 的模型不是找不到文件（wide_scatter），而是找到了但理解不了（deep_stuck）
- **47% losses 检出循环** — 显著高于其他 UID（通常 <10%）
- **63% 的 losses 没有 patch** — 最高的 no-patch 率，模型在 TypeScript 上不敢编辑

**提出不足**: PATCH-TARGET ALIGNMENT 中 `mismatch` 任务目前只显示模块名不匹配。但同一个 `mismatch` 内可能有不同的 "错误距离"：修了同一目录下的邻近文件（如 `useOwnDevices` vs `DeviceDetails`）比修了完全不同目录的文件（如 `helpers` vs `user`）更接近正确。当前的 related 要求 ≥3 段共享路径前缀，可能对 shallow 项目结构过于严格。应该根据目录深度自适应：浅层项目（如 NodeBB 的 `src/` 直接下）用 ≥2 段匹配，深层项目（如 element-hq 的 5-6 级嵌套）用 ≥3 段匹配。

### 迭代 29 — 2026-03-17

**分析对象**: UID=228 (NodeBB) 验证 + 全 7 UID 交叉验证

**本次改进**:
1. **目录匹配深度自适应 (#42)** — 在 `_compute_patch_target_alignment()` 的目录匹配逻辑中新增浅层项目结构处理。当 test 目录为空（如 `test/user.js` → dir=""）时，回退到检查 test 模块名是否出现在 patch 目录路径的某个段中。例如：
   - `src/user/data.js`（dir segments=`['user']`）+ `test/user.js`（test mod=`user`）→ `user` in `['user']` → `related`
   - `src/flags.js`（dir segments=`[]`）+ `test/i18n.js`（test mod=`i18n`）→ 无匹配 → `mismatch`
2. **反向检查** — 也处理 patch 目录为空但 test 目录有深度的对称情况

**关键发现 (修复前 vs 修复后)**:

UID 228 (NodeBB):
- 修复前: match=50%, related=0%, **mismatch=50%**
- 修复后: match=50%, **related=39%**, **mismatch=11%**
- 7 个原来的 mismatch 正确升级为 related（如 `src/user/data.js` vs `test/user.js`）
- 仅剩 2 个真正的 mismatch（`flags` vs `i18n`, `messaging+middleware` vs `i18n`）

**全 7 UID 汇总 (修复后)**:

| UID | match | related | mismatch | 定位能力 |
|-----|-------|---------|----------|---------|
| **30** | **92%** | 8% | **0%** | 最好 |
| 60 | 57% | 14% | 29% | 良好 |
| 228 | 50% | 39% | 11% | 良好 |
| 162 | 36% | 18% | 45% | 中等 |
| 242 | 33% | 17% | 50% | 差 |
| 248 | 27% | 0% | 73% | 最差 |
| 55 | 0% | 17% | 83% | 极差(N=6) |

- **UID 30 的 92% match 0% mismatch 极为突出** — 该模型几乎总是找到正确文件，失败纯粹是逻辑错误
- **UID 248 的 73% mismatch** — 该模型在 3/4 的 patched losses 中修了完全错误的文件
- **修复对 UID 228 影响最大**: 从 50% mismatch → 11% mismatch，因为 NodeBB 的浅层 `test/*.js` 结构被正确处理
- 其他 UID 影响极小或无变化（element-hq 是深层结构，不受影响）

**提出不足**: near-win 表中的 `align` 列对没有 `target_tests` 数据的任务显示 `-`。但部分旧数据确实缺少 `target_tests` 字段（如 UID 248 的早期任务）。当 `target_tests` 为空但 `target_result` 不为空时（如 `0/4`），可以尝试从 `missing_tests` 字段中推断 target test 名称来补充 alignment 计算——因为 `missing_tests` 包含了所有失败的测试，其中可能就有 target tests。

### 迭代 30 — 2026-03-17

**分析对象**: 环境源码审查 (`affinetes/environments/SWE-SYNTH/env.py`, `breaker/`) + UID=30, UID=162 验证

**本次改进**:
1. **环境评分源码审查（目标 #7: 环境相关代码提升点）** — 深度阅读 `env.py` 和 `breaker/` 模块，确认了以下关键机制：
   - **评分逻辑**: `if all_passed: return 1.0, else: return 0.0` (行 576)
   - `all_required = fail_to_pass ∪ pass_to_pass`（不仅是 target tests）
   - `target_passed` 仅为 informational，不影响评分
   - `missing_tests = all_required - passed_tests`（未通过测试列表）
   - 二元评分，无部分分数
   - 任务生成时 `max_failed_ratio: 0.2`（bug 最多让 20% 测试失败）
   - `target_tests` = 注入 bug 后实际失败的测试（非随机抽样）

2. **SCORING ANOMALIES 描述更新** — 从 "scoring may use all_passed" → "env scores on ALL tests passing, not target tests"（确认性语言替代猜测性语言）

3. **新增 OPT-9: SCORING GAP** — 检测 `target_pass+minor_regress` 任务并标注环境评分机制
4. **新增 OPT-10: LOCALIZATION GAP** — 当 >=40% patched losses 是 mismatch 时，建议改进 problem_statement 的定位信息
5. **OPT-4 更新** — 增加 "env scores on ALL tests" 注释，更新建议为 "consider partial credit scoring"

**关键发现 (环境设计层面)**:

1. **评分基于 all_passed 而非 target_passed** — 这是所有 scoring anomalies 的根因：
   - task 2225: WIN (all=2984/2984) 尽管 target=0/46 — 合法！all tests 全通过
   - task 2936: WIN (all=174/174) 尽管 target=1/4 — 同理
   - near-wins 失分原因: 1-2 个非 target 测试回归，不是 target test 问题

2. **target_tests 的实际来源**: `injection.failed_tests`（bug 注入后实际失败的测试），不是随机抽样。但 breaker 中有 `_select_target_tests()` 随机选择 ≤5 个测试——这是用于验证 bug 注入有效性的，最终 target_tests 来自实际执行结果

3. **max_failed_ratio: 0.2** — bug 注入不能让超过 20% 的测试失败。这意味着每个 task 最多有 20% 的测试是 target_tests 相关的失败。对于大测试套件（如 NodeBB 的 2984 个），最多 ~600 个测试可以因 bug 失败

4. **验证流程**: `base_commit → gold_patch → bug_patch → fix_patch → run_tests`。Agent 的 fix_patch 必须同时修复 bug 且不破坏任何现有测试

**环境优化建议总结**:
- **OPT-9**: `target_pass+minor_regress` 任务在当前二元评分下被浪费（score=0.0），但它们是最高 SFT 价值的候选。建议为这些任务引入部分分数或标记为 "near-correct"
- **OPT-10**: 40-73% 的 patched losses 修了完全错误的文件。problem_statement 可能不提供足够的定位信息。建议在 task 生成时纳入文件路径提示
- **near-win 的核心矛盾**: agent 需要同时做对两件事：(1) 修对 target bug, (2) 不破坏任何其他测试。当前评分不区分 "修对了 bug 但引入副作用" vs "修了完全错误的东西"

**提出不足**: 环境源码审查揭示了 `breaker/orchestrator.py` 中的 `min_failed_tests: 1, max_failed_ratio: 0.2` 约束。这意味着对于大测试套件的项目（如 NodeBB/2984 tests），bug 可以影响最多 ~597 个测试，但对于小测试套件项目（如某些只有 5 个测试的），bug 只能影响 1 个测试。这个约束是否会导致不同项目的任务难度系统性不同？小测试套件 = 每个测试权重更大 = 更难在不破坏其他测试的情况下修复。应该分析 all_total（测试套件大小）与 win rate 的相关性。

### 迭代 31 — 2026-03-17

**分析对象**: 跨 6 UID 聚合 (30,60,162,228,242,248) + UID=162, UID=228, UID=30 单独验证

**本次改进**:
1. **TEST SUITE SIZE vs WIN RATE 分析 (#45 新增)** — 在 ENVIRONMENT OPTIMIZATION SUGGESTIONS 段落内新增 TEST SUITE SIZE 子段落。按测试套件大小分桶（tiny 1-10, small 11-50, medium 51-200, large 201+），展示每个桶的 win rate、near-win rate、平均测试数。并比较 wins vs losses 的平均测试套件大小

**关键发现 (跨 6 UID 聚合, N=120)**:

| 测试套件大小 | 任务数 | Win% | NearWin% | AvgTests |
|------------|-------|------|----------|----------|
| tiny(1-10) | 21 | **66.7%** | 0.0% | 4 |
| small(11-50) | 30 | 30.0% | 76.2% | 28 |
| medium(51-200) | 53 | 47.2% | 82.1% | 131 |
| large(201+) | 16 | **18.8%** | 38.5% | 849 |

- **Wins avg=148 tests vs Losses avg=201 tests** — losses 的测试套件 1.4x 更大
- **tiny 套件 66.7% win rate** — 每个测试权重大但 bug 通常也只影响那几个测试，修复直接明确
- **large 套件 18.8% win rate** — 最差。NodeBB (2984 tests) 的 catastrophic regression 问题使得大套件极难完美修复
- **medium 套件 47.2% > small 30.0%** — 反直觉！可能因为 element-hq 的测试数在 medium 范围且某些 UID 对 element-hq 适应良好
- **near-win 模式**: tiny 0%（要么全过要么明确失败），small/medium 76-82%（大部分失败都很接近），large 38.5%（失败往往是 catastrophic）

**Per-UID 验证**:
- UID 162: tiny(3 tasks) 100% win, medium(13) 46% win — 符合趋势
- UID 228: large(10) 只有 20% win + 12.5% near-win — large 套件 + NodeBB 耦合 = 最难
- UID 30: wins avg=256 vs losses avg=139 — **反趋势！** UID 30 在大套件上反而更强，说明测试套件大小与 win rate 的关系是 miner × project 交互效应，不是简单的单一因素

**提出不足**: TEST SUITE SIZE 分析目前只在 single-UID 报告中。在 `--compare` 模式中应该展示跨 miner 的 suite size 效应差异——如果 miner A 在 large 套件上 40% win 而 miner B 只有 10%，说明 miner A 有更强的回归避免能力。此外，当前分桶边界是硬编码的（1-10, 11-50 等），应该根据数据分布自适应选择分位点。

### 迭代 32 — 2026-03-17

**分析对象**: UID=248, SWE-SYNTH, --all --recent 30 + 跨 6 UID test-free wins 系统性验证

**本次改进**:
1. **TOP FINDINGS 段落实现（目标 #6）** — 在 EXECUTIVE SUMMARY 之后自动生成 3-5 个最高价值洞察。检测逻辑：
   - **⚠ REWARD GAMING**: wins 中 <50% target tests passed → 环境允许不修 target bug 就赢
   - **LOCALIZATION** (≥30% mismatch) 或 **FIX QUALITY** (≥50% match) → 定位能力 vs 修复质量
   - **NEAR-WINS** (≥30% losses) → 接近胜利的比例
   - **BOTTLENECK** (≥40% 单一失败模式) → 主导性瓶颈
   - **PATTERN MATCHING** (≥90% test-free wins) → 不验证就提交
   - **SCORING GAP** (target_pass+minor_regress) → 修对 bug 但被判 0 分
2. **早期计算 near_wins 和 ztw** — 避免 UnboundLocalError，移至 generate_report 开头

**关键发现 (UID 248, recent 30)**:

TOP FINDINGS 输出：
```
1. LOCALIZATION: 8/11 (72%) patched losses modify the wrong file
2. BOTTLENECK: target_fail_only accounts for 10/23 (43%) of losses
3. PATTERN MATCHING: 7/7 wins (100%) use zero test commands
```

- **UID 248 定位能力最差 (73% mismatch)** — 持续确认
- **LATE COLLAPSE 检出**: batch 5 (0% win) vs batch 2-4 (33%)
- **exception-swallow → explore_only: 3/3 (100%) CAPABILITY GAP** — 持续确认
- **explore ratio gap: 0.54 vs 0.84** — 30% gap，losses 严重 over-explore

**跨 UID 系统性发现**:
| UID | Test-free wins |
|-----|---------------|
| 30 | 8/8 (100%) |
| 60 | 9/11 (82%) |
| 162 | 9/11 (82%) |
| 228 | 5/5 (100%) |
| 242 | 11/11 (100%) |
| 248 | 7/7 (100%) |

**所有 6 个 UID 的 82-100% wins 从不跑测试。** 这不是个别模型行为，而是环境设计的系统性后果——当前环境中跑测试不提供任何胜率优势（甚至可能浪费 turn 预算），模型已通过 RL 学会跳过测试。这是一种 reward gaming/optimization：agent 正确地推断出 "验证不如直接提交" 是最优策略。

**环境改进建议**：
- 引入 "test-before-submit" 的 reward shaping（如果 agent 跑了测试且测试通过，给予 bonus score）
- 或者在 max_iterations 之外给测试一个独立的 budget（不占用编辑 turn）

**提出不足**: TOP FINDINGS 中的 LOCALIZATION/FIX QUALITY 判断只基于 patched losses。但 explore_only 任务（从未提交 patch 的）也有定位失败的信号——wide_scatter 和 deep_stuck 反映了不同的定位困难。当前 TOP FINDINGS 不考虑 explore_only 的定位信号，可能低估了定位问题的严重程度。一个更全面的 "定位能力评分" 应该综合 patch-target alignment + explore_only subtype 分布。