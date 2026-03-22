#!/usr/bin/env python3
"""
LIVEWEB (web browsing/interaction) trajectory analysis engine.

Provides single-miner deep analysis with full report mode,
plus exports used by batch_analyze.py.

Usage:
    python3 scripts/analyze_liveweb.py --uid 42
    python3 scripts/analyze_liveweb.py --uid 42 --all -o reports/liveweb_uid42_all.txt
    python3 scripts/analyze_liveweb.py --uid 42 --limit 50
    python3 scripts/analyze_liveweb.py --uid 42 --recent 20
    python3 scripts/analyze_liveweb.py --uid 42 --inspect
    python3 scripts/analyze_liveweb.py --uid 42 --json
    python3 scripts/analyze_liveweb.py --compare "120 162 248"
    python3 scripts/analyze_liveweb.py --uid 42 --verbose
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Constants ────────────────────────────────────────────────────────────────

# Known websites that appear in LIVEWEB tasks
# Active LiveWeb Arena plugin sites (from liveweb-arena repo, 2026-03-22)
# hybrid plugin combines coingecko + stooq, weather plugin (wttr.in) disabled
# New since 03-19: arxiv plugin (arxiv.org), openmeteo plugin (open-meteo.com)
KNOWN_SITES = [
    "stooq.com", "taostats.io", "coingecko.com",
    "news.ycombinator.com", "openlibrary.org",
    "arxiv.org", "open-meteo.com",
]

# Legacy/external sites that may appear in goto URLs but are NOT plugin sites
# Kept for domain extraction fallback (agent may navigate to these)
KNOWN_EXTERNAL_SITES = [
    "coinmarketcap.com", "finance.yahoo.com", "tradingview.com",
    "investing.com", "marketwatch.com", "stockanalysis.com",
    "macrotrends.net", "companiesmarketcap.com", "statista.com",
    "worldometers.info", "duckduckgo.com", "google.com", "bing.com",
    "weather.com", "openweathermap.org", "wttr.in",
    "scholar.google.com",
]

# Domains that look like websites but are actually crypto/project names
# mentioned in questions — not real LiveWeb plugin sites.
FALSE_POSITIVE_DOMAINS = {
    "fetch.ai", "xen.com", "render.com", "near.org",
    "polygon.technology", "cosmos.network",
}

# Question type classification patterns
_QUESTION_TYPE_PATTERNS = [
    ("price", [r"\bprice\b", r"\bcurrent price\b", r"\bspot price\b",
               r"\blast price\b", r"\bclosing price\b", r"\bopen price\b",
               r"\btrading at\b", r"\bcurrently at\b", r"\bquoted at\b"]),
    ("volume", [r"\bvolume\b", r"\btrading volume\b", r"\b24h volume\b",
                r"\bdaily volume\b"]),
    ("change_%", [r"\bchange\b.*%", r"\b%\s*change\b", r"\bpercentage change\b",
                  r"\bpercent change\b", r"\bgain\b.*%", r"\bloss\b.*%",
                  r"\b% gain\b", r"\b% loss\b", r"\bperformance\b"]),
    ("supply", [r"\bsupply\b", r"\bcirculating supply\b", r"\btotal supply\b",
                r"\bmax supply\b", r"\bmarket cap\b", r"\bmarketcap\b"]),
    ("ath/range", [r"\ball.time.high\b", r"\bath\b", r"\b52.week\b",
                   r"\bhighest\b", r"\blowest\b", r"\brange\b",
                   r"\ball.time.low\b", r"\batl\b"]),
    ("ranking", [r"\brank\b", r"\branking\b", r"\bposition\b",
                 r"\btop\s+\d+\b", r"\b#\d+\b"]),
    ("comparison", [r"\bcompare\b", r"\bvs\b", r"\bversus\b",
                    r"\bhigher\b.*\bor\b", r"\blower\b.*\bor\b",
                    r"\bwhich\b.*\bmore\b", r"\bwhich\b.*\bless\b",
                    r"\bdifference between\b",
                    r"\bperformed\s+(better|worse)\b", r"\bwhich\b.*\bcheapest\b",
                    r"\bclosest to\b.*\b(high|low)\b", r"\bnearest to\b.*\b(high|low)\b",
                    r"\bwhich\b.*\bbiggest\b", r"\bwhich\b.*\bmost\b",
                    r"\bwhich\b.*\blost the most\b", r"\bup or down\b"]),
    ("count/how_many", [r"\bhow many\b", r"\bcount\b", r"\bnumber of\b",
                        r"\btotal number\b"]),
    ("convert", [r"\bconvert\b", r"\bin\s+(usd|eur|gbp|btc|eth)\b",
                 r"\bexchange rate\b", r"\bconversion\b"]),
    ("weather", [r"\btemperature\b", r"\bweather\b", r"\bforecast\b",
                 r"\bwind\b", r"\bhumidity\b", r"\bprecipitation\b",
                 r"\brain\b.*\bchance\b", r"\bsnow\b"]),
    ("paper/author", [r"\bpaper\b", r"\bauthor\b", r"\barxiv\b",
                      r"\bcategory\b.*\bpaper\b", r"\btitle\b.*\bpaper\b",
                      r"\bpublication\b", r"\babstract\b"]),
    ("subnet/network", [r"\bsubnet\b", r"\bvalidator\b", r"\bemission\b",
                        r"\bregistration\b", r"\bstaking\b", r"\bdelegat",
                        r"\btao\b", r"\bbittensor\b", r"\bnetuid\b"]),
    ("identify/lookup", [r"\bname of\b", r"\bidentify\b", r"\bwhat is the\b.*\bfor\b",
                          r"\bfind the\b", r"\blook up\b", r"\bretrieve\b"]),
    ("book/library", [r"\bbook\b", r"\bauthor\b.*\bwrote\b", r"\bisbn\b",
                      r"\bpublisher\b", r"\blibrary\b", r"\bfirst.edition\b"]),
    ("news/article", [r"\bnews\b", r"\bstory\b", r"\bstories\b", r"\barticle\b",
                      r"\bpoints\b.*\bhacker\b", r"\bcomment\b.*\bhacker\b",
                      r"\bhacker\s*news\b", r"\bupvote\b"]),
    ("filter/threshold", [r"\bfind any\b.*\bthat\b", r"\bfilter\b", r"\bthreshold\b",
                          r"\banomaly\b", r"\boutlier\b", r"\bmore than\b.*%",
                          r"\bgained more than\b", r"\blost more than\b"]),
    ("calculate", [r"\bcalculate\b", r"\bcompute\b", r"\bwhat percentage\b",
                   r"\bpercentage of\b", r"\bratio\b", r"\baverage\b.*\bacross\b"]),
]

# Browser action patterns in conversation (fallback regex for non-tool-call formats)
_ACTION_PATTERNS = {
    "goto": re.compile(r'goto\s*\(\s*["\']([^"\']+)["\']\s*\)', re.IGNORECASE),
    "click": re.compile(r'click\s*\(', re.IGNORECASE),
    "scroll": re.compile(r'scroll\s*\(', re.IGNORECASE),
    "view_more": re.compile(r'view_more', re.IGNORECASE),
}

# All action types from liveweb-arena agent_protocol.py
# All 11 action types from liveweb-arena agent_protocol.py BROWSER_ACTIONS
_ALL_ACTION_NAMES = {
    "goto", "click", "scroll", "view_more", "type", "press",
    "wait", "click_role", "type_role", "stop",
}

# Wrong answer sub-classification keywords
_GAVE_UP_PATTERNS = [
    "i cannot", "i'm unable", "i could not", "unable to find",
    "not able to", "failed to", "i apologize", "i don't have",
    "cannot determine", "couldn't find", "no data", "not available",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pct(n, d):
    if d == 0:
        return "-"
    return f"{100.0 * n / d:.1f}%"


def _pct_str(n, d):
    if d == 0:
        return "-"
    return f"{100 * n / d:.0f}%"


def _safe_mean(values):
    if not values:
        return 0.0
    return statistics.mean(values)


def _safe_median(values):
    if not values:
        return 0.0
    return statistics.median(values)


def _safe_stdev(values):
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _extract_domain(url):
    """Extract domain from URL, stripping www. prefix."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        domain = parsed.hostname or ""
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return ""


def _classify_question_type(question_text):
    """Classify a question into a type based on keyword patterns."""
    if not question_text:
        return "other"
    text = question_text.lower()
    for qtype, patterns in _QUESTION_TYPE_PATTERNS:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return qtype
    return "other"


def _extract_websites_from_question(question_text):
    """Extract website domains mentioned in a question."""
    if not question_text:
        return []
    domains = []
    # Look for known sites
    text_lower = question_text.lower()
    for site in KNOWN_SITES:
        if site.lower() in text_lower:
            domains.append(site.lower())
    # Look for URL-like patterns
    url_pattern = re.compile(r'https?://([^\s/]+)')
    for m in url_pattern.finditer(question_text):
        domain = m.group(1).lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain and domain not in domains:
            domains.append(domain)
    # Look for domain-like patterns (e.g. "stooq.com")
    domain_pattern = re.compile(r'\b([a-z0-9][-a-z0-9]*\.[a-z]{2,}(?:\.[a-z]{2,})?)\b')
    # Short TLDs that are valid for known sites; reject very short domains as noise
    for m in domain_pattern.finditer(question_text.lower()):
        domain = m.group(1)
        if domain in domains or domain.startswith("e.g"):
            continue
        # Filter out false positive domains (crypto names that look like domains)
        if domain in FALSE_POSITIVE_DOMAINS:
            continue
        # Filter out false positives: must have at least 4 chars before TLD
        # or be a known site
        name_part = domain.split(".")[0]
        if len(name_part) < 3 and domain not in [s.lower() for s in KNOWN_SITES]:
            continue
        domains.append(domain)
    return domains


def _classify_wrong_answer(expected, actual, is_correct):
    """Classify a wrong answer into a category."""
    if is_correct:
        return "correct"
    if not actual or not expected:
        return "completely_wrong"

    actual_str = str(actual).strip().lower()
    expected_str = str(expected).strip().lower()

    # Check for gave_up
    for pat in _GAVE_UP_PATTERNS:
        if pat in actual_str:
            return "gave_up"

    # Check for verbose_wrong (answer too long)
    if len(actual_str) > 100:
        return "verbose_wrong"

    # Check for format_mismatch (numeric values close but different format)
    try:
        # Strip common formatting
        a_clean = re.sub(r'[$%,\s]', '', actual_str)
        e_clean = re.sub(r'[$%,\s]', '', expected_str)
        a_num = float(a_clean)
        e_num = float(e_clean)
        if e_num != 0:
            ratio = abs(a_num - e_num) / abs(e_num)
            if ratio < 0.01:
                return "format_mismatch"
            elif ratio < 0.20:
                return "close_value"
    except (ValueError, TypeError):
        pass

    # Check for partial_info
    if expected_str in actual_str or actual_str in expected_str:
        return "partial_info"

    return "completely_wrong"


def _sub_classify_completely_wrong(expected, actual):
    """Sub-classify completely_wrong answers."""
    actual_str = str(actual).strip().lower() if actual else ""
    expected_str = str(expected).strip().lower() if expected else ""

    # gave_up
    for pat in _GAVE_UP_PATTERNS:
        if pat in actual_str:
            return "gave_up"

    # verbose_wrong
    if len(actual_str) > 80:
        return "verbose_wrong"

    # format_mismatch (number formatting differences)
    try:
        a_clean = re.sub(r'[$%,\s]', '', actual_str)
        e_clean = re.sub(r'[$%,\s]', '', expected_str)
        a_num = float(a_clean)
        e_num = float(e_clean)
        if e_num != 0 and abs(a_num - e_num) / abs(e_num) < 0.05:
            return "format_mismatch"
    except (ValueError, TypeError):
        pass

    # wrong_entity/metric (default for completely wrong with a concrete answer)
    return "wrong_entity/metric"


# ── TrajectoryData ───────────────────────────────────────────────────────────

class TrajectoryData:
    """Parsed trajectory wrapper for LIVEWEB environment."""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.task_id = raw.get("task_id", 0)
        if isinstance(self.task_id, str):
            try:
                self.task_id = int(self.task_id)
            except (ValueError, TypeError):
                self.task_id = 0
        self.score = float(raw.get("score", 0) or 0)
        self.timestamp = raw.get("timestamp", 0) or 0
        if isinstance(self.timestamp, str):
            self.timestamp = int(self.timestamp) if self.timestamp else 0
        if self.timestamp and self.timestamp > 1e15:
            self.timestamp = self.timestamp / 1000  # ms -> s
        self.latency_ms = raw.get("latency_ms", 0) or 0

        # Parse extra
        extra = raw.get("extra", {}) or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        self.extra = extra

        # Core fields
        self.answer_details = extra.get("answer_details", []) or []
        self.num_subtasks = int(extra.get("num_subtasks", 0) or 0)
        if self.num_subtasks == 0 and self.answer_details:
            self.num_subtasks = len(self.answer_details)
        self.conversation = extra.get("conversation", []) or []
        self.final_url = str(extra.get("final_url", "") or "")
        self.failure_reason = extra.get("failure_reason", None)
        self.seed = extra.get("seed", None)
        self.output_format = str(extra.get("output_format", "") or "")
        self.image = str(extra.get("image", "") or "")

        # Cache stats
        cache = extra.get("cache_stats", {}) or {}
        self.cache_hits = int(cache.get("hits", 0) or 0)
        self.cache_misses = int(cache.get("misses", 0) or 0)
        self.cache_hit_rate = float(cache.get("hit_rate", 0) or 0)

        # Usage
        usage = extra.get("usage", {}) or {}
        self.total_tokens = int(usage.get("total_tokens", 0) or 0)
        self.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        # Derived: per-subtask analysis
        self.subtask_scores = []
        self.subtask_websites = []
        self.subtask_questions = []
        self.subtask_qtypes = []
        self.wrong_answers = []
        self._parse_answer_details()

        # Derived: action analysis
        self.goto_urls = []
        self.goto_domains = []
        self.action_counts = Counter()
        self.url_loops = []
        # Per-site action attribution: domain -> Counter(action_type -> count)
        self.site_actions = defaultdict(Counter)
        self._parse_actions()

        # Derived: navigation metrics
        self.required_sites = sorted(set(self.subtask_websites))
        self.visited_sites = sorted(set(self.goto_domains))
        self.site_coverage = self._compute_site_coverage()
        self.is_perfect = abs(self.score - 1.0) < 1e-6
        self.is_zero = abs(self.score) < 1e-6
        self.is_multi_site = self.num_subtasks >= 2
        self.total_steps = sum(self.action_counts.values())
        # Browser steps: actions counted against step budget (excludes stop)
        self.browser_steps = sum(
            v for k, v in self.action_counts.items() if k != "stop"
        )
        self.unique_urls = len(set(self.goto_urls))
        self.url_diversity = (self.unique_urls / len(self.goto_urls)
                              if self.goto_urls else 0.0)
        self.steps_per_subtask = (self.total_steps / self.num_subtasks
                                  if self.num_subtasks > 0 else 0)
        self.step_budget_exhausted = self._detect_step_budget_exhaustion()

    def _parse_answer_details(self):
        """Parse answer_details to extract per-subtask information."""
        # Pre-extract websites from user messages (page state URLs)
        page_urls = []
        for msg in self.conversation:
            if msg.get("role") == "user":
                content = str(msg.get("content", "") or "")
                url_match = re.search(r'URL:\s*(https?://[^\s\n]+)', content)
                if url_match:
                    domain = _extract_domain(url_match.group(1))
                    if domain and domain not in ("about:blank",):
                        page_urls.append(domain)

        for detail in self.answer_details:
            if not isinstance(detail, dict):
                continue
            score = float(detail.get("score", 0) or 0)
            self.subtask_scores.append(score)

            question = str(detail.get("question", "") or "")
            self.subtask_questions.append(question)

            # Extract website from question text first
            websites = _extract_websites_from_question(question)
            if not websites and page_urls:
                # Fallback: use most common visited domain from page state
                domain_counts = Counter(page_urls)
                websites = [domain_counts.most_common(1)[0][0]]
            website = websites[0] if websites else "unknown"
            self.subtask_websites.append(website)

            # Classify question type
            qtype = _classify_question_type(question)
            self.subtask_qtypes.append(qtype)

            # Track wrong answers
            is_correct = bool(detail.get("is_correct", False))
            if not is_correct:
                expected = detail.get("expected", "")
                actual = detail.get("actual", "")
                classification = _classify_wrong_answer(expected, actual, is_correct)
                sub_class = ""
                if classification == "completely_wrong":
                    sub_class = _sub_classify_completely_wrong(expected, actual)
                self.wrong_answers.append({
                    "question": question,
                    "expected": expected,
                    "actual": actual,
                    "classification": classification,
                    "sub_class": sub_class,
                    "website": website,
                    "qtype": qtype,
                })

    def _parse_actions(self):
        """Parse conversation messages to extract browser actions.

        Actions are stored as OpenAI-style tool_calls on assistant messages:
          msg["tool_calls"] = [{"function": {"name": "goto", "arguments": '{"url": "..."}'}}]
        Also falls back to regex matching on content text for other formats.

        Tracks current_domain (set by each goto) to attribute non-goto actions
        to the site being browsed at that moment (stored in self.site_actions).
        """
        current_domain = ""  # tracks which site the agent is currently on

        def _attribute(action_name, domain=None):
            """Record action in both global counts and site-specific counts."""
            self.action_counts[action_name] += 1
            target = domain or current_domain
            if target:
                self.site_actions[target][action_name] += 1

        for msg in self.conversation:
            if msg.get("role") != "assistant":
                continue

            # Primary: parse tool_calls (OpenAI function calling format)
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                name = func.get("name", "")
                args_str = func.get("arguments", "{}")

                if name == "goto":
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        url = args.get("url", "")
                    except (json.JSONDecodeError, AttributeError):
                        url = ""
                    if url:
                        self.goto_urls.append(url)
                        domain = _extract_domain(url)
                        if domain:
                            self.goto_domains.append(domain)
                            current_domain = domain
                    _attribute("goto", current_domain)
                elif name in ("view_more", "viewmore"):
                    _attribute("view_more")
                elif name in _ALL_ACTION_NAMES:
                    _attribute(name)

            # Fallback: regex on content text (for non-tool-call formats)
            content = str(msg.get("content", "") or "")
            if content and content != "None":
                for m in _ACTION_PATTERNS["goto"].finditer(content):
                    url = m.group(1)
                    self.goto_urls.append(url)
                    domain = _extract_domain(url)
                    if domain:
                        self.goto_domains.append(domain)
                        current_domain = domain
                    _attribute("goto", current_domain)
                for _ in _ACTION_PATTERNS["click"].findall(content):
                    _attribute("click")
                for _ in _ACTION_PATTERNS["scroll"].findall(content):
                    _attribute("scroll")
                for _ in _ACTION_PATTERNS["view_more"].findall(content):
                    _attribute("view_more")

        # Detect URL loops (>=3 consecutive identical goto URLs)
        if len(self.goto_urls) >= 3:
            streak = 1
            streak_url = self.goto_urls[0] if self.goto_urls else ""
            for i in range(1, len(self.goto_urls)):
                if self.goto_urls[i] == self.goto_urls[i - 1]:
                    streak += 1
                else:
                    if streak >= 3:
                        self.url_loops.append((streak_url, streak))
                    streak = 1
                    streak_url = self.goto_urls[i]
            if streak >= 3:
                self.url_loops.append((streak_url, streak))

    def _compute_site_coverage(self):
        """Compute fraction of required sites that were actually visited."""
        if not self.required_sites:
            return 1.0
        visited_domains = set(self.goto_domains)
        matched = 0
        for req in self.required_sites:
            req_lower = req.lower()
            # Check if any visited domain contains the required site
            if any(req_lower in d or d in req_lower for d in visited_domains):
                matched += 1
        return matched / len(self.required_sites) if self.required_sites else 1.0

    def _detect_step_budget_exhaustion(self):
        """Heuristic: if browser steps >= 25 and score < 1.0, likely exhausted budget.
        Threshold 25 chosen because liveweb-arena max_steps defaults to 30,
        and tasks hitting 25+ browser actions are near or at the limit.
        """
        return self.browser_steps >= 25 and not self.is_perfect

    @property
    def has_loops(self):
        return len(self.url_loops) > 0

    @property
    def max_loop_streak(self):
        if not self.url_loops:
            return 0
        return max(streak for _, streak in self.url_loops)

    @property
    def view_more_count(self):
        return self.action_counts.get("view_more", 0)

    @property
    def never_visited_sites(self):
        """Sites required but never visited."""
        visited = set(self.goto_domains)
        missing = []
        for req in self.required_sites:
            req_lower = req.lower()
            if not any(req_lower in d or d in req_lower for d in visited):
                missing.append(req)
        return missing


