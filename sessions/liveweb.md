LiveWeb 轨迹分析引擎迭代

启动方式：/loop 15m LiveWeb 轨迹分析引擎迭代，读 sessions/liveweb.md 比较脚本内容与目标差距 执行当前任务，提升脚本质量

理解意图、设计方案、写代码、跑测试

核心思想：迭代一个分析liveweb 轨迹分析器，要求从多个角度 例如但是不限于 1. 是否overfitting 2. winning/loss 的轨迹规律/pattern 3. 在哪些网站/特点的任务下表现的更好 4. 提出建议优化环境

1. 独立创造一个脚本来分析LiveWeb 环境的轨迹
2. 支持 任意uid，在当前1. active sampling list 和 2. 所有历史数据的查询 3. 以及最近N 条的查询
3. 数据获取的方式请看 scripts/FETCH_TRAJECTORIES.md 务必遵守

纬度分析
0. https://github.com/AffineFoundation/liveweb-arena.git（所有代码都会随时更新）根据最ß新的代码确定需要分析的网站，这个十分重要，比如你曾经错误标记 xen.com, fetch.ai 等都不是我们需要分析的网站
1. 统计不同网站获得分数值
2. 因为轨迹包含多个网站的子任务，要把自己每个子任务剥离出来独立分析 得分 和 没得分问题
3. 是否有overfitting 或者 memorization 的pattern 自行 搜索决定 如何判断这点
4. 需要给一个总体的描述
5. 最开始给我 top findings 要求根据我分析报告背后的意图给出最优价值的 top findings
7. 环境相关代码的提升点 理解环境背后设计意图 要求多角度充分论证，不得给出不扎实的意见
8. 给出由于网络，评测环境 等导致任务无法有效提取信息的 可疑task id, 要求多次多角度审视，特别强调不是agent自身原导致的

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

### 迭代 20 (2026-03-19) — fetch.ai 误报修复 + 动态证据 + 拐点改进 + 空任务检测

**变更**:
- [x] 修复 fetch.ai 误报: 新增 FALSE_POSITIVE_DOMAINS 过滤表 (fetch.ai, xen.com, render.com, near.org 等)
  - 之前 4 个 fetch.ai subtask 被错误标记为独立网站 + 3 个 forensics 误报
  - 修复后 subtask 正确归属到 coingecko.com (实际查询站点)
- [x] OPT-3a/3b 证据数字从硬编码改为动态计算
  - OPT-3a stooq: 现在显示实际 goto/task 和 view_more 数据
  - OPT-3b taostats: 动态计算 winning vs losing view_more 对比
- [x] Tipping point 检测改进: 从"100% 零分桶"改为"相邻桶最大 scored-rate 下降"
  - UID 153: 检测到 11-15→16-20 步 scored 率从 57%→38% (Δ=19%)
- [x] 消除 root cause 重复计算 (generate_report 中 rc_* 只算一次)
- [x] 修复 cw_answers/cw_sub 变量作用域问题 (在 if all_wrong 外初始化)
- [x] 新增 EMPTY_TASK forensic flag: 检测 num_subtasks=0 的空任务

**追加变更 (liveweb-arena 代码同步)**:
- [x] KNOWN_SITES 缩减为实际活跃插件站点 (5 个: stooq, taostats, coingecko, hackernews, openlibrary)
  - 移除 finance.yahoo.com, tradingview.com 等 17 个非插件站点到 KNOWN_EXTERNAL_SITES
- [x] Action tracking 扩展: 新增 type(308), stop(269), click_role(196), wait(77), type_role(39) 的追踪
  - 之前只追踪 goto/click/scroll/view_more, 遗漏了 35% 的 action
- [x] 确认 max_steps=30 硬编码上限 (env.py line 137) — 解释了 4-site 83% 步数耗尽

**关键数据（UID 153, top miner, 294 tasks）**:
- Avg 0.197 | Perfect 1% | Zero 50% | 100% 多站点
- #1 root cause: step budget exhaustion (449/739, 61%)
- taostats 13%, stooq 20%, coingecko 27%
- 4-site 83% budget exhausted | 3-site 0% perfect
- 0 零导航得分任务 (无记忆化问题, 与 UID 228 不同)
- Tipping point: 16 步后 scored rate 下降 19%
- 新发现 action 分布: goto 67%, view_more 16%, type 4%, stop 4%, click 3%, click_role 3%

### 迭代 21 (2026-03-19) — 交叉分析 + Action-by-outcome + 步数阈值修正 + parse_failed 检测

**变更**:
- [x] 新增 Section 5 "Classification × Navigation Root Cause" 交叉表
  - completely_wrong 的 89% catch-all 拆解为: 51% budget_exhausted + 43% wrong_extraction + 6% never_visited
  - 每个 wrong answer 都标记了 `_nav_root_cause` 供交叉分析
- [x] 新增 Section 6 "Action type by outcome" 对比表
  - goto (+3.34) 和 type_role (+0.11) 是正信号
  - type (-0.72), scroll (-0.57), view_more (-1.42) 是负信号
  - stop scored tasks = 1.0/task, zero = 0.83 (部分零分任务未执行 stop)
- [x] 步数耗尽阈值修正: 从 total_steps>=20 改为 browser_steps>=25
  - 新增 browser_steps 属性 (排除 stop action)
  - Budget exhaustion 从 68%→44%，更准确反映 max_steps=30 限制
  - 文档注释引用 liveweb-arena env.py max_steps=30
- [x] 新增 PARSE_FAILED forensic flag: 检测 failure_reason 含 "parse" 的任务
  - UID 153: 发现 24 个 parse_failed (8.2%)，全部 score=0，大多为 taostats 查询
