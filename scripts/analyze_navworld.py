#!/usr/bin/env python3
"""
NAVWORLD (travel planning) trajectory analysis engine.

Provides single-miner deep analysis with 10-section report,
cross-miner comparison, temporal trend detection, deep dump,
and exports used by batch_analyze.py and detect_think_blocks.py.

Usage:
    python3 scripts/analyze_navworld.py --uid 42
    python3 scripts/analyze_navworld.py --uid 42 --all -o reports/navworld_uid42_all.txt
    python3 scripts/analyze_navworld.py --uid 42 --recent 30
    python3 scripts/analyze_navworld.py --uid 42 --inspect
    python3 scripts/analyze_navworld.py --uid 42 --json
    python3 scripts/analyze_navworld.py --uid 42 --deep 482196016
    python3 scripts/analyze_navworld.py --compare 78,142
    python3 scripts/analyze_navworld.py --multi-compare 57,78,142
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Constants ────────────────────────────────────────────────────────────────

PROBLEM_TYPES = (
    "intercity", "multiday", "hybrid", "single_poi",
    "food_tour", "business", "family_study",
)

ALL_TOOLS = (
    "poi_search", "around_search", "direction",
    "weather", "search_flights", "search_train_tickets",
)

TRANSPORT_TOOLS = {"search_flights", "search_train_tickets"}
REQUIRES_TRANSPORT = {"intercity", "hybrid", "business"}

REQUIRED_TOOLS_BY_TYPE = {
    "intercity": ["poi_search", "direction", "weather", "search_flights", "search_train_tickets"],
    "multiday": ["poi_search", "around_search", "direction", "weather"],
    "hybrid": ["poi_search", "around_search", "direction", "weather", "search_flights", "search_train_tickets"],
    "single_poi": ["poi_search", "around_search", "direction", "weather"],
    "food_tour": ["poi_search", "around_search", "direction", "weather"],
    "business": ["poi_search", "direction", "weather", "search_flights", "search_train_tickets"],
    "family_study": ["poi_search", "around_search", "direction", "weather"],
}

# Hard constraints defined in scorer
HARD_CONSTRAINTS = [
    "format_valid",
    "tool_info_used",
    "required_tools_called",
    "poi_names_verified",
    "transport_grounded",
    "tool_quality",
]

# LLM scoring dimensions
LLM_DIMENSIONS = [
    "practicality", "logic", "user_experience",
    "analysis_depth", "factual_grounding",
]

# Regex patterns for transport IDs
RE_FLIGHT = re.compile(r"(?<![A-Za-z])([A-Z]{2}\d{3,4}|\d[A-Z]\d{3,4})(?!\d)")
RE_TRAIN = re.compile(r"(?<![A-Z])([GDCZTK]\d{1,5})(?!\d)")

# Regex patterns for POI names (Chinese names from tool results and output)
# Multiple patterns to catch various formats
RE_POI_NAME = re.compile(r"(?:名称|(?<![a-z])name)[：:]\s*([^\n,，]{2,40})")
RE_POI_NAME_JSON = re.compile(r'"(?:name|名称|title|poi_name)"[：:]\s*"([^"]{2,60})"')
RE_POI_NAME_CN = re.compile(r'(?:推荐|酒店|餐厅|景点|地点|景区|公园|博物馆|商场|美食)[：:]\s*([^\n,，。]{2,30})')
RE_POI_NAME_BULLET = re.compile(r'[•\-\d][.、）)]\s*([\u4e00-\u9fff][\u4e00-\u9fff\w·（）\(\)]{2,25})')

# Think-block patterns
RE_THINK_CLOSED = re.compile(r"<think>(.*?)</think>", re.DOTALL)
RE_THINK_UNCLOSED = re.compile(r"<think>(.*)", re.DOTALL)

# Reasoning connectors for quality analysis
REASONING_CONNECTORS = [
    "因此", "所以", "考虑到", "根据", "由于", "综合",
    "建议", "推荐", "相比", "对比", "优先", "兼顾",
    "结合", "鉴于", "基于", "总结", "分析", "评估",
]

# Score tiers
SCORE_TIERS = {
    "good+": lambda s: s >= 30,
    "acceptable": lambda s: 15 <= s < 30,
    "poor": lambda s: s < 15,
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 40) -> str:
    """Render a bar chart segment."""
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _trunc(s: str, maxlen: int = 40) -> str:
    """Truncate string with ellipsis."""
    if not s:
        return ""
    s = str(s).replace("\n", " ")
    return s[:maxlen - 1] + "…" if len(s) > maxlen else s


def _stat_line(label: str, values: List[float], width: int = 14) -> str:
    """Format a statistics line: label avg med min max stdev."""
    if not values:
        return f"  {label:{width}s}  (no data)"
    avg = statistics.mean(values)
    med = statistics.median(values)
    mn = min(values)
    mx = max(values)
    std = statistics.stdev(values) if len(values) >= 2 else 0
    return f"  {label:{width}s} {len(values):5d} {avg:7.1f} {med:7.1f} {mn:7.1f} {mx:7.1f} {std:7.1f}"


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    """Compute Pearson correlation coefficient."""
    n = len(xs)
    if n < 5 or len(ys) != n:
        return None
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx < 1e-10 or sy < 1e-10:
        return None
    return cov / (sx * sy)


def _safe_mean(values: List[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _safe_median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def _safe_stdev(values: List[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def _pct(n: int, d: int) -> str:
    if d == 0:
        return "-"
    return f"{100 * n / d:.1f}%"


# ── TrajectoryData ──────────────────────────────────────────────────────────

class TrajectoryData:
    """Parsed trajectory wrapper for NAVWORLD environment."""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.task_id = int(raw.get("task_id", 0))
        self.score_norm = float(raw.get("score", 0) or 0)  # 0-1 normalized
        self.timestamp = raw.get("timestamp", 0) or 0
        if isinstance(self.timestamp, str):
            self.timestamp = int(self.timestamp) if self.timestamp else 0
        if self.timestamp and self.timestamp > 1e15:
            self.timestamp = self.timestamp / 1000  # ms -> s
        self.latency_ms = raw.get("latency_ms", 0) or 0

        extra = raw.get("extra", {}) or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}

        # Score (0-100 scale)
        self.score = float(extra.get("score_raw", self.score_norm * 100))
        if self.score <= 1 and self.score_norm > 0:
            self.score = self.score_norm * 100

        # Problem info
        problem = extra.get("problem", {}) or {}
        self.problem_type = problem.get("problem_type", "unknown")
        self.destination = problem.get("destination_city", problem.get("destination", ""))
        self.origin = problem.get("origin_city", problem.get("origin", ""))
        self.budget = problem.get("budget", 0) or 0
        self.days = problem.get("days", 1) or 1
        self.constraints = problem.get("constraints", []) or []
        self.user_query = problem.get("query", problem.get("user_query", ""))

        # Conversation
        self.conversation = extra.get("conversation", []) or []

        # Tool trace
        self.tool_trace = extra.get("tool_trace", []) or []

        # Score breakdown
        self.score_breakdown = extra.get("score_breakdown", {}) or {}
        self.hard_constraints = self.score_breakdown.get("hard_constraints", {}) or {}

        # Code / LLM scores (production uses noisy_code/noisy_llm bands)
        self.code_total = float(self.score_breakdown.get("noisy_code", 0) or 0)
        self.llm_total = float(self.score_breakdown.get("noisy_llm", 0) or 0)
        self.code_band = self.score_breakdown.get("code_band", "")
        self.llm_band = self.score_breakdown.get("llm_band", "")
        self.llm_available = self.score_breakdown.get("llm_available", True)

        # Fallback: check for detailed breakdown (offline evaluation)
        self.ic_score = float(self.score_breakdown.get("info_consistency", 0) or 0)
        self.comp_score = float(self.score_breakdown.get("completeness", 0) or 0)
        self.fab_penalty = float(self.score_breakdown.get("fabrication_penalty", 0) or 0)

        # LLM dimension scores (only in offline evaluation)
        self.llm_scores = {}
        for dim in LLM_DIMENSIONS:
            key = f"llm_{dim}"
            self.llm_scores[dim] = float(self.score_breakdown.get(key, 0) or 0)

        # Parse tool usage
        self._parse_tools()

        # Parse response
        self._parse_response()

        # Step rewards (if available)
        self.step_rewards = extra.get("step_rewards", []) or []

        # Derived
        self.hc_all_pass = all(
            v is None or v for v in self.hard_constraints.values()
        ) if self.hard_constraints else True

        self.tier = "good+" if self.score >= 30 else "acceptable" if self.score >= 15 else "poor"

    def _parse_tools(self):
        """Parse tool trace into structured data."""
        self.tools_used = Counter()  # tool_name -> count
        self.tool_errors = Counter()  # tool_name -> error count
        self.tool_sequence = []  # ordered list of tool names
        self.tool_calls = []  # full call data

        for entry in self.tool_trace:
            if not isinstance(entry, dict):
                continue
            name = entry.get("tool") or entry.get("name") or entry.get("function", "")
            if not name:
                continue

            self.tools_used[name] += 1
            self.tool_sequence.append(name)

            # Detect errors and classify error type
            result = entry.get("result", entry.get("output", ""))
            result_str = str(result) if result else ""
            is_error = False
            err_type = ""  # api_error, timeout, empty, tool_error
            result_lower = result_str.lower()
            if entry.get("error"):
                is_error = True
                err_type = "tool_error"
            elif any(kw in result_lower for kw in
                     ["timeout", "超时", "timed out"]):
                is_error = True
                err_type = "timeout"
            elif any(kw in result_lower for kw in
                     ["error executing tool", "api response", "api error",
                      "rate limit", "over_limit", "quota", "限流",
                      "超限", "forbidden", "unauthorized", "429",
                      "mcp connection failed", "tool execution failed"]):
                is_error = True
                err_type = "api_error"
            elif any(kw in result_lower for kw in
                     ["error", "failed", "invalid", "not found",
                      "no results", "no data", "empty", "[]", "count: 0"]):
                is_error = True
                err_type = "api_error"
            elif not result_str or result_str.strip() in ("", "{}", "null", "None"):
                is_error = True
                err_type = "empty"

            if is_error:
                self.tool_errors[name] += 1

            self.tool_calls.append({
                "name": name,
                "args": entry.get("args", entry.get("arguments", {})),
                "result": result_str[:500],
                "error": is_error,
                "err_type": err_type,
            })

        self.unique_tools = len(self.tools_used)
        self.total_calls = sum(self.tools_used.values())
        self.total_errors = sum(self.tool_errors.values())
        self.error_rate = self.total_errors / max(self.total_calls, 1)

        # Error type counts for this task
        self.err_type_counts = Counter(
            c["err_type"] for c in self.tool_calls if c["error"]
        )
        # API-blocked: >80% calls failed with API/infra errors, not model's fault
        api_errs = self.err_type_counts.get("api_error", 0) + self.err_type_counts.get("timeout", 0)
        self.is_api_blocked = (
            self.total_calls > 0
            and api_errs / max(self.total_calls, 1) > 0.80
        )

        # POI-specific error rate
        poi_total = self.tools_used.get("poi_search", 0)
        poi_err = self.tool_errors.get("poi_search", 0)
        self.poi_error_rate = poi_err / max(poi_total, 1) if poi_total > 0 else None

        # MONO_TOOL detection
        self.is_mono_tool = (
            self.unique_tools == 1 and
            self.total_calls >= 3 and
            "poi_search" in self.tools_used
        )

    def _parse_response(self):
        """Parse final assistant response."""
        self.response = ""
        for msg in reversed(self.conversation):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                self.response = msg.get("content", "")
                break

        self.response_len = len(self.response)

        # Think-block analysis
        closed = RE_THINK_CLOSED.findall(self.response)
        think_closed_len = sum(len(b) for b in closed)
        resp_no_closed = RE_THINK_CLOSED.sub("", self.response)
        unclosed_match = RE_THINK_UNCLOSED.search(resp_no_closed)
        self.has_unclosed_think = unclosed_match is not None
        think_unclosed_len = len(unclosed_match.group(1)) if unclosed_match else 0

        self.think_len = think_closed_len + think_unclosed_len

        # User-facing content
        user_content = RE_THINK_CLOSED.sub("", self.response)
        if self.has_unclosed_think:
            user_content = RE_THINK_UNCLOSED.sub("", user_content)
        user_content = re.sub(r"</?think>", "", user_content).strip()
        self.user_content = user_content
        self.user_len = len(user_content)

        self.think_ratio = self.think_len / max(self.response_len, 1)
        self.is_think_only = (
            (self.think_ratio > 0.9 or (self.think_len > 0 and self.user_len < 100))
            and self.response_len > 0
        )
        # Strict think-only: truly zero useful output (for ghost high-scorer detection)
        self.is_strict_think_only = (
            self.think_len > 0 and self.user_len < 100
            and self.response_len > 0
        )
        self.has_no_think = self.think_len == 0 and self.response_len > 0

        # Transport ID extraction
        self.flight_ids = set(RE_FLIGHT.findall(self.user_content))
        self.train_ids = set(RE_TRAIN.findall(self.user_content))
        self.transport_ids = self.flight_ids | self.train_ids

        # Fabrication detection: POI names in output vs from tools
        # Use multiple regex patterns for broader coverage
        self.output_poi_names = set()
        for pat in (RE_POI_NAME, RE_POI_NAME_JSON, RE_POI_NAME_CN, RE_POI_NAME_BULLET):
            self.output_poi_names.update(pat.findall(self.user_content))
        # Clean extracted names (strip whitespace, filter too-short)
        self.output_poi_names = {n.strip() for n in self.output_poi_names if len(n.strip()) >= 2}

        self.tool_poi_names = set()
        for call in self.tool_calls:
            if call["name"] in ("poi_search", "around_search"):
                # Unescape JSON string escapes for proper regex matching
                result_text = call["result"].replace("\\n", "\n").replace('\\"', '"')
                for pat in (RE_POI_NAME, RE_POI_NAME_JSON):
                    self.tool_poi_names.update(pat.findall(result_text))
        # Clean: strip whitespace/backslashes/parens artifacts
        self.tool_poi_names = {
            n.strip().rstrip("\\").strip()
            for n in self.tool_poi_names if len(n.strip().rstrip("\\").strip()) >= 2
        }

        # Match: check if output POI name is a substring of any tool POI or vice versa
        # This handles partial name matches (e.g., "天府广场" in tool vs "成都天府广场" in output)
        # Also normalize full-width parens for comparison
        def _norm_poi(s):
            """Normalize POI name for comparison: strip parens variants, stores."""
            return s.replace("（", "(").replace("）", ")").replace("·", "").strip()

        matched = set()
        norm_tool = {_norm_poi(t): t for t in self.tool_poi_names}
        for oname in self.output_poi_names:
            on = _norm_poi(oname)
            # Extract base name (before parens) for fuzzy match
            base_o = on.split("(")[0].strip() if "(" in on else on
            for tn, traw in norm_tool.items():
                base_t = tn.split("(")[0].strip() if "(" in tn else tn
                # Full substring match or base name match (>=3 chars)
                if on in tn or tn in on or (len(base_o) >= 3 and (base_o in tn or base_t in on)):
                    matched.add(oname)
                    break
        total_out = len(self.output_poi_names)
        self.fab_count = total_out - len(matched) if total_out > 0 else 0
        self.fab_rate = self.fab_count / max(total_out, 1) if total_out > 0 else 0.0

        # Reasoning quality
        self.reasoning_count = sum(
            1 for kw in REASONING_CONNECTORS if kw in self.user_content
        )

        # Tool-call dump detection: output is mostly <tool_call> tags, not real content
        tool_call_count = self.user_content.count("<tool_call>")
        self.is_tool_call_dump = (
            tool_call_count > 5 and self.user_len > 500
            and tool_call_count * 12 > self.user_len * 0.3  # >30% of content is <tool_call> tags
        )

        # Synthesis failure: tools called but no/short response
        self.is_synth_fail = (
            self.total_calls > 0 and self.response_len < 100
            and not self.is_think_only
        )


# ── Data Fetching ───────────────────────────────────────────────────────────

async def fetch_trajectories(
    uid: int,
    env_name: str = "navworld",
    source: str = "sampling",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Fetch trajectories for a miner UID.

    Args:
        uid: Miner UID (0-255)
        env_name: Environment name (default "navworld")
        source: "sampling" for active sampling list, "all" for all historical data

    Returns:
        (miner_info, raw_trajectories)
    """
    if os.getenv("FORCE_DB"):
        return await _fetch_via_db(uid, env_name, source)

    base_url = os.getenv("API_URL", "https://api.affine.io/api/v1")

    try:
        from affine.utils.api_client import cli_api_client
    except ImportError:
        return await _fetch_via_db(uid, env_name, source)

    try:
        return await _fetch_via_api(uid, env_name, source, base_url, cli_api_client)
    except Exception as e:
        print(f"  API failed ({e}), falling back to DB ...", file=sys.stderr)
        return await _fetch_via_db(uid, env_name, source)