# ── Data Fetching ────────────────────────────────────────────────────────────

async def fetch_trajectories(
    uid: int,
    env: str = "LIVEWEB",
    mode: str = "sampling",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Fetch trajectories for a miner UID.

    Args:
        uid: Miner UID (0-255)
        env: Environment name (default "LIVEWEB")
        mode: "sampling" for active sampling list, "all" for all historical data

    Returns:
        (miner_info, raw_trajectories) where miner_info has keys:
            matched, sampling_list_size, hotkey, model_revision
    """
    # Map mode to source for internal use
    source = mode

    # Skip API if FORCE_DB is set
    if os.getenv("FORCE_DB"):
        return await _fetch_via_db(uid, env, source)

    base_url = os.getenv("API_URL", "https://api.affine.io/api/v1")

    try:
        from affine.utils.api_client import cli_api_client
    except ImportError:
        return await _fetch_via_db(uid, env, source)

    try:
        return await _fetch_via_api(uid, env, source, base_url, cli_api_client)
    except Exception as e:
        print(f"  API failed ({e}), falling back to DB ...", file=sys.stderr)
        return await _fetch_via_db(uid, env, source)


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
            return {
                "matched": 0, "sampling_list_size": 0,
                "hotkey": hotkey, "model_revision": revision,
            }, []

        sem = asyncio.Semaphore(10)
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
        return {
            "matched": len(results), "sampling_list_size": sl_size,
            "hotkey": hotkey, "model_revision": revision,
        }, results


async def _fetch_via_db(uid, env_name, source):
    """Fallback: fetch via direct DB access."""
    from affine.database.client import init_client, close_client
    from affine.database.dao.miners import MinersDAO
    from affine.database.dao.sample_results import SampleResultsDAO
    from affine.database.dao.system_config import SystemConfigDAO
    from affine.core.sampling_list import get_task_id_set_from_config

    await init_client()
    try:
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
        if env_key not in environments and ":" not in env_key:
            matches = [e for e in environments if e.endswith(f":{env_key}")]
            if len(matches) == 1:
                env_key = matches[0]

        if source == "all":
            task_ids = sorted(await sample_dao.get_completed_task_ids(hotkey, revision, env_key))
        else:
            env_config = environments.get(env_key, {})
            task_ids = sorted(get_task_id_set_from_config(env_config))

        results = []
        for i, task_id in enumerate(task_ids):
            try:
                item = await sample_dao.get_sample_by_task_id(
                    miner_hotkey=hotkey, model_revision=revision,
                    env=env_key, task_id=str(task_id), include_extra=True,
                )
                if item:
                    results.append(item)
            except Exception:
                pass
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i + 1}/{len(task_ids)} ...", file=sys.stderr)

        return {
            "matched": len(results), "sampling_list_size": len(task_ids),
            "hotkey": hotkey, "model_revision": revision,
        }, results
    finally:
        await close_client()


# ── Report Generation ────────────────────────────────────────────────────────

def generate_report(miner_info, raw_trajectories, verbose=False):
    """Generate full LIVEWEB analysis report."""
    lines = []
    p = lines.append

    parsed = []
    for t in raw_trajectories:
        try:
            parsed.append(TrajectoryData(t))
        except Exception:
            pass

    if not parsed:
        return "No valid trajectories to analyze."

    n = len(parsed)
    scores = [t.score for t in parsed]
    avg_score = _safe_mean(scores)
    perfect_tasks = [t for t in parsed if t.is_perfect]
    zero_tasks = [t for t in parsed if t.is_zero]
    perfect_count = len(perfect_tasks)
    zero_count = len(zero_tasks)
    perfect_rate = perfect_count / n * 100
    zero_rate = zero_count / n * 100

    matched = miner_info.get("matched", n)
    sl_size = miner_info.get("sampling_list_size", n)
    match_pct = matched / max(sl_size, 1) * 100

    multi_site = [t for t in parsed if t.is_multi_site]
    single_site = [t for t in parsed if not t.is_multi_site]

    # Group by website
    website_groups = defaultdict(list)  # website -> list of (task, subtask_idx)
    for t in parsed:
        for idx, website in enumerate(t.subtask_websites):
            website_groups[website].append((t, idx))

    # Group by question type
    qtype_groups = defaultdict(list)
    for t in parsed:
        for idx, qtype in enumerate(t.subtask_qtypes):
            qtype_groups[qtype].append((t, idx))

    # Group by num_subtasks
    subtask_groups = defaultdict(list)
    for t in parsed:
        subtask_groups[t.num_subtasks].append(t)

    # ═══════════════════════════════════════════════════════════════════════
    # Pre-compute metrics needed for TOP FINDINGS
    # ═══════════════════════════════════════════════════════════════════════
    no_nav_scored_pre = [t for t in parsed
                         if t.action_counts.get("goto", 0) == 0 and t.score > 0]
    nav_tasks_pre = [t for t in parsed if t.action_counts.get("goto", 0) > 0]
    budget_exhausted_pre = [t for t in parsed if t.step_budget_exhausted]
    loop_tasks_pre = [t for t in parsed if t.has_loops]

    # Navigation-aware root cause pre-compute (per wrong answer)
    rc_budget = 0
    rc_wrong_extract = 0
    rc_never = 0
    rc_no_nav = 0
    # Tag each wrong answer with its navigation root cause for cross-analysis
    for t in parsed:
        for wa in t.wrong_answers:
            site_lower = wa["website"].lower()
            visited = any(site_lower in d or d in site_lower for d in t.goto_domains)
            if t.action_counts.get("goto", 0) == 0:
                rc_no_nav += 1
                wa["_nav_root_cause"] = "no_navigation"
            elif not visited:
                rc_never += 1
                wa["_nav_root_cause"] = "never_visited"
            elif t.step_budget_exhausted:
                rc_budget += 1
                wa["_nav_root_cause"] = "budget_exhausted"
            else:
                rc_wrong_extract += 1
                wa["_nav_root_cause"] = "wrong_extraction"

    total_wrong_pre = sum(len(t.wrong_answers) for t in parsed)

    # Suspicious tasks: score > 0 with 0% coverage or 0 steps
    suspicious_tasks = [t for t in parsed
                        if t.score > 0
                        and (t.site_coverage < 0.01 or t.total_steps == 0)]

    # ═══════════════════════════════════════════════════════════════════════
    # TOP FINDINGS (highest-value insights first)
    # ═══════════════════════════════════════════════════════════════════════
    p("ENVIRONMENT: LIVEWEB")
    p("=" * 80)
    p(f"  Samples: {n} | Avg: {avg_score:.3f} | Perfect: {perfect_count} ({perfect_rate:.0f}%) | Zero: {zero_count} ({zero_rate:.0f}%)")
    p("")
    p("TOP FINDINGS")
    p("=" * 80)
    p("")

    findings = []

    # Finding: Wrong answer root cause
    if total_wrong_pre > 0:
        top_cause = max(
            [("step budget exhaustion", rc_budget),
             ("wrong extraction (right site)", rc_wrong_extract),
             ("never visited required site", rc_never),
             ("no navigation at all", rc_no_nav)],
            key=lambda x: x[1],
        )
        findings.append(
            f"#1 failure root cause: {top_cause[0]} ({top_cause[1]}/{total_wrong_pre}, "
            f"{top_cause[1] / total_wrong_pre * 100:.0f}% of wrong answers)"
        )

    # Finding: Memorization / world knowledge
    if no_nav_scored_pre:
        no_nav_avg = _safe_mean([t.score for t in no_nav_scored_pre])
        nav_avg = _safe_mean([t.score for t in nav_tasks_pre]) if nav_tasks_pre else 0
        findings.append(
            f"Memorization risk: {len(no_nav_scored_pre)} tasks ({len(no_nav_scored_pre) / n * 100:.0f}%) "
            f"score with 0 goto (avg {no_nav_avg:.3f} vs navigating {nav_avg:.3f})"
        )

    # Finding: Worst website
    worst_site_info = None
    for site_name, entries in sorted(website_groups.items(), key=lambda x: len(x[1]), reverse=True):
        if site_name == "unknown" or len(entries) < 5:
            continue
        correct_cnt = sum(1 for t, idx in entries if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5)
        acc_val = correct_cnt / len(entries) * 100
        if worst_site_info is None or acc_val < worst_site_info[2]:
            worst_site_info = (site_name, len(entries), acc_val)
    if worst_site_info:
        findings.append(
            f"Worst website: {worst_site_info[0]} at {worst_site_info[2]:.0f}% accuracy "
            f"({worst_site_info[1]} subtasks)"
        )

    # Finding: Budget exhaustion
    if budget_exhausted_pre:
        findings.append(
            f"Step budget exhaustion: {len(budget_exhausted_pre)}/{n} ({len(budget_exhausted_pre) / n * 100:.0f}%) "
            f"tasks, avg score {_safe_mean([t.score for t in budget_exhausted_pre]):.3f}"
        )

    # Finding: Suspicious tasks (score without browsing)
    if suspicious_tasks:
        findings.append(
            f"Suspicious evaluation: {len(suspicious_tasks)} tasks score >0 with 0% site coverage "
            f"(possible scoring bug or world knowledge bypass)"
        )

    # Finding: 3+ site perfect rate
    three_plus = [t for t in parsed if t.num_subtasks >= 3]
    if three_plus:
        tp_perf = sum(1 for t in three_plus if t.is_perfect)
        if tp_perf == 0:
            findings.append(
                f"3+ site tasks: 0/{len(three_plus)} perfect — structurally unsolvable at current capability"
            )

    # Finding: Parse failures (agent format error) + empty tasks (env issue)
    parse_failed_tasks = [t for t in parsed
                          if t.failure_reason and "parse" in str(t.failure_reason).lower()]
    empty_tasks = [t for t in parsed if t.num_subtasks == 0]
    if parse_failed_tasks:
        # Classify parse failure modes by inspecting last assistant message
        pf_modes = {"bare_json": 0, "xml_tool_call": 0, "plain_text": 0, "other": 0}
        for t in parse_failed_tasks:
            asst_msgs = [m for m in t.conversation if m.get("role") == "assistant"]
            if not asst_msgs:
                pf_modes["other"] += 1
                continue
            content = str(asst_msgs[-1].get("content", "") or "")
            tc = asst_msgs[-1].get("tool_calls") or []
            if tc:
                pf_modes["other"] += 1
            elif "<tool_call>" in content or "<tool>" in content:
                pf_modes["xml_tool_call"] += 1
            elif '"name"' in content and '"arguments"' in content:
                pf_modes["bare_json"] += 1
            else:
                pf_modes["plain_text"] += 1
        mode_parts = [f"{v} {k}" for k, v in sorted(pf_modes.items(), key=lambda x: -x[1]) if v > 0]
        findings.append(
            f"Agent format failures: {len(parse_failed_tasks)} tasks ({len(parse_failed_tasks) / n * 100:.0f}%) "
            f"output stop action in wrong format ({', '.join(mode_parts)}) — "
            f"SFT target for function-calling compliance"
        )
    if empty_tasks and len(empty_tasks) >= 3:
        findings.append(
            f"Environment issues: {len(empty_tasks)} tasks ({len(empty_tasks) / n * 100:.0f}%) "
            f"have 0 subtasks (task initialization failure)"
        )

    # Finding: Token waste
    perf_tok = [t.total_tokens for t in perfect_tasks if t.total_tokens > 0]
    zero_tok = [t.total_tokens for t in zero_tasks if t.total_tokens > 0]
    if perf_tok and zero_tok:
        ratio = _safe_mean(zero_tok) / max(_safe_mean(perf_tok), 1)
        if ratio > 1.5:
            findings.append(
                f"Token waste: zero-score tasks use {ratio:.1f}x more tokens than perfect tasks "
                f"({_safe_mean(zero_tok):.0f} vs {_safe_mean(perf_tok):.0f})"
            )

    for i, f_text in enumerate(findings, 1):
        p(f"  {i}. {f_text}")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 1: EXECUTIVE SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("1. EXECUTIVE SUMMARY")
    p("=" * 80)
    p("")
    p(f"  Total tasks:     {n}")
    p(f"  Avg score:       {avg_score:.3f}")
    p(f"  Perfect (1.0):   {perfect_count}/{n} ({perfect_rate:.1f}%)")
    p(f"  Zero (0.0):      {zero_count}/{n} ({zero_rate:.1f}%)")
    p(f"  Partial (0<s<1): {n - perfect_count - zero_count}/{n} ({(n - perfect_count - zero_count) / n * 100:.1f}%)")
    p("")

    if multi_site:
        multi_pct = len(multi_site) / n * 100
        multi_zero = sum(1 for t in multi_site if t.is_zero)
        multi_perfect = sum(1 for t in multi_site if t.is_perfect)
        # How many multi-site tasks missed at least one site
        multi_missed = sum(1 for t in multi_site if t.site_coverage < 1.0)
        multi_missed_pct = multi_missed / len(multi_site) * 100 if multi_site else 0
        # How many never visited 2nd site
        never_2nd = sum(1 for t in multi_site if len(t.never_visited_sites) >= 1)
        never_2nd_pct = never_2nd / len(multi_site) * 100 if multi_site else 0

        p("  Multi-site coverage:")
        p(f"    Multi-site tasks: {len(multi_site)}/{n} ({multi_pct:.0f}%)")
        p(f"    Missed >=1 site:  {multi_missed}/{len(multi_site)} ({multi_missed_pct:.0f}%)")
        p(f"    Never visited 2nd site: {never_2nd}/{len(multi_site)} ({never_2nd_pct:.0f}%)")
        p(f"    Multi-site zero:     {multi_zero}/{len(multi_site)} ({multi_zero / len(multi_site) * 100:.0f}%)")
        p(f"    Multi-site perfect:  {multi_perfect}/{len(multi_site)} ({multi_perfect / len(multi_site) * 100:.0f}%)")
        p("")

    p("  Top bottlenecks:")
    bottlenecks = []

    if multi_site and multi_missed:
        bottlenecks.append(
            f"Multi-site navigation: {multi_missed_pct:.0f}% miss >=1 required site"
        )

    # Worst website
    if website_groups:
        worst_site, worst_site_data = None, (0, 0)
        for site, entries in website_groups.items():
            if site == "unknown" or len(entries) < 3:
                continue
            correct = sum(1 for t, idx in entries if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5)
            if len(entries) - correct > worst_site_data[1]:
                worst_site = site
                worst_site_data = (correct, len(entries) - correct)
        if worst_site:
            ws_total = worst_site_data[0] + worst_site_data[1]
            ws_acc = worst_site_data[0] / ws_total * 100 if ws_total else 0
            bottlenecks.append(
                f"Worst website: {worst_site} ({ws_acc:.0f}% accuracy, {worst_site_data[1]} wrong)"
            )

    # URL loops
    loop_tasks = [t for t in parsed if t.has_loops]
    if loop_tasks:
        bottlenecks.append(f"URL loops: {len(loop_tasks)}/{n} ({len(loop_tasks) / n * 100:.0f}%) tasks with repeated URL navigation")

    # Zero-score analysis
    if zero_tasks:
        bottlenecks.append(f"Zero-score tasks: {zero_count}/{n} ({zero_rate:.0f}%)")

    for b in bottlenecks:
        p(f"    - {b}")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 2: SCORE DISTRIBUTION
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("2. SCORE DISTRIBUTION")
    p("=" * 80)
    p("")

    # Histogram with bucket ranges
    buckets = [
        ("0.00", lambda s: abs(s) < 1e-6),
        ("0.01-0.24", lambda s: 0.01 <= s < 0.25),
        ("0.25", lambda s: abs(s - 0.25) < 1e-6),
        ("0.26-0.49", lambda s: 0.26 <= s < 0.50),
        ("0.50", lambda s: abs(s - 0.50) < 1e-6),
        ("0.51-0.74", lambda s: 0.51 <= s < 0.75),
        ("0.75", lambda s: abs(s - 0.75) < 1e-6),
        ("0.76-0.99", lambda s: 0.76 <= s < 1.0),
        ("1.00", lambda s: abs(s - 1.0) < 1e-6),
    ]

    bucket_counts = []
    for label, pred in buckets:
        cnt = sum(1 for s in scores if pred(s))
        bucket_counts.append((label, cnt))

    max_cnt = max(cnt for _, cnt in bucket_counts) if bucket_counts else 1
    bw = 40
    p("  Score histogram:")
    for label, cnt in bucket_counts:
        bar_len = int(cnt / max(max_cnt, 1) * bw)
        p(f"    {label:>9}: {cnt:>4} ({cnt / n * 100:>5.1f}%) {chr(9608) * bar_len}")
    p("")

    p("  Statistics:")
    p(f"    Mean:   {avg_score:.3f}")
    p(f"    Median: {_safe_median(scores):.3f}")
    p(f"    Stdev:  {_safe_stdev(scores):.3f}")
    p("")

    # By num_subtasks breakdown
    p("  By num_subtasks:")
    p(f"  {'Subtasks':>8} {'Count':>6} {'Avg':>6} {'Perfect':>8} {'Zero':>8} {'Perfect%':>9} {'Zero%':>7}")
    p("  " + chr(9472) * 60)
    for ns in sorted(subtask_groups.keys()):
        tasks = subtask_groups[ns]
        ns_avg = _safe_mean([t.score for t in tasks])
        ns_perf = sum(1 for t in tasks if t.is_perfect)
        ns_zero = sum(1 for t in tasks if t.is_zero)
        p(f"  {ns:>8} {len(tasks):>6} {ns_avg:>6.3f} {ns_perf:>8} {ns_zero:>8} {ns_perf / len(tasks) * 100:>8.1f}% {ns_zero / len(tasks) * 100:>6.1f}%")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 3: PER-WEBSITE ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("3. PER-WEBSITE ANALYSIS")
    p("=" * 80)
    p("")

    # Per-website accuracy
    p("  Per-website accuracy:")
    p(f"  {'Website':<30} {'Total':>5} {'Correct':>7} {'Acc%':>6} {'DNC':>4} {'DNC%':>6}")
    p("  " + chr(9472) * 62)

    site_stats = []
    for site in sorted(website_groups.keys()):
        entries = website_groups[site]
        total = len(entries)
        correct = 0
        dnc = 0  # did-not-complete: subtask scored 0 AND site was never visited
        for t, idx in entries:
            if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5:
                correct += 1
            elif idx < len(t.subtask_scores) and t.subtask_scores[idx] < 1e-6:
                # Check if site was never visited
                site_lower = site.lower()
                visited = any(site_lower in d or d in site_lower for d in t.goto_domains)
                if not visited:
                    dnc += 1
        acc = correct / total * 100 if total else 0
        dnc_pct = dnc / total * 100 if total else 0
        site_stats.append((site, total, correct, acc, dnc, dnc_pct))

    site_stats.sort(key=lambda x: -x[1])  # Sort by count
    for site, total, correct, acc, dnc, dnc_pct in site_stats:
        p(f"  {site[:30]:<30} {total:>5} {correct:>7} {acc:>5.1f}% {dnc:>4} {dnc_pct:>5.1f}%")
    p("")

    # Per-website top goto URLs
    p("  Per-website top goto URLs:")
    for site, total, correct, acc, dnc, dnc_pct in site_stats[:10]:
        if site == "unknown":
            continue
        p(f"    {site}:")
        url_counter = Counter()
        vm_count = 0
        for t, idx in website_groups[site]:
            site_lower = site.lower()
            for url in t.goto_urls:
                if site_lower in _extract_domain(url):
                    url_counter[url] += 1
            # view_more count for this site
            # Approximate: count view_more in tasks that have this site
            vm_count += t.view_more_count

        for url, cnt in url_counter.most_common(5):
            p(f"      {cnt:>4}x  {url[:80]}")
        if vm_count > 0:
            p(f"      view_more total: {vm_count}")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 4: MULTI-SITE NAVIGATION ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("4. MULTI-SITE NAVIGATION ANALYSIS")
    p("=" * 80)
    p("")

    if not multi_site:
        p("  No multi-site tasks found.")
        p("")
    else:
        p(f"  Multi-site tasks: {len(multi_site)}/{n} ({len(multi_site) / n * 100:.0f}%)")
        p(f"  Single-site tasks: {len(single_site)}/{n} ({len(single_site) / n * 100:.0f}%)")
        p("")

        # Site coverage distribution
        p("  Site coverage distribution:")
        coverage_bins = defaultdict(int)
        for t in multi_site:
            cov = t.site_coverage
            if cov >= 1.0:
                coverage_bins["100%"] += 1
            elif cov >= 0.5:
                coverage_bins["50-99%"] += 1
            else:
                coverage_bins["0-49%"] += 1
        for label in ["100%", "50-99%", "0-49%"]:
            cnt = coverage_bins.get(label, 0)
            p(f"    {label:>6}: {cnt:>4} ({cnt / len(multi_site) * 100:.1f}%)")
        p("")

        # By num_subtasks detail
        p("  Multi-site analysis by subtask count:")
        for ns in sorted(subtask_groups.keys()):
            if ns < 2:
                continue
            tasks = subtask_groups[ns]
            ns_n = len(tasks)
            ns_perf = sum(1 for t in tasks if t.is_perfect)
            ns_zero = sum(1 for t in tasks if t.is_zero)
            ns_missed = sum(1 for t in tasks if t.site_coverage < 1.0)
            # Never visited 2nd site
            ns_never_2nd = 0
            for t in tasks:
                if len(t.never_visited_sites) >= 1:
                    ns_never_2nd += 1
            # Step budget exhaustion
            ns_budget = sum(1 for t in tasks if t.step_budget_exhausted)

            p(f"    {ns}-site tasks (n={ns_n}):")
            p(f"      Perfect:          {ns_perf} ({ns_perf / ns_n * 100:.0f}%)")
            p(f"      Zero:             {ns_zero} ({ns_zero / ns_n * 100:.0f}%)")
            p(f"      Missed >=1 site:  {ns_missed} ({ns_missed / ns_n * 100:.0f}%)")
            p(f"      Never visited 2nd: {ns_never_2nd} ({ns_never_2nd / ns_n * 100:.0f}%)")
            p(f"      Budget exhausted: {ns_budget} ({ns_budget / ns_n * 100:.0f}%)")
            p(f"      Avg steps:        {_safe_mean([t.total_steps for t in tasks]):.1f}")
            p(f"      Avg score:        {_safe_mean([t.score for t in tasks]):.3f}")
            p("")

        # Navigation timing: when does the agent switch sites
        p("  Navigation timing (site switching):")
        switch_positions = []
        for t in multi_site:
            if len(t.goto_domains) < 2:
                continue
            first_domain = t.goto_domains[0] if t.goto_domains else ""
            for i, domain in enumerate(t.goto_domains[1:], 1):
                if domain != first_domain and domain:
                    switch_positions.append(i / len(t.goto_domains))
                    break

        if switch_positions:
            p(f"    Tasks that switch sites: {len(switch_positions)}/{len(multi_site)}")
            p(f"    Avg switch position: {_safe_mean(switch_positions):.1%} through navigation")
            p(f"    Median switch position: {_safe_median(switch_positions):.1%} through navigation")

            # Breakdown by outcome
            perf_switch = []
            zero_switch = []
            for t in multi_site:
                if len(t.goto_domains) < 2:
                    continue
                first_domain = t.goto_domains[0] if t.goto_domains else ""
                for i, domain in enumerate(t.goto_domains[1:], 1):
                    if domain != first_domain and domain:
                        pos = i / len(t.goto_domains)
                        if t.is_perfect:
                            perf_switch.append(pos)
                        elif t.is_zero:
                            zero_switch.append(pos)
                        break
            if perf_switch:
                p(f"    Perfect tasks switch at: {_safe_mean(perf_switch):.1%} (n={len(perf_switch)})")
            if zero_switch:
                p(f"    Zero tasks switch at:    {_safe_mean(zero_switch):.1%} (n={len(zero_switch)})")
        else:
            p("    No site switches detected in multi-site tasks.")
        p("")

        # Step budget analysis
        p("  Step budget analysis:")
        budget_exhausted = [t for t in parsed if t.step_budget_exhausted]
        p(f"    Budget exhausted (>=25 browser steps, imperfect): {len(budget_exhausted)}/{n} ({len(budget_exhausted) / n * 100:.0f}%)")
        if budget_exhausted:
            p(f"    Avg steps (exhausted): {_safe_mean([t.total_steps for t in budget_exhausted]):.1f}")
            p(f"    Avg score (exhausted): {_safe_mean([t.score for t in budget_exhausted]):.3f}")
        non_exhausted = [t for t in parsed if not t.step_budget_exhausted and not t.is_perfect]
        if non_exhausted:
            p(f"    Avg steps (non-exhausted, imperfect): {_safe_mean([t.total_steps for t in non_exhausted]):.1f}")
            p(f"    Avg score (non-exhausted, imperfect): {_safe_mean([t.score for t in non_exhausted]):.3f}")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 5: WRONG ANSWER ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("5. WRONG ANSWER ANALYSIS")
    p("=" * 80)
    p("")

    all_wrong = []
    for t in parsed:
        all_wrong.extend(t.wrong_answers)
    cw_answers = [w for w in all_wrong if w["classification"] == "completely_wrong"]
    cw_sub = Counter(w["sub_class"] for w in cw_answers)

    total_subtasks = sum(t.num_subtasks for t in parsed)
    total_correct = total_subtasks - len(all_wrong)
    p(f"  Total subtasks: {total_subtasks}")
    p(f"  Correct: {total_correct} ({total_correct / total_subtasks * 100:.1f}%)" if total_subtasks else "  Correct: 0")
    p(f"  Wrong:   {len(all_wrong)} ({len(all_wrong) / total_subtasks * 100:.1f}%)" if total_subtasks else "  Wrong: 0")
    p("")

    if all_wrong:
        # Examples of wrong answer sub-types (quick reference)
        if cw_answers:
            p("  completely_wrong examples:")
            shown_subs = set()
            for w in cw_answers:
                sub = w["sub_class"]
                if sub in shown_subs:
                    continue
                shown_subs.add(sub)
                expected_str = str(w["expected"])[:60]
                actual_str = str(w["actual"])[:60]
                p(f"    [{sub}]")
                p(f"      Q: {w['question'][:80]}")
                p(f"      Expected: {expected_str}")
                p(f"      Actual:   {actual_str}")
            p("")

        # Pre-compute qtype_stats (used by cross-tab and SFT section)
        qtype_stats = []
        for qtype in sorted(qtype_groups.keys()):
            entries = qtype_groups[qtype]
            qt_total = len(entries)
            qt_correct = sum(
                1 for t, idx in entries
                if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5
            )
            qt_acc = qt_correct / qt_total * 100 if qt_total else 0
            qtype_stats.append((qtype, qt_total, qt_correct, qt_acc))
        qtype_stats.sort(key=lambda x: -x[3])  # Sort by accuracy descending
        # (per-question-type accuracy is shown in the combined cross-tab below)

        # Wrong answers by website
        p("  Wrong answers by website:")
        wa_by_site = Counter(w["website"] for w in all_wrong)
        for site, cnt in wa_by_site.most_common(10):
            site_total = len(website_groups.get(site, []))
            p(f"    {site:<30} {cnt:>4} wrong / {site_total:>4} total ({cnt / site_total * 100:.0f}%)" if site_total else f"    {site:<30} {cnt:>4} wrong")
        p("")

        # Cross-tabulation: wrong answer classification × navigation root cause
        # (replaces separate classification + root cause tables — see TOTAL row/column)
        p("  Classification × Navigation Root Cause:")
        nav_causes = ["budget_exhausted", "wrong_extraction", "never_visited", "no_navigation"]
        nav_cause_labels = {
            "budget_exhausted": "budget",
            "wrong_extraction": "extract",
            "never_visited": "no_visit",
            "no_navigation": "no_nav",
        }
        # Collect unique classifications that matter
        class_counts = Counter(w["classification"] for w in all_wrong)
        top_classes = [cls for cls, _ in class_counts.most_common() if cls != "correct"]

        # Header
        header_parts = [f"{'classification':<20}"]
        for nc in nav_causes:
            header_parts.append(f"{nav_cause_labels[nc]:>8}")
        header_parts.append(f"{'total':>7}")
        p("  " + " ".join(header_parts))
        p("  " + chr(9472) * (20 + 8 * len(nav_causes) + 8))

        for cls in top_classes:
            cls_wrong = [w for w in all_wrong if w["classification"] == cls]
            parts = [f"{cls:<20}"]
            for nc in nav_causes:
                cnt = sum(1 for w in cls_wrong if w.get("_nav_root_cause") == nc)
                parts.append(f"{cnt:>8}")
            parts.append(f"{len(cls_wrong):>7}")
            p("  " + " ".join(parts))

        # Total row
        parts = [f"{'TOTAL':<20}"]
        for nc in nav_causes:
            cnt = sum(1 for w in all_wrong if w.get("_nav_root_cause") == nc)
            parts.append(f"{cnt:>8}")
        parts.append(f"{len(all_wrong):>7}")
        p("  " + " ".join(parts))
        p("")

        # Question Type: accuracy + root cause combined table
        # Merges per-question-type accuracy with root cause cross-tab for conciseness
        p("  Question Type Performance + Root Cause:")
        qt_rc_data = defaultdict(lambda: defaultdict(int))
        qt_rc_totals = Counter()
        for w in all_wrong:
            qt = w.get("qtype", "other")
            rc = w.get("_nav_root_cause", "unknown")
            qt_rc_data[qt][rc] += 1
            qt_rc_totals[qt] += 1

        # Build lookup for accuracy
        qt_acc_map = {qt: (total, acc) for qt, total, _, acc in qtype_stats}

        # Show all types sorted by accuracy descending (n≥5 wrong for root cause)
        qt_rc_types = [(qt, cnt) for qt, cnt in qt_rc_totals.most_common()
                       if cnt >= 5]
        if qt_rc_types:
            header_parts = [f"{'question_type':<20} {'n':>4} {'acc%':>5}"]
            for nc in nav_causes:
                header_parts.append(f"{nav_cause_labels[nc]:>7}")
            header_parts.append(f"{'primary':>14}")
            p("  " + " ".join(header_parts))
            p("  " + chr(9472) * (20 + 5 + 6 + 7 * len(nav_causes) + 15))

            # Classify each type by dominant root cause (budget vs extract)
            budget_dominant = []   # budget > extract by >10pp
            extract_dominant = []  # extract > budget by >10pp
            mixed_types = []       # budget ≈ extract (gap <10pp)

            # Sort by accuracy descending (matching qtype_stats order)
            qt_rc_types_sorted = sorted(qt_rc_types, key=lambda x: qt_acc_map.get(x[0], (0, 0))[1], reverse=True)
            for qt, total in qt_rc_types_sorted:
                qt_n, qt_acc = qt_acc_map.get(qt, (0, 0))
                flag = "†" if qt_n < 10 else ""
                parts = [f"{qt:<20} {qt_n:>4} {qt_acc:>4.0f}%{flag}"]
                rc_counts = {}
                for nc in nav_causes:
                    cnt = qt_rc_data[qt].get(nc, 0)
                    rc_counts[nc] = cnt
                    parts.append(f"{cnt:>7}")
                # Compare budget vs extract share
                b_pct = rc_counts.get("budget_exhausted", 0) / total * 100
                e_pct = rc_counts.get("wrong_extraction", 0) / total * 100
                gap = abs(b_pct - e_pct)
                if gap < 10:
                    parts.append(f"mixed({b_pct:.0f}b/{e_pct:.0f}e)")
                    mixed_types.append((qt, b_pct, e_pct))
                elif b_pct > e_pct:
                    parts.append(f"budget({b_pct:.0f}%)")
                    budget_dominant.append((qt, b_pct))
                else:
                    parts.append(f"extract({e_pct:.0f}%)")
                    extract_dominant.append((qt, e_pct))
                p("  " + " ".join(parts))

            # Show types not in cross-tab (< 5 wrong answers) as footnote
            small_types = [(qt, total, acc) for qt, total, _, acc in qtype_stats
                           if qt_rc_totals.get(qt, 0) < 5 and total >= 3]
            if small_types:
                st_str = ", ".join(f"{qt}({acc:.0f}%,n={total})" for qt, total, acc in small_types)
                p(f"  (small sample types: {st_str})")
            if any(qt_n < 10 for qt, _ in qt_rc_types for qt_n, _ in [qt_acc_map.get(qt, (0, 0))]):
                p("  (†n<10)")
            p("")
            # Actionable insight: balanced budget vs extract split
            # Include wrong answer count (n=) for prioritization within groups
            if budget_dominant or extract_dominant or mixed_types:
                p("  Root cause insight by question type:")
                if budget_dominant:
                    # Sort by wrong answer count descending for priority
                    bt_items = sorted(
                        [(qt, pct, qt_rc_totals[qt]) for qt, pct in budget_dominant],
                        key=lambda x: -x[2])
                    bt_str = ", ".join(f"{qt}({pct:.0f}%,n={cnt})" for qt, pct, cnt in bt_items)
                    p(f"    Budget-limited (need more steps): {bt_str}")
                if extract_dominant:
                    et_items = sorted(
                        [(qt, pct, qt_rc_totals[qt]) for qt, pct in extract_dominant],
                        key=lambda x: -x[2])
                    et_str = ", ".join(f"{qt}({pct:.0f}%,n={cnt})" for qt, pct, cnt in et_items)
                    p(f"    Extraction-limited (right site, wrong data): {et_str}")
                if mixed_types:
                    mt_items = sorted(
                        [(qt, qt_rc_totals[qt]) for qt, _, _ in mixed_types],
                        key=lambda x: -x[1])
                    mt_str = ", ".join(f"{qt}(n={cnt})" for qt, cnt in mt_items)
                    p(f"    Mixed (budget ≈ extraction): {mt_str}")
                p("")
        else:
            p("  (insufficient data for cross-tab)")
            p("")

        # Insight: completely_wrong decomposition + sub-class info
        if cw_answers:
            cw_budget = sum(1 for w in cw_answers if w.get("_nav_root_cause") == "budget_exhausted")
            cw_extract = sum(1 for w in cw_answers if w.get("_nav_root_cause") == "wrong_extraction")
            cw_never = sum(1 for w in cw_answers if w.get("_nav_root_cause") == "never_visited")
            p(f"  Insight: of {len(cw_answers)} completely_wrong ({len(cw_answers) / len(all_wrong) * 100:.0f}% of all wrong):")
            p(f"    Root cause: budget={cw_budget}({cw_budget * 100 // len(cw_answers)}%) "
              f"extraction={cw_extract}({cw_extract * 100 // len(cw_answers)}%) "
              f"no-visit={cw_never}({cw_never * 100 // len(cw_answers)}%)")
            # Sub-class breakdown in one line
            sub_str = ", ".join(f"{s}({c})" for s, c in cw_sub.most_common())
            p(f"    Sub-class: {sub_str}")
            p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 6: ACTION PATTERN ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("6. ACTION PATTERN ANALYSIS")
    p("=" * 80)
    p("")

    # Overall action distribution
    total_actions = Counter()
    for t in parsed:
        for action, cnt in t.action_counts.items():
            total_actions[action] += cnt

    p("  Action type distribution:")
    grand_total = sum(total_actions.values())
    for action, cnt in total_actions.most_common():
        p(f"    {action:<15} {cnt:>6} ({cnt / grand_total * 100:.1f}%)" if grand_total else f"    {action:<15} {cnt:>6}")
    p(f"    {'TOTAL':<15} {grand_total:>6}")
    p("")

    # Per-task action stats
    p("  Per-task action stats:")
    goto_counts = [t.action_counts.get("goto", 0) for t in parsed]
    click_counts = [t.action_counts.get("click", 0) for t in parsed]
    scroll_counts = [t.action_counts.get("scroll", 0) for t in parsed]
    vm_counts = [t.view_more_count for t in parsed]
    p(f"    goto:      avg={_safe_mean(goto_counts):.1f}, median={_safe_median(goto_counts):.0f}, max={max(goto_counts) if goto_counts else 0}")
    p(f"    click:     avg={_safe_mean(click_counts):.1f}, median={_safe_median(click_counts):.0f}, max={max(click_counts) if click_counts else 0}")
    p(f"    scroll:    avg={_safe_mean(scroll_counts):.1f}, median={_safe_median(scroll_counts):.0f}, max={max(scroll_counts) if scroll_counts else 0}")
    p(f"    view_more: avg={_safe_mean(vm_counts):.1f}, median={_safe_median(vm_counts):.0f}, max={max(vm_counts) if vm_counts else 0}")
    p("")

    # Action type by outcome (scored vs zero)
    scored_for_actions = [t for t in parsed if t.score > 0]
    zero_for_actions = [t for t in parsed if t.is_zero]
    if scored_for_actions and zero_for_actions:
        # Collect all action types that appear
        all_action_types = sorted(set(
            a for t in parsed for a in t.action_counts.keys()
        ))
        p("  Action type by outcome (avg per task):")
        p(f"    {'Action':<15} {'Scored>0':>10} {'Zero':>10} {'Delta':>10} {'Signal':>8}")
        p("    " + chr(9472) * 55)
        for atype in all_action_types:
            s_avg = _safe_mean([t.action_counts.get(atype, 0) for t in scored_for_actions])
            z_avg = _safe_mean([t.action_counts.get(atype, 0) for t in zero_for_actions])
            delta = s_avg - z_avg
            # Signal: significant if relative diff >15% OR absolute diff >=2.0
            # (2+ extra actions per task is always meaningful with max_steps=30)
            mean_val = (s_avg + z_avg) / 2
            rel_diff = abs(delta) / mean_val if mean_val > 0 else 0
            is_sig = rel_diff > 0.15 or abs(delta) >= 2.0
            signal = "+" if delta > 0 and is_sig else (
                     "-" if delta < 0 and is_sig else "~")
            p(f"    {atype:<15} {s_avg:>10.2f} {z_avg:>10.2f} {delta:>+10.2f} {signal:>8}")
        p("")

    # URL loop detection
    p("  URL loop detection:")
    p(f"    Tasks with URL loops (>=3 consecutive same URL): {len(loop_tasks)}/{n} ({len(loop_tasks) / n * 100:.0f}%)")
    if loop_tasks:
        loop_urls = Counter()
        max_streaks = []
        for t in loop_tasks:
            for url, streak in t.url_loops:
                domain = _extract_domain(url)
                loop_urls[domain] += streak
                max_streaks.append(streak)
        p(f"    Max loop streak: {max(max_streaks)}")
        p(f"    Avg max loop streak: {_safe_mean(max_streaks):.1f}")
        p("    Top loop domains:")
        for domain, cnt in loop_urls.most_common(5):
            p(f"      {domain:<30} {cnt:>5} repeated navigations")

        # Loop vs score correlation
        loop_scores = [t.score for t in loop_tasks]
        non_loop_scores = [t.score for t in parsed if not t.has_loops]
        p(f"    Avg score (with loops):    {_safe_mean(loop_scores):.3f}")
        p(f"    Avg score (without loops): {_safe_mean(non_loop_scores):.3f}")
    p("")

    # Navigation efficiency score
    p("  Navigation efficiency:")
    p(f"    Avg URL diversity (unique/total goto): {_safe_mean([t.url_diversity for t in parsed if t.goto_urls]):.2f}")
    p(f"    Avg site coverage: {_safe_mean([t.site_coverage for t in parsed]):.2f}")
    p(f"    Avg steps per subtask: {_safe_mean([t.steps_per_subtask for t in parsed if t.num_subtasks > 0]):.1f}")
    p("")

    # (Scored-vs-zero efficiency comparison moved to Section 6b)

    # Per-website action patterns (all action types)
    # Collect all action types across the dataset
    all_action_types_global = sorted(set(
        a for t in parsed for a in t.action_counts.keys()
    ))
    # Only show action types with meaningful volume (>= 1% of total actions)
    significant_actions = [a for a in all_action_types_global
                           if total_actions.get(a, 0) >= grand_total * 0.01]

    # Exclude task-level actions (stop = answer submission, wait = page loading)
    # from site attribution — they don't meaningfully belong to any site
    site_excluded_actions = {"stop", "wait"}
    site_significant = [a for a in significant_actions if a not in site_excluded_actions]

    p("  Per-website action profile (avg per task, site-attributed):")
    # Table header
    header = f"    {'website':<22} {'n':>4}"
    for a in site_significant:
        header += f" {a:>8}"
    p(header)
    p("    " + chr(9472) * (22 + 4 + 9 * len(site_significant)))

    for site, total, correct, acc, dnc, dnc_pct in site_stats[:8]:
        if site == "unknown":
            continue
        site_lower = site.lower()
        seen_tasks = set()
        site_action_totals = Counter()
        site_task_count = 0
        for t, idx in website_groups[site]:
            if id(t) in seen_tasks:
                continue
            seen_tasks.add(id(t))
            site_task_count += 1
            # Use site_actions for site-attributed counts
            # Match site_lower against all domains in site_actions
            for domain, acounts in t.site_actions.items():
                if site_lower in domain or domain in site_lower:
                    for a in site_significant:
                        site_action_totals[a] += acounts.get(a, 0)

        if site_task_count > 0:
            row = f"    {site[:22]:<22} {site_task_count:>4}"
            for a in site_significant:
                avg_val = site_action_totals[a] / site_task_count
                row += f" {avg_val:>8.1f}"
            p(row)
    p("    (all actions attributed to site via last-goto domain tracking)")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 6b: WINNING vs LOSING TRAJECTORY PATTERNS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("6b. WINNING vs LOSING TRAJECTORY PATTERNS")
    p("=" * 80)
    p("")

    scored_tasks = [t for t in parsed if t.score > 0]
    # Nav-only: exclude zero-navigation tasks to avoid confounding coverage stats
    scored_nav = [t for t in scored_tasks if t.action_counts.get("goto", 0) > 0]
    zero_nav = [t for t in zero_tasks if t.action_counts.get("goto", 0) > 0]

    if scored_tasks and zero_tasks:
        # A. Behavioral fingerprint comparison
        p("  A. BEHAVIORAL FINGERPRINT (scored >0 vs zero):")
        p(f"  {'Metric':<30} {'Scored>0':>10} {'Zero':>10} {'Delta':>10}")
        p("  " + chr(9472) * 62)

        def _metric_row(label, scored_fn, zero_fn):
            sv = scored_fn(scored_tasks)
            zv = zero_fn(zero_tasks)
            delta = sv - zv
            p(f"  {label:<30} {sv:>10.2f} {zv:>10.2f} {delta:>+10.2f}")

        _metric_row("Avg steps",
                    lambda ts: _safe_mean([t.total_steps for t in ts]),
                    lambda ts: _safe_mean([t.total_steps for t in ts]))
        _metric_row("Avg goto/task",
                    lambda ts: _safe_mean([t.action_counts.get("goto", 0) for t in ts]),
                    lambda ts: _safe_mean([t.action_counts.get("goto", 0) for t in ts]))
        _metric_row("Avg view_more/task",
                    lambda ts: _safe_mean([t.view_more_count for t in ts]),
                    lambda ts: _safe_mean([t.view_more_count for t in ts]))
        _metric_row("Avg click/task",
                    lambda ts: _safe_mean([t.action_counts.get("click", 0) for t in ts]),
                    lambda ts: _safe_mean([t.action_counts.get("click", 0) for t in ts]))
        _metric_row("Site coverage",
                    lambda ts: _safe_mean([t.site_coverage for t in ts]),
                    lambda ts: _safe_mean([t.site_coverage for t in ts]))
        _metric_row("URL diversity",
                    lambda ts: _safe_mean([t.url_diversity for t in ts if t.goto_urls]),
                    lambda ts: _safe_mean([t.url_diversity for t in ts if t.goto_urls]) if any(t.goto_urls for t in ts) else 0)
        _metric_row("Steps per subtask",
                    lambda ts: _safe_mean([t.steps_per_subtask for t in ts if t.num_subtasks > 0]),
                    lambda ts: _safe_mean([t.steps_per_subtask for t in ts if t.num_subtasks > 0]))
        p("")

        # Coverage confound check: scored_tasks includes zero-nav tasks (coverage=0)
        # which pull down the scored average. Show nav-only comparison.
        if scored_nav and zero_nav:
            scored_cov_raw = _safe_mean([t.site_coverage for t in scored_tasks])
            scored_cov_nav = _safe_mean([t.site_coverage for t in scored_nav])
            zero_cov_nav = _safe_mean([t.site_coverage for t in zero_nav])
            no_nav_in_scored = len(scored_tasks) - len(scored_nav)
            if no_nav_in_scored > 0 and abs(scored_cov_nav - scored_cov_raw) > 0.05:
                p(f"  NOTE: Site coverage for scored includes {no_nav_in_scored} zero-nav tasks (coverage=0)")
                p(f"    Nav-only comparison: scored={scored_cov_nav:.2f} vs zero={zero_cov_nav:.2f} "
                  f"(delta={scored_cov_nav - zero_cov_nav:+.2f})")
                if scored_cov_nav < zero_cov_nav:
                    p(f"    -> Even with nav-only filter, zero tasks navigate more broadly but fail at extraction")
                else:
                    p(f"    -> With nav-only filter, scored tasks have better coverage (confound resolved)")
                p("")

        # B. Success tipping point: at what step count does score drop to zero?
        p("  B. SUCCESS TIPPING POINT (score vs step count):")
        step_buckets = [(0, 0), (1, 5), (6, 10), (11, 15), (16, 20), (21, 30), (31, 50)]
        p(f"  {'Steps':>10} {'Count':>6} {'Avg Score':>10} {'Scored%':>8} {'Zero%':>7}")
        p("  " + chr(9472) * 45)
        for lo, hi in step_buckets:
            bucket = [t for t in parsed if lo <= t.total_steps <= hi]
            if not bucket:
                continue
            avg_s = _safe_mean([t.score for t in bucket])
            scored_pct = sum(1 for t in bucket if t.score > 0) / len(bucket) * 100
            zero_pct = sum(1 for t in bucket if t.is_zero) / len(bucket) * 100
            p(f"  {f'{lo}-{hi}':>10} {len(bucket):>6} {avg_s:>10.3f} {scored_pct:>7.0f}% {zero_pct:>6.0f}%")
        p("")

        # Identify the tipping point (steepest scored-rate drop between adjacent buckets)
        bucket_scored_rates = []
        for lo, hi in step_buckets:
            bucket = [t for t in parsed if lo <= t.total_steps <= hi]
            if bucket and len(bucket) >= 3:
                scored_rate = sum(1 for t in bucket if t.score > 0) / len(bucket)
                bucket_scored_rates.append((lo, hi, scored_rate, len(bucket)))
        max_drop = 0
        tip_idx = -1
        for i in range(1, len(bucket_scored_rates)):
            drop = bucket_scored_rates[i - 1][2] - bucket_scored_rates[i][2]
            if drop > max_drop:
                max_drop = drop
                tip_idx = i
        if tip_idx >= 0 and max_drop > 0.10:
            prev = bucket_scored_rates[tip_idx - 1]
            curr = bucket_scored_rates[tip_idx]
            p(f"  Tipping point: scored rate drops {prev[2]:.0%} → {curr[2]:.0%} "
              f"between {prev[0]}-{prev[1]} and {curr[0]}-{curr[1]} steps "
              f"(Δ={max_drop:-.0%})")
            p(f"    -> Agent should prioritize efficiency before step {curr[0]}")
        elif bucket_scored_rates:
            # Check if all buckets are uniformly poor
            all_rates = [r for _, _, r, _ in bucket_scored_rates]
            if max(all_rates) - min(all_rates) < 0.15:
                p(f"  No clear tipping point: scored rate is uniformly "
                  f"{_safe_mean(all_rates):.0%} across step ranges")

        # Cross-cut: goto=0 tasks (view_more-only or zero-interaction) mixed into buckets
        no_goto_tasks = [t for t in parsed if t.action_counts.get("goto", 0) == 0]
        with_goto_tasks = [t for t in parsed if t.action_counts.get("goto", 0) > 0]
        if no_goto_tasks and with_goto_tasks:
            ng_avg = _safe_mean([t.score for t in no_goto_tasks])
            ng_scored = sum(1 for t in no_goto_tasks if t.score > 0) / len(no_goto_tasks) * 100
            wg_avg = _safe_mean([t.score for t in with_goto_tasks])
            wg_scored = sum(1 for t in with_goto_tasks if t.score > 0) / len(with_goto_tasks) * 100
            p("")
            p("  Cross-cut by navigation type:")
            p(f"    goto=0 (n={len(no_goto_tasks)}): avg={ng_avg:.3f}, scored={ng_scored:.0f}%"
              f"  — view_more only or zero-interaction")
            p(f"    goto>0 (n={len(with_goto_tasks)}): avg={wg_avg:.3f}, scored={wg_scored:.0f}%"
              f"  — actual browser navigation")
            if ng_avg > wg_avg and len(no_goto_tasks) >= 3:
                p(f"    ⚠ goto=0 tasks score HIGHER ({ng_avg:.3f} vs {wg_avg:.3f})")
                p(f"      — world knowledge bypass outperforms actual browsing")
        p("")

        # C. Per-website winning patterns
        p("  C. PER-WEBSITE WINNING vs LOSING PATTERNS:")
        for site in sorted(website_groups.keys()):
            if site == "unknown":
                continue
            entries = website_groups[site]
            if len(entries) < 5:
                continue

            # Split into correct vs wrong subtasks
            correct_entries = [(t, idx) for t, idx in entries
                               if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5]
            wrong_entries = [(t, idx) for t, idx in entries
                             if idx < len(t.subtask_scores) and t.subtask_scores[idx] < 0.01]

            if not correct_entries or not wrong_entries:
                continue

            p(f"    {site} ({len(correct_entries)} correct, {len(wrong_entries)} wrong):")

            # Winning URL patterns (URLs visited by tasks that got this subtask correct)
            win_urls = Counter()
            lose_urls = Counter()
            site_lower = site.lower()
            for t, idx in correct_entries:
                for url in t.goto_urls:
                    if site_lower in _extract_domain(url):
                        win_urls[url] += 1
            for t, idx in wrong_entries:
                for url in t.goto_urls:
                    if site_lower in _extract_domain(url):
                        lose_urls[url] += 1

            # Show winning-only URLs (appear in wins but not losses, or much higher ratio)
            winning_only = []
            for url, cnt in win_urls.most_common(5):
                lose_cnt = lose_urls.get(url, 0)
                if cnt > lose_cnt:
                    winning_only.append((url, cnt, lose_cnt))

            if winning_only:
                p(f"      Winning URLs (higher hit rate in correct subtasks):")
                for url, w, l in winning_only[:3]:
                    p(f"        {url[:65]}  win={w} lose={l}")
            elif win_urls:
                # Show top winning URLs even if they also appear in losses
                p(f"      Top URLs in correct subtasks:")
                for url, cnt in win_urls.most_common(2):
                    l_cnt = lose_urls.get(url, 0)
                    p(f"        {url[:65]}  win={cnt} lose={l_cnt}")

            # Action profile comparison (site-attributed)
            # Collect site-specific action counts for winning vs losing tasks
            def _site_action_avg(task_entries, site_key):
                """Get avg site-attributed action counts for a set of (task, idx) entries."""
                seen = set()
                totals = Counter()
                count = 0
                for t, idx in task_entries:
                    if id(t) not in seen:
                        seen.add(id(t))
                        count += 1
                        for domain, acounts in t.site_actions.items():
                            if site_key in domain or domain in site_key:
                                for a, v in acounts.items():
                                    totals[a] += v
                if count == 0:
                    return {}, 0
                return {a: totals[a] / count for a in totals}, count

            win_profile, n_win = _site_action_avg(correct_entries, site_lower)
            lose_profile, n_lose = _site_action_avg(wrong_entries, site_lower)

            if win_profile and lose_profile:
                # Show the most differentiating actions for this site
                all_acts = sorted(set(list(win_profile.keys()) + list(lose_profile.keys())))
                # Filter to actions with meaningful signal (>= 0.3 avg in either group)
                diffs = []
                for a in all_acts:
                    if a in site_excluded_actions:
                        continue
                    wv = win_profile.get(a, 0)
                    lv = lose_profile.get(a, 0)
                    if wv >= 0.3 or lv >= 0.3:
                        diffs.append((a, wv, lv, wv - lv))
                diffs.sort(key=lambda x: -abs(x[3]))
                if diffs:
                    parts = []
                    for a, wv, lv, delta in diffs[:4]:
                        # Use relative difference for signal: >15% of mean = significant
                        mean_val = (wv + lv) / 2
                        rel_diff = abs(delta) / mean_val if mean_val > 0 else 0
                        is_sig = rel_diff > 0.15 or abs(delta) >= 2.0
                        sig = "+" if delta > 0 and is_sig else (
                              "-" if delta < 0 and is_sig else "~")
                        parts.append(f"{a}: w={wv:.1f} l={lv:.1f}{sig}")
                    p(f"      Actions (site-attributed, n={n_win}w/{n_lose}l): {' | '.join(parts)}")
            p("")
    else:
        p("  Insufficient data for winning/losing comparison.")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 7: ENVIRONMENT OPTIMIZATION SUGGESTIONS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("7. ENVIRONMENT OPTIMIZATION SUGGESTIONS")
    p("=" * 80)
    p("")

    opts = []

    # OPT-1: Multi-site navigation failure
    if multi_site and multi_missed_pct > 50:
        p(f"  [OPT-1] MULTI-SITE NAVIGATION FAILURE: {multi_missed_pct:.0f}% of multi-site tasks miss >=1 site")
        p("    Impact: this is the #1 bottleneck for LIVEWEB performance")
        p("    Suggestions:")
        p("      - Add explicit site-switching hints in system prompt")
        p("      - Implement per-site step budget allocation (total_steps / num_subtasks)")
        p("      - Add progress tracking: 'You have completed N/M subtasks'")
        p("")
        opts.append("OPT-1: multi-site navigation failure")

    # OPT-2: URL loops
    if loop_tasks and len(loop_tasks) / n > 0.3:
        p(f"  [OPT-2] URL LOOP EPIDEMIC: {len(loop_tasks)}/{n} ({len(loop_tasks) / n * 100:.0f}%) tasks have URL loops")
        p("    Suggestions:")
        p("      - Add loop detection in agent harness (detect >=3 consecutive same-URL goto)")
        p("      - Auto-pivot strategy: if URL loop detected, force different action")
        p("      - Reduce max_iterations for single URL to prevent resource waste")
        p("")
        opts.append("OPT-2: URL loop epidemic")

    # OPT-3: Specific website issues
    for site, total, correct, acc, dnc, dnc_pct in site_stats:
        if site == "unknown" or total < 5:
            continue
        # stooq.com "step blackhole"
        if "stooq" in site.lower() and acc < 30:
            # Compute actual per-task action stats for stooq
            stooq_entries = website_groups.get(site, [])
            stooq_seen = set()
            stooq_goto_total, stooq_vm_total, stooq_task_n = 0, 0, 0
            for t, idx in stooq_entries:
                if id(t) not in stooq_seen:
                    stooq_seen.add(id(t))
                    stooq_task_n += 1
                    for url in t.goto_urls:
                        if "stooq" in _extract_domain(url):
                            stooq_goto_total += 1
                    stooq_vm_total += t.view_more_count
            stooq_goto_avg = stooq_goto_total / max(stooq_task_n, 1)
            stooq_vm_avg = stooq_vm_total / max(stooq_task_n, 1)
            p(f"  [OPT-3a] STOOQ STEP BLACKHOLE: {site} at {acc:.0f}% accuracy")
            p("    Agent loops on stooq.com/q/ without proper URL parameters")
            p(f"    Evidence: avg {stooq_goto_avg:.1f} goto/task vs {stooq_vm_avg:.1f} view_more — agent uses goto excessively")
            p("    Fix: system prompt builder should include URL construction hints per plugin")
            p("    Suggestion: add plugin_hints for stooq URL patterns (e.g. /q/?s=TICKER.US)")
            p("")
            opts.append(f"OPT-3a: {site} step blackhole")
        # taostats.io view_more trap
        if "taostats" in site.lower() and acc < 30:
            # Compute actual winning vs losing view_more for taostats
            tao_entries = website_groups.get(site, [])
            tao_win_vm, tao_lose_vm = [], []
            tao_seen_w, tao_seen_l = set(), set()
            for t, idx in tao_entries:
                is_correct = idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5
                if is_correct and id(t) not in tao_seen_w:
                    tao_seen_w.add(id(t))
                    tao_win_vm.append(t.view_more_count)
                elif not is_correct and id(t) not in tao_seen_l:
                    tao_seen_l.add(id(t))
                    tao_lose_vm.append(t.view_more_count)
            tao_win_avg = _safe_mean(tao_win_vm)
            tao_lose_avg = _safe_mean(tao_lose_vm)
            p(f"  [OPT-3b] TAOSTATS VIEW_MORE NUANCE: {site} at {acc:.0f}% accuracy")
            if tao_win_avg > tao_lose_avg:
                p(f"    CAUTION: winning taostats tasks use MORE view_more ({tao_win_avg:.1f} vs {tao_lose_avg:.1f})")
            else:
                p(f"    view_more profile: win={tao_win_avg:.1f} vs lose={tao_lose_avg:.1f}")
            p("    The issue is NOT view_more itself — it's view_more WITHOUT goto navigation")
            p("    Evidence: zero-coverage tasks using only view_more score 0, but tasks")
            p("      combining goto + view_more have higher success rates")
            p("    Suggestion: cap view_more only when goto=0 (no initial navigation)")
            p("      Do NOT cap view_more globally — it helps on data-dense sites like taostats")
            p("")
            opts.append(f"OPT-3b: {site} view_more trap")
        # DD (DuckDuckGo) at 0% accuracy
        if "duckduckgo" in site.lower() and acc < 5:
            p(f"  [OPT-3c] DUCKDUCKGO GT ISSUE: {site} at {acc:.0f}% accuracy ({total} tasks)")
            p("    All DuckDuckGo-based tasks fail — likely ground truth collection issue")
            p("    Suggestion: investigate if GT was collected via DD search (results change over time)")
            p("")
            opts.append(f"OPT-3c: {site} GT collection issue")

    # OPT-4: 3-site tasks at 0% perfect
    three_site = subtask_groups.get(3, [])
    if three_site and sum(1 for t in three_site if t.is_perfect) == 0:
        p(f"  [OPT-4] 3-SITE TASKS AT 0% PERFECT: {len(three_site)} tasks, none completed")
        p(f"    Evidence: 3-site avg steps={_safe_mean([t.total_steps for t in three_site]):.0f}, "
          f"{sum(1 for t in three_site if t.step_budget_exhausted)} budget-exhausted")
        p("    Fix: environment config uses fixed max_iterations — should scale with num_subtasks")
        p("    Suggestion: max_iterations = base * num_subtasks (e.g. 15 * 3 = 45 for 3-site)")
        p("")
        opts.append("OPT-4: 3-site tasks at 0% perfect")

    # OPT-5: Step budget exhaustion
    if budget_exhausted and len(budget_exhausted) / n > 0.4:
        p(f"  [OPT-5] HIGH STEP BUDGET EXHAUSTION: {len(budget_exhausted)}/{n} ({len(budget_exhausted) / n * 100:.0f}%) tasks exhaust step budget")
        p(f"    This is the #1 root cause of wrong answers ({rc_budget}/{total_wrong_pre}, {rc_budget / max(total_wrong_pre, 1) * 100:.0f}%)")
        p("    Fix: template expected_steps underestimates actual difficulty for multi-site tasks")
        p("    Suggestion: either increase budget or add early-exit when agent is clearly stuck")
        p("")
        opts.append("OPT-5: high step budget exhaustion")

    # OPT-8: World knowledge bypass (from forensics)
    if suspicious_tasks and len(suspicious_tasks) >= 3:
        p(f"  [OPT-8] WORLD KNOWLEDGE BYPASS: {len(suspicious_tasks)} tasks score without site visits")
        p("    Evidence: tasks with 0% coverage score avg {:.3f}".format(
            _safe_mean([t.score for t in suspicious_tasks])))
        p("    Fix: scoring function does not verify that answers came from page content")
        p("    Suggestion: add navigation_required flag — reject answers if site_coverage < threshold")
        p("    Alternative: use PAGE_ONLY GT source (like openlibrary plugin) for all plugins")
        p("")
        opts.append("OPT-8: world knowledge bypass")

    # OPT-6: Question type gaps (skip "other" — it's a catch-all, not actionable)
    for qtype, qt_total, qt_correct, qt_acc in qtype_stats:
        if qt_total >= 5 and qt_acc < 20 and qtype != "other":
            p(f"  [OPT-6] QUESTION TYPE GAP: {qtype} at {qt_acc:.0f}% accuracy ({qt_total} subtasks)")
            p(f"    Suggestion: focus SFT training on {qtype}-type queries")
            p("")
            opts.append(f"OPT-6: {qtype} question type gap")
            break  # Only show worst one

    # OPT-7: Token usage optimization
    all_tokens = [t.total_tokens for t in parsed if t.total_tokens > 0]
    if all_tokens:
        perf_tokens = [t.total_tokens for t in perfect_tasks if t.total_tokens > 0]
        zero_tokens = [t.total_tokens for t in zero_tasks if t.total_tokens > 0]
        if perf_tokens and zero_tokens and _safe_mean(zero_tokens) > _safe_mean(perf_tokens) * 1.5:
            p(f"  [OPT-7] TOKEN WASTE ON ZERO TASKS:")
            p(f"    Perfect avg tokens: {_safe_mean(perf_tokens):.0f}")
            p(f"    Zero avg tokens:    {_safe_mean(zero_tokens):.0f}")
            p("    Suggestion: implement early termination for clearly failing tasks")
            p("")
            opts.append("OPT-7: token waste on zero tasks")

    if opts:
        p(f"  Summary: {len(opts)} recommendations")
        for opt in opts:
            p(f"    - {opt}")
    else:
        p("  No significant optimization recommendations at current data level.")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 8: SFT STRATEGY
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("8. SFT STRATEGY")
    p("=" * 80)
    p("")
    p("  TRAINING DATA CANDIDATES:")
    p("")

    # Strategy 1: Multi-site navigation fix (highest leverage)
    multi_zeros = [t for t in multi_site if t.is_zero]
    multi_partials = [t for t in multi_site if not t.is_zero and not t.is_perfect]
    potential_gain = len(multi_zeros) * avg_score if multi_zeros else 0

    p(f"  1. MULTI-SITE NAVIGATION FIX [highest leverage]:")
    p(f"     Zero-score multi-site tasks: {len(multi_zeros)}")
    p(f"     Partial multi-site tasks: {len(multi_partials)}")
    if multi_zeros:
        p(f"     Potential score gain if fixed: +{potential_gain / n:.3f} avg score")
    p("     Priority: teach agent to visit ALL required sites before answering")
    p("     Data source: perfect multi-site tasks as positive examples")
    if perfect_tasks:
        multi_perfect_examples = [t for t in perfect_tasks if t.is_multi_site]
        p(f"     Available positive examples: {len(multi_perfect_examples)} perfect multi-site tasks")
    p("")

    # Strategy 2: Extraction fix (highest per-task ROI)
    partial_tasks = [t for t in parsed if not t.is_zero and not t.is_perfect]
    extraction_candidates = []
    for t in partial_tasks:
        # Tasks where agent visited right sites but extracted wrong data
        if t.site_coverage >= 0.8 and t.wrong_answers:
            extraction_candidates.append(t)

    p(f"  2. EXTRACTION FIX [highest per-task ROI]:")
    p(f"     Partial tasks with correct navigation but wrong extraction: {len(extraction_candidates)}")
    if extraction_candidates:
        avg_partial_score = _safe_mean([t.score for t in extraction_candidates])
        p(f"     Current avg score: {avg_partial_score:.3f}")
        p(f"     Potential per-task gain: {1.0 - avg_partial_score:.3f}")
    p("     Priority: teach precise data extraction from accessibility tree")
    p("     Focus areas: wrong_entity/metric, verbose_wrong")
    p("")

    # Strategy 3: Weakness targets (condensed — see Sections 3 & 5 for full data)
    p("  3. WEAKNESS TARGETS (see Sections 3, 5 for details):")
    # Per-website: one line per weak site with SFT action
    for site, total, correct, acc, dnc, dnc_pct in site_stats[:8]:
        if site == "unknown" or total < 3 or acc >= 40:
            continue
        action = "navigation" if dnc > total * 0.05 else "extraction"
        p(f"     {site} ({acc:.0f}%, n={total}): teach {action}")
    # Per-question-type: weakest types with root cause annotation
    weakest_qtypes = [(qt, qt_total, qa) for qt, qt_total, _, qa in qtype_stats
                      if qa < 30 and qt_total >= 5]
    if weakest_qtypes:
        qt_parts = []
        for qt, qt_total, qa in weakest_qtypes[:6]:
            # Determine dominant root cause: budget vs extract with mixed detection
            qt_wrong = [w for w in all_wrong if w.get("qtype") == qt]
            if qt_wrong:
                n_wrong = len(qt_wrong)
                b_cnt = sum(1 for w in qt_wrong if w.get("_nav_root_cause") == "budget_exhausted")
                e_cnt = sum(1 for w in qt_wrong if w.get("_nav_root_cause") == "wrong_extraction")
                b_pct = b_cnt / n_wrong * 100
                e_pct = e_cnt / n_wrong * 100
                if abs(b_pct - e_pct) < 10:
                    rc_label = "mixed"
                elif b_pct > e_pct:
                    rc_label = "budget"
                else:
                    rc_label = "extract"
                qt_parts.append(f"{qt}({qa:.0f}%,{rc_label})")
            else:
                qt_parts.append(f"{qt}({qa:.0f}%)")
        p(f"     Weak question types: {', '.join(qt_parts)}")
    p("")

    # Improvement priority ranking (navigation-aware)
    p("  IMPROVEMENT PRIORITY RANKING (root-cause weighted):")
    p("")

    # Reuse pre-computed root cause counts (from TOP FINDINGS)
    _rc_budget = rc_budget
    _rc_extract = rc_wrong_extract
    _rc_never = rc_never
    _rc_no_nav = rc_no_nav

    priorities = []
    if _rc_budget > 0:
        # Estimate score gain: budget-exhausted tasks avg score with more steps
        be_tasks = [t for t in parsed if t.step_budget_exhausted]
        be_current = _safe_mean([t.score for t in be_tasks])
        priorities.append(("Step budget / efficiency", _rc_budget,
                           f"{_rc_budget} wrong answers from budget exhaustion "
                           f"(avg score {be_current:.3f}), fix via step allocation or early-exit"))
    if _rc_extract > 0:
        priorities.append(("Extraction accuracy", _rc_extract,
                           f"{_rc_extract} wrong answers on correctly-navigated sites"))
    if _rc_no_nav > 0:
        priorities.append(("Zero-nav guessing", _rc_no_nav,
                           f"{_rc_no_nav} wrong answers from tasks with no goto navigation"))
    if _rc_never > 0:
        priorities.append(("Site discovery / navigation", _rc_never,
                           f"{_rc_never} wrong answers from never visiting the required site"))
    if extraction_candidates:
        priorities.append(("Partial→Perfect conversion", len(extraction_candidates),
                           f"{len(extraction_candidates)} partial tasks with good coverage "
                           f"(avg {_safe_mean([t.score for t in extraction_candidates]):.3f}→1.0)"))

    priorities.sort(key=lambda x: -x[1])
    for i, (name, count, desc) in enumerate(priorities, 1):
        p(f"    {i}. [{count} wrong answers] {name}")
        p(f"       {desc}")
    if not priorities:
        p("    No specific priorities identified.")
    p("")

    # Data synthesis strategy
    p("  DATA SYNTHESIS PIPELINE:")
    p("")

    # Pipeline 1: Perfect trajectory export
    if perfect_tasks:
        p(f"  A. POSITIVE EXAMPLES (n={len(perfect_tasks)}):")
        p(f"     Source: perfect-score trajectories (score=1.0)")
        p(f"     Format: multi-turn conversation (user=observation, assistant=tool_call)")
        p(f"     Use: liveweb-arena eval.py --export-sft to extract in JSONL format")
        multi_perf = [t for t in perfect_tasks if t.is_multi_site]
        p(f"     Multi-site perfect: {len(multi_perf)} (highest training value)")
        if multi_perf:
            avg_steps_perf = _safe_mean([t.total_steps for t in multi_perf])
            p(f"     Avg steps in perfect multi-site: {avg_steps_perf:.0f} (target step budget)")
        p("")

    # Pipeline 2: Partial trajectory repair
    if extraction_candidates:
        p(f"  B. TRAJECTORY REPAIR (n={len(extraction_candidates)}):")
        p(f"     Source: partial tasks with coverage>=0.8 but wrong extraction")
        p(f"     Method: keep navigation prefix, replace final extraction with correct answer")
        p(f"     Current avg: {_safe_mean([t.score for t in extraction_candidates]):.3f} → target 1.0")
        # Identify which subtask types fail in these tasks
        repair_wrong_types = Counter()
        for t in extraction_candidates:
            for w in t.wrong_answers:
                repair_wrong_types[w.get("sub_class") or w["classification"]] += 1
        if repair_wrong_types:
            top_repair = repair_wrong_types.most_common(3)
            p(f"     Top repair targets: {', '.join(f'{k}({v})' for k, v in top_repair)}")
        p("")

    # Pipeline 3: Negative examples (anti-patterns to avoid)
    anti_patterns = []
    vm_loop_tasks = [t for t in parsed if t.view_more_count >= 20 and t.is_zero]
    url_loop_tasks_for_synth = [t for t in parsed if t.has_loops and t.is_zero]
    if vm_loop_tasks:
        anti_patterns.append(f"view_more loops (n={len(vm_loop_tasks)}): agent clicking view_more >20x without extracting")
    if url_loop_tasks_for_synth:
        anti_patterns.append(f"URL loops (n={len(url_loop_tasks_for_synth)}): repeated goto to same URL >=3x")
    stuck_single_site = [t for t in multi_site if t.is_zero and t.site_coverage < 0.5
                         and t.total_steps >= 15]
    if stuck_single_site:
        anti_patterns.append(f"stuck on 1st site (n={len(stuck_single_site)}): >=15 steps on first site, never moved")
    if anti_patterns:
        p(f"  C. ANTI-PATTERN EXAMPLES (DPO negative pairs):")
        for ap in anti_patterns:
            p(f"     - {ap}")
        p(f"     Method: pair with corrected trajectory (positive) for DPO/RLHF training")
        p("")

    # Pipeline 4: Per-website synthesis recipe with MVD estimation
    p("  D. PER-WEBSITE SYNTHESIS RECIPE + MINIMUM VIABLE DATASET:")
    p("")

    # MVD thresholds (empirical: SFT needs ~50 examples per category for signal)
    MVD_PER_SITE = 50  # minimum positive examples per website
    MVD_PER_QTYPE = 30  # minimum per question type

    total_have = 0
    total_need = 0
    site_mvd_rows = []
    for site, total, correct, acc, dnc, dnc_pct in site_stats[:8]:
        if site == "unknown" or total < 3:
            continue
        correct_count = sum(
            1 for t, idx in website_groups[site]
            if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5
        )
        gap = max(0, MVD_PER_SITE - correct_count)
        total_have += correct_count
        total_need += gap
        site_mvd_rows.append((site, correct_count, gap, acc))

    p(f"  {'Website':<25} {'Have':>5} {'Need':>5} {'Gap':>5} {'Acc%':>6}")
    p("  " + chr(9472) * 50)
    for site, have, gap, acc in site_mvd_rows:
        status = "OK" if gap == 0 else f"+{gap}"
        p(f"  {site[:25]:<25} {have:>5} {MVD_PER_SITE:>5} {status:>5} {acc:>5.0f}%")
    p(f"  {'TOTAL':<25} {total_have:>5} {total_have + total_need:>5} {'+' + str(total_need) if total_need > 0 else 'OK':>5}")
    p("")

    if total_need > 0:
        p(f"     Synthesis needed: {total_need} additional positive trajectories")
        p(f"     Method: run eval.py --templates <plugin>/<template> --export-sft")
        p(f"     Estimate: at current {_safe_mean([s[3] for s in site_mvd_rows]):.0f}% avg success rate,")
        avg_acc = _safe_mean([s[3] for s in site_mvd_rows]) / 100
        if avg_acc > 0:
            runs_needed = int(total_need / avg_acc)
            p(f"     ~{runs_needed} eval runs needed to collect {total_need} successes")
        p("")
    else:
        p("     All websites meet MVD threshold.")
        p("")

    # Question-type MVD
    qtype_gaps = []
    for qtype, qt_total, qt_correct, qt_acc in qtype_stats:
        if qt_total >= 3:
            gap = max(0, MVD_PER_QTYPE - qt_correct)
            if gap > 0:
                qtype_gaps.append((qtype, qt_correct, gap, qt_acc))
    if qtype_gaps:
        p("  Question-type gaps (need >=30 correct per type):")
        for qtype, have, gap, acc in sorted(qtype_gaps, key=lambda x: -x[2])[:5]:
            p(f"     {qtype:<20} have={have:>3}, need +{gap}, acc={acc:.0f}%")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 9: MEMORIZATION / OVERFITTING ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("9. MEMORIZATION / OVERFITTING ANALYSIS")
    p("=" * 80)
    p("")

    # Detect tasks where agent scores without navigation (world-knowledge leakage)
    no_nav_scored = [t for t in parsed if t.action_counts.get("goto", 0) == 0 and t.score > 0]
    no_nav_zero = [t for t in parsed if t.action_counts.get("goto", 0) == 0 and t.is_zero]
    nav_tasks = [t for t in parsed if t.action_counts.get("goto", 0) > 0]

    p("  A. ZERO-NAVIGATION SCORING (possible world knowledge / memorization):")
    p(f"     Tasks scoring >0 with 0 goto actions: {len(no_nav_scored)}/{n} ({len(no_nav_scored) / n * 100:.1f}%)")
    if no_nav_scored:
        p(f"     Avg score (no-nav, scored): {_safe_mean([t.score for t in no_nav_scored]):.3f}")
        if nav_tasks:
            p(f"     Avg score (with-nav):       {_safe_mean([t.score for t in nav_tasks]):.3f}")
        p("")
        # Show details of zero-nav scored tasks
        p("     Zero-navigation scored tasks:")
        p(f"     {'task_id':>8} {'score':>5} {'#sub':>4} {'subtask_scores':<20} {'actions':<20}")
        p("     " + chr(9472) * 65)
        for t in sorted(no_nav_scored, key=lambda x: -x.score):
            ss = ",".join(f"{s:.0f}" if s == int(s) else f"{s:.2f}" for s in t.subtask_scores)
            action_str = ", ".join(f"{k}={v}" for k, v in t.action_counts.items() if v > 0)
            if not action_str:
                action_str = "none"
            p(f"     {t.task_id:>8} {t.score:>5.2f} {t.num_subtasks:>4} {ss:<20} {action_str:<20}")
        p("")

        # Analyze: are these tasks easier or does agent use memorized knowledge?
        no_nav_qtypes = Counter()
        for t in no_nav_scored:
            for qt in t.subtask_qtypes:
                no_nav_qtypes[qt] += 1
        if no_nav_qtypes:
            p("     Question types in zero-nav scored tasks:")
            for qt, cnt in no_nav_qtypes.most_common():
                p(f"       {qt:<20} {cnt}")
            p("")

        # Flag: if zero-nav scored rate > 10%, this is a memorization concern
        no_nav_rate = len(no_nav_scored) / n * 100
        if no_nav_rate > 10:
            p(f"     ⚠ WARNING: {no_nav_rate:.0f}% of tasks score without any goto navigation.")
            p("       This suggests the agent may be using world knowledge or memorization")
            p("       rather than actually browsing. Investigate whether these answers come")
            p("       from the LLM's training data rather than live page content.")
            p("")
    else:
        p("     (none detected)")
        p("")

    # B. Repeated URL pattern analysis (overfitting to specific URL patterns)
    p("  B. URL PATTERN CONCENTRATION (overfitting indicator):")
    all_goto_urls = []
    for t in parsed:
        all_goto_urls.extend(t.goto_urls)
    if all_goto_urls:
        url_counter = Counter(all_goto_urls)
        total_gotos = len(all_goto_urls)
        top_5_urls = url_counter.most_common(5)
        top_5_count = sum(cnt for _, cnt in top_5_urls)
        p(f"     Total goto actions: {total_gotos}")
        p(f"     Unique URLs: {len(url_counter)}")
        p(f"     Top 5 URLs account for: {top_5_count}/{total_gotos} ({top_5_count / total_gotos * 100:.0f}%)")
        p("")
        for url, cnt in top_5_urls:
            p(f"       {cnt:>4}x  {url[:80]}")
        p("")
        # Flag concentrated patterns
        if len(url_counter) < total_gotos * 0.15:
            p("     ⚠ Low URL diversity — agent may be stuck in repetitive navigation patterns")
            p("")
    else:
        p("     No goto URLs recorded.")
        p("")

    # C. Score vs step-count correlation (overfitting to short-cuts)
    p("  C. VIEW_MORE-ONLY BEHAVIOR (no goto navigation):")
    vm_only = [t for t in parsed if t.action_counts.get("goto", 0) == 0
               and t.view_more_count > 0]
    if vm_only:
        p(f"     Tasks with only view_more (no goto): {len(vm_only)}/{n}")
        vm_scored = [t for t in vm_only if t.score > 0]
        vm_zero = [t for t in vm_only if t.is_zero]
        p(f"       Scored >0: {len(vm_scored)}  Zero: {len(vm_zero)}")
        if vm_scored:
            p(f"       Avg score (view_more only, scored): {_safe_mean([t.score for t in vm_scored]):.3f}")
            p(f"       Avg view_more count: {_safe_mean([t.view_more_count for t in vm_scored]):.1f}")
            p("       These tasks answer correctly using only view_more — possible if page was")
            p("       already loaded, but suspicious if site_coverage is 0%.")
        p("")
    else:
        p("     (none detected)")
        p("")

    # D. Seed repetition check (if seeds are available)
    seeds = [t.seed for t in parsed if t.seed is not None]
    if seeds:
        seed_counter = Counter(seeds)
        repeated_seeds = {s: c for s, c in seed_counter.items() if c > 1}
        if repeated_seeds:
            p("  D. SEED REPETITION CHECK:")
            p(f"     Seeds with >1 occurrence: {len(repeated_seeds)}")
            for seed, cnt in sorted(repeated_seeds.items(), key=lambda x: -x[1])[:5]:
                p(f"       seed={seed} appears {cnt}x")
            p("     Repeated seeds could enable memorization of specific task instances.")
            p("")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 10: SUSPICIOUS TRAJECTORY FORENSICS
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("10. SUSPICIOUS TRAJECTORY FORENSICS")
    p("=" * 80)
    p("")
    p("  Tasks flagged for environment or agent format issues:")
    p("")

    flagged = []

    # Flag E: Tasks with 0 subtasks (task initialization failure — ENV issue)
    for t in parsed:
        if t.num_subtasks == 0:
            flagged.append((t, "EMPTY_TASK",
                            f"num_subtasks=0, steps={t.total_steps} — "
                            f"task may have failed to initialize (no answer_details)"))

    # Flag F: Tasks with parse_failed — AGENT format error (not env issue)
    # Agent outputs stop action in content text instead of tool_calls array
    # Also attempt answer recovery: extract answers from content and compare with expected
    parse_failed_recovery = []  # (task, mode, recovered_answers, match_count, total_subtasks)
    for t in parsed:
        if t.failure_reason and "parse" in str(t.failure_reason).lower():
            # Classify the format error mode
            asst_msgs = [m for m in t.conversation if m.get("role") == "assistant"]
            mode = "unknown"
            recovered_answers = []
            if asst_msgs:
                content = str(asst_msgs[-1].get("content", "") or "")
                tc = asst_msgs[-1].get("tool_calls") or []
                if tc:
                    mode = "has_tc_but_invalid"
                elif "<tool_call>" in content or "<tool>" in content:
                    mode = "xml_tool_call"
                elif '"name"' in content and '"arguments"' in content:
                    mode = "bare_json"
                else:
                    mode = "plain_text"

                # Attempt answer extraction from content for recoverable modes
                if mode in ("bare_json", "xml_tool_call"):
                    # Strategy 1: Find the outermost JSON blob containing "stop"+"answers"
                    # Content may have <tool_call>JSON</tool_call> or bare JSON
                    # Answers format: {"answer1": "...", "answer2": "..."} (dict) or ["...", "..."] (list)
                    json_candidates = []
                    # Strip XML tags if present
                    clean = re.sub(r'</?tool_call>', '', content)
                    # Find all JSON-like blobs (greedy nested braces)
                    brace_depth = 0
                    start = -1
                    for ci, ch in enumerate(clean):
                        if ch == '{':
                            if brace_depth == 0:
                                start = ci
                            brace_depth += 1
                        elif ch == '}':
                            brace_depth -= 1
                            if brace_depth == 0 and start >= 0:
                                json_candidates.append(clean[start:ci+1])
                                start = -1

                    for blob in json_candidates:
                        if '"answers"' not in blob and '"answer' not in blob:
                            continue
                        try:
                            obj = json.loads(blob)
                        except json.JSONDecodeError:
                            # Try fixing common issues: missing closing brace
                            try:
                                obj = json.loads(blob + '}')
                            except json.JSONDecodeError:
                                continue

                        # Navigate to answers: obj.arguments.answers or obj.answers
                        ans_obj = None
                        if isinstance(obj, dict):
                            if "arguments" in obj:
                                args = obj["arguments"]
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except json.JSONDecodeError:
                                        args = {}
                                if isinstance(args, dict):
                                    ans_obj = args.get("answers")
                            elif "answers" in obj:
                                ans_obj = obj["answers"]

                        if ans_obj is not None:
                            if isinstance(ans_obj, dict):
                                # {"answer1": "...", "answer2": "..."} → ordered list
                                keys = sorted(ans_obj.keys())
                                recovered_answers = [str(ans_obj[k]).strip() for k in keys]
                            elif isinstance(ans_obj, list):
                                recovered_answers = [str(a).strip() for a in ans_obj]
                            else:
                                recovered_answers = [str(ans_obj).strip()]
                            break

            # Compare recovered answers with expected
            # NOTE: liveweb-arena uses LLM-based validation (not exact match).
            # The LLM validator is flexible with format differences.
            # Our matching here is still conservative but aligned closer to real scoring:
            # 1. case-insensitive exact match
            # 2. numeric within 5% (LLM validator accepts format differences)
            # 3. substring containment (expected in actual or vice versa, min 3 chars)
            match_count = 0
            if recovered_answers and t.answer_details:
                for idx, detail in enumerate(t.answer_details):
                    if not isinstance(detail, dict):
                        continue
                    expected = str(detail.get("expected", "")).strip().lower()
                    if idx < len(recovered_answers):
                        actual = recovered_answers[idx].strip().lower()
                        if expected and actual:
                            # Match 1: exact (case-insensitive)
                            if actual == expected:
                                match_count += 1
                                continue
                            # Match 2: normalize whitespace/punctuation
                            a_norm = re.sub(r'[\s,_\-]+', ' ', actual).strip()
                            e_norm = re.sub(r'[\s,_\-]+', ' ', expected).strip()
                            if a_norm == e_norm:
                                match_count += 1
                                continue
                            # Match 3: numeric within 5%
                            matched = False
                            try:
                                a_num = float(re.sub(r'[$%,\s]', '', actual))
                                e_num = float(re.sub(r'[$%,\s]', '', expected))
                                if e_num != 0 and abs(a_num - e_num) / abs(e_num) < 0.05:
                                    matched = True
                            except (ValueError, TypeError):
                                pass
                            # Match 4: substring containment (min 3 chars)
                            if not matched and len(expected) >= 3:
                                if expected in actual or actual in expected:
                                    matched = True
                            if matched:
                                match_count += 1

            parse_failed_recovery.append((t, mode, recovered_answers, match_count, t.num_subtasks))
            flagged.append((t, "PARSE_FAILED",
                            f"score={t.score:.2f}, steps={t.total_steps}, "
                            f"mode={mode} — agent wrote stop in content text, not tool_calls"))

    # Flag A: Score > 0 with 0 total steps (zero browser interaction)
    for t in parsed:
        if t.score > 0 and t.total_steps == 0:
            flagged.append((t, "ZERO_INTERACTION",
                            f"score={t.score:.2f} with 0 total steps — agent answered without any browser action"))

    # Flag B: Score > 0 with 0% coverage (never visited any required site)
    for t in parsed:
        if t.score > 0 and t.site_coverage < 0.01 and t.total_steps > 0:
            flagged.append((t, "ZERO_COVERAGE",
                            f"score={t.score:.2f}, coverage=0%, steps={t.total_steps} — "
                            f"scored without visiting required sites"))

    # Flag C: Individual subtask scores 1.0 on sites never visited
    # Also collect expected/actual for forensic answer verification
    unvisited_evidence = {}  # task_id -> list of (subtask_idx, site, expected, actual, question)
    for t in parsed:
        for idx in range(min(len(t.subtask_scores), len(t.subtask_websites))):
            if t.subtask_scores[idx] >= 1.0:
                site = t.subtask_websites[idx].lower()
                visited = any(site in d or d in site for d in t.goto_domains)
                if not visited:
                    # Collect evidence from answer_details
                    expected = ""
                    actual = ""
                    question = t.subtask_questions[idx] if idx < len(t.subtask_questions) else ""
                    if idx < len(t.answer_details) and isinstance(t.answer_details[idx], dict):
                        expected = str(t.answer_details[idx].get("expected", ""))[:60]
                        actual = str(t.answer_details[idx].get("actual", ""))[:60]
                    if t.task_id not in unvisited_evidence:
                        unvisited_evidence[t.task_id] = []
                        flagged.append((t, "UNVISITED_CORRECT",
                                        f"subtask {idx+1} ({site}) scores 1.0 but site never visited via goto"))
                    unvisited_evidence[t.task_id].append(
                        (idx, site, expected, actual, question)
                    )

    # Flag D: Extremely high view_more with zero score (possible infinite loop)
    for t in parsed:
        if t.view_more_count >= 30 and t.is_zero:
            flagged.append((t, "VM_LOOP",
                            f"view_more={t.view_more_count} with score=0 — agent stuck in view_more loop"))

    if flagged:
        # Deduplicate: group flags by task_id, show most severe first
        from collections import OrderedDict
        flag_severity = {"EMPTY_TASK": 0, "PARSE_FAILED": 1, "ZERO_INTERACTION": 2,
                         "UNVISITED_CORRECT": 3, "ZERO_COVERAGE": 4, "VM_LOOP": 5}
        task_flags = OrderedDict()
        for t, flag_type, reason in flagged:
            if t.task_id not in task_flags:
                task_flags[t.task_id] = (t, [])
            task_flags[t.task_id][1].append((flag_type, reason))

        # Sort tasks by score descending
        sorted_tasks = sorted(task_flags.values(), key=lambda x: -x[0].score)

        unique_task_count = len(sorted_tasks)
        p(f"  Flagged: {unique_task_count} unique tasks with suspicious patterns")
        p("")

        # Separate bulk flags (summarize) from high-value flags (show detail)
        bulk_flag_types = {"PARSE_FAILED", "EMPTY_TASK"}
        detail_tasks = [(t, flags) for t, flags in sorted_tasks
                        if any(ft not in bulk_flag_types for ft, _ in flags)]
        bulk_tasks = [(t, flags) for t, flags in sorted_tasks
                      if all(ft in bulk_flag_types for ft, _ in flags)]

        # Show detailed flags individually
        for t, flags in detail_tasks:
            flags.sort(key=lambda x: flag_severity.get(x[0], 99))
            primary = flags[0]
            p(f"  [{primary[0]}] Task {t.task_id} (score={t.score:.2f}):")
            p(f"    {primary[1]}")
            for extra_flag, extra_reason in flags[1:]:
                p(f"    + [{extra_flag}] {extra_reason}")
            p(f"    subtasks: {t.num_subtasks}, scores: {t.subtask_scores}")
            if t.subtask_questions:
                p(f"    Q1: {t.subtask_questions[0][:80]}")
            # Show answer evidence for UNVISITED_CORRECT
            if t.task_id in unvisited_evidence:
                for sub_idx, site, expected, actual, question in unvisited_evidence[t.task_id]:
                    p(f"    EVIDENCE subtask {sub_idx+1} ({site}):")
                    p(f"      Q: {question[:70]}")
                    p(f"      Expected: {expected}")
                    p(f"      Actual:   {actual}")
                    if actual and expected and actual.strip().lower() == expected.strip().lower():
                        p(f"      -> EXACT MATCH without browsing — world knowledge or memorization")
                    elif actual and expected:
                        p(f"      -> Answer provided without site visit — source unclear")
            p("")

        # Summarize bulk flags (PARSE_FAILED, EMPTY_TASK) as compact tables
        if bulk_tasks:
            # Group by flag type
            bulk_by_type = defaultdict(list)
            for t, flags in bulk_tasks:
                for ft, _ in flags:
                    bulk_by_type[ft].append(t)

            for ft_name in ["PARSE_FAILED", "EMPTY_TASK"]:
                ft_tasks = bulk_by_type.get(ft_name, [])
                if not ft_tasks:
                    continue
                # Summarize by website
                ft_sites = Counter()
                for t in ft_tasks:
                    for site in t.subtask_websites:
                        ft_sites[site] += 1
                if not ft_sites:
                    ft_sites["unknown"] = len(ft_tasks)

                label = "AGENT FORMAT ERROR" if ft_name == "PARSE_FAILED" else ft_name
                p(f"  [{label}] {len(ft_tasks)} tasks (all score=0):")
                avg_steps = _safe_mean([t.total_steps for t in ft_tasks])
                p(f"    Avg steps: {avg_steps:.0f} | By site: {', '.join(f'{s}({c})' for s, c in ft_sites.most_common(5))}")

                # For PARSE_FAILED, show format mode breakdown
                if ft_name == "PARSE_FAILED":
                    modes = Counter()
                    for t in ft_tasks:
                        for _, flags_list in [(t2, fl) for t2, fl in sorted_tasks if t2.task_id == t.task_id]:
                            for ft2, reason in flags_list:
                                if ft2 == "PARSE_FAILED" and "mode=" in reason:
                                    mode = reason.split("mode=")[1].split(" ")[0].rstrip(",")
                                    modes[mode] += 1
                    if modes:
                        mode_str = ", ".join(f"{m}({c})" for m, c in modes.most_common())
                        p(f"    Format modes: {mode_str}")
                        p(f"    Root cause: agent writes stop action in content text instead of tool_calls array")

                    # Answer recovery analysis: how many have correct answers in wrong format?
                    if parse_failed_recovery:
                        recoverable = [(t, mode, ans, mc, ns)
                                       for t, mode, ans, mc, ns in parse_failed_recovery
                                       if ans and mc > 0]
                        extractable = [(t, mode, ans, mc, ns)
                                       for t, mode, ans, mc, ns in parse_failed_recovery
                                       if ans]  # could extract answers, regardless of correctness
                        total_pf = len(parse_failed_recovery)
                        p(f"    Answer recovery analysis ({total_pf} tasks):")
                        p(f"      JSON extractable: {len(extractable)}/{total_pf}"
                          f" (answers could be parsed from content text)")
                        if recoverable:
                            total_matched = sum(mc for _, _, _, mc, _ in recoverable)
                            total_subs = sum(ns for _, _, _, _, ns in recoverable)
                            p(f"      Correct answers found: {len(recoverable)} tasks, "
                              f"{total_matched}/{total_subs} subtasks match expected")
                            p(f"      -> Would score >0 with env fallback (conservative estimate; env uses LLM validator)")
                            # Show recoverable task IDs
                            rec_ids = sorted(t.task_id for t, _, _, _, _ in recoverable)
                            rec_str = ", ".join(str(i) for i in rec_ids[:8])
                            if len(rec_ids) > 8:
                                rec_str += f", ... (+{len(rec_ids) - 8} more)"
                            p(f"      Recoverable task IDs: {rec_str}")
                        else:
                            p(f"      Correct answers found: 0 — all extracted answers differ from expected")
                        # Tasks where answers couldn't even be extracted
                        no_extract = total_pf - len(extractable)
                        if no_extract:
                            p(f"      Not extractable: {no_extract}/{total_pf}"
                              f" (plain_text or malformed — no JSON to parse)")
                    p(f"    Fix: SFT on function-calling format OR env fallback parse content JSON")
                # Show task IDs compactly
                ids = sorted(t.task_id for t in ft_tasks)
                id_str = ", ".join(str(i) for i in ids[:10])
                if len(ids) > 10:
                    id_str += f", ... (+{len(ids) - 10} more)"
                p(f"    Task IDs: {id_str}")
                p("")

        # Summary verdict
        env_tasks = set()
        agent_tasks = set()
        for t, flags in sorted_tasks:
            for ft, _ in flags:
                if ft in ("ZERO_INTERACTION", "UNVISITED_CORRECT", "EMPTY_TASK"):
                    env_tasks.add(t.task_id)
                if ft in ("VM_LOOP", "ZERO_COVERAGE", "PARSE_FAILED"):
                    agent_tasks.add(t.task_id)

        p("  FORENSIC VERDICT:")
        if env_tasks:
            # Break down environment concern by type
            empty_cnt = sum(1 for tid in env_tasks
                           for t, flags in sorted_tasks
                           if t.task_id == tid
                           for ft, _ in flags if ft == "EMPTY_TASK")
            knowledge_cnt = sum(1 for tid in env_tasks
                                for t, flags in sorted_tasks
                                if t.task_id == tid
                                for ft, _ in flags if ft in ("ZERO_INTERACTION", "UNVISITED_CORRECT"))
            parts = []
            if empty_cnt:
                parts.append(f"{empty_cnt} empty tasks (no subtasks generated)")
            if knowledge_cnt:
                parts.append(f"{knowledge_cnt} world-knowledge bypasses (scored without visiting sites)")
            p(f"    Environment/evaluation concern: {len(env_tasks)} unique tasks")
            for part in parts:
                p(f"      - {part}")
        if agent_tasks:
            # Break down agent concern by type
            parse_cnt = sum(1 for tid in agent_tasks
                           for t, flags in sorted_tasks
                           if t.task_id == tid
                           for ft, _ in flags if ft == "PARSE_FAILED")
            loop_cnt = sum(1 for tid in agent_tasks
                          for t, flags in sorted_tasks
                          if t.task_id == tid
                          for ft, _ in flags if ft in ("VM_LOOP", "ZERO_COVERAGE"))
            parts = []
            if parse_cnt:
                parts.append(f"{parse_cnt} format failures (stop action in content text, not tool_calls)")
            if loop_cnt:
                parts.append(f"{loop_cnt} pathological navigation (infinite loops, zero coverage)")
            p(f"    Agent behavior concern: {len(agent_tasks)} unique tasks")
            for part in parts:
                p(f"      - {part}")
        p("")
    else:
        p("  No suspicious trajectories detected.")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # ALL TASKS TABLE (verbose only)
    # ═══════════════════════════════════════════════════════════════════════
    if verbose:
        p("=" * 80)
        p("ALL TASKS")
        p("=" * 80)
        p("")

        # Header
        p(f"  {'task_id':>8} {'score':>5} {'#sub':>4} {'subtask_scores':<20} {'steps':>5} {'sites_visited':>13} {'goto':>4} {'click':>5} {'scroll':>6} {'vm':>3} {'loops':>5} {'coverage':>8}")
        p("  " + chr(9472) * 105)

        for t in sorted(parsed, key=lambda x: x.task_id):
            subtask_str = ",".join(f"{s:.0f}" if s == int(s) else f"{s:.2f}" for s in t.subtask_scores)
            if len(subtask_str) > 18:
                subtask_str = subtask_str[:17] + chr(8230)

            sites_str = ",".join(t.visited_sites[:3])
            if len(sites_str) > 12:
                sites_str = sites_str[:11] + chr(8230)

            loop_str = str(t.max_loop_streak) if t.has_loops else "-"

            p(f"  {t.task_id:>8} {t.score:>5.2f} {t.num_subtasks:>4} {subtask_str:<20} {t.total_steps:>5} {sites_str:>13} {t.action_counts.get('goto', 0):>4} {t.action_counts.get('click', 0):>5} {t.action_counts.get('scroll', 0):>6} {t.view_more_count:>3} {loop_str:>5} {t.site_coverage:>7.0%}")

        p("")

    return "\n".join(lines)


# ── Comparison Report ────────────────────────────────────────────────────────

def generate_comparison_report(uid_data):
    """Generate a comparison report across multiple UIDs."""
    lines = []
    p = lines.append
    uids = sorted(uid_data.keys())

    uid_parsed = {}
    for uid, (info, trajs) in uid_data.items():
        parsed = []
        for t in trajs:
            try:
                parsed.append(t if isinstance(t, TrajectoryData) else TrajectoryData(t))
            except Exception:
                pass
        uid_parsed[uid] = parsed

    p("LIVEWEB COMPARISON REPORT")
    p("=" * 80)
    p(f"  UIDs compared: {', '.join(str(u) for u in uids)}")
    p("")

    uid_cols = [f"UID_{u}" for u in uids]
    cw = 10

    # Overview
    p("  OVERVIEW:")
    p(f"  {'UID':>6} {'Count':>6} {'Avg':>6} {'Perfect%':>8} {'Zero%':>7} {'AdjZero%':>9} {'Multi%':>7} {'Coverage':>8}")
    p("  " + chr(9472) * 76)
    for uid in uids:
        ps = uid_parsed[uid]
        if not ps:
            p(f"  {uid:>6} (no data)")
            continue
        nn = len(ps)
        avg = _safe_mean([t.score for t in ps])
        perf = sum(1 for t in ps if t.is_perfect) / nn * 100
        zero = sum(1 for t in ps if t.is_zero) / nn * 100
        multi = sum(1 for t in ps if t.is_multi_site) / nn * 100
        cov = _safe_mean([t.site_coverage for t in ps])
        # Adjusted zero: exclude only empty tasks (true env issues)
        # parse_failed is agent format error, NOT excluded
        env_only = sum(1 for t in ps if t.num_subtasks == 0)
        adj_n = nn - env_only
        adj_zero = sum(1 for t in ps if t.is_zero) - sum(
            1 for t in ps if t.is_zero and t.num_subtasks == 0)
        adj_zero_pct = adj_zero / adj_n * 100 if adj_n > 0 else 0
        p(f"  {uid:>6} {nn:>6} {avg:>6.3f} {perf:>7.1f}% {zero:>6.1f}% {adj_zero_pct:>8.1f}% {multi:>6.0f}% {cov:>7.0%}")
    p("  (AdjZero% excludes empty tasks only; parse_failed is agent error)")
    p("")

    # Per-website accuracy comparison
    p("  PER-WEBSITE ACCURACY:")
    all_sites = sorted(set(
        w for uid in uids for t in uid_parsed[uid] for w in t.subtask_websites
    ))
    pw = 28
    header = f"  {'website':<{pw}}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (pw + (cw + 1) * len(uid_cols)))

    for site in all_sites:
        if site == "unknown":
            continue
        row = f"  {site[:pw]:<{pw}}"
        for uid in uids:
            site_entries = []
            for t in uid_parsed[uid]:
                for idx, sw in enumerate(t.subtask_websites):
                    if sw == site:
                        site_entries.append((t, idx))
            if site_entries:
                correct = sum(
                    1 for t, idx in site_entries
                    if idx < len(t.subtask_scores) and t.subtask_scores[idx] > 0.5
                )
                acc = correct / len(site_entries) * 100
                row += f" {acc:>{cw - 1}.0f}%"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Per-subtask-count comparison
    p("  PER-SUBTASK-COUNT COMPARISON:")
    all_ns = sorted(set(t.num_subtasks for uid in uids for t in uid_parsed[uid]))
    header = f"  {'#subtasks':<10}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (10 + (cw + 1) * len(uid_cols)))
    for ns in all_ns:
        row = f"  {ns:<10}"
        for uid in uids:
            ns_tasks = [t for t in uid_parsed[uid] if t.num_subtasks == ns]
            if ns_tasks:
                avg = _safe_mean([t.score for t in ns_tasks])
                row += f" {avg:>{cw}.3f}"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Navigation pattern comparison
    p("  NAVIGATION PATTERN COMPARISON:")
    header = f"  {'Metric':<25}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (25 + (cw + 1) * len(uid_cols)))

    metrics = [
        ("Avg steps/task", lambda ps: _safe_mean([t.total_steps for t in ps])),
        ("Avg browser_steps", lambda ps: _safe_mean([t.browser_steps for t in ps])),
        ("Avg goto/task", lambda ps: _safe_mean([t.action_counts.get("goto", 0) for t in ps])),
        ("Avg click/task", lambda ps: _safe_mean([t.action_counts.get("click", 0) for t in ps])),
        ("Avg click_role/task", lambda ps: _safe_mean([t.action_counts.get("click_role", 0) for t in ps])),
        ("Avg type/task", lambda ps: _safe_mean([t.action_counts.get("type", 0) for t in ps])),
        ("Avg view_more/task", lambda ps: _safe_mean([t.view_more_count for t in ps])),
        ("URL diversity", lambda ps: _safe_mean([t.url_diversity for t in ps if t.goto_urls])),
        ("Site coverage", lambda ps: _safe_mean([t.site_coverage for t in ps])),
        ("Loop rate%", lambda ps: sum(1 for t in ps if t.has_loops) / len(ps) * 100 if ps else 0),
        ("Budget exhausted%", lambda ps: sum(1 for t in ps if t.step_budget_exhausted) / len(ps) * 100 if ps else 0),
        ("Parse failed%", lambda ps: sum(1 for t in ps if t.failure_reason and "parse" in str(t.failure_reason).lower()) / len(ps) * 100 if ps else 0),
    ]

    for name, fn in metrics:
        row = f"  {name:<25}"
        for uid in uids:
            ps = uid_parsed[uid]
            if ps:
                val = fn(ps)
                row += f" {val:>{cw}.2f}"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Wrong answer type comparison
    p("  WRONG ANSWER TYPE COMPARISON:")
    all_classes = sorted(set(
        w["classification"]
        for uid in uids for t in uid_parsed[uid] for w in t.wrong_answers
    ))
    header = f"  {'class':<20}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (20 + (cw + 1) * len(uid_cols)))
    for cls in all_classes:
        row = f"  {cls:<20}"
        for uid in uids:
            cnt = sum(1 for t in uid_parsed[uid] for w in t.wrong_answers if w["classification"] == cls)
            total = sum(len(t.wrong_answers) for t in uid_parsed[uid])
            if total > 0:
                pct = cnt / total * 100
                row += f" {cnt:>{cw - 5}}/{pct:>3.0f}%"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Head-to-head on shared tasks
    p("  HEAD-TO-HEAD ON SHARED TASKS:")
    uid_task_sets = {uid: set(t.task_id for t in uid_parsed[uid]) for uid in uids}
    shared = set.intersection(*uid_task_sets.values()) if uid_task_sets else set()
    p(f"  Shared tasks: {len(shared)}")

    if shared:
        utm = {uid: {t.task_id: t for t in uid_parsed[uid]} for uid in uids}

        # Difficulty classification
        td = {}
        for tid in shared:
            scores_list = [utm[uid][tid].score for uid in uids if tid in utm[uid]]
            avg_s = _safe_mean(scores_list)
            if avg_s >= 0.9:
                td[tid] = "easy"
            elif avg_s >= 0.5:
                td[tid] = "medium"
            elif avg_s > 0:
                td[tid] = "hard"
            else:
                td[tid] = "impossible"

        dc = Counter(td.values())
        p("")
        p("  TASK DIFFICULTY DISTRIBUTION:")
        for d in ["easy", "medium", "hard", "impossible"]:
            cnt = dc.get(d, 0)
            p(f"    {d:<12}: {cnt} ({_pct_str(cnt, len(shared))})")
        p("")

        # Show first 30 shared tasks
        header = f"  {'task':>8} {'diff':>10}"
        for uc in uid_cols:
            header += f" {uc:>{cw}}"
        p(header)
        p("  " + chr(9472) * (8 + 10 + (cw + 1) * len(uid_cols) + 5))

        for tid in sorted(shared)[:30]:
            diff = td.get(tid, "?")
            row = f"  {tid:>8} {diff:>10}"
            for uid in uids:
                t = utm[uid].get(tid)
                if t:
                    row += f" {t.score:>{cw}.3f}"
                else:
                    row += f" {'-':>{cw}}"
            p(row)

        if len(shared) > 30:
            p(f"  ... ({len(shared) - 30} more tasks)")
        p("")

        # Winner/loser behavior on shared tasks
        win_behavior = {"steps": [], "goto": [], "click": [], "view_more": []}
        lose_behavior = {"steps": [], "goto": [], "click": [], "view_more": []}
        for tid in shared:
            for uid in uids:
                t = utm[uid].get(tid)
                if not t:
                    continue
                tgt = win_behavior if t.is_perfect else lose_behavior
                tgt["steps"].append(t.total_steps)
                tgt["goto"].append(t.action_counts.get("goto", 0))
                tgt["click"].append(t.action_counts.get("click", 0))
                tgt["view_more"].append(t.view_more_count)

        if win_behavior["steps"] and lose_behavior["steps"]:
            p("  WINNER vs LOSER BEHAVIOR (on shared tasks):")
            p(f"  {'Metric':<25} {'Winners':>10} {'Losers':>10} {'Delta':>10}")
            p("  " + chr(9472) * 55)
            for m in ["steps", "goto", "click", "view_more"]:
                wa = _safe_mean(win_behavior[m])
                la = _safe_mean(lose_behavior[m])
                p(f"  {m:<25} {wa:>10.1f} {la:>10.1f} {wa - la:>+10.1f}")
            p("")

    # 3-site deep drill
    p("  3-SITE TASK DEEP DRILL:")
    for uid in uids:
        three_site = [t for t in uid_parsed[uid] if t.num_subtasks == 3]
        if not three_site:
            continue
        perf_3 = sum(1 for t in three_site if t.is_perfect)
        zero_3 = sum(1 for t in three_site if t.is_zero)
        p(f"    UID {uid}: {len(three_site)} 3-site tasks, {perf_3} perfect, {zero_3} zero")
        p(f"      Avg score: {_safe_mean([t.score for t in three_site]):.3f}")
        p(f"      Avg coverage: {_safe_mean([t.site_coverage for t in three_site]):.0%}")
        p(f"      Avg steps: {_safe_mean([t.total_steps for t in three_site]):.0f}")
    p("")

    # SFT insight
    p("  SFT CROSS-MINER INSIGHT:")
    for uid in uids:
        ps = uid_parsed[uid]
        if not ps:
            continue
        multi_perf = [t for t in ps if t.is_multi_site and t.is_perfect]
        if multi_perf:
            p(f"    UID {uid}: {len(multi_perf)} perfect multi-site tasks (potential SFT positive examples)")
    p("")

    # Spread analysis
    uid_avgs = {uid: _safe_mean([t.score for t in uid_parsed[uid]]) for uid in uids if uid_parsed[uid]}
    if len(uid_avgs) >= 2:
        spread = max(uid_avgs.values()) - min(uid_avgs.values())
        p(f"  Score spread across UIDs: {spread:.3f}")
        if spread < 0.05:
            p("    -> Minimal spread suggests environment-level bottleneck (not model-specific)")
        else:
            p("    -> Significant spread suggests model capability differences")
    p("")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(description="LIVEWEB trajectory analysis")
    parser.add_argument("--uid", type=int, default=None,
                        help="Miner UID (0-255), required unless --compare")
    parser.add_argument("--env", type=str, default="LIVEWEB",
                        help="Environment name (default: LIVEWEB)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Write report to file")
    parser.add_argument("--all", action="store_true",
                        help='Fetch all historical data (mode="all")')
    parser.add_argument("--recent", type=int, default=None,
                        help="Only analyze N most recent trajectories")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to first N trajectories")
    parser.add_argument("--inspect", action="store_true",
                        help="Dump raw extra field structure")
    parser.add_argument("--compare", type=str, default=None,
                        help="Compare multiple UIDs (space-separated)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed per-task info")
    parser.add_argument("--json", action="store_true",
                        help="Also dump raw JSON")
    args = parser.parse_args()

    env_name = args.env
    mode = "all" if args.all else "sampling"
    limit = args.limit or args.recent

    if args.compare:
        uids = [int(u.strip()) for u in args.compare.replace(",", " ").split() if u.strip()]
        print(f"Comparing UIDs: {uids} env={env_name} mode={mode}", file=sys.stderr)
        uid_data = {}
        for uid in uids:
            print(f"  Fetching UID={uid} ...", file=sys.stderr)
            miner_info, trajs = await fetch_trajectories(uid, env_name, mode=mode)
            if limit and trajs:
                trajs = sorted(trajs, key=lambda t: t.get("timestamp", 0) or 0, reverse=True)[:limit]
            uid_data[uid] = (miner_info, trajs)
            print(f"    -> {len(trajs)} trajectories", file=sys.stderr)

        report = generate_comparison_report(uid_data)
        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w") as f:
                f.write(report + "\n")
            print(f"Report written to {args.output} ({len(report)} chars)", file=sys.stderr)
        else:
            print(report)
        return

    if args.uid is None:
        parser.error("--uid is required unless --compare is used")

    uid = args.uid
    print(f"Fetching trajectories for UID={uid} env={env_name} mode={mode} ...", file=sys.stderr)
    miner_info, raw_trajectories = await fetch_trajectories(uid, env_name, mode=mode)

    if not raw_trajectories:
        print(f"No trajectories found for UID={uid}", file=sys.stderr)
        return

    hotkey = miner_info.get("hotkey", "?")[:16]
    revision = miner_info.get("model_revision", "?")[:12]
    sl_size = miner_info.get("sampling_list_size", 0)
    matched = miner_info.get("matched", len(raw_trajectories))
    match_pct = matched / max(sl_size, 1) * 100
    print(f"  Hotkey: {hotkey}...  Revision: {revision}...", file=sys.stderr)
    print(f"  Sampling list: {sl_size} task_ids, {matched} matched ({match_pct:.1f}%)", file=sys.stderr)

    if limit:
        raw_trajectories = sorted(
            raw_trajectories,
            key=lambda t: t.get("timestamp", 0) or 0,
            reverse=True,
        )[:limit]
        print(f"  Limited to {len(raw_trajectories)} most recent trajectories", file=sys.stderr)

    if args.inspect:
        for t in raw_trajectories[:5]:
            safe = {k: v for k, v in t.items() if k != "extra"}
            extra = t.get("extra", {})
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            if isinstance(extra, dict):
                safe["extra_keys"] = list(extra.keys())
                for k in ["answer_details", "usage", "num_subtasks", "final_url",
                           "cache_stats", "failure_reason", "seed", "output_format"]:
                    if k in extra:
                        if k == "conversation":
                            safe["conversation_len"] = len(extra[k]) if isinstance(extra[k], list) else 0
                        elif k == "answer_details":
                            ad = extra[k]
                            safe["answer_details_len"] = len(ad) if isinstance(ad, list) else 0
                            if isinstance(ad, list) and ad:
                                safe["answer_details_sample"] = ad[0]
                                safe["answer_details_keys"] = list(ad[0].keys()) if isinstance(ad[0], dict) else []
                        else:
                            safe[k] = extra[k]
                if "conversation" in extra:
                    conv = extra["conversation"]
                    safe["conversation_len"] = len(conv) if isinstance(conv, list) else 0
                    if isinstance(conv, list) and conv:
                        # Show first assistant message summary
                        for msg in conv:
                            if msg.get("role") == "assistant":
                                content = str(msg.get("content", ""))[:200]
                                safe["first_assistant_preview"] = content
                                break
            print(json.dumps(safe, indent=2, default=str))
        return

    if args.json:
        print(json.dumps(raw_trajectories[:3], indent=2, default=str, ensure_ascii=False))
        return

    miner_info["uid"] = uid
    report = generate_report(miner_info, raw_trajectories, verbose=args.verbose)

    if args.verbose:
        # Append verbose per-task details
        verbose_lines = []
        vp = verbose_lines.append
        vp("")
        vp("=" * 80)
        vp("VERBOSE: PER-TASK DETAILS")
        vp("=" * 80)
        vp("")
        parsed = []
        for t in raw_trajectories:
            try:
                parsed.append(TrajectoryData(t))
            except Exception:
                pass

        for t in sorted(parsed, key=lambda x: x.task_id):
            vp(f"  Task {t.task_id}:")
            vp(f"    Score: {t.score:.3f}  Subtasks: {t.num_subtasks}")
            vp(f"    Subtask scores: {t.subtask_scores}")
            vp(f"    Required sites: {t.required_sites}")
            vp(f"    Visited sites:  {t.visited_sites}")
            vp(f"    Never visited:  {t.never_visited_sites}")
            vp(f"    Site coverage:  {t.site_coverage:.0%}")
            vp(f"    Actions: goto={t.action_counts.get('goto', 0)} click={t.action_counts.get('click', 0)} scroll={t.action_counts.get('scroll', 0)} view_more={t.view_more_count}")
            vp(f"    Total steps: {t.total_steps}  Unique URLs: {t.unique_urls}")
            if t.url_loops:
                vp(f"    URL loops: {t.url_loops}")
            if t.wrong_answers:
                vp(f"    Wrong answers ({len(t.wrong_answers)}):")
                for w in t.wrong_answers:
                    vp(f"      [{w['classification']}] Q: {w['question'][:60]}")
                    vp(f"        Expected: {str(w['expected'])[:50]}  Actual: {str(w['actual'])[:50]}")
            if t.failure_reason:
                vp(f"    Failure reason: {t.failure_reason}")
            if t.total_tokens > 0:
                vp(f"    Tokens: {t.total_tokens} (prompt={t.prompt_tokens}, completion={t.completion_tokens})")
            vp("")

        report += "\n".join(verbose_lines)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report + "\n")
        print(f"Report written to {args.output} ({len(report)} chars)", file=sys.stderr)
    else:
        print(report)

    print(f"\n  Fetched {len(raw_trajectories)} trajectories", file=sys.stderr)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
