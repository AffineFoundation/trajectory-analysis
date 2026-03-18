LiveWeb 轨迹分析引擎迭代

启动方式：/loop 10m LiveWeb 轨迹分析引擎迭代，读 sessions/liveweb.md 比较脚本内容与目标差距 执行当前任务，提升脚本质量

理解意图、设计方案、写代码、跑测试

核心思想：迭代一个分析liveweb 轨迹分析器，要求从多个角度 例如但是不限于 1. 是否overfitting 2. winning/loss 的轨迹规律/pattern 3. 在哪些网站/特点的任务下表现的更好 4. 提出建议优化环境

1. 独立创造一个脚本来分析LiveWeb 环境的轨迹
2. 支持 任意uid，在当前1. active sampling list 和 2. 所有历史数据的查询 3. 以及最近N 条的查询
3. 数据获取的方式请看 scripts/FETCH_TRAJECTORIES.md 务必遵守

纬度分析
1. 统计不同网站获得分数值
2. 因为轨迹包含多个网站的子任务，要把自己每个子任务剥离出来独立分析 得分 和 没得分问题
3. 是否有overfitting 或者 memorization 的pattern 自行 搜索决定 如何判断这点
4. 需要给一个总体的描述
5. 最开始给我 top findings 要求根据我分析报告背后的意图给出最优价值的 top findings
7. 环境相关代码的提升点 理解环境背后设计意图 要求多角度充分论证，不得给出不扎实的意见

每次迭代工作流
0. https://github.com/AffineFoundation/liveweb-arena.git（所有代码都会随时更新）确保所有分析都基于最新代码
1. 理解目标 + 问题区问题 并思考背后意图后 深度思考，提出待办计划 记录在待办工作去
2. 根据待办的工作深度思考完成工作
3. 脚本更新完后 完整的跑一次脚本 针对当前排名最高的miner 的采样列表跑一次分析，并且针对输出每个token 阅读，提出至少1条不足 写入本文件的待办区。不得不写入，或者说已经很好。要用对抗性思维去提出需要解决问题。并把问题记录在问题区
4. 根据想法 更新 markdown, 要求保留每次迭代记录
5. 根据 sft 提出可能得分的策略 以及对应数据合成的策略
6. 要求每次的报告需要精炼但是一定包含重点，自动审查 删掉冗余&无价值信息
7. 最开始给我 top findings 要求根据我分析报告背后的意图给出最优价值的 top findings
8. 重点寻找下是否由于环境设计，基建设等问题导致轨迹失败/甚至评分有偏差的问题，重点分析，反复论证 给出可疑的轨迹&原因

待办工作区

### 已完成迭代摘要 (迭代 1-6, 2026-03-14)

**脚本功能清单** (`scripts/analyze_liveweb.py`):
- 8 个报告 Section + 轨迹可视化 + 环境优化建议 + SFT 策略
- 支持 `--uid`, `--compare`, `--env`, `--verbose`, `--output`, `--all`, `--recent N`, `--inspect`
- Per-website DNC 根因 + top goto URL | view_more counterfactual ROI | Q4 恢复验证
- URL pattern quality (perf vs zero) | 导航效率评分 | wrong answer 分类
- 跨 UID 对比报告含 3-site 行为深钻 + SFT insight
- 报告精简：679→648 行，Section 6 从 180→142 行

**关键数据（UID 228, top miner, 300 tasks）**:
- Avg 0.245 | Perfect 4% | Zero 47% | 89% 多站点
- 67% 多站点任务漏访 ≥1 站点 | 52% 从未访问第2站点 | 54% URL 循环
- 3-site 0% perfect | stooq 67% goto + DNC 84% never-visited | taostats view_more 93%
- DD 40% 全部 0% accuracy | wrong_answer 65% completely_wrong
- 63 partial tasks 有正确导航但提取错误（SFT 最优素材）

**SFT 策略优先级**:
1. [最大杠杆 +0.173] 多站点导航修复 126 zeros
2. [最高per-task ROI] extraction 修复 63 partials (0.451→1.0)
3. [环境级] DD 独立追踪 + 3-site 步数缩放 + view_more 限制