async def _fetch_via_api(uid, env_name, source, base_url, cli_api_client):
    async with cli_api_client(base_url) as client:
        pool = await client.get(f"/samples/pool/uid/{uid}/{env_name}")

        hotkey = pool.get("hotkey", "")
        revision = pool.get("model_revision", "")
        sampling_config = pool.get("sampling_config", {})
        sampling_list = sampling_config.get("sampling_list", [])
        sampled_ids = set(pool.get("sampled_task_ids", []))

        if source == "all":
            task_ids = sorted(sampled_ids)
        else:
            task_ids = sampling_list if sampling_list else sorted(sampled_ids)

        if not task_ids:
            return {"matched": 0, "sampling_list_size": 0,
                    "hotkey": hotkey, "model_revision": revision}, []

        sem = asyncio.Semaphore(10)
        results = []
        errors = []

        async def fetch_one(task_id):
            async with sem:
                try:
                    data = await client.get(
                        f"/samples/{hotkey}/{env_name}/{task_id}",
                        params={"model_revision": revision},
                    )
                    return data
                except Exception:
                    errors.append(task_id)
                    return None

        raw = await asyncio.gather(*[fetch_one(tid) for tid in task_ids])
        results = [r for r in raw if r is not None]

        sl_size = len(sampling_list) if sampling_list else len(sampled_ids)
        miner_info = {
            "matched": len(results),
            "sampling_list_size": sl_size,
            "hotkey": hotkey,
            "model_revision": revision,
        }
        return miner_info, results


_db_initialized = False


async def _ensure_db():
    global _db_initialized
    if not _db_initialized:
        from affine.database.client import init_client
        await init_client()
        _db_initialized = True


async def close_db():
    """Cleanly shut down DB connection."""
    global _db_initialized
    if _db_initialized:
        try:
            from affine.database.client import close_client
            await close_client()
        except Exception:
            pass
        _db_initialized = False


async def _fetch_via_db(uid: int, env_name: str, source: str):
    from affine.database.dao.miners import MinersDAO
    from affine.database.dao.sample_results import SampleResultsDAO
    from affine.database.dao.system_config import SystemConfigDAO
    from affine.core.sampling_list import get_task_id_set_from_config

    await _ensure_db()

    miners_dao = MinersDAO()
    sample_dao = SampleResultsDAO()
    config_dao = SystemConfigDAO()

    miner = await miners_dao.get_miner_by_uid(uid)
    if not miner:
        return {"matched": 0, "sampling_list_size": 0}, []

    hotkey = miner["hotkey"]
    revision = miner["revision"]

    environments = await config_dao.get_param_value("environments", default={})

    env_key = env_name
    if env_key not in environments:
        # Try case-insensitive match
        for e in environments:
            if e.lower() == env_key.lower():
                env_key = e
                break
        else:
            # Try suffix match (e.g. "affine:navworld")
            if ":" not in env_key:
                matches = [e for e in environments if e.endswith(f":{env_key}")]
                if len(matches) == 1:
                    env_key = matches[0]

    env_config = environments.get(env_key, {})
    sampling_list = sorted(get_task_id_set_from_config(env_config)) if env_config else []

    if source == "all":
        task_ids = sorted(await sample_dao.get_completed_task_ids(hotkey, revision, env_key))
    else:
        completed = set(await sample_dao.get_completed_task_ids(hotkey, revision, env_key))
        task_ids = [tid for tid in sampling_list if tid in completed] if sampling_list else sorted(completed)

    db_concurrency = int(os.getenv("DB_CONCURRENCY", "20"))
    sem = asyncio.Semaphore(db_concurrency)

    async def fetch_one(task_id):
        async with sem:
            try:
                return await sample_dao.get_sample_by_task_id(
                    miner_hotkey=hotkey, model_revision=revision,
                    env=env_key, task_id=str(task_id), include_extra=True,
                )
            except Exception:
                return None

    raw = await asyncio.gather(*[fetch_one(tid) for tid in task_ids])
    results = [r for r in raw if r is not None]

    sl_size = len(sampling_list) if sampling_list else len(task_ids)
    miner_info = {
        "matched": len(results),
        "sampling_list_size": sl_size,
        "hotkey": hotkey,
        "model_revision": revision,
    }
    return miner_info, results


# ── Inspect / Deep Dump ─────────────────────────────────────────────────────

def inspect_extra(raw_trajectories: List[Dict], limit: int = 5) -> str:
    """Dump raw trajectory structure for debugging."""
    lines = []
    for t in raw_trajectories[:limit]:
        safe = {k: v for k, v in t.items() if k != "extra"}
        extra = t.get("extra", {})
        if isinstance(extra, dict):
            safe["extra_keys"] = list(extra.keys())
            if "conversation" in extra:
                safe["conversation_len"] = len(extra["conversation"])
            if "tool_trace" in extra:
                safe["tool_trace_len"] = len(extra.get("tool_trace", []) or [])
            if "problem" in extra:
                safe["problem"] = extra["problem"]
            if "score_breakdown" in extra:
                safe["score_breakdown"] = extra["score_breakdown"]
        lines.append(json.dumps(safe, indent=2, default=str, ensure_ascii=False))
        lines.append("")
    return "\n".join(lines)


def deep_dump(task_id: int, trajectories: List[TrajectoryData]) -> str:
    """Deep dump a single task with full tool trace and analysis."""
    lines = []
    w = lines.append

    t = None
    for traj in trajectories:
        if traj.task_id == task_id:
            t = traj
            break

    if t is None:
        return f"Task {task_id} not found in trajectories"

    w(f"\n{'='*80}")
    w(f"DEEP DUMP: Task {t.task_id}")
    w(f"{'='*80}")

    w(f"\n  Score:        {t.score:.1f}/100  (code={t.code_total:.1f}, llm={t.llm_total:.1f})")
    w(f"  Type:         {t.problem_type}")
    w(f"  Destination:  {t.destination}")
    if t.origin:
        w(f"  Origin:       {t.origin}")
    w(f"  Budget:       {t.budget}")
    w(f"  Days:         {t.days}")
    if t.constraints:
        w(f"  Constraints:  {', '.join(str(c) for c in t.constraints[:5])}")
    w(f"  Latency:      {t.latency_ms}ms")

    # Hard constraints
    w(f"\n  Hard Constraints:")
    for hc, val in t.hard_constraints.items():
        status = "PASS" if val else "FAIL" if val is False else "N/A"
        w(f"    {hc:30s} {status}")

    # Score breakdown
    w(f"\n  Score Breakdown:")
    w(f"    Code:        {t.code_total:.1f}/50 (band={t.code_band})")
    w(f"    LLM:         {t.llm_total:.1f}/50 (band={t.llm_band}, avail={t.llm_available})")
    if t.ic_score or t.comp_score:
        w(f"    IC:          {t.ic_score:.1f}/25")
        w(f"    Comp:        {t.comp_score:.1f}/25")
        w(f"    Fab penalty: {t.fab_penalty:.1f}")

    # Tool trace
    w(f"\n  Tool Trace ({t.total_calls} calls, {t.unique_tools} unique, {t.total_errors} errors):")
    for i, call in enumerate(t.tool_calls):
        err_mark = " ⚠ ERROR" if call["error"] else ""
        args_str = json.dumps(call["args"], ensure_ascii=False) if call["args"] else ""
        args_str = _trunc(args_str, 60)
        result_preview = _trunc(call["result"], 80)
        w(f"    Step {i+1:2d}: {call['name']:25s} {args_str}")
        w(f"             → {result_preview}{err_mark}")

        # Step reward
        if i < len(t.step_rewards):
            w(f"             SR: {t.step_rewards[i]:.3f}")

    # Think-block info
    w(f"\n  Response Analysis:")
    w(f"    Total length:  {t.response_len}")
    w(f"    Think length:  {t.think_len}")
    w(f"    User length:   {t.user_len}")
    w(f"    Think ratio:   {t.think_ratio:.1%}")
    w(f"    Think-only:    {'YES' if t.is_think_only else 'no'}")
    w(f"    No-think:      {'YES' if t.has_no_think else 'no'}")
    w(f"    Unclosed:      {'YES' if t.has_unclosed_think else 'no'}")

    # Transport IDs
    if t.transport_ids:
        w(f"    Flight IDs:    {', '.join(sorted(t.flight_ids)) or 'none'}")
        w(f"    Train IDs:     {', '.join(sorted(t.train_ids)) or 'none'}")

    # Fabrication
    w(f"\n  Fabrication:")
    w(f"    Output POIs:   {len(t.output_poi_names)}")
    w(f"    Tool POIs:     {len(t.tool_poi_names)}")
    w(f"    Fabricated:    {t.fab_count} ({t.fab_rate:.0%})")

    # Reasoning
    w(f"    Reasoning connectors: {t.reasoning_count}")

    # User-facing content preview
    w(f"\n  User Content Preview (first 500 chars):")
    preview = t.user_content[:500] if t.user_content else "(empty)"
    for line in preview.split("\n"):
        w(f"    {line}")

    return "\n".join(lines)


# ── Report Generation ───────────────────────────────────────────────────────