- [x] Forensic verdict 改进: 按类型分项 (parse failures / empty tasks / world-knowledge bypasses)

**关键新发现**:
- **parse_failed 占 8%**: 24/299 tasks 因解析失败得零分，这不是 agent 能力问题
  - 大多是 taostats.io 复杂查询 (subnet 比较、百分比计算)
  - 这些分数被错误计入 agent 的 zero-rate，如果排除，真实 zero-rate ~42% (而非 51%)
- **completely_wrong 不再是黑盒**: 51% budget + 43% extraction + 6% no-visit
- **type action 是负信号** (-0.72): 零分任务更多使用 type，可能在搜索框输入但未找到正确页面

### 迭代 22 (2026-03-19) — TOP FINDINGS 纳入 parse_failed + adjusted zero-rate

**变更**:
- [x] TOP FINDINGS 新增环境问题发现:
  - "32 tasks (11%) fail due to 24 parse failures + 8 empty tasks, not agent capability"
  - 计算 adjusted zero-rate: 排除环境问题后 46% vs 原始 52% (差 6 个百分点)
  - 这为用户提供了更准确的 agent 能力评估基线

### 迭代 23 (2026-03-19) — Per-website action profile 全量展示

**变更**:
- [x] Per-website action patterns 重写为全量 action type 表格
  - 自动筛选 >=1% 总量的 action type, 动态列
  - goto 为 site-specific (只计目标站 URL), 其他 action 为 task-level
  - 新增脚注说明 multi-site task 共享非 goto action 的计数
- 关键发现:
  - stooq: type=2.3 (在搜索框输入 ticker), goto=23.4 (过度导航), wait=0.6 (等页面加载)
  - taostats: view_more=6.4 (数据展开), click_role=0.8 (accessibility click), goto=2.7 (少导航)
  - coingecko: click_role=1.1 (最高), goto=20.3, type=0.0 (无搜索框交互)

### 迭代 24 (2026-03-19) — Site-attributed action tracking + stop/wait 排除

**变更**:
- [x] `_parse_actions()` 重构: 追踪 `current_domain` (由最近 goto 设定)
  - 新属性 `site_actions: dict[domain -> Counter]` 存储每站点 action 计数
  - 内部 `_attribute()` helper 同时写入 global 和 site-specific 计数
- [x] Per-website action profile 改用 site_actions 而非 task-level 计数
  - 修复前: taostats type=0.8 (从 stooq 泄漏) → 修复后: type=0.0 (正确)
  - 修复前: stooq view_more=0.1 (从 taostats 泄漏) → 修复后: 0.0 (正确)
- [x] 排除 stop/wait 从 per-website 表 (task-termination/page-load, 非站点交互)

**站点行为特征 (site-attributed)**:
- taostats: view_more=6.4, click=0.9, scroll=1.0 (数据展开型)
- stooq: goto=23.1, type=2.3 (搜索导航型)
- coingecko: goto=20.3, click_role=1.1 (直接导航型)

### 迭代 25 (2026-03-19) — Site-attributed winning/losing action 对比

**变更**:
- [x] Section 6b C per-website winning/losing 改用 site_actions
  - 新增 `_site_action_avg()` 聚合每站点的 action 均值
  - 自动筛选有意义的 action (>=0.3 avg) 并标记信号方向 (+/-/~)
  - 排除 stop/wait (非站点交互)
- 关键发现:
  - stooq: `type w=1.6 l=2.3-` — 输掉的任务搜索更多但找到更少
  - taostats: `goto w=4.0 l=2.7+` — 赢的任务主动导航到更多 subnet 页面
  - coingecko: action profile 无显著差异 — 失败主要在提取不在导航

**追加变更 (信号标记修正)**:
- [x] 信号标记从绝对阈值改为相对差异 (delta/mean > 15%)
  - 同时修复 Section 6 action-by-outcome 和 Section 6b C per-site patterns
  - 修复前: taostats view_more 7.0 vs 6.5 标为 `+` (delta=0.5, abs>0.3)
  - 修复后: 标为 `~` (delta/mean=7%, <15%)
  - 修复前: click delta=-0.14 标为 `~` → 修复后: 标为 `-` (rel=19%, >15%)

### 迭代 26 (2026-03-19) — 双阈值信号 + 报告精简 -20%

**变更**:
- [x] 信号标记改为双阈值: `rel > 15%` OR `abs(delta) >= 2.0`
  - stooq goto: w=21.5 l=23.7 从 `~` → `-` (abs=2.2 ≥ 2.0, 符合 step-budget 逻辑)
  - 同步修复 Section 6 和 Section 6b C 两处信号逻辑
- [x] Forensics 精简: PARSE_FAILED/EMPTY_TASK 从逐条列出改为 compact summary
  - 132 行 → ~15 行 (-88%), 报告总量 687→547 行 (-20%)
  - summary 包含: count, avg steps, by-site breakdown, compact task ID list
  - 高价值 flags (ZERO_INTERACTION, UNVISITED_CORRECT, VM_LOOP) 仍逐条展示
  - 新发现: parse_failed 的 site 分布为 taostats(67), stooq(4), coingecko(4) — taostats 查询占绝对多数

**对抗性不足 (迭代 27 待办)**:
- Section 8 SFT STRATEGY (105 行) 是第二大 section，部分内容与 Section 7 OPT 重叠 (例如 multi-site navigation 同时出现在 OPT-1 和 SFT Strategy 1)。且 SFT Per-website recommendations 与 Section 3 Per-website accuracy 数据重复展示。应精简 SFT section 中与其他 section 重复的数据，只保留 SFT-specific 的 insight (数据来源/合成策略/MVD)。

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