**跨 UID 对比 (228 vs 45 vs 153)**:
- spread 仅 0.030，核心问题是环境级别 | 排名反转：228 在 3-site 最差
- UID 45 的 non-zero 3-site 轨迹(n=49)是最佳 SFT 正例

### 迭代 7-8 (2026-03-14) — 问题类型 + wrong answer 细分 ✅
- 12 种问题类型分类，覆盖 88%。最弱: change_% 14%, ranking 15%
- completely_wrong 4 子类: wrong_entity/metric 42%, verbose_wrong 12%, gave_up 8%, format_mismatch 3%

### 迭代 17-18 (2026-03-17) — Winning/Losing 轨迹规律 + Coverage 校正

**迭代 17 变更**:
- [x] 新增 Section 6b: WINNING vs LOSING TRAJECTORY PATTERNS (A. fingerprint, B. tipping point, C. per-website)
- [x] OPT 代码引用 → 功能描述 | OPT-3b 重写 (view_more ≠ trap on taostats)

**迭代 18 变更**:
- [x] 修复 coverage 混淆: scored=0.73 vs zero=0.90 是假象
  - 原因: 9 个零导航高分任务 (coverage=0) 拉低了 scored 均值
  - Nav-only 校正后: scored=0.98 vs zero=0.96 (delta=+0.02, 混淆解除)
- [x] 删除 Section 6 "Navigation efficiency by outcome" (与 6b fingerprint 冗余)
- [x] 报告 777→771 行

**关键发现**:
- **11-15 步死亡区**: 6-10 步 scored 69% → 11-15 步 scored 11% (断崖式下降)
- **Click 是正信号**: scored +0.77 clicks vs zero 0.06
- **Coverage 无差异** (nav-only: scored 0.98 vs zero 0.96) — 差距在提取不在导航
- **taostats view_more = 成功** 推翻了 OPT-3b 的全局限制建议

**迭代 19 变更**:
- [x] Tipping point 增加 "0 steps" 桶: 1 task, score 0.50, 100% scored — 纯世界知识得分
  - 确认: 0-step tasks 之前被完全排除，现在可见
- [x] ALL TASKS table 移至 --verbose: 默认报告 771→678 行 (-12%)
- [x] generate_report() 增加 verbose 参数

**对抗性不足 (迭代 20 待办)**:
- 0-step 桶仅显示 1 task — 其他零导航任务 (view_more only, steps>0) 散布在 1-5/6-10 桶中。Tipping point 分析无法区分"用了 view_more 但没 goto"和"正常导航"。考虑增加 "goto=0" 行作为独立视角。

### 迭代 16 (2026-03-17) — MVD 估算 + 环境代码级优化 + Session 精简

**变更**:
- [x] DATA SYNTHESIS PIPELINE 增加 MVD (Minimum Viable Dataset) 估算表
  - Per-website: stooq +35, taostats +40, coingecko +33 → 共需 108 条合成轨迹
  - ~603 eval runs (at 18% success rate) 才能收集足够训练数据
  - Per-question-type gaps: comparison(+29), convert(+28), count(+28), ranking(+28)
- [x] Section 7 环境优化建议增加代码级引用 + evidence
  - OPT-3a: agent_protocol.py build_step_prompt() + plugin_hints for stooq URL patterns
  - OPT-3b: agent_loop.py cap consecutive view_more + inject extraction hint
  - OPT-4: env.py max_iterations scale with num_subtasks
  - OPT-5: 引用 root cause 数据 (127/226 = 56%)
  - OPT-8 [NEW]: 世界知识绕过 — eval.py 应加 navigation_required 或 PAGE_ONLY GT
- [x] Session 文件精简: 迭代 7-14 压缩为摘要行 (180→~130行)
- [x] OPT-4 f-string 格式修复

**对抗性不足 (迭代 17 待办)**:
- OPT 建议中引用的代码路径 (agent_protocol.py, agent_loop.py, env.py) 是基于迭代 13 的代码阅读，未直接验证当前代码行号。若 liveweb-arena 再次更新，这些引用可能过时。应在建议中使用功能描述而非硬编码文件名。