def generate_report(
    miner_info: Dict[str, Any],
    raw_trajectories: List[Dict[str, Any]],
) -> str:
    """Generate full NAVWORLD analysis report (10+ sections)."""
    lines: List[str] = []
    w = lines.append

    # Parse trajectories
    trajectories = []
    parse_errors = 0
    for raw in raw_trajectories:
        try:
            trajectories.append(TrajectoryData(raw))
        except Exception as e:
            parse_errors += 1

    if not trajectories:
        return f"No valid trajectories to analyze (parse_errors={parse_errors})"

    # Sort by timestamp
    trajectories.sort(key=lambda t: t.timestamp)

    uid = miner_info.get("uid", "?")
    matched = miner_info.get("matched", len(trajectories))
    sl_size = miner_info.get("sampling_list_size", 0)
    hotkey = str(miner_info.get("hotkey", "?"))[:16]
    revision = str(miner_info.get("model_revision", "?"))[:12]

    scores = [t.score for t in trajectories]

    # Pre-compute key metrics for TOP FINDINGS
    good_tasks = [t for t in trajectories if t.tier == "good+"]
    poor_tasks = [t for t in trajectories if t.tier == "poor"]
    # Ghost-excluded Good+ for tool comparisons (ghost tool patterns come from think blocks)
    real_good = [t for t in good_tasks if not t.is_strict_think_only]
    n_ghost_in_good = len(good_tasks) - len(real_good)
    # Use real_good for tool comparisons; fallback to good_tasks only if ALL Good+ are ghosts
    s3_good = real_good if real_good else good_tasks
    think_only = [t for t in trajectories if t.is_think_only]
    ghost_high = [t for t in think_only if t.score >= 30 and t.is_strict_think_only]
    mono_tool = [t for t in trajectories if t.is_mono_tool]
    poi_err_tasks = [t for t in trajectories if t.poi_error_rate is not None]
    avg_poi_err = _safe_mean([t.poi_error_rate for t in poi_err_tasks]) if poi_err_tasks else 0

    # Code vs LLM deep analysis
    code_scores = [t.code_total for t in trajectories]
    llm_scores_list = [t.llm_total for t in trajectories]
    code_avg = _safe_mean(code_scores)
    llm_avg = _safe_mean(llm_scores_list)
    code_util = code_avg / 50 * 100
    llm_util = llm_avg / 50 * 100
    score_bottleneck = "LLM" if llm_util < code_util else "Code"

    # Per-type performance
    type_avgs = {}
    for ptype in PROBLEM_TYPES:
        tt = [t.score for t in trajectories if t.problem_type == ptype]
        if tt:
            type_avgs[ptype] = _safe_mean(tt)
    best_type = max(type_avgs, key=type_avgs.get) if type_avgs else "N/A"
    worst_type = min(type_avgs, key=type_avgs.get) if type_avgs else "N/A"

    r_tools_score = _pearson([t.unique_tools for t in trajectories], scores)

    # ════════════════════════════════════════════════════════════════════════
    # HEADER + TEMPORAL TREND
    # ════════════════════════════════════════════════════════════════════════
    w(f"{'='*80}")
    w(f"NAVWORLD TRAJECTORY ANALYSIS — UID {uid}")
    w(f"{'='*80}")
    w(f"  Hotkey:     {hotkey}...  Revision: {revision}...")
    w(f"  Tasks:      {len(trajectories)} analyzed ({matched}/{sl_size} sampling list, "
      f"{matched/max(sl_size,1)*100:.1f}%)")
    if parse_errors:
        w(f"  Parse errs: {parse_errors}")
    w(f"  Score:      avg={_safe_mean(scores):.1f}  med={_safe_median(scores):.1f}  "
      f"min={min(scores):.1f}  max={max(scores):.1f}  std={_safe_stdev(scores):.1f}")

    # Tier distribution
    tier_counts = Counter(t.tier for t in trajectories)
    n = len(trajectories)
    w(f"  Tiers:      good+={tier_counts.get('good+',0)} ({tier_counts.get('good+',0)/n*100:.0f}%)  "
      f"acceptable={tier_counts.get('acceptable',0)} ({tier_counts.get('acceptable',0)/n*100:.0f}%)  "
      f"poor={tier_counts.get('poor',0)} ({tier_counts.get('poor',0)/n*100:.0f}%)")

    # Temporal trend detection
    if len(trajectories) >= 10:
        q_size = max(len(trajectories) // 4, 1)
        q1 = trajectories[:q_size]
        q4 = trajectories[-q_size:]
        q1_avg = _safe_mean([t.score for t in q1])
        q4_avg = _safe_mean([t.score for t in q4])
        delta = q4_avg - q1_avg

        q1_poi_err = _safe_mean([t.poi_error_rate for t in q1 if t.poi_error_rate is not None])
        q4_poi_err = _safe_mean([t.poi_error_rate for t in q4 if t.poi_error_rate is not None])
        poi_delta = (q4_poi_err - q1_poi_err) * 100 if q1_poi_err is not None and q4_poi_err is not None else None

        trend_dir = "↑" if delta > 5 else "↓" if delta < -5 else "→"
        w(f"\n  TEMPORAL TREND: Q1 avg={q1_avg:.1f} → Q4 avg={q4_avg:.1f} (delta={delta:+.1f} {trend_dir})")
        if poi_delta is not None:
            w(f"                  Q1 POI err={q1_poi_err*100:.0f}% → Q4 POI err={q4_poi_err*100:.0f}% (delta={poi_delta:+.0f}pp)")
            if poi_delta > 20:
                w(f"  ⚠ API DEGRADATION DETECTED: POI failure rate increasing over time")
            elif poi_delta < -20:
                w(f"  ✓ API RECOVERY DETECTED: POI failure rate decreasing over time")
        if abs(delta) > 5:
            w(f"  ⚠ SCORE SHIFT DETECTED: {'declining' if delta < 0 else 'improving'} trend")

        # Per-type temporal trend (types with >=4 tasks in each half)
        half = len(trajectories) // 2
        first_half = trajectories[:half]
        second_half = trajectories[half:]
        type_trends = []
        for ptype in PROBLEM_TYPES:
            fh = [t for t in first_half if t.problem_type == ptype]
            sh = [t for t in second_half if t.problem_type == ptype]
            if len(fh) >= 2 and len(sh) >= 2:
                fh_avg = _safe_mean([t.score for t in fh])
                sh_avg = _safe_mean([t.score for t in sh])
                td = sh_avg - fh_avg
                if abs(td) > 5:
                    type_trends.append((ptype, fh_avg, sh_avg, td))
        if type_trends:
            w(f"  Per-type shifts:")
            for ptype, fh_avg, sh_avg, td in sorted(type_trends, key=lambda x: -abs(x[3])):
                tag = "↑" if td > 0 else "↓"
                w(f"    {ptype:<15}: {fh_avg:.1f} → {sh_avg:.1f} ({td:+.1f} {tag})")

    # ════════════════════════════════════════════════════════════════════════
    # EXECUTIVE SUMMARY (auto-generated 2-4 line digest)
    # ════════════════════════════════════════════════════════════════════════

    # Build summary components
    avg_score = _safe_mean(scores)
    good_pct = len(good_tasks) / n * 100
    poor_pct = len(poor_tasks) / n * 100

    # Performance level
    if avg_score >= 40:
        perf_label = "STRONG"
    elif avg_score >= 25:
        perf_label = "MODERATE"
    elif avg_score >= 15:
        perf_label = "WEAK"
    else:
        perf_label = "VERY WEAK"

    # Trend
    trend_str = ""
    if len(trajectories) >= 10:
        q_sz = max(len(trajectories) // 4, 1)
        _q1a = _safe_mean([t.score for t in trajectories[:q_sz]])
        _q4a = _safe_mean([t.score for t in trajectories[-q_sz:]])
        _delta = _q4a - _q1a
        if _delta > 5:
            trend_str = f", improving (+{_delta:.0f})"
        elif _delta < -5:
            trend_str = f", declining ({_delta:.0f})"
        else:
            trend_str = ", stable"

    # Key risk
    to_pct = len(think_only) / n * 100 if think_only else 0
    risks = []
    if ghost_high:
        risks.append(f"{len(ghost_high)} ghost high-scorers (Q12)")
    if to_pct > 30:
        risks.append(f"{to_pct:.0f}% think-only")
    if avg_poi_err > 0.15:
        risks.append(f"POI API {avg_poi_err*100:.0f}% err")
    zero_tool_n = sum(1 for t in trajectories if t.total_calls == 0)
    if zero_tool_n / n > 0.1:
        risks.append(f"{zero_tool_n} zero-tool tasks")

    # Top action preview
    action_preview = f"Improve {score_bottleneck} score ({min(code_util, llm_util):.0f}% utilized)"

    # API-adjusted score: exclude api-blocked tasks to show true model capability
    api_blocked_pre = [t for t in trajectories if t.is_api_blocked and t.score < 15]
    non_blocked = [t for t in trajectories if not (t.is_api_blocked and t.score < 15)]
    adj_score = _safe_mean([t.score for t in non_blocked]) if non_blocked else avg_score
    adj_str = ""
    if len(api_blocked_pre) >= n * 0.15 and non_blocked:
        # Recalculate performance label on non-blocked tasks
        if adj_score >= 40:
            adj_label = "STRONG"
        elif adj_score >= 25:
            adj_label = "MODERATE"
        elif adj_score >= 15:
            adj_label = "WEAK"
        else:
            adj_label = "VERY WEAK"
        if adj_label != perf_label:
            adj_str = f" → adj. {adj_label} (avg={adj_score:.1f}, excl. {len(api_blocked_pre)} API-blocked)"
        else:
            adj_str = f" [adj. avg={adj_score:.1f} excl. {len(api_blocked_pre)} API-blocked]"

    # Emit summary
    w(f"\n  EXECUTIVE SUMMARY: {perf_label} (avg={avg_score:.1f}, "
      f"{good_pct:.0f}% good+, {poor_pct:.0f}% poor{trend_str}){adj_str}")
    w(f"  Bottleneck: {score_bottleneck} ({min(code_util, llm_util):.0f}% utilized vs "
      f"{max(code_util, llm_util):.0f}%). Best type: {best_type} ({type_avgs.get(best_type, 0):.0f}), "
      f"worst: {worst_type} ({type_avgs.get(worst_type, 0):.0f})")
    if risks:
        w(f"  Risks: {' | '.join(risks)}")

    # ════════════════════════════════════════════════════════════════════════
    # TOP FINDINGS (highest-value insights first)
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"TOP FINDINGS")
    w(f"{'='*80}")

    finding_num = 0

    # F1: Score bottleneck (Code vs LLM)
    finding_num += 1
    w(f"\n  F{finding_num}. SCORE BOTTLENECK: {score_bottleneck} score is the primary limiter")
    w(f"     Code: avg={code_avg:.1f}/50 ({code_util:.0f}% utilized)  |  "
      f"LLM: avg={llm_avg:.1f}/50 ({llm_util:.0f}% utilized)")
    if score_bottleneck == "LLM":
        w(f"     → LLM judge scores are low; improving reasoning quality, output structure,")
        w(f"       and factual grounding will have the highest score impact")
    else:
        w(f"     → Code score is low; improving tool data usage (IC) and content completeness")
        w(f"       will have the highest score impact")

    # F2: Tool diversity or efficiency
    r_total_score = _pearson([t.total_calls for t in trajectories], scores)
    if r_tools_score is not None and abs(r_tools_score) > 0.2:
        finding_num += 1
        w(f"\n  F{finding_num}. TOOL DIVERSITY is the strongest score predictor (r={r_tools_score:.3f})")
        if s3_good and poor_tasks:
            g_uniq = _safe_mean([t.unique_tools for t in s3_good])
            p_uniq = _safe_mean([t.unique_tools for t in poor_tasks])
            w(f"     Good+ avg unique tools: {g_uniq:.1f}  |  Poor: {p_uniq:.1f}  |  Gap: {g_uniq-p_uniq:+.1f}")
        w(f"     → Using 4+ different tool types is strongly associated with higher scores")
    elif (r_tools_score is not None and abs(r_tools_score) <= 0.2
          and r_total_score is not None and r_total_score < -0.3):
        # Diversity doesn't matter but more calls = lower score → efficiency finding
        finding_num += 1
        w(f"\n  F{finding_num}. TOOL EFFICIENCY matters more than diversity")
        w(f"     unique_tools ↔ score: r={r_tools_score:.3f} (weak)  |  "
          f"total_calls ↔ score: r={r_total_score:.3f} (negative)")
        if s3_good and poor_tasks:
            g_total = _safe_mean([t.total_calls for t in s3_good])
            p_total = _safe_mean([t.total_calls for t in poor_tasks])
            g_err = _safe_mean([t.error_rate for t in s3_good]) * 100
            p_err = _safe_mean([t.error_rate for t in poor_tasks]) * 100
            w(f"     Good+ avg calls: {g_total:.1f}  |  Poor: {p_total:.1f}  |  "
              f"Good+ err: {g_err:.0f}%  |  Poor err: {p_err:.0f}%")
        w(f"     → Miner already uses diverse tools; fewer, more targeted calls yield higher scores")

    # F3: Think-only vulnerability
    if think_only:
        finding_num += 1
        to_pct = len(think_only) / n * 100
        w(f"\n  F{finding_num}. THINK-ONLY RESPONSES: {len(think_only)}/{n} ({to_pct:.0f}%) — "
          f"model produces internal reasoning but no user-facing plan")
        if ghost_high:
            w(f"     ⚠ {len(ghost_high)} ghost high-scorers (score≥30 with 0 user content)")
            w(f"       → Scorer does not strip <think> tags — known P0 vulnerability (Q12)")
        else:
            w(f"     None scored ≥30 — scoring correctly penalizes think-only in this window")

    # F4: API health (consolidated with F11 API-BLOCKED TASKS to avoid redundancy)
    api_blocked = [t for t in trajectories if t.is_api_blocked and t.score < 15]
    if avg_poi_err > 0.15 and api_blocked:
        # Consolidated: high API error + specific blocked tasks
        finding_num += 1
        api_blocked_sorted = sorted(api_blocked, key=lambda t: t.error_rate, reverse=True)
        w(f"\n  F{finding_num}. POI API FAILURE: avg error rate {avg_poi_err*100:.0f}% — "
          f"{len(api_blocked)}/{n} tasks API-blocked")
        shown = api_blocked_sorted[:10]
        for t in shown:
            api_e = t.err_type_counts.get("api_error", 0) + t.err_type_counts.get("timeout", 0)
            w(f"     task {t.task_id:>12d}  score={t.score:5.1f}  err={t.error_rate:.0%} "
              f"({api_e}/{t.total_calls} api/infra)  type={t.problem_type}")
        if len(api_blocked) > 10:
            w(f"     ... and {len(api_blocked)-10} more")
        all_api_err_types = Counter()
        for t in api_blocked:
            all_api_err_types.update(t.err_type_counts)
        if all_api_err_types:
            breakdown = ", ".join(f"{k}={v}" for k, v in all_api_err_types.most_common())
            w(f"     Error types: {breakdown}")
        w(f"     → These tasks scored low due to server-side API failures, not model quality")
        w(f"       Exclude from model evaluation or re-run after API fix")
        _f4_has_blocked = True
    elif avg_poi_err > 0.15:
        finding_num += 1
        w(f"\n  F{finding_num}. POI API FAILURE: avg error rate {avg_poi_err*100:.0f}%")
        w(f"     → API failures are a structural factor limiting all miners' scores")
        _f4_has_blocked = False
    elif avg_poi_err <= 0.05 and poi_err_tasks:
        finding_num += 1
        w(f"\n  F{finding_num}. API HEALTH: POI error rate {avg_poi_err*100:.0f}% — healthy")
        _f4_has_blocked = False
    else:
        _f4_has_blocked = False

    # F5: Best/worst type
    if type_avgs and len(type_avgs) >= 3:
        finding_num += 1
        w(f"\n  F{finding_num}. TYPE PERFORMANCE SPREAD:")
        w(f"     Best:  {best_type} (avg {type_avgs[best_type]:.1f})")
        w(f"     Worst: {worst_type} (avg {type_avgs[worst_type]:.1f})")
        gap = type_avgs[best_type] - type_avgs[worst_type]
        w(f"     Gap:   {gap:.1f} pts — {'significant variance across types' if gap > 15 else 'relatively uniform'}")

    # F6: Code/LLM divergence patterns
    # Exclude think-only tasks: their code/LLM scores come from think-block content,
    # not from real tool data usage vs reasoning quality
    normal_tasks = [t for t in trajectories if not t.is_think_only]
    n_normal = len(normal_tasks)
    if n_normal >= 5:
        code_dom = sum(1 for t in normal_tasks
                       if t.code_total > 3 and t.code_total > max(t.llm_total, 1) * 1.5)
        llm_dom = sum(1 for t in normal_tasks
                      if t.llm_total > 3 and t.llm_total > max(t.code_total, 1) * 1.5)
        balanced_f6 = n_normal - code_dom - llm_dom
        # Utilization excluding think-only
        code_util_f6 = _safe_mean([t.code_total for t in normal_tasks]) / 50 * 100
        llm_util_f6 = _safe_mean([t.llm_total for t in normal_tasks]) / 50 * 100
        finding_num += 1
        excl_note = f" (excl. {len(think_only)} think-only)" if think_only else ""
        w(f"\n  F{finding_num}. CODE/LLM BALANCE{excl_note}: "
          f"{code_dom} code-dominated, {llm_dom} LLM-dominated, {balanced_f6} balanced")
        if code_util_f6 > llm_util_f6 * 1.5:
            w(f"     → Code scores consistently higher than LLM ({code_util_f6:.0f}% vs {llm_util_f6:.0f}%)")
            w(f"       SFT should focus on output format + reasoning connectors + analysis depth")
        elif llm_util_f6 > code_util_f6 * 1.5:
            w(f"     → LLM scores consistently higher than code ({llm_util_f6:.0f}% vs {code_util_f6:.0f}%)")
            w(f"       SFT should focus on tool usage patterns + data extraction + grounding")
        elif code_util_f6 < 25 and llm_util_f6 < 25:
            w(f"     → Both scores very low (code {code_util_f6:.0f}%, LLM {llm_util_f6:.0f}%)")
            w(f"       Model needs fundamental improvement in both tool usage AND reasoning")
        else:
            w(f"     → Relatively balanced — improve both dimensions in parallel")

    # F7: HC failure patterns
    hc_failures = defaultdict(int)
    for t in trajectories:
        for hc_name, val in t.hard_constraints.items():
            if val is False:
                hc_failures[hc_name] += 1
    if hc_failures:
        finding_num += 1
        top_hc = max(hc_failures, key=hc_failures.get)
        w(f"\n  F{finding_num}. TOP HC FAILURE: {top_hc} ({hc_failures[top_hc]}/{n}, "
          f"{hc_failures[top_hc]/n*100:.0f}%)")
        if top_hc == "tool_info_used":
            w(f"     → Model's output doesn't reference enough tool-returned data (IC threshold)")
        elif top_hc == "required_tools_called":
            w(f"     → Model doesn't call enough required tool types for the problem")
        elif top_hc == "transport_grounded":
            w(f"     → Transport IDs/prices in output don't match tool results")

    # F8: MONO_TOOL (distinguish API-blocked from strategy-driven)
    if mono_tool and len(mono_tool) / n > 0.05:
        finding_num += 1
        mono_api = [t for t in mono_tool if t.is_api_blocked]
        mono_strategy = [t for t in mono_tool if not t.is_api_blocked]
        w(f"\n  F{finding_num}. MONO_TOOL: {len(mono_tool)}/{n} ({len(mono_tool)/n*100:.0f}%) tasks only use poi_search")
        mono_avg = _safe_mean([t.score for t in mono_tool])
        diverse_avg = _safe_mean([t.score for t in trajectories if not t.is_mono_tool])
        w(f"     MONO avg={mono_avg:.1f} vs diverse avg={diverse_avg:.1f} — score gap={diverse_avg-mono_avg:+.1f}")
        if mono_api and mono_strategy:
            w(f"     Breakdown: {len(mono_api)} API-blocked (couldn't diversify) + "
              f"{len(mono_strategy)} strategy (chose not to diversify)")
        elif mono_api and not mono_strategy:
            w(f"     All {len(mono_api)} are API-blocked — model couldn't diversify due to API failures, not strategy")

    # F9: SYNTHESIS FAILURE (tools called but no/short response)
    synth_fail = [t for t in trajectories if t.is_synth_fail]
    if synth_fail and len(synth_fail) / n > 0.05:
        finding_num += 1
        sf_pct = len(synth_fail) / n * 100
        sf_avg = _safe_mean([t.total_calls for t in synth_fail])
        w(f"\n  F{finding_num}. SYNTHESIS FAILURE: {len(synth_fail)}/{n} ({sf_pct:.0f}%) tasks "
          f"called tools (avg {sf_avg:.0f}) but produced no response")
        w(f"     → All scored 0. Model collects data but fails to generate output")

    # F10: TOOL BUDGET SATURATION (most tasks hit max tool calls)
    # Note: MAX_TOOL_STEPS=15 is an environment ceiling (config.py), NOT a requirement.
    # Models CAN stop early by not requesting more tool calls.
    if n >= 10:
        max_calls = max(t.total_calls for t in trajectories)
        at_max = sum(1 for t in trajectories if t.total_calls >= max_calls)
        at_max_pct = at_max / n * 100
        if at_max_pct >= 70 and max_calls >= 10:
            finding_num += 1
            def _has_rep5(t):
                for i in range(len(t.tool_sequence) - 4):
                    if len(set(t.tool_sequence[i:i+5])) == 1:
                        return True
                return False
            rep_pct = sum(1 for t in trajectories if _has_rep5(t)) / n * 100
            w(f"\n  F{finding_num}. TOOL BUDGET SATURATION: {at_max}/{n} ({at_max_pct:.0f}%) tasks "
              f"hit {max_calls} calls (env MAX_TOOL_STEPS ceiling)")
            w(f"     → Model always exhausts the environment's tool budget (models CAN stop early)")
            if rep_pct > 50:
                rep_tool_counts = Counter()
                for t in trajectories:
                    for i in range(len(t.tool_sequence) - 4):
                        if len(set(t.tool_sequence[i:i+5])) == 1:
                            rep_tool_counts[t.tool_sequence[i]] += 1
                            break
                if rep_tool_counts:
                    top_rep = rep_tool_counts.most_common(1)[0]
                    w(f"     → {rep_pct:.0f}% tasks have 5+ repeated calls "
                      f"(mostly {top_rep[0]}) — SFT should teach early stopping")
            # Budget reallocation insight: when saturated, show what Good+ tasks
            # trade away to make room for differentiating tools
            if good_tasks and poor_tasks:
                realloc_from = []  # tools Poor uses more
                realloc_to = []    # tools Good+ uses more
                for tool in ALL_TOOLS:
                    gf = _safe_mean([t.tools_used.get(tool, 0) for t in good_tasks])
                    pf = _safe_mean([t.tools_used.get(tool, 0) for t in poor_tasks])
                    d = gf - pf
                    if d < -0.5:
                        realloc_from.append((tool, abs(d)))
                    elif d > 0.3:
                        realloc_to.append((tool, d))
                if realloc_from and realloc_to:
                    from_str = " + ".join(f"{t} (-{d:.1f})" for t, d in
                                          sorted(realloc_from, key=lambda x: -x[1]))
                    to_str = " + ".join(f"{t} (+{d:.1f})" for t, d in
                                        sorted(realloc_to, key=lambda x: -x[1]))
                    w(f"     → Budget reallocation: Good+ trades {from_str} → {to_str}")

    # F11: API-BLOCKED TASKS — only emit separately when F4 didn't already include them
    # (i.e. when avg_poi_err <= 0.15 but there are still individual api-blocked tasks)
    if not _f4_has_blocked and api_blocked:
        finding_num += 1
        api_blocked_sorted = sorted(api_blocked, key=lambda t: t.error_rate, reverse=True)
        w(f"\n  F{finding_num}. API-BLOCKED TASKS: {len(api_blocked)}/{n} tasks failed due to API/infrastructure errors")
        shown = api_blocked_sorted[:10]
        for t in shown:
            api_e = t.err_type_counts.get("api_error", 0) + t.err_type_counts.get("timeout", 0)
            w(f"     task {t.task_id:>12d}  score={t.score:5.1f}  err={t.error_rate:.0%} "
              f"({api_e}/{t.total_calls} api/infra)  type={t.problem_type}")
        if len(api_blocked) > 10:
            w(f"     ... and {len(api_blocked)-10} more")
        all_api_err_types = Counter()
        for t in api_blocked:
            all_api_err_types.update(t.err_type_counts)
        if all_api_err_types:
            breakdown = ", ".join(f"{k}={v}" for k, v in all_api_err_types.most_common())
            w(f"     Error types: {breakdown}")
        w(f"     → These tasks scored low due to server-side API failures, not model quality")

    w(f"\n  {'─'*70}")
    w(f"  Total findings: {finding_num}")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 1: OVERALL SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 1: OVERALL SUMMARY")
    w(f"{'='*80}")

    # Score distribution histogram
    w(f"\n  Score distribution:")
    buckets = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 50), (50, 100)]
    for lo, hi in buckets:
        cnt = sum(1 for s in scores if lo <= s < hi)
        pct = cnt / n * 100
        w(f"    [{lo:3d}-{hi:3d}) {cnt:4d} ({pct:5.1f}%) {_bar(pct)}")

    # HC pass rates
    w(f"\n  Hard constraint pass rates:")
    for hc_name in HARD_CONSTRAINTS:
        passed = sum(1 for t in trajectories if t.hard_constraints.get(hc_name, True))
        w(f"    {hc_name:30s} {passed:4d}/{n:4d} ({passed/n*100:5.1f}%)")

    hc_all_pass = sum(1 for t in trajectories if t.hc_all_pass)
    w(f"    {'ALL PASS':30s} {hc_all_pass:4d}/{n:4d} ({hc_all_pass/n*100:5.1f}%)")

    # Code/LLM score split
    code_vals = [t.code_total for t in trajectories]
    llm_vals = [t.llm_total for t in trajectories]
    w(f"\n  Score split:")
    w(f"    Code:  avg={_safe_mean(code_vals):.1f}  med={_safe_median(code_vals):.1f}  /50")
    w(f"    LLM:   avg={_safe_mean(llm_vals):.1f}  med={_safe_median(llm_vals):.1f}  /50")
    llm_avail = sum(1 for t in trajectories if t.llm_available)
    w(f"    LLM available: {llm_avail}/{n} ({llm_avail/n*100:.0f}%)")

    # Code/LLM band distribution
    code_bands = Counter(t.code_band for t in trajectories if t.code_band)
    llm_bands = Counter(t.llm_band for t in trajectories if t.llm_band)
    if code_bands:
        w(f"    Code bands: {', '.join(f'{b}={c}' for b, c in code_bands.most_common())}")
    if llm_bands:
        w(f"    LLM bands:  {', '.join(f'{b}={c}' for b, c in llm_bands.most_common())}")

    # Code vs LLM deep analysis
    r_code_llm = _pearson(code_scores, llm_scores_list)
    if r_code_llm is not None:
        w(f"\n  Code ↔ LLM correlation: r={r_code_llm:.3f}")
        if r_code_llm > 0.7:
            w(f"    Strong coupling — code and LLM scores rise/fall together")
        elif r_code_llm < 0.3:
            w(f"    Weak coupling — code and LLM capture independent quality dimensions")

    # Code/LLM by tier
    w(f"\n  Code/LLM by performance tier:")
    w(f"    {'Tier':12s} {'N':>4s}  {'Code avg':>8s} {'LLM avg':>8s} {'Code%':>6s} {'LLM%':>6s} {'Bottleneck':>10s}")
    w(f"    {'─'*60}")
    for tier_name in ["good+", "acceptable", "poor"]:
        tier_tasks = [t for t in trajectories if t.tier == tier_name]
        if not tier_tasks:
            continue
        c_avg = _safe_mean([t.code_total for t in tier_tasks])
        l_avg = _safe_mean([t.llm_total for t in tier_tasks])
        c_pct = c_avg / 50 * 100
        l_pct = l_avg / 50 * 100
        bn = "LLM" if l_pct < c_pct else "Code" if c_pct < l_pct else "Even"
        w(f"    {tier_name:12s} {len(tier_tasks):4d}  {c_avg:8.1f} {l_avg:8.1f} {c_pct:5.0f}% {l_pct:5.0f}% {bn:>10s}")

    # Code/LLM by problem type
    w(f"\n  Code/LLM by problem type:")
    w(f"    {'Type':14s} {'Code avg':>8s} {'LLM avg':>8s} {'Bottleneck':>10s}")
    w(f"    {'─'*45}")
    for ptype in PROBLEM_TYPES:
        tt = [t for t in trajectories if t.problem_type == ptype]
        if not tt:
            continue
        c_avg = _safe_mean([t.code_total for t in tt])
        l_avg = _safe_mean([t.llm_total for t in tt])
        bn = "LLM" if l_avg / 50 < c_avg / 50 - 0.1 else "Code" if c_avg / 50 < l_avg / 50 - 0.1 else "Balanced"
        w(f"    {ptype:14s} {c_avg:8.1f} {l_avg:8.1f} {bn:>10s}")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 2: PER-TYPE BREAKDOWN
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 2: PER-TYPE BREAKDOWN")
    w(f"{'='*80}")

    w(f"\n  {'Type':14s} {'N':>4s} {'Avg':>6s} {'Med':>6s} {'Min':>6s} {'Max':>6s}  "
      f"{'Good+':>5s} {'Acc':>5s} {'Poor':>5s}  {'HC%':>5s}  {'Err%':>5s}")
    w(f"  {'─'*90}")

    for ptype in PROBLEM_TYPES:
        tt = [t for t in trajectories if t.problem_type == ptype]
        if not tt:
            w(f"  {ptype:14s} {'(none)':>4s}")
            continue
        ts = [t.score for t in tt]
        good = sum(1 for t in tt if t.tier == "good+")
        acc = sum(1 for t in tt if t.tier == "acceptable")
        poor = sum(1 for t in tt if t.tier == "poor")
        hc_p = sum(1 for t in tt if t.hc_all_pass) / len(tt) * 100
        err_rates = [t.error_rate for t in tt]
        avg_err = _safe_mean(err_rates) * 100
        w(f"  {ptype:14s} {len(tt):4d} {_safe_mean(ts):6.1f} {_safe_median(ts):6.1f} "
          f"{min(ts):6.1f} {max(ts):6.1f}  {good:5d} {acc:5d} {poor:5d}  {hc_p:4.0f}%  {avg_err:4.0f}%")

    # Unknown types
    unknown = [t for t in trajectories if t.problem_type not in PROBLEM_TYPES]
    if unknown:
        ts = [t.score for t in unknown]
        w(f"  {'(unknown)':14s} {len(unknown):4d} {_safe_mean(ts):6.1f}")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 3: TOOL USAGE ANALYSIS
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 3: TOOL USAGE ANALYSIS")
    w(f"{'='*80}")

    # Per-tool stats
    w(f"\n  Per-tool usage:")
    w(f"    {'Tool':25s} {'Used':>5s} {'Err':>5s} {'Err%':>5s}  {'Avg/task':>8s}")
    w(f"    {'─'*55}")
    for tool in ALL_TOOLS:
        used = sum(t.tools_used.get(tool, 0) for t in trajectories)
        errs = sum(t.tool_errors.get(tool, 0) for t in trajectories)
        tasks_using = sum(1 for t in trajectories if tool in t.tools_used)
        err_pct = errs / max(used, 1) * 100
        avg_per = used / n
        w(f"    {tool:25s} {used:5d} {errs:5d} {err_pct:4.0f}%  {avg_per:8.1f}")

    # Tool diversity
    w(f"\n  Tool diversity:")
    uniq_vals = [t.unique_tools for t in trajectories]
    total_vals = [t.total_calls for t in trajectories]
    w(f"    Unique tools: avg={_safe_mean(uniq_vals):.1f}  med={_safe_median(uniq_vals):.1f}")
    w(f"    Total calls:  avg={_safe_mean(total_vals):.1f}  med={_safe_median(total_vals):.1f}")

    # Tool diversity vs score correlation
    r = _pearson(uniq_vals, scores)
    if r is not None:
        w(f"    Unique tools ↔ score: r={r:.3f}")

    r2 = _pearson(total_vals, scores)
    if r2 is not None:
        w(f"    Total calls ↔ score:  r={r2:.3f}")

    # High vs Low tool diversity (s3_good = ghost-excluded Good+, pre-computed above)
    if s3_good and poor_tasks:
        small_gp = len(s3_good) < 5
        ghost_note = f", excl. {n_ghost_in_good} ghost" if n_ghost_in_good else ""
        gp_warn = f"  ⚠ small Good+ sample (n={len(s3_good)}{ghost_note})" if small_gp else ""
        if not small_gp and n_ghost_in_good:
            gp_warn = f"  (excl. {n_ghost_in_good} ghost)"
        w(f"\n  Tool diversity: Good+ vs Poor:{gp_warn}")
        w(f"    {'Metric':20s} {'Good+':>8s} {'Poor':>8s} {'Delta':>8s}")
        w(f"    {'─'*50}")
        g_uniq = _safe_mean([t.unique_tools for t in s3_good])
        p_uniq = _safe_mean([t.unique_tools for t in poor_tasks])
        g_total = _safe_mean([t.total_calls for t in s3_good])
        p_total = _safe_mean([t.total_calls for t in poor_tasks])
        g_err = _safe_mean([t.error_rate for t in s3_good]) * 100
        p_err = _safe_mean([t.error_rate for t in poor_tasks]) * 100
        w(f"    {'unique_tools':20s} {g_uniq:8.1f} {p_uniq:8.1f} {g_uniq-p_uniq:+8.1f}")
        w(f"    {'total_calls':20s} {g_total:8.1f} {p_total:8.1f} {g_total-p_total:+8.1f}")
        w(f"    {'error_rate%':20s} {g_err:7.0f}% {p_err:7.0f}% {g_err-p_err:+7.0f}pp")

        # Per-tool adoption gap (using s3_good = ghost-excluded Good+)
        w(f"\n  Per-tool adoption: Good+ vs Poor:")
        w(f"    {'Tool':25s} {'Good+':>6s} {'Poor':>6s} {'Gap':>6s}")
        w(f"    {'─'*48}")
        for tool in ALL_TOOLS:
            g_adopt = sum(1 for t in s3_good if tool in t.tools_used) / len(s3_good) * 100
            p_adopt = sum(1 for t in poor_tasks if tool in t.tools_used) / len(poor_tasks) * 100
            w(f"    {tool:25s} {g_adopt:5.0f}% {p_adopt:5.0f}% {g_adopt-p_adopt:+5.0f}pp")

        # Per-tool call frequency: Good+ vs Poor (avg calls per task, not just adoption)
        # This reveals over-allocation: tools called many times but not differentiating
        w(f"\n  Per-tool call frequency: Good+ vs Poor (avg calls/task):")
        w(f"    {'Tool':25s} {'Good+':>6s} {'Poor':>6s} {'Delta':>6s} {'Signal':>14s}")
        w(f"    {'─'*62}")
        over_alloc = []
        under_alloc = []
        for tool in ALL_TOOLS:
            g_freq = _safe_mean([t.tools_used.get(tool, 0) for t in s3_good])
            p_freq = _safe_mean([t.tools_used.get(tool, 0) for t in poor_tasks])
            delta = g_freq - p_freq
            # Classify signal: absolute threshold for common tools,
            # relative threshold for rare tools (delta>0.4 AND ratio>2.5x)
            max_freq = max(g_freq, p_freq)
            if delta < -1.0 and p_freq >= 2.0:
                signal = "OVER-CALLED"
                over_alloc.append((tool, g_freq, p_freq))
            elif delta > 1.0 and g_freq >= 1.0:
                signal = "UNDER-CALLED"
                under_alloc.append((tool, g_freq, p_freq))
            elif (delta > 0.4 and max_freq < 2.0
                  and g_freq > 0.3 and p_freq < g_freq * 0.4):
                signal = "UNDER-CALLED"
                under_alloc.append((tool, g_freq, p_freq))
            elif (delta < -0.4 and max_freq < 2.0
                  and p_freq > 0.3 and g_freq < p_freq * 0.4):
                signal = "OVER-CALLED"
                over_alloc.append((tool, g_freq, p_freq))
            else:
                signal = ""
            w(f"    {tool:25s} {g_freq:6.1f} {p_freq:6.1f} {delta:+6.1f} {signal:>14s}")
        # Compute per-tool error rates for cross-referencing with allocation signals
        tool_err_rates = {}
        for tool in ALL_TOOLS:
            t_total = sum(t.tools_used.get(tool, 0) for t in trajectories)
            t_errors = sum(t.tool_errors.get(tool, 0) for t in trajectories)
            tool_err_rates[tool] = t_errors / max(t_total, 1) if t_total > 0 else None

        if over_alloc or under_alloc:
            w(f"\n    Allocation insight:")
            for tool, gf, pf in over_alloc:
                ter = tool_err_rates.get(tool)
                caveat = ""
                if ter is not None and ter < 0.10:
                    caveat = " (note: tool has low error rate {:.0f}% — calls may be justified)".format(ter*100)
                w(f"      ⚠ {tool}: Poor tasks call {pf:.1f}x vs Good+ {gf:.1f}x — reduce repetitive calls{caveat}")
            for tool, gf, pf in under_alloc:
                ter = tool_err_rates.get(tool)
                caveat = ""
                if ter is not None and ter > 0.50:
                    caveat = " (caution: tool has {:.0f}% error rate — more calls may not help)".format(ter*100)
                w(f"      → {tool}: Good+ tasks call {gf:.1f}x vs Poor {pf:.1f}x — increase usage{caveat}")

        # Dominant non-differentiating tool: uses >30% of call budget but ~0 score signal
        avg_total = _safe_mean([t.total_calls for t in trajectories])
        if avg_total >= 5:
            for tool in ALL_TOOLS:
                total_tool = sum(t.tools_used.get(tool, 0) for t in trajectories)
                total_all = sum(t.total_calls for t in trajectories)
                share = total_tool / max(total_all, 1) * 100
                if share < 30:
                    continue
                g_freq = _safe_mean([t.tools_used.get(tool, 0) for t in good_tasks])
                p_freq = _safe_mean([t.tools_used.get(tool, 0) for t in poor_tasks])
                if abs(g_freq - p_freq) < 1.0:
                    r_tool_score = _pearson(
                        [t.tools_used.get(tool, 0) for t in trajectories], scores)
                    if r_tool_score is not None and abs(r_tool_score) < 0.15:
                        w(f"\n    ⚠ BUDGET SINK: {tool} uses {share:.0f}% of all calls "
                          f"(Good+ {g_freq:.1f} ≈ Poor {p_freq:.1f}) but r={r_tool_score:.3f} with score")
                        w(f"      → High usage without score impact; reallocate to differentiating tools")

    # Opening tool sequence analysis
    w(f"\n  Most common opening sequences (first 3 tools):")
    openings = Counter()
    opening_scores = {}  # seq -> list of scores
    for t in trajectories:
        seq = tuple(t.tool_sequence[:3])
        if seq:
            openings[seq] += 1
            opening_scores.setdefault(seq, []).append(t.score)
    for seq, cnt in openings.most_common(10):
        avg_s = _safe_mean(opening_scores[seq])
        w(f"    {' → '.join(seq):50s} {cnt:4d} ({cnt/n*100:4.1f}%)  avg={avg_s:.1f}")

    # Opening strategy insight: flag when most common opening is not the best
    opening_gap = None  # (best_seq, best_avg, mc_seq, mc_avg) — reused in SFT Action Plan
    if len(openings) >= 2:
        most_common_seq = openings.most_common(1)[0][0]
        mc_avg = _safe_mean(opening_scores[most_common_seq])
        # Find best opening (by avg score, minimum 2 uses to avoid noise)
        best_seq, best_avg = None, mc_avg
        for seq, scores_list in opening_scores.items():
            if len(scores_list) >= 2 and seq != most_common_seq:
                s_avg = _safe_mean(scores_list)
                if s_avg > best_avg:
                    best_seq, best_avg = seq, s_avg
        if best_seq and best_avg - mc_avg > 10:
            opening_gap = (best_seq, best_avg, most_common_seq, mc_avg)
            best_cnt = openings[best_seq]
            w(f"\n    ⚠ OPENING STRATEGY GAP: most common '{' → '.join(most_common_seq)}' "
              f"avg={mc_avg:.1f} vs '{' → '.join(best_seq)}' avg={best_avg:.1f} "
              f"(+{best_avg-mc_avg:.0f} pts, used {best_cnt}x)")
            # Check if best opening starts with transport tools
            if best_seq[0] in TRANSPORT_TOOLS or (len(best_seq) > 1 and best_seq[1] in TRANSPORT_TOOLS):
                w(f"      → Transport-first opening scores {best_avg/max(mc_avg,0.1):.0f}x higher; "
                  f"SFT should train this as default opening for transport-dependent types")
            else:
                w(f"      → Switch to higher-scoring opening strategy")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 4: OVERFITTING & MEMORIZATION DETECTION
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 4: OVERFITTING & MEMORIZATION DETECTION")
    w(f"{'='*80}")

    # MONO_TOOL
    mono = [t for t in trajectories if t.is_mono_tool]
    diverse = [t for t in trajectories if not t.is_mono_tool]
    w(f"\n  MONO_TOOL (only poi_search): {len(mono)}/{n} ({len(mono)/n*100:.1f}%)")
    if mono and diverse:
        m_avg = _safe_mean([t.score for t in mono])
        d_avg = _safe_mean([t.score for t in diverse])
        w(f"    MONO avg={m_avg:.1f} vs diverse avg={d_avg:.1f} (gap={d_avg-m_avg:+.1f})")
        # API-blocked vs strategy breakdown (consistent with F8)
        mono_api = [t for t in mono if t.is_api_blocked]
        if mono_api and len(mono_api) == len(mono):
            w(f"    (all {len(mono)} are API-blocked — see MONO_TOOL in TOP FINDINGS)")
        elif mono_api:
            w(f"    ({len(mono_api)} API-blocked + {len(mono)-len(mono_api)} strategy-driven)")

    # Repetitive tool calls (same tool called 5+ times in a row)
    repetitive = 0
    for t in trajectories:
        for i in range(len(t.tool_sequence) - 4):
            if len(set(t.tool_sequence[i:i+5])) == 1:
                repetitive += 1
                break
    w(f"  Repetitive sequences (same tool 5+): {repetitive}/{n} ({repetitive/n*100:.1f}%)")

    # Destination diversity (are tasks spread across different cities?)
    dest_counts = Counter(t.destination for t in trajectories if t.destination)
    w(f"  Unique destinations: {len(dest_counts)}")
    w(f"  Top destinations: {', '.join(f'{d}({c})' for d, c in dest_counts.most_common(8))}")

    # Think-only prevalence
    think_only = [t for t in trajectories if t.is_think_only]
    no_think = [t for t in trajectories if t.has_no_think]
    synth_fail = [t for t in trajectories if t.is_synth_fail]
    w(f"\n  Response patterns:")
    w(f"    Think-only:    {len(think_only):4d} ({len(think_only)/n*100:5.1f}%)")
    w(f"    No-think:      {len(no_think):4d} ({len(no_think)/n*100:5.1f}%)")
    w(f"    Synth-fail:    {len(synth_fail):4d} ({len(synth_fail)/n*100:5.1f}%)")
    if think_only:
        # Use strict definition (user_len<100) consistent with F3 and Section 9.2.2
        to_high = [t for t in think_only if t.score >= 30 and t.is_strict_think_only]
        w(f"    Strict ghost high-scorers (score≥30, user_len<100): {len(to_high)} ⚠" if to_high
          else f"    Strict ghost high-scorers (score≥30, user_len<100): 0")
        w(f"    Think-only avg score: {_safe_mean([t.score for t in think_only]):.1f} "
          f"vs normal avg: {_safe_mean([t.score for t in trajectories if not t.is_think_only]):.1f}")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 4.5: REWARD HACKABILITY
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 4.5: REWARD HACKABILITY")
    w(f"{'='*80}")

    # 4.5.1 Code Score: reasoning density vs data density
    w(f"\n  4.5.1 Reasoning vs Data Density:")
    reasoning_vals = [t.reasoning_count for t in trajectories]
    r_reason = _pearson(reasoning_vals, scores)
    if r_reason is not None:
        w(f"    Reasoning connectors ↔ score: r={r_reason:.3f}")
        if r_reason > 0.3:
            w(f"    ⚠ High reasoning → higher score (potential reasoning keyword hack)")
        else:
            w(f"    ✓ Reasoning connectors don't predict score strongly")

    # 4.5.2 LLM Score: formulaic reasoning detection
    w(f"\n  4.5.2 LLM Score Correlation:")
    llm_vals = [t.llm_total for t in trajectories]
    code_vals = [t.code_total for t in trajectories]
    r_lc = _pearson(llm_vals, code_vals)
    if r_lc is not None:
        w(f"    LLM ↔ code score: r={r_lc:.3f}")

    # 4.5.3 Cross-source divergence
    w(f"\n  4.5.3 Cross-Source Divergence:")
    code_high_llm_low = sum(1 for t in trajectories if t.code_total > 25 and t.llm_total < 10)
    llm_high_code_low = sum(1 for t in trajectories if t.llm_total > 25 and t.code_total < 10)
    balanced = sum(1 for t in trajectories if abs(t.code_total - t.llm_total) < 15)
    w(f"    Code-high / LLM-low: {code_high_llm_low}")
    w(f"    LLM-high / Code-low: {llm_high_code_low}")
    w(f"    Balanced (|delta|<15): {balanced}")

    if code_high_llm_low == 0 and llm_high_code_low == 0:
        w(f"    ✓ No single-source hack detected — geometric mean effective")
    elif code_high_llm_low > 0 or llm_high_code_low > 0:
        w(f"    ⚠ {code_high_llm_low + llm_high_code_low} divergent tasks warrant investigation")

    # 4.5.4 Minimum viable strategy (exclude ghost high-scorers — their efficiency is Q12 artifact)
    w(f"\n  4.5.4 Score Efficiency (pts per tool call):")
    eff_tasks = [(t, t.score / max(t.total_calls, 1))
                 for t in trajectories
                 if t.total_calls > 0 and t.score > 0 and not t.is_strict_think_only]
    eff_tasks.sort(key=lambda x: -x[1])
    if eff_tasks:
        w(f"    {'task_id':>12s} {'score':>6s} {'calls':>5s} {'pts/call':>8s} {'type':>14s}")
        w(f"    {'─'*50}")
        for t, eff in eff_tasks[:5]:
            w(f"    {t.task_id:>12d} {t.score:6.1f} {t.total_calls:5d} {eff:8.1f} {t.problem_type:>14s}")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 5: ENVIRONMENT QUALITY — API FAILURE
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 5: ENVIRONMENT QUALITY — API FAILURE")
    w(f"{'='*80}")

    # Per-tool error rates
    w(f"\n  Per-tool error rates:")
    w(f"    {'Tool':25s} {'Total':>6s} {'Errors':>6s} {'Rate':>6s}")
    w(f"    {'─'*48}")
    for tool in ALL_TOOLS:
        total = sum(t.tools_used.get(tool, 0) for t in trajectories)
        errs = sum(t.tool_errors.get(tool, 0) for t in trajectories)
        rate = errs / max(total, 1) * 100
        w(f"    {tool:25s} {total:6d} {errs:6d} {rate:5.1f}%")

    # Error rate vs score
    err_rates = [t.error_rate for t in trajectories]
    r_err = _pearson(err_rates, scores)
    if r_err is not None:
        w(f"\n  Error rate ↔ score: r={r_err:.3f}")

    # POI error rate specifics
    poi_err_tasks = [t for t in trajectories if t.poi_error_rate is not None]
    if poi_err_tasks:
        poi_errs = [t.poi_error_rate for t in poi_err_tasks]
        w(f"\n  POI search error rate: avg={_safe_mean(poi_errs)*100:.0f}%  "
          f"med={_safe_median(poi_errs)*100:.0f}%")

        # Group by POI success rate
        all_success = [t for t in poi_err_tasks if t.poi_error_rate == 0]
        all_fail = [t for t in poi_err_tasks if t.poi_error_rate == 1.0]
        partial = [t for t in poi_err_tasks if 0 < t.poi_error_rate < 1.0]
        w(f"    POI all-success: {len(all_success):4d}  avg score={_safe_mean([t.score for t in all_success]):.1f}")
        w(f"    POI partial:     {len(partial):4d}  avg score={_safe_mean([t.score for t in partial]):.1f}")
        w(f"    POI all-fail:    {len(all_fail):4d}  avg score={_safe_mean([t.score for t in all_fail]):.1f}")

    # around_search as fallback
    around_tasks = [t for t in trajectories if "around_search" in t.tools_used]
    if around_tasks:
        around_errs = [t.tool_errors.get("around_search", 0) / max(t.tools_used.get("around_search", 1), 1)
                       for t in around_tasks]
        w(f"\n  around_search as fallback: {len(around_tasks)} tasks use it, "
          f"avg error rate {_safe_mean(around_errs)*100:.0f}%")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 6: TOOL ARGUMENT QUALITY
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 6: TOOL ARGUMENT QUALITY")
    w(f"{'='*80}")

    # Analyze argument patterns
    arg_quality = defaultdict(lambda: {"correct": 0, "total": 0, "issues": []})
    for t in trajectories:
        for call in t.tool_calls:
            name = call["name"]
            args = call["args"] if isinstance(call["args"], dict) else {}
            arg_quality[name]["total"] += 1

            if name == "poi_search":
                if args.get("address"):
                    arg_quality[name]["correct"] += 1
                else:
                    arg_quality[name]["issues"].append("missing address")
            elif name == "around_search":
                if args.get("location"):
                    arg_quality[name]["correct"] += 1
                else:
                    arg_quality[name]["issues"].append("missing location")
            elif name == "direction":
                if args.get("origin") and args.get("destination"):
                    arg_quality[name]["correct"] += 1
                else:
                    arg_quality[name]["issues"].append("missing origin/destination")
            elif name == "weather":
                if args.get("city"):
                    arg_quality[name]["correct"] += 1
                else:
                    arg_quality[name]["issues"].append("missing city")
            elif name in ("search_flights", "search_train_tickets"):
                if args.get("from_city") and args.get("to_city") and args.get("date"):
                    arg_quality[name]["correct"] += 1
                else:
                    arg_quality[name]["issues"].append("missing required fields")
            else:
                arg_quality[name]["correct"] += 1

    w(f"\n  {'Tool':25s} {'Total':>5s} {'Correct':>7s} {'Rate':>6s}")
    w(f"  {'─'*48}")
    total_correct = 0
    total_all = 0
    for tool in ALL_TOOLS:
        q = arg_quality[tool]
        if q["total"] == 0:
            continue
        rate = q["correct"] / q["total"] * 100
        total_correct += q["correct"]
        total_all += q["total"]
        w(f"  {tool:25s} {q['total']:5d} {q['correct']:7d} {rate:5.1f}%")
        # Show top issues
        issue_counts = Counter(arg_quality[tool]["issues"])
        for issue, cnt in issue_counts.most_common(2):
            if cnt > 0:
                w(f"    ↳ {issue}: {cnt}")

    if total_all > 0:
        w(f"\n  Overall: {total_correct}/{total_all} ({total_correct/total_all*100:.1f}%) correct arguments")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 7: PER-TASK MINI-DIAGNOSIS
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 7: PER-TASK MINI-DIAGNOSIS")
    w(f"{'='*80}")

    # Root cause classification
    root_causes = Counter()
    for t in trajectories:
        if t.score >= 30:
            root_causes["HIGH_SCORE"] += 1
        elif t.total_calls == 0:
            root_causes["ZERO_TOOLS"] += 1
        elif t.is_think_only:
            root_causes["THINK_ONLY"] += 1
        elif t.is_synth_fail:
            root_causes["SYNTHESIS_FAIL"] += 1
        elif not t.hard_constraints.get("tool_info_used", True):
            root_causes["HC_FAIL_tool_info"] += 1
        elif not t.hard_constraints.get("format_valid", True):
            root_causes["HC_FAIL_format"] += 1
        elif not t.hard_constraints.get("required_tools_called", True):
            root_causes["HC_FAIL_tools_called"] += 1
        elif t.error_rate > 0.5:
            root_causes["API_ERROR_HIGH"] += 1
        elif t.is_mono_tool:
            root_causes["MONO_TOOL"] += 1
        elif t.llm_total < 5:
            root_causes["LLM_BOTTLENECK"] += 1
        elif t.unique_tools < 3:
            root_causes["LOW_DIVERSITY"] += 1
        else:
            root_causes["LOW_QUALITY"] += 1

    w(f"\n  Root cause distribution:")
    for cause, cnt in root_causes.most_common():
        w(f"    {cause:25s} {cnt:4d} ({cnt/n*100:5.1f}%)")

    # 7.2 Suspicious underscorers: tasks with good metrics but poor scores
    # These may indicate scoring bias, HC edge cases, or environment issues
    suspicious = []
    for t in trajectories:
        if t.score >= 15:
            continue  # not underscoring
        reasons = []
        if t.unique_tools >= 4 and t.error_rate < 0.3 and t.user_len > 1000:
            reasons.append("diverse tools + low errors + long output")
        if t.user_len > 2000 and not t.hc_all_pass and t.error_rate < 0.3:
            reasons.append("substantial output but HC fail")
        if t.code_total > 20 and t.llm_total < 5:
            reasons.append("high code but near-zero LLM")
        if t.score < 5 and t.user_len > 5000:
            if t.is_tool_call_dump:
                reasons.append(f"tool_call dump ({t.user_len} chars of <tool_call> tags, not real content)")
            else:
                reasons.append(f"massive output ({t.user_len} chars) but near-zero score")
        if reasons:
            # Find which HC failed
            failed_hc = [hc for hc, val in t.hard_constraints.items() if val is False]
            suspicious.append((t, reasons, failed_hc))

    if suspicious:
        w(f"\n  7.2 SUSPICIOUS UNDERSCORERS ({len(suspicious)} tasks with good metrics but score<15):")
        w(f"    {'task_id':>12s} {'score':>6s} {'type':>14s} {'uniq':>4s} {'err%':>5s} "
          f"{'ulen':>6s} {'code':>5s} {'llm':>5s} {'HC fail':>20s} {'Why suspicious'}")
        w(f"    {'─'*100}")
        for t, reasons, failed_hc in sorted(suspicious, key=lambda x: x[0].score):
            hc_str = ",".join(failed_hc) if failed_hc else "all pass"
            reason_str = "; ".join(reasons)
            w(f"    {t.task_id:>12d} {t.score:6.1f} {t.problem_type:>14s} {t.unique_tools:4d} "
              f"{t.error_rate*100:4.0f}% {t.user_len:6d} {t.code_total:5.1f} {t.llm_total:5.1f} "
              f"{_trunc(hc_str, 20):>20s} {reason_str}")
        # Summary insight
        hc_fail_counts = Counter()
        for _, _, fhc in suspicious:
            for hc in fhc:
                hc_fail_counts[hc] += 1
        if hc_fail_counts:
            top_block = hc_fail_counts.most_common(1)[0]
            w(f"\n    → Primary blocker: {top_block[0]} ({top_block[1]}/{len(suspicious)} suspicious tasks)")
            if top_block[0] == "required_tools_called":
                # Check what tools are missing
                for t, _, fhc in suspicious:
                    if "required_tools_called" in fhc:
                        req = set(REQUIRED_TOOLS_BY_TYPE.get(t.problem_type, []))
                        used = set(t.tools_used.keys())
                        missing = req - used
                        if missing:
                            w(f"      task {t.task_id}: missing {', '.join(sorted(missing))} "
                              f"(has {t.unique_tools}/{len(req)} required)")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 8: WINNING PATTERN & PER-STEP ALIGNMENT
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 8: WINNING PATTERN & PER-STEP ALIGNMENT")
    w(f"{'='*80}")

    # 8.1 Tool Error Rate Impact
    w(f"\n  8.1 Tool Error Rate Impact:")
    err_rates_all = [t.error_rate for t in trajectories]
    r_err_score = _pearson(err_rates_all, scores)
    if r_err_score is not None:
        w(f"    Error rate ↔ score: r={r_err_score:.3f}")

    # Tasks with vs without errors (exclude zero-tool tasks from "without errors"
    # since 0 errors from 0 calls is not meaningful clean execution)
    has_err = [t for t in trajectories if t.total_errors > 0]
    no_err = [t for t in trajectories if t.total_errors == 0 and t.total_calls > 0]
    zero_tool = [t for t in trajectories if t.total_calls == 0]
    if has_err and no_err:
        w(f"    With errors:    avg={_safe_mean([t.score for t in has_err]):.1f} (n={len(has_err)})")
        w(f"    Without errors: avg={_safe_mean([t.score for t in no_err]):.1f} (n={len(no_err)})")
    if zero_tool:
        w(f"    Zero-tool tasks: {len(zero_tool)} (excluded — 0 errors from 0 calls is not clean execution)")

    # 8.2 Winning Pattern Extraction
    # Exclude ghost high-scorers (think-only) — their tool sequences don't reflect
    # real winning strategies since they produced no user content (Q12 vulnerability)
    real_good = [t for t in good_tasks if not t.is_strict_think_only]
    n_ghost_excl = len(good_tasks) - len(real_good)
    w(f"\n  8.2 Winning Patterns:")
    if real_good:
        excl_note = f" (excl. {n_ghost_excl} ghost high-scorers)" if n_ghost_excl else ""
        w(f"    High-scoring tasks (≥30): {len(real_good)}{excl_note}")

        # Common opening in good tasks
        good_openings = Counter()
        for t in real_good:
            seq = tuple(t.tool_sequence[:3])
            if seq:
                good_openings[seq] += 1
        w(f"    Most common openings in good+ tasks:")
        for seq, cnt in good_openings.most_common(5):
            w(f"      {' → '.join(seq):50s} {cnt:3d} ({cnt/len(real_good)*100:.0f}%)")

        # Good task characteristics (excluding ghost high-scorers)
        w(f"\n    Good+ task profile:")
        w(f"      Unique tools:    avg={_safe_mean([t.unique_tools for t in real_good]):.1f}")
        w(f"      Total calls:     avg={_safe_mean([t.total_calls for t in real_good]):.1f}")
        w(f"      Error rate:      avg={_safe_mean([t.error_rate for t in real_good])*100:.0f}%")
        w(f"      Response len:    avg={_safe_mean([t.user_len for t in real_good]):.0f}")
        w(f"      Reasoning:       avg={_safe_mean([t.reasoning_count for t in real_good]):.1f}")
    elif good_tasks and not real_good:
        w(f"    All {len(good_tasks)} good+ tasks are ghost high-scorers (think-only) — no real winning patterns")
    else:
        w(f"    No good+ tasks found (all scores < 30)")

    # 8.3 Per-Step Reward Alignment
    w(f"\n  8.3 Per-Step Reward Alignment:")
    tasks_with_sr = [t for t in trajectories if t.step_rewards]
    if tasks_with_sr:
        max_steps = max(len(t.step_rewards) for t in tasks_with_sr)
        w(f"    Tasks with step rewards: {len(tasks_with_sr)}")
        w(f"    Max steps: {max_steps}")

        # Per-step score correlation
        w(f"\n    Step-score correlation (Pearson r):")
        w(f"    {'Step':>6s} {'r':>8s} {'n':>5s}")
        w(f"    {'─'*22}")
        best_step = (0, 0.0, 0)
        for step in range(min(max_steps, 15)):
            step_vals = []
            score_vals = []
            for t in tasks_with_sr:
                if step < len(t.step_rewards):
                    step_vals.append(t.step_rewards[step])
                    score_vals.append(t.score)
            r_step = _pearson(step_vals, score_vals)
            if r_step is not None:
                flag = " ⚠ n<20" if len(step_vals) < 20 else ""
                w(f"    {step+1:6d} {r_step:8.3f} {len(step_vals):5d}{flag}")
                step_n = len(step_vals)
                # Prefer steps with n>=20 (reliable); only pick n<20 if no reliable step exists
                cur_n = best_step[2]
                if step_n >= 20 and cur_n >= 20:
                    # Both reliable: pick higher |r|
                    if abs(r_step) > abs(best_step[1]):
                        best_step = (step + 1, r_step, step_n)
                elif step_n >= 20 and cur_n < 20:
                    # New step is reliable, current isn't: always prefer reliable
                    best_step = (step + 1, r_step, step_n)
                elif step_n < 20 and cur_n < 20 and step_n >= 10:
                    # Both unreliable: pick higher |r| with min n=10
                    if abs(r_step) > abs(best_step[1]):
                        best_step = (step + 1, r_step, step_n)
                # else: new step n<20 but current n>=20 — keep current (reliable)

        if best_step[1] != 0:
            warn = " (low n, interpret cautiously)" if best_step[2] < 20 else ""
            w(f"\n    Most predictive step: step {best_step[0]} (r={best_step[1]:.3f}, n={best_step[2]}){warn}")
    else:
        w(f"    No step reward data available")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 9: POI API FAILURE & FABRICATION ANALYSIS
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 9: POI API FAILURE & FABRICATION ANALYSIS")
    w(f"{'='*80}")

    # 9.1 POI Search Success Categorization
    w(f"\n  9.1 POI Search Success Categorization:")
    tasks_with_poi = [t for t in trajectories if "poi_search" in t.tools_used]
    if tasks_with_poi:
        total_poi_calls = sum(t.tools_used.get("poi_search", 0) for t in tasks_with_poi)
        total_poi_errs = sum(t.tool_errors.get("poi_search", 0) for t in tasks_with_poi)
        w(f"    Total POI calls: {total_poi_calls}, errors: {total_poi_errs} ({total_poi_errs/max(total_poi_calls,1)*100:.0f}%)")

    # 9.2 Fabrication Detection
    w(f"\n  9.2 Fabrication Detection:")
    tasks_with_output_pois = [t for t in trajectories if t.output_poi_names]
    if tasks_with_output_pois:
        total_output = sum(len(t.output_poi_names) for t in tasks_with_output_pois)
        total_fab = sum(t.fab_count for t in tasks_with_output_pois)
        w(f"    Tasks with output POIs: {len(tasks_with_output_pois)}")
        w(f"    Total output POI names: {total_output}")
        w(f"    Fabricated: {total_fab} ({total_fab/max(total_output,1)*100:.0f}%)")

        # Fabrication vs score
        fab_rates = [t.fab_rate for t in tasks_with_output_pois]
        fab_scores = [t.score for t in tasks_with_output_pois]

        if _safe_stdev(fab_rates) < 0.01:
            w(f"    Fabrication ↔ score: N/A (no variance in fabrication rate)")
        else:
            r_fab = _pearson(fab_rates, fab_scores)
            n_fab = len(fab_rates)
            if r_fab is not None:
                warn = ""
                if n_fab < 30:
                    warn = f" ⚠ small sample — may be unreliable"
                elif n_fab < 50:
                    warn = f" (moderate sample)"
                w(f"    Fabrication rate ↔ score: r={r_fab:.3f} (n={n_fab}){warn}")

        # 9.2.1 Fabrication by problem type
        w(f"\n  9.2.1 Fabrication Rate by Problem Type:")
        w(f"    {'Type':14s} {'w/POI':>5s} {'Total':>5s} {'Cov%':>4s}  "
          f"{'Out':>4s} {'Grnd':>4s} {'Fab':>4s} {'Fab%':>4s}  "
          f"{'AvgSc':>5s} {'POIe%':>5s}")
        w(f"    {'─'*70}")
        for ptype in PROBLEM_TYPES:
            tt_all = [t for t in trajectories if t.problem_type == ptype]
            tt_fab = [t for t in tasks_with_output_pois if t.problem_type == ptype]
            if not tt_all:
                continue
            n_total = len(tt_all)
            n_with = len(tt_fab)
            cov_pct = n_with / n_total * 100 if n_total > 0 else 0
            if not tt_fab:
                w(f"    {ptype:14s} {n_with:5d} {n_total:5d} {cov_pct:3.0f}%  "
                  f"{'—':>4s} {'—':>4s} {'—':>4s} {'—':>4s}  {'—':>5s} {'—':>5s}")
                continue
            t_out = sum(len(t.output_poi_names) for t in tt_fab)
            t_fab = sum(t.fab_count for t in tt_fab)
            t_grnd = t_out - t_fab
            fab_pct = t_fab / max(t_out, 1) * 100
            avg_sc = _safe_mean([t.score for t in tt_fab])
            avg_pe = _safe_mean([t.poi_error_rate for t in tt_fab
                                  if t.poi_error_rate is not None]) * 100
            w(f"    {ptype:14s} {n_with:5d} {n_total:5d} {cov_pct:3.0f}%  "
              f"{t_out:4d} {t_grnd:4d} {t_fab:4d} {fab_pct:3.0f}%  "
              f"{avg_sc:5.1f} {avg_pe:4.0f}%")

        # Coverage summary: how many tasks are analyzable for fabrication
        n_analyzable = len(tasks_with_output_pois)
        n_total_all = len(trajectories)
        n_think_only = sum(1 for t in trajectories if t.is_think_only)
        w(f"\n    Coverage: {n_analyzable}/{n_total_all} tasks have output POIs "
          f"({n_analyzable/max(n_total_all,1)*100:.0f}%)")
        if n_think_only > 0:
            w(f"    → {n_think_only} think-only tasks excluded from fabrication analysis")

        # Insight: types that depend on POI data should fabricate more
        poi_dep_types = {"food_tour", "single_poi", "family_study", "multiday"}
        transport_types = {"intercity", "business", "hybrid"}
        poi_dep_fab = [t.fab_rate for t in tasks_with_output_pois
                       if t.problem_type in poi_dep_types]
        transport_fab = [t.fab_rate for t in tasks_with_output_pois
                         if t.problem_type in transport_types]
        if poi_dep_fab and transport_fab:
            pd_avg = _safe_mean(poi_dep_fab) * 100
            tr_avg = _safe_mean(transport_fab) * 100
            n_pd = len(poi_dep_fab)
            n_tr = len(transport_fab)
            small = " (small sample)" if n_pd < 5 or n_tr < 5 else ""
            w(f"\n    POI-dependent types avg fab: {pd_avg:.0f}% (n={n_pd})  |  "
              f"Transport types avg fab: {tr_avg:.0f}% (n={n_tr}){small}")
            if pd_avg > tr_avg + 10:
                w(f"    → POI-dependent types fabricate more — expected since they rely on POI data")
            elif abs(pd_avg - tr_avg) <= 10:
                w(f"    → Fabrication uniform across types — suggests model-level behavior, not type-driven")
            else:
                w(f"    → Transport types show higher fabrication — may reflect output length/detail correlation")
    else:
        w(f"    No tasks with detectable output POIs")

    # 9.2.2 Ghost High-Scorer Detail (strict think-only: user_len<100 AND score>=30)
    ghost_list = [t for t in trajectories if t.is_strict_think_only and t.score >= 30]
    if ghost_list:
        w(f"\n  9.2.2 Ghost High-Scorers ({len(ghost_list)} think-only tasks with score≥30):")
        w(f"    {'task_id':>12s} {'score':>6s} {'type':>14s} {'code':>5s} {'llm':>5s} "
          f"{'think':>6s} {'user':>6s} {'tools':>5s} {'HC':>4s}")
        w(f"    {'─'*72}")
        for t in sorted(ghost_list, key=lambda x: -x.score):
            hc = "PASS" if t.hc_all_pass else "FAIL"
            w(f"    {t.task_id:>12d} {t.score:6.1f} {t.problem_type:>14s} "
              f"{t.code_total:5.1f} {t.llm_total:5.1f} {t.think_len:6d} {t.user_len:6d} "
              f"{t.unique_tools:5d} {hc:>4s}")
        ghost_hc_pass = sum(1 for t in ghost_list if t.hc_all_pass)
        w(f"    HC pass rate: {ghost_hc_pass}/{len(ghost_list)} "
          f"({ghost_hc_pass/len(ghost_list)*100:.0f}%) — confirms Q12 vulnerability")
        # Score source breakdown
        ghost_code = _safe_mean([t.code_total for t in ghost_list])
        ghost_llm = _safe_mean([t.llm_total for t in ghost_list])
        w(f"    Avg code={ghost_code:.1f}  avg llm={ghost_llm:.1f} — "
          f"{'code-dominated' if ghost_code > ghost_llm + 5 else 'llm-dominated' if ghost_llm > ghost_code + 5 else 'balanced'}")

    # 9.3 Environment Fix Recommendations
    w(f"\n  9.3 CONSOLIDATED ENVIRONMENT FIX RECOMMENDATIONS:")
    poi_total = sum(t.tools_used.get("poi_search", 0) for t in trajectories)
    poi_errs = sum(t.tool_errors.get("poi_search", 0) for t in trajectories)
    around_total = sum(t.tools_used.get("around_search", 0) for t in trajectories)
    around_errs = sum(t.tool_errors.get("around_search", 0) for t in trajectories)

    poi_err_pct = poi_errs / max(poi_total, 1) * 100
    around_err_pct = around_errs / max(around_total, 1) * 100

    if poi_err_pct > 30:
        w(f"    P1 API Infrastructure: poi_search {poi_err_pct:.0f}% error rate")
        w(f"       → Fix API rate limits or increase quotas")
    if around_err_pct > 30:
        w(f"    P1 API Infrastructure: around_search {around_err_pct:.0f}% error rate (shared quota)")
    # Fabrication recommendation — guarded by correlation strength (Q4: high fab rates
    # are often regex noise; only flag when fab actually correlates with score inflation)
    if tasks_with_output_pois:
        fab_pct_total = total_fab / max(total_output, 1) * 100
        fab_rates_all = [t.fab_rate for t in tasks_with_output_pois]
        fab_scores_all = [t.score for t in tasks_with_output_pois]
        r_fab_global = _pearson(fab_rates_all, fab_scores_all) if _safe_stdev(fab_rates_all) > 0.01 else None
        n_fab_sample = len(tasks_with_output_pois)
        # P2 requires: r>0.25 AND n>=20 — avoids small-sample false positives
        # (iter 29 confirmed: all recent-N positive correlations vanish at full-sample)
        if fab_pct_total > 50 and r_fab_global is not None and r_fab_global > 0.25 and n_fab_sample >= 20:
            w(f"    P2 Scoring: Fabrication {fab_pct_total:.0f}% AND positively correlated with score "
              f"(r={r_fab_global:.3f}, n={n_fab_sample})")
            w(f"       → Scoring may reward fabrication; review poi_names_verified HC threshold")
        elif fab_pct_total > 50 and r_fab_global is not None and r_fab_global > 0.15:
            # Weak signal — report as Info, not P2
            warn = " ⚠ small sample" if n_fab_sample < 20 else ""
            w(f"    Info: Fabrication {fab_pct_total:.0f}%, weak positive correlation "
              f"(r={r_fab_global:.3f}, n={n_fab_sample}){warn} — verify with --all")
        elif fab_pct_total > 50:
            w(f"    Info: High fabrication rate ({fab_pct_total:.0f}%) detected but NOT correlated with higher scores")
            w(f"       → Likely regex noise or model using pretrained knowledge; low priority")

    # Zero-tool tasks
    zero_tool = [t for t in trajectories if t.total_calls == 0]
    if zero_tool:
        w(f"    P2 Zero-tool tasks: {len(zero_tool)}/{n} tasks made 0 tool calls (all score=0)")
        w(f"       → Model fails to initiate tool usage; check system prompt delivery")

    w(f"    P3 Reward Shaping: Step reward concordance may need fundamental redesign (see Section 8.3)")

    # ════════════════════════════════════════════════════════════════════════
    # SECTION 10: SFT STRATEGY & DATA SYNTHESIS RECOMMENDATIONS
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"SECTION 10: SFT STRATEGY & DATA SYNTHESIS RECOMMENDATIONS")
    w(f"{'='*80}")

    # 10.1 Optimal Tool Sequence (require >=2 real good+ tasks per type)
    # Exclude ghost high-scorers — their tool sequences don't reflect real strategies
    sft_good = [t for t in good_tasks if not t.is_strict_think_only]
    n_sft_excl = len(good_tasks) - len(sft_good)
    w(f"\n  10.1 Optimal Tool Sequence:")
    if n_sft_excl:
        w(f"    (excl. {n_sft_excl} ghost high-scorers from pattern extraction)")
    if sft_good:
        shown = 0
        for ptype in PROBLEM_TYPES:
            gt = [t for t in sft_good if t.problem_type == ptype]
            if len(gt) < 2:
                continue
            # Most common opening (first 3 tools) — more robust than full sequence
            openings = Counter(tuple(t.tool_sequence[:3]) for t in gt if len(t.tool_sequence) >= 3)
            if not openings:
                continue
            top_open, top_cnt = openings.most_common(1)[0]
            consensus = top_cnt / len(gt) * 100
            avg_score = _safe_mean([t.score for t in gt])
            w(f"    {ptype:14s}: {' → '.join(top_open)} ({top_cnt}/{len(gt)}, {consensus:.0f}% consensus, avg={avg_score:.1f})")
            shown += 1
        if shown == 0:
            w(f"    Insufficient good+ data (need >=2 real non-ghost tasks per type)")
    else:
        w(f"    No good+ tasks found (or all are ghost high-scorers)")

    # 10.2 Per-Type SFT Templates
    w(f"\n  10.2 Per-Type SFT Needs:")
    w(f"    {'Type':14s} {'Required tools':>5s} {'Gap to 50':>9s} {'Priority':>8s}")
    w(f"    {'─'*42}")
    for ptype in PROBLEM_TYPES:
        tt = [t for t in trajectories if t.problem_type == ptype]
        if not tt:
            continue
        avg = _safe_mean([t.score for t in tt])
        gap = 50 - avg
        req = len(REQUIRED_TOOLS_BY_TYPE.get(ptype, []))
        priority = "HIGH" if gap > 35 else "MED" if gap > 20 else "LOW"
        w(f"    {ptype:14s} {req:5d}       {gap:7.1f}  {priority:>8s}")

    # 10.3 Consolidated SFT Action Plan
    # Synthesize top insights from F1-F10, frequency analysis, opening gap, and underscorers
    w(f"\n  10.3 CONSOLIDATED SFT ACTION PLAN:")
    action_num = 0

    # A0: Opening strategy gap (most actionable single change when detected)
    if opening_gap:
        best_s, best_a, mc_s, mc_a = opening_gap
        action_num += 1
        best_str = " → ".join(best_s)
        mc_str = " → ".join(mc_s)
        w(f"    A{action_num}. [HIGH] Switch opening strategy: '{best_str}' (avg={best_a:.0f}) "
          f"instead of '{mc_str}' (avg={mc_a:.0f})")
        w(f"       +{best_a-mc_a:.0f} pts score gap — highest single-change impact")

    # A1: Score bottleneck → primary training focus
    action_num += 1
    if score_bottleneck == "LLM":
        w(f"    A{action_num}. [HIGH] Improve LLM-scored dimensions (currently {llm_util:.0f}% vs code {code_util:.0f}%)")
        w(f"       Focus: output structure (sections/headers), reasoning depth, factual grounding")
        # Check if suspicious underscorers confirm this
        if suspicious:
            hc_pass_low = [t for t, _, fhc in suspicious if not fhc]
            if hc_pass_low:
                w(f"       Evidence: {len(hc_pass_low)} tasks pass all HC + have good tools but score<15 (LLM bottleneck)")
    else:
        w(f"    A{action_num}. [HIGH] Improve code-scored dimensions (currently {code_util:.0f}% vs LLM {llm_util:.0f}%)")
        w(f"       Focus: tool data extraction, content completeness, transport grounding")

    # A2: OVER-CALLED tool → reduce (with causal explanation based on error rate)
    # Use s3_good (ghost-excluded) for consistent comparison with Section 3
    if s3_good and poor_tasks:
        over_tools = []
        for tool in ALL_TOOLS:
            gf = _safe_mean([t.tools_used.get(tool, 0) for t in s3_good])
            pf = _safe_mean([t.tools_used.get(tool, 0) for t in poor_tasks])
            if pf - gf > 1.0 and pf >= 2.0:
                t_total = sum(t.tools_used.get(tool, 0) for t in trajectories)
                t_errors = sum(t.tool_errors.get(tool, 0) for t in trajectories)
                t_err_rate = t_errors / max(t_total, 1) if t_total > 0 else 0
                over_tools.append((tool, gf, pf, t_err_rate))
        if over_tools:
            action_num += 1
            tool_str = ", ".join(f"{t} ({pf:.0f}→{gf:.0f})" for t, gf, pf, _ in over_tools)
            w(f"    A{action_num}. [HIGH] Reduce repetitive calls: {tool_str}")
            # Provide causal explanation based on error rate
            high_err_tools = [(t, er) for t, _, _, er in over_tools if er > 0.50]
            low_err_tools = [(t, er) for t, _, _, er in over_tools if er <= 0.50]
            if high_err_tools and not low_err_tools:
                w(f"       Cause: API failures ({high_err_tools[0][1]*100:.0f}% err) — "
                  f"stop retrying after 1-2 failures, switch to other tool types")
            elif high_err_tools and low_err_tools:
                he_str = ", ".join(f"{t} ({er*100:.0f}% err)" for t, er in high_err_tools)
                w(f"       {he_str}: stop retrying failed API; others: Good+ diversifies earlier")
            else:
                w(f"       Good+ tasks diversify earlier — redirect budget to transport/weather tools")

    # A3: UNDER-CALLED tool → increase (skip tools with >50% error rate)
    if s3_good and poor_tasks:
        under_tools = []
        high_err_skipped = []
        for tool in ALL_TOOLS:
            g_adopt = sum(1 for t in s3_good if tool in t.tools_used) / len(s3_good) * 100
            p_adopt = sum(1 for t in poor_tasks if tool in t.tools_used) / len(poor_tasks) * 100
            if g_adopt - p_adopt > 30:
                # Check tool error rate — don't recommend increasing a failing tool
                t_total = sum(t.tools_used.get(tool, 0) for t in trajectories)
                t_errors = sum(t.tool_errors.get(tool, 0) for t in trajectories)
                t_err_rate = t_errors / max(t_total, 1) if t_total > 0 else 0
                if t_err_rate > 0.50:
                    high_err_skipped.append((tool, g_adopt, p_adopt, t_err_rate))
                else:
                    under_tools.append((tool, g_adopt, p_adopt))
        if under_tools:
            action_num += 1
            tool_str = ", ".join(f"{t} (+{ga-pa:.0f}pp)" for t, ga, pa in under_tools)
            w(f"    A{action_num}. [MED] Increase adoption of: {tool_str}")
            w(f"       These tools have large Good+ vs Poor adoption gaps")
        if high_err_skipped:
            skipped_str = ", ".join(f"{t} ({ter*100:.0f}% err)" for t, _, _, ter in high_err_skipped)
            w(f"       Skipped (high error rate): {skipped_str}")

    # A4: Think-only / synth-fail → response generation
    to_pct = len(think_only) / n * 100 if think_only else 0
    sf_list = [t for t in trajectories if t.is_synth_fail]
    sf_pct = len(sf_list) / n * 100 if sf_list else 0
    no_response_pct = to_pct + sf_pct
    if no_response_pct > 15:
        action_num += 1
        parts = []
        if to_pct > 5:
            parts.append(f"think-only {to_pct:.0f}%")
        if sf_pct > 5:
            parts.append(f"synth-fail {sf_pct:.0f}%")
        w(f"    A{action_num}. [MED] Fix response generation: {' + '.join(parts)} = {no_response_pct:.0f}% no-output")
        w(f"       SFT data should emphasize producing user-facing plans, not just internal reasoning")

    # A5: Top HC failure → specific fix
    if hc_failures:
        top_hc = max(hc_failures, key=hc_failures.get)
        top_rate = hc_failures[top_hc] / n * 100
        if top_rate > 15:
            action_num += 1
            fix_map = {
                "required_tools_called": "call all required tool types for each problem type",
                "tool_info_used": "reference tool-returned data in the output (IC threshold)",
                "format_valid": "ensure output has >200 chars with travel plan structure",
                "poi_names_verified": "use POI names from tool results, not pre-trained knowledge",
                "transport_grounded": "only cite flight/train IDs that appear in tool results",
            }
            fix = fix_map.get(top_hc, "address the constraint")
            w(f"    A{action_num}. [MED] Fix {top_hc} ({top_rate:.0f}% fail): {fix}")

    if action_num == 0:
        w(f"    No urgent actions — miner is performing well")
    else:
        w(f"\n    Total actions: {action_num}")

    # ════════════════════════════════════════════════════════════════════════
    # ALL TASKS TABLE
    # ════════════════════════════════════════════════════════════════════════
    w(f"\n{'='*80}")
    w(f"ALL TASKS ({len(trajectories)})")
    w(f"{'='*80}")

    w(f"\n  {'task_id':>12s} {'score':>6s} {'tier':>5s} {'type':>14s} {'dest':>8s} "
      f"{'uniq':>4s} {'calls':>5s} {'err%':>5s} {'user_len':>8s} {'HC':>4s}")
    w(f"  {'─'*85}")

    for t in sorted(trajectories, key=lambda x: -x.score):
        hc = "PASS" if t.hc_all_pass else "FAIL"
        tier_mark = "★" if t.tier == "good+" else "·" if t.tier == "acceptable" else " "
        err_pct = t.error_rate * 100
        think_mark = "T" if t.is_think_only else "S" if t.is_synth_fail else " "
        api_mark = "A" if t.is_api_blocked and t.score < 15 else " "
        w(f"  {t.task_id:>12d} {t.score:6.1f} {tier_mark:>1s}{t.tier:>4s} {t.problem_type:>14s} "
          f"{_trunc(t.destination, 8):>8s} {t.unique_tools:4d} {t.total_calls:5d} {err_pct:4.0f}% "
          f"{t.user_len:8d} {hc:>4s} {think_mark}{api_mark}")

    return "\n".join(lines)