### 迭代 15 (2026-03-17) — Forensics 证据链 + 数据合成 Pipeline

**变更**:
- [x] Forensics UNVISITED_CORRECT 增加 EVIDENCE 块: 展示每个未访问站点的 Q/Expected/Actual + 判定
  - EXACT MATCH: 未浏览但精确匹配 → 世界知识或记忆化
  - source unclear: 未浏览但近似匹配 → 来源不明
- [x] 新增 DATA SYNTHESIS PIPELINE (Section 8 末尾): 4 条具体合成策略
  - A. Positive examples (eval.py --export-sft)
  - B. Trajectory repair (keep nav prefix, fix extraction)
  - C. Anti-pattern DPO pairs (view_more loops, stuck-on-1st-site)
  - D. Per-website synthesis recipe (gap detection: positive examples 不足时建议生成)
- [x] Section 5 root cause 去重: 改为引用 pre-computed 变量，删除冗余 Interpretation 段

**关键 Forensic 发现**:
- **3 个 EXACT MATCH** (未浏览却精确匹配):
  - Task 9400237: NASDAQ 100 = `24533.58` 精确匹配 — 高度变动值
  - Task 55298476: `τemplar` 精确匹配 — Bittensor subnet 名
  - Task 66960494: `grail` 精确匹配 — subnet ranking
- **结论**: 这些值实时变化，LLM 训练数据不可能包含。两种可能:
  1. GT 使用缓存/快照值，恰好与 LLM 的"猜测"吻合 (概率极低)
  2. agent 通过 stop action 提交答案时，评估器接受了 LLM 世界知识而非要求浏览器获取的数据
  3. 存在未检测的数据通道 (e.g., system prompt hints, view_more 返回内容)

**对抗性不足 (迭代 16 待办)**:
- DATA SYNTHESIS PIPELINE 只标注了正例数量，未估算最少需要多少条合成数据才有训练意义。应加 minimum viable dataset 估计。

### 迭代 12-14 (2026-03-17) — 重写 + 记忆化 + TOP FINDINGS + Forensics
- 迭代12: 从头重写脚本 (1837行), 修复 action parsing (tool_calls 格式)
- 迭代13: Section 9 记忆化/overfitting + 导航感知错误归因 + KNOWN_SITES 更新
- 迭代14: TOP FINDINGS + Section 10 Forensics (4 flag types, 去重) + root-cause weighted SFT
- 环境更新: agent_protocol.py (FunctionCallingProtocol) + OpenLibrary + --export-sft

### 迭代 9-11 (2026-03-14) — 细分 + 样例 + 全量审查 ✅
- wrong answer 样例展示, SFT Strategy 整合, 全量审查通过

问题区

### 累积关键问题
1. Agent 导航策略失败 — 困在第一个站点，从不前往第二/三个站点
2. stooq.com "步数黑洞"：循环 goto `stooq.com/q/` (不带参数) 514 次
3. taostats.io view_more 陷阱：zero task never-left 68%，max streak 22
4. DD 问题(40%) 全部失败 — GT 收集机制与导航失败混淆
5. wrong_answer 65% completely_wrong — 不是精度问题而是字段提取错误
6. 3-site 0% perfect，50%+ 仅访问 1 站点，96% 耗尽步数
7. **[NEW] 记忆化/世界知识泄漏**: 10.3% tasks 零导航得分 (avg 0.463 vs nav tasks 0.140)，task 9054548 零交互 score 0.50
8. **[NEW] wrong_entity/metric 是 catch-all**: 占 completely_wrong 的 84.5%，未区分「到了对的页面提取错字段」vs「从未到达页面」vs「步数耗尽」— 迭代 13 已加导航感知归因
9. **[CRITICAL] 评估接受世界知识答案**: 3 tasks EXACT MATCH 未浏览得分 (NASDAQ=24533.58, τemplar, grail)。评估器未强制要求 agent 必须通过浏览器获取数据，stop action 提交的 LLM 猜测可直接得分。这是环境设计漏洞，会奖励记忆化而非浏览能力。