# ── Cross-Miner Comparison ──────────────────────────────────────────────────

async def cross_miner_step_compare(
    uid1: int, uid2: int,
    source: str = "sampling",
    recent: Optional[int] = None,
) -> str:
    """Compare two miners on navworld trajectories."""
    lines = []
    w = lines.append

    info1, raw1 = await fetch_trajectories(uid1, "navworld", source)
    info2, raw2 = await fetch_trajectories(uid2, "navworld", source)

    trajs1 = [TrajectoryData(r) for r in raw1]
    trajs2 = [TrajectoryData(r) for r in raw2]

    if recent:
        trajs1.sort(key=lambda t: t.timestamp, reverse=True)
        trajs2.sort(key=lambda t: t.timestamp, reverse=True)
        trajs1 = trajs1[:recent]
        trajs2 = trajs2[:recent]

    w(f"\n{'='*80}")
    w(f"CROSS-MINER COMPARISON: UID {uid1} vs UID {uid2}")
    w(f"{'='*80}")

    w(f"\n  {'Metric':25s} {'UID '+str(uid1):>12s} {'UID '+str(uid2):>12s} {'Delta':>10s}")
    w(f"  {'─'*65}")

    for label, t_list1, t_list2 in [
        ("Tasks", trajs1, trajs2),
    ]:
        w(f"  {'Tasks':25s} {len(t_list1):12d} {len(t_list2):12d}")

    def _cmp(label, vals1, vals2, fmt=".1f"):
        a1 = _safe_mean(vals1)
        a2 = _safe_mean(vals2)
        w(f"  {label:25s} {a1:12{fmt}} {a2:12{fmt}} {a1-a2:+10{fmt}}")

    _cmp("Avg score", [t.score for t in trajs1], [t.score for t in trajs2])
    _cmp("Unique tools", [t.unique_tools for t in trajs1], [t.unique_tools for t in trajs2])
    _cmp("Total calls", [t.total_calls for t in trajs1], [t.total_calls for t in trajs2])
    _cmp("Error rate %", [t.error_rate*100 for t in trajs1], [t.error_rate*100 for t in trajs2])
    _cmp("POI err %", [t.poi_error_rate*100 for t in trajs1 if t.poi_error_rate is not None],
         [t.poi_error_rate*100 for t in trajs2 if t.poi_error_rate is not None])
    _cmp("Think-only %", [100 if t.is_think_only else 0 for t in trajs1],
         [100 if t.is_think_only else 0 for t in trajs2])
    _cmp("HC all-pass %", [100 if t.hc_all_pass else 0 for t in trajs1],
         [100 if t.hc_all_pass else 0 for t in trajs2])

    # Per-type comparison
    w(f"\n  Per-type avg score:")
    w(f"    {'Type':14s} {'UID '+str(uid1):>8s} {'UID '+str(uid2):>8s} {'Delta':>8s}")
    w(f"    {'─'*42}")
    for ptype in PROBLEM_TYPES:
        s1 = [t.score for t in trajs1 if t.problem_type == ptype]
        s2 = [t.score for t in trajs2 if t.problem_type == ptype]
        if s1 or s2:
            a1 = _safe_mean(s1)
            a2 = _safe_mean(s2)
            w(f"    {ptype:14s} {a1:8.1f} {a2:8.1f} {a1-a2:+8.1f}")

    # Cross-miner POI failure correlation
    common_tasks = set(t.task_id for t in trajs1) & set(t.task_id for t in trajs2)
    if common_tasks:
        map1 = {t.task_id: t for t in trajs1}
        map2 = {t.task_id: t for t in trajs2}

        both_fail = sum(1 for tid in common_tasks
                        if map1[tid].poi_error_rate and map1[tid].poi_error_rate > 0.5
                        and map2[tid].poi_error_rate and map2[tid].poi_error_rate > 0.5)
        both_success = sum(1 for tid in common_tasks
                          if (map1[tid].poi_error_rate is not None and map1[tid].poi_error_rate == 0)
                          and (map2[tid].poi_error_rate is not None and map2[tid].poi_error_rate == 0))

        w(f"\n  Cross-miner POI failure consistency ({len(common_tasks)} common tasks):")
        w(f"    Both fail:    {both_fail} ({both_fail/max(len(common_tasks),1)*100:.1f}%)")
        w(f"    Both success: {both_success} ({both_success/max(len(common_tasks),1)*100:.1f}%)")

        # POI error rate correlation
        poi1 = []
        poi2 = []
        for tid in common_tasks:
            if map1[tid].poi_error_rate is not None and map2[tid].poi_error_rate is not None:
                poi1.append(map1[tid].poi_error_rate)
                poi2.append(map2[tid].poi_error_rate)
        r_poi = _pearson(poi1, poi2)
        if r_poi is not None:
            w(f"    POI error rate correlation: r={r_poi:.3f}")

    # Temporal trend comparison
    if len(trajs1) >= 10 and len(trajs2) >= 10:
        w(f"\n  CROSS-MINER TEMPORAL TREND:")
        for uid_label, trajs in [(uid1, trajs1), (uid2, trajs2)]:
            trajs_sorted = sorted(trajs, key=lambda t: t.timestamp)
            q = max(len(trajs_sorted) // 4, 1)
            q1_avg = _safe_mean([t.score for t in trajs_sorted[:q]])
            q4_avg = _safe_mean([t.score for t in trajs_sorted[-q:]])
            q1_poi = _safe_mean([t.poi_error_rate for t in trajs_sorted[:q] if t.poi_error_rate is not None]) * 100
            q4_poi = _safe_mean([t.poi_error_rate for t in trajs_sorted[-q:] if t.poi_error_rate is not None]) * 100
            w(f"    UID {uid_label}: score {q1_avg:.1f}→{q4_avg:.1f} ({q4_avg-q1_avg:+.1f}), "
              f"POI err {q1_poi:.0f}%→{q4_poi:.0f}% ({q4_poi-q1_poi:+.0f}pp)")

    return "\n".join(lines)


async def multi_miner_step_compare(
    uids: List[int],
    source: str = "sampling",
    recent: Optional[int] = None,
) -> str:
    """Compare multiple miners on navworld trajectories."""
    lines = []
    w = lines.append

    all_trajs = {}
    for uid in uids:
        info, raw = await fetch_trajectories(uid, "navworld", source)
        trajs = [TrajectoryData(r) for r in raw]
        if recent:
            trajs.sort(key=lambda t: t.timestamp, reverse=True)
            trajs = trajs[:recent]
        all_trajs[uid] = trajs

    w(f"\n{'='*80}")
    w(f"MULTI-MINER COMPARISON: UIDs {','.join(map(str, uids))}")
    w(f"{'='*80}")

    # Summary table
    w(f"\n  {'UID':>5s} {'Tasks':>5s} {'Avg':>6s} {'Med':>6s} {'Good+':>5s} {'Err%':>5s} "
      f"{'POI%':>5s} {'T-only%':>7s} {'HC%':>5s}")
    w(f"  {'─'*55}")

    for uid in uids:
        trajs = all_trajs[uid]
        if not trajs:
            w(f"  {uid:5d}  (no data)")
            continue
        scores = [t.score for t in trajs]
        good = sum(1 for t in trajs if t.tier == "good+")
        err = _safe_mean([t.error_rate for t in trajs]) * 100
        poi = _safe_mean([t.poi_error_rate for t in trajs if t.poi_error_rate is not None]) * 100
        to = sum(1 for t in trajs if t.is_think_only) / len(trajs) * 100
        hc = sum(1 for t in trajs if t.hc_all_pass) / len(trajs) * 100
        w(f"  {uid:5d} {len(trajs):5d} {_safe_mean(scores):6.1f} {_safe_median(scores):6.1f} "
          f"{good:5d} {err:4.0f}% {poi:4.0f}% {to:6.1f}% {hc:4.0f}%")

    # Per-type comparison
    w(f"\n  Per-type avg score:")
    header = f"  {'Type':14s}"
    for uid in uids:
        header += f" {'UID '+str(uid):>8s}"
    w(header)
    w(f"  {'─'*(14 + 9*len(uids))}")

    for ptype in PROBLEM_TYPES:
        row = f"  {ptype:14s}"
        for uid in uids:
            s = [t.score for t in all_trajs[uid] if t.problem_type == ptype]
            row += f" {_safe_mean(s):8.1f}" if s else f" {'N/A':>8s}"
        w(row)

    # Cross-miner POI failure consistency
    if len(uids) >= 2:
        w(f"\n  CROSS-MINER POI FAILURE CONSISTENCY:")
        for i in range(len(uids)):
            for j in range(i + 1, len(uids)):
                uid_a, uid_b = uids[i], uids[j]
                common = set(t.task_id for t in all_trajs[uid_a]) & set(t.task_id for t in all_trajs[uid_b])
                if not common:
                    continue
                map_a = {t.task_id: t for t in all_trajs[uid_a]}
                map_b = {t.task_id: t for t in all_trajs[uid_b]}
                poi_a = [map_a[tid].poi_error_rate for tid in common if map_a[tid].poi_error_rate is not None]
                poi_b = [map_b[tid].poi_error_rate for tid in common if map_b[tid].poi_error_rate is not None]
                r = _pearson(poi_a[:len(poi_b)], poi_b[:len(poi_a)])
                if r is not None:
                    w(f"    {uid_a} vs {uid_b}: r={r:.3f} ({len(common)} common tasks)")

    # Temporal trend
    w(f"\n  CROSS-MINER TEMPORAL TREND:")
    for uid in uids:
        trajs = sorted(all_trajs[uid], key=lambda t: t.timestamp)
        if len(trajs) < 10:
            w(f"    UID {uid}: insufficient data ({len(trajs)} tasks)")
            continue
        q = max(len(trajs) // 4, 1)
        q1_avg = _safe_mean([t.score for t in trajs[:q]])
        q4_avg = _safe_mean([t.score for t in trajs[-q:]])
        q1_poi = _safe_mean([t.poi_error_rate for t in trajs[:q] if t.poi_error_rate is not None]) * 100
        q4_poi = _safe_mean([t.poi_error_rate for t in trajs[-q:] if t.poi_error_rate is not None]) * 100
        w(f"    UID {uid}: score {q1_avg:.1f}→{q4_avg:.1f} ({q4_avg-q1_avg:+.1f}), "
          f"POI err {q1_poi:.0f}%→{q4_poi:.0f}% ({q4_poi-q1_poi:+.0f}pp)")

    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(description="NAVWORLD (travel planning) trajectory analysis")
    parser.add_argument("--uid", type=int, help="Miner UID (0-255)")
    parser.add_argument("--all", action="store_true",
                        help="Use all historical data (default: active sampling list)")
    parser.add_argument("--recent", type=int, default=None,
                        help="Only analyze N most recent trajectories")
    parser.add_argument("--limit", type=int, default=None,
                        help="Alias for --recent")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file")
    parser.add_argument("--inspect", action="store_true", help="Dump raw trajectory data")
    parser.add_argument("--json", action="store_true", help="Dump raw JSON")
    parser.add_argument("--deep", type=int, default=None,
                        help="Deep dump a specific task_id")
    parser.add_argument("--compare", type=str, default=None,
                        help="Compare with another UID (e.g. --compare 78)")
    parser.add_argument("--multi-compare", type=str, default=None,
                        help="Compare multiple UIDs (e.g. --multi-compare 57,78,142)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    source = "all" if args.all else "sampling"
    recent = args.recent or args.limit

    # Multi-compare mode
    if args.multi_compare:
        uids = [int(u.strip()) for u in args.multi_compare.split(",")]
        print(f"Multi-comparing UIDs: {uids}", file=sys.stderr)
        report = await multi_miner_step_compare(uids, source=source, recent=recent)
        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w") as f:
                f.write(report + "\n")
            print(f"Report written to {args.output}", file=sys.stderr)
        else:
            print(report)
        await close_db()
        return

    # Compare mode
    if args.compare:
        uids = [int(u.strip()) for u in args.compare.split(",")]
        if not args.uid:
            print("Error: --uid required for --compare", file=sys.stderr)
            sys.exit(1)
        for other_uid in uids:
            report = await cross_miner_step_compare(args.uid, other_uid, source=source, recent=recent)
            if args.output:
                os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
                with open(args.output, "a") as f:
                    f.write(report + "\n")
                print(f"Report appended to {args.output}", file=sys.stderr)
            else:
                print(report)
        await close_db()
        return

    # Single-miner mode requires --uid
    if not args.uid and args.uid != 0:
        parser.print_help()
        sys.exit(1)

    print(f"Fetching trajectories for UID={args.uid} env=navworld source={source} ...",
          file=sys.stderr)
    miner_info, raw_trajectories = await fetch_trajectories(args.uid, "navworld", source=source)

    if not raw_trajectories:
        print(f"No trajectories found for UID={args.uid}", file=sys.stderr)
        await close_db()
        return

    hotkey = miner_info.get("hotkey", "?")[:16]
    revision = miner_info.get("model_revision", "?")[:12]
    sl_size = miner_info.get("sampling_list_size", 0)
    matched = miner_info.get("matched", len(raw_trajectories))
    match_pct = matched / max(sl_size, 1) * 100
    print(f"  Hotkey: {hotkey}...  Revision: {revision}...", file=sys.stderr)
    print(f"  Sampling list: {sl_size} task_ids, {matched} matched ({match_pct:.1f}%)",
          file=sys.stderr)

    if recent:
        sorted_trajs = sorted(raw_trajectories,
                              key=lambda t: t.get("timestamp", 0) or 0, reverse=True)
        raw_trajectories = sorted_trajs[:recent]
        print(f"  Limited to {len(raw_trajectories)} most recent trajectories", file=sys.stderr)

    if args.inspect:
        report = inspect_extra(raw_trajectories)
        print(report)
        await close_db()
        return

    if args.json:
        print(json.dumps(raw_trajectories[:3], indent=2, default=str, ensure_ascii=False))
        await close_db()
        return

    miner_info["uid"] = args.uid

    if args.deep:
        trajectories = [TrajectoryData(r) for r in raw_trajectories]
        report = deep_dump(args.deep, trajectories)
    else:
        report = generate_report(miner_info, raw_trajectories)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report + "\n")
        print(f"Report written to {args.output} ({len(report)} chars)", file=sys.stderr)
    else:
        print(report)

    print(f"\n  Analyzed {len(raw_trajectories)} trajectories", file=sys.stderr)
    await close_db()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
