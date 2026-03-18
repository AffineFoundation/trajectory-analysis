#!/usr/bin/env python3
"""
GAME (OpenSpiel) environment trajectory analysis engine.

Provides single-miner deep analysis with full and brief report modes,
plus exports used by summary_game.py, scan_game_landscape.py, batch_analyze.py.

Usage:
    python3 scripts/analyze_game.py --uid 42
    python3 scripts/analyze_game.py --uid 42 --all -o reports/game_uid42_all.txt
    python3 scripts/analyze_game.py --uid 42 --brief
    python3 scripts/analyze_game.py --uid 42 --limit 50
    python3 scripts/analyze_game.py --uid 42 --inspect
    python3 scripts/analyze_game.py --uid 42 --json
"""

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Constants ────────────────────────────────────────────────────────────────

AVAILABLE_GAMES = [
    "goofspiel",       # idx=0
    "liars_dice",      # idx=1
    "leduc_poker",     # idx=2
    "gin_rummy",       # idx=3
    "othello",         # idx=4
    "backgammon",      # idx=5
    "hex",             # idx=6
    "clobber",         # idx=7
    "hearts",          # idx=8
    "euchre",          # idx=9
    "dots_and_boxes",  # idx=10
    "go",              # idx=11
    "chess",           # idx=12
    "checkers",        # idx=13
    "quoridor",        # idx=14
    "blackjack",       # idx=15
    "phantom_ttt",     # idx=16
    "2048",            # idx=17
    "solitaire",       # idx=18
    "bridge",          # idx=19
    "amazons",         # idx=20
    "oware",           # idx=21
]

GAME_TIERS = {
    "goofspiel": "T1 (excellent)", "liars_dice": "T1 (excellent)",
    "leduc_poker": "T1 (excellent)", "gin_rummy": "T1 (excellent)",
    "othello": "T2 (high quality)", "backgammon": "T2 (high quality)",
    "hex": "T2 (high quality)", "clobber": "T2 (high quality)",
    "hearts": "T3 (multi-player)", "euchre": "T3 (multi-player)",
    "dots_and_boxes": "T3 (multi-player)",
    "go": "T4 (high complexity)", "chess": "T4 (high complexity)",
    "checkers": "T4 (high complexity)", "quoridor": "T4 (high complexity)",
    "blackjack": "T5 (probability)", "phantom_ttt": "T5 (probability)",
    "2048": "T6 (single-player)", "solitaire": "T6 (single-player)",
    "bridge": "T7 (advanced)", "amazons": "T7 (advanced)", "oware": "T7 (advanced)",
}

# MCTS opponent configurations: game_name -> (max_simulations, n_rollouts)
# Games not in this dict use random bot (e.g. goofspiel is simultaneous-move)
MCTS_CONFIGS = {
    "gin_rummy": (500, 10),
    "hex": (1000, 50),
    "othello": (1000, 20),
    "leduc_poker": (3000, 200),
    "clobber": (1500, 100),
    "liars_dice": (3000, 200),
}

# Known small action spaces (high Jaccard is expected, not suspicious)
SMALL_ACTION_SPACE = {
    "leduc_poker": 3,   # Fold, Call, Raise
    "liars_dice": 30,   # ~30 bid options
}


# ── TrajectoryData ──────────────────────────────────────────────────────────

class TrajectoryData:
    """Parsed trajectory wrapper for GAME environment."""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.task_id = int(raw.get("task_id", 0))
        self.score = float(raw.get("score", 0))
        self.timestamp = raw.get("timestamp", 0) or 0
        if isinstance(self.timestamp, str):
            self.timestamp = int(self.timestamp) if self.timestamp else 0
        if self.timestamp and self.timestamp > 1e15:
            self.timestamp = self.timestamp / 1000  # ms -> s
        self.latency_ms = raw.get("latency_ms", 0) or 0

        # Extra data (read early so we can use game_name from extra)
        extra = raw.get("extra", {}) or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}

        # Decode task_id -> game + config
        game_idx = self.task_id // 100000000
        self.config_id = self.task_id % 100000000
        # Prefer game_name from extra (direct from environment) over task_id decode
        self.game_name = extra.get("game_name") or AVAILABLE_GAMES[game_idx % len(AVAILABLE_GAMES)]

        # Game-specific params derived from config_id
        self.board_size = 0
        self.num_cards = 0
        self.hand_size = 0
        if self.game_name == "hex":
            self.board_size = 5 + (self.config_id % 4) * 2  # 5, 7, 9, 11
        elif self.game_name == "clobber":
            self.board_size = 5 + (self.config_id % 3)       # 5, 6, 7
        elif self.game_name == "goofspiel":
            self.num_cards = 8 + (self.config_id % 5) * 2    # 8, 10, 12, 14, 16
        elif self.game_name == "gin_rummy":
            self.hand_size = 7 + (self.config_id // 3) % 3   # 7, 8, 9

        self.conversation = extra.get("conversation", []) or []
        usage = extra.get("usage", {}) or {}
        self.total_tokens = int(usage.get("total_tokens", 0) or 0)
        self.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        self.llm_player_id = int(extra.get("llm_player_id", 0) or 0)
        self.opponent_type = extra.get("opponent_type", "mcts")

        # Parse actions
        self.llm_actions: List[str] = []
        self.all_actions: List[str] = []
        self._parse_actions(extra)

        # Derived fields
        self.is_win = self.score > 0.5
        self.is_draw = 0 < self.score <= 0.5 and abs(self.score - 0.5) < 0.01
        self.is_loss = self.score < 0.5 and not self.is_draw

        self.total_moves = len(self.all_actions) if self.all_actions else self._count_moves_from_conversation()
        self.llm_moves = len(self.llm_actions) if self.llm_actions else self._count_llm_moves_from_conversation()
        self.first_llm_action = self.llm_actions[0] if self.llm_actions else self._get_first_assistant_content()

        # Parse failures (user messages containing error feedback)
        self.parse_failures = 0
        for msg in self.conversation:
            if msg.get("role") == "user":
                c = str(msg.get("content", "")).lower()
                if "invalid action" in c or "not a valid" in c or "please choose" in c:
                    self.parse_failures += 1

    def _parse_actions(self, extra: Dict):
        action_history = extra.get("action_history", []) or []
        if action_history:
            for a in action_history:
                act_str = str(a.get("action_str", a.get("action", "")))
                # Support both "player_id" and "player" keys, plus "is_llm" flag
                is_llm = a.get("is_llm", False)
                player = a.get("player_id", a.get("player", -1))
                self.all_actions.append(act_str)
                if is_llm or player == self.llm_player_id:
                    self.llm_actions.append(act_str)
            return
        # Fallback: extract from conversation
        for msg in self.conversation:
            if msg.get("role") == "assistant":
                content = str(msg.get("content", "")).strip()
                if content:
                    self.llm_actions.append(content)
                    self.all_actions.append(content)

    def _count_moves_from_conversation(self) -> int:
        return sum(1 for m in self.conversation if m.get("role") in ("assistant", "user") and m.get("role") != "system")

    def _count_llm_moves_from_conversation(self) -> int:
        return sum(1 for m in self.conversation if m.get("role") == "assistant")

    def _get_first_assistant_content(self) -> Optional[str]:
        for msg in self.conversation:
            if msg.get("role") == "assistant":
                return str(msg.get("content", "")).strip() or None
        return None


# ── Data Fetching ───────────────────────────────────────────────────────────

async def fetch_trajectories(
    uid: int,
    env_name: str = "GAME",
    source: str = "sampling",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Fetch trajectories for a miner UID.

    Args:
        uid: Miner UID (0-255)
        env_name: Environment name (default "GAME")
        source: "sampling" for active sampling list, "all" for all historical data

    Returns:
        (miner_info, raw_trajectories) where miner_info has keys:
            matched, sampling_list_size, hotkey, model_revision
    """
    # Skip API if FORCE_DB is set (avoids slow 403 retries during batch scans)
    if os.getenv("FORCE_DB"):
        return await _fetch_via_db(uid, env_name, source)

    base_url = os.getenv("API_URL", "https://api.affine.io/api/v1")

    try:
        from affine.utils.api_client import cli_api_client
    except ImportError:
        # Fallback to direct DB
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
            return {"matched": 0, "sampling_list_size": 0, "hotkey": hotkey, "model_revision": revision}, []

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
    """Cleanly shut down DB connection. Call at process exit to suppress warnings."""
    global _db_initialized
    if _db_initialized:
        try:
            from affine.database.client import close_client
            await close_client()
        except Exception:
            pass
        _db_initialized = False


async def _fetch_via_db(uid: int, env_name: str, source: str):
    """Fallback: fetch via direct DB access. Keeps DB connection open for reuse."""
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

    # Resolve env name
    env_key = env_name
    if env_key not in environments and ":" not in env_key:
        matches = [e for e in environments if e.endswith(f":{env_key}")]
        if len(matches) == 1:
            env_key = matches[0]

    env_config = environments.get(env_key, {})
    sampling_list = sorted(get_task_id_set_from_config(env_config)) if env_config else []

    if source == "all":
        task_ids = sorted(await sample_dao.get_completed_task_ids(hotkey, revision, env_key))
    else:
        # Get completed task IDs first, then intersect with sampling list
        completed = set(await sample_dao.get_completed_task_ids(hotkey, revision, env_key))
        task_ids = [tid for tid in sampling_list if tid in completed] if sampling_list else sorted(completed)

    # Concurrent fetch with semaphore to avoid overwhelming DynamoDB
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


# ── Classification ──────────────────────────────────────────────────────────

def classify_model_family(
    trajectories: List[TrajectoryData],
) -> Tuple[str, str, int, int]:
    """Classify miner into model family based on completion token fingerprint + gin_rummy WR.

    Returns: (family_code, description, comp_tokens_median, comp_tokens_max)
    """
    comp_tokens = [t.completion_tokens for t in trajectories if t.completion_tokens > 0]
    if not comp_tokens:
        return "?", "unknown", 0, 0

    med = int(statistics.median(comp_tokens))
    mx = max(comp_tokens)

    # gin_rummy win rate for A1/A2 split
    gin_tasks = [t for t in trajectories if t.game_name == "gin_rummy"]
    gin_wr = sum(1 for t in gin_tasks if t.is_win) / len(gin_tasks) * 100 if gin_tasks else 0

    if mx > 100:
        family = "C"
        desc = f"unstable \u2014 high token variance, comp_max={mx}"
    elif med >= 5:
        family = "B"
        desc = f"verbose \u2014 higher completion tokens, liars_dice often strong"
    else:
        # A1/A2 boundary at 60% gin_rummy WR
        # Flag borderline cases (55-65%) with ~ suffix
        borderline = 55 <= gin_wr <= 65 and len(gin_tasks) >= 5
        margin = f", borderline \u00b1{abs(gin_wr-60):.0f}%" if borderline else ""
        if gin_wr >= 60:
            family = "A1"
            desc = f"standard-strong \u2014 concise output, gin_rummy {gin_wr:.0f}%{margin}"
        else:
            family = "A2"
            desc = f"standard-weak \u2014 concise output, gin_rummy {gin_wr:.0f}% (below A1 threshold){margin}"

    return family, desc, med, mx


# ── Hex Opening Quality ────────────────────────────────────────────────────

def _hex_opening_quality(action_str: Any, board_size: int) -> str:
    """Classify hex opening move quality by Chebyshev distance from center."""
    if action_str is None or board_size <= 0:
        return "unknown"
    s = str(action_str).strip().lower()
    if not s:
        return "unknown"
    try:
        col = ord(s[0]) - ord('a')
        row = int(s[1:]) - 1
    except (ValueError, IndexError):
        # Try as numeric action_id
        try:
            aid = int(s)
            row = aid // board_size
            col = aid % board_size
        except (ValueError, TypeError):
            return "unknown"

    if col < 0 or col >= board_size or row < 0 or row >= board_size:
        return "unknown"

    center = board_size // 2
    dist = max(abs(row - center), abs(col - center))

    if dist == 0:
        return "center"
    elif dist <= 1:
        return "near-center"
    else:
        return "suboptimal (edge/corner)"


def _spearman_rho(xs: List[float], ys: List[float]) -> Optional[float]:
    """Compute Spearman rank correlation between two lists."""
    n = len(xs)
    if n < 5 or len(ys) != n:
        return None
    # Rank the values
    def _rank(vals):
        indexed = sorted(enumerate(vals), key=lambda iv: iv[1])
        ranks = [0.0] * n
        for rank_idx, (orig_idx, _) in enumerate(indexed):
            ranks[orig_idx] = rank_idx + 1
        return ranks
    rx = _rank(xs)
    ry = _rank(ys)
    # Pearson on ranks
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = sum((rx[i] - mean_rx) ** 2 for i in range(n)) ** 0.5
    den_y = sum((ry[i] - mean_ry) ** 2 for i in range(n)) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _hex_action_to_str(action_str: Any, board_size: int) -> str:
    """Convert hex action to position string like 'c5'."""
    if action_str is None:
        return "?"
    s = str(action_str).strip()
    # Already a position string
    if len(s) >= 2 and s[0].isalpha():
        return s
    # Numeric action_id
    try:
        aid = int(s)
        col = aid % board_size
        row = aid // board_size
        return f"{chr(ord('a') + col)}{row + 1}"
    except (ValueError, TypeError):
        return s


# ── Report Generation ──────────────────────────────────────────────────────

def generate_report(
    miner_info: Dict[str, Any],
    raw_trajectories: List[Dict[str, Any]],
    include_task_list: bool = False,
) -> str:
    """Generate full GAME analysis report."""
    lines: List[str] = []
    p = lines.append

    # Parse trajectories
    parsed: List[TrajectoryData] = []
    for t in raw_trajectories:
        try:
            parsed.append(TrajectoryData(t))
        except Exception:
            pass

    if not parsed:
        return "No valid trajectories to analyze."

    n = len(parsed)
    avg_score = statistics.mean([t.score for t in parsed])
    family, family_desc, comp_med, comp_max = classify_model_family(parsed)

    matched = miner_info.get("matched", n)
    sl_size = miner_info.get("sampling_list_size", n)
    match_pct = matched / max(sl_size, 1) * 100

    # Group by game
    game_groups: Dict[str, List[TrajectoryData]] = defaultdict(list)
    for t in parsed:
        game_groups[t.game_name].append(t)

    # ── Header ──
    p("ENVIRONMENT: GAME")
    p("=" * 80)
    p(f"  Samples: {n}")
    p(f"  Sampling list: {sl_size} task_ids, {matched} matched ({match_pct:.1f}%)")
    p(f"  Avg score: {avg_score:.3f}")
    p(f"  Model family: {family} ({family_desc})")
    p(f"    comp_tokens median={comp_med}, max={comp_max}")
    p("")

    # ── Executive Summary ──
    exec_findings = []

    # Best/worst games
    game_wrs_for_exec = {}
    for g, ts in game_groups.items():
        game_wrs_for_exec[g] = sum(1 for t in ts if t.is_win) / len(ts) * 100
    if game_wrs_for_exec:
        best_g = max(game_wrs_for_exec, key=game_wrs_for_exec.get)
        worst_g = min(game_wrs_for_exec, key=game_wrs_for_exec.get)
        best_opp = "vs random" if MCTS_CONFIGS.get(best_g) is None else "vs MCTS"
        worst_opp = "vs random" if MCTS_CONFIGS.get(worst_g) is None else "vs MCTS"
        # Also show best MCTS-only game if best is vs random
        best_str = f"{best_g} {game_wrs_for_exec[best_g]:.0f}%({best_opp})"
        if MCTS_CONFIGS.get(best_g) is None:
            mcts_games = {g: wr for g, wr in game_wrs_for_exec.items() if MCTS_CONFIGS.get(g)}
            if mcts_games:
                best_mcts_g = max(mcts_games, key=mcts_games.get)
                best_str += f", best MCTS: {best_mcts_g} {mcts_games[best_mcts_g]:.0f}%"
        exec_findings.append(f"Best: {best_str} | Worst: {worst_g} {game_wrs_for_exec[worst_g]:.0f}%({worst_opp})")

    # MCTS vs random gap
    r_tasks = [t for t in parsed if MCTS_CONFIGS.get(t.game_name) is None]
    m_tasks = [t for t in parsed if MCTS_CONFIGS.get(t.game_name) is not None]
    if r_tasks and m_tasks:
        r_wr = sum(1 for t in r_tasks if t.is_win) / len(r_tasks) * 100
        m_wr = sum(1 for t in m_tasks if t.is_win) / len(m_tasks) * 100
        exec_findings.append(f"MCTS WR: {m_wr:.0f}% ({len(m_tasks)} tasks) | vs random: {r_wr:.0f}%")

    # Hex position bias
    hex_ts = game_groups.get("hex", [])
    if hex_ts:
        hp0 = [t for t in hex_ts if t.llm_player_id == 0]
        hp1 = [t for t in hex_ts if t.llm_player_id == 1]
        if hp0 and hp1:
            hp0w = sum(1 for t in hp0 if t.is_win) / len(hp0) * 100
            hp1w = sum(1 for t in hp1 if t.is_win) / len(hp1) * 100
            if abs(hp0w - hp1w) > 20:
                exec_findings.append(f"Hex P0/P1 bias: {hp0w:.0f}%/{hp1w:.0f}% (gap {abs(hp0w-hp1w):.0f}%)")

    # Clobber board cliff
    clob_ts = game_groups.get("clobber", [])
    if clob_ts:
        c5 = [t for t in clob_ts if t.board_size == 5]
        c67 = [t for t in clob_ts if t.board_size in (6, 7)]
        if c5 and c67:
            c5w = sum(1 for t in c5 if t.is_win) / len(c5) * 100
            c67w = sum(1 for t in c67 if t.is_win) / len(c67) * 100
            if c5w > 20 and c67w < 10:
                exec_findings.append(f"Clobber cliff: 5x5={c5w:.0f}% vs 6x6+7x7={c67w:.0f}%")

    # Notable othello path
    oth_ts = game_groups.get("othello", [])
    if oth_ts:
        oth_paths: Dict[str, List[TrajectoryData]] = defaultdict(list)
        for t in oth_ts:
            if len(t.llm_actions) >= 2:
                oth_paths[f"{t.llm_actions[0]}->{t.llm_actions[1]}"].append(t)
        strong = [(p, ts) for p, ts in oth_paths.items() if len(ts) >= 5 and sum(1 for t in ts if t.is_win)/len(ts) > 0.6]
        weak = [(p, ts) for p, ts in oth_paths.items() if len(ts) >= 5 and sum(1 for t in ts if t.is_win)/len(ts) < 0.2]
        # Also flag the most-used path if it's below 35% WR (dominant but underperforming)
        most_used = max(oth_paths.items(), key=lambda kv: len(kv[1])) if oth_paths else None
        oth_parts = []
        if strong:
            strong.sort(key=lambda x: -sum(1 for t in x[1] if t.is_win)/len(x[1]))
            bp, bts = strong[0]
            bwr = sum(1 for t in bts if t.is_win) / len(bts) * 100
            oth_parts.append(f"{bp} {bwr:.0f}%\u2191(n={len(bts)})")
        if weak:
            weak.sort(key=lambda x: sum(1 for t in x[1] if t.is_win)/len(x[1]))
            wp, wts = weak[0]
            wwr = sum(1 for t in wts if t.is_win) / len(wts) * 100
            oth_parts.append(f"{wp} {wwr:.0f}%\u2193(n={len(wts)})")
        if most_used and len(most_used[1]) >= 8:
            mu_wr = sum(1 for t in most_used[1] if t.is_win) / len(most_used[1]) * 100
            mu_path = most_used[0]
            # Only flag if underperforming AND not already captured above
            if mu_wr < 35 and not any(mu_path in p for p in oth_parts):
                oth_parts.append(f"{mu_path} {mu_wr:.0f}% DOMINANT(n={len(most_used[1])})")
        if oth_parts:
            exec_findings.append(f"Othello paths: {' | '.join(oth_parts)}")

    # Landscape-relative performance (baselines from 94-miner scan)
    LANDSCAPE_AVG = {
        "goofspiel": 82, "gin_rummy": 51, "hex": 50, "othello": 26,
        "clobber": 15, "liars_dice": 22, "leduc_poker": 32,
    }
    LANDSCAPE_SCORE_AVG = 0.445  # overall avg across 94 miners
    standouts = []
    for g, wr in game_wrs_for_exec.items():
        baseline = LANDSCAPE_AVG.get(g)
        if baseline and abs(wr - baseline) > 15:
            direction = "\u25b2" if wr > baseline else "\u25bc"
            standouts.append((g, wr, baseline, wr - baseline, direction))
    standouts.sort(key=lambda x: -abs(x[3]))
    if standouts:
        parts = [f"{g} {d}{abs(delta):.0f}%({wr:.0f}% vs avg {bl:.0f}%)" for g, wr, bl, delta, d in standouts[:3]]
        exec_findings.append(f"vs landscape: {', '.join(parts)}")

    score_vs = avg_score - LANDSCAPE_SCORE_AVG
    if abs(score_vs) > 0.02:
        rank_est = "top 10%" if score_vs > 0.06 else ("top 25%" if score_vs > 0.03 else ("above avg" if score_vs > 0 else "below avg"))
        confidence = "" if n >= 100 else (", low confidence N<100" if n >= 30 else ", UNRELIABLE N<30")
        exec_findings.append(f"Score vs landscape avg: {avg_score:.3f} vs {LANDSCAPE_SCORE_AVG:.3f} ({score_vs:+.3f}, {rank_est}{confidence})")

    # Strategy fingerprint — one-line cross-game strategy profile (min 5 per game)
    strat_parts = []
    _MIN_STRAT = 5
    # Hex: opening quality
    hex_fp_tasks = [t for t in game_groups.get("hex", []) if t.llm_player_id == 0 and t.first_llm_action and t.board_size > 0]
    if len(hex_fp_tasks) >= _MIN_STRAT:
        center_pct = sum(1 for t in hex_fp_tasks if _hex_opening_quality(t.first_llm_action, t.board_size) in ("center", "near-center")) / len(hex_fp_tasks) * 100
        strat_parts.append(f"hex:center {center_pct:.0f}%")
    # Othello: dominant opening
    oth_fp = game_groups.get("othello", [])
    if len(oth_fp) >= _MIN_STRAT:
        oth_opens = Counter(str(t.first_llm_action) for t in oth_fp if t.first_llm_action)
        if oth_opens:
            top_o, top_oc = oth_opens.most_common(1)[0]
            strat_parts.append(f"oth:{top_o}({top_oc/len(oth_fp)*100:.0f}%)")
    # Gin rummy: opening type
    gin_fp = game_groups.get("gin_rummy", [])
    if len(gin_fp) >= _MIN_STRAT:
        def _gin_key(t):
            s = str(t.llm_actions[0]) if t.llm_actions else ""
            return s.split("Action:")[-1].strip()[:15] if "Action:" in s else s[:15]
        gin_opens_fp = Counter(_gin_key(t) for t in gin_fp if t.llm_actions)
        if gin_opens_fp:
            top_g, _ = gin_opens_fp.most_common(1)[0]
            pass_pct = sum(1 for t in gin_fp if t.llm_actions and _gin_key(t) == "Pass") / len(gin_fp) * 100
            strat_parts.append(f"gin:{top_g[:12]}{'(\u26a0pass '+str(int(pass_pct))+'%)' if pass_pct > 40 else ''}")
    # Liars dice: conservative vs aggressive
    ld_fp = game_groups.get("liars_dice", [])
    if len(ld_fp) >= _MIN_STRAT:
        cons = 0
        for t in ld_fp:
            if t.first_llm_action:
                parts_ld = str(t.first_llm_action).split("-")
                if len(parts_ld) == 2:
                    try:
                        if int(parts_ld[0]) <= 4:
                            cons += 1
                    except ValueError:
                        pass
        cons_pct = cons / len(ld_fp) * 100
        style = "conservative" if cons_pct > 40 else "aggressive"
        strat_parts.append(f"liars:{style[:4]}({cons_pct:.0f}%)")
    # Leduc: R1 opening
    lp_fp = game_groups.get("leduc_poker", [])
    if len(lp_fp) >= _MIN_STRAT:
        raise_r1 = sum(1 for t in lp_fp if t.llm_actions and t.llm_actions[0] == "Raise") / len(lp_fp) * 100
        strat_parts.append(f"leduc:R1raise {raise_r1:.0f}%")

    if strat_parts:
        exec_findings.append(f"Strategy: {' | '.join(strat_parts)}")

    if exec_findings:
        p("\u2500" * 80)
        p("EXECUTIVE SUMMARY")
        p("\u2500" * 80)
        for f in exec_findings:
            p(f"  {f}")
        p("\u2500" * 80)
        p("")

    # ═══════════════════════════════════════════════════════════════════
    # Section 1: OVERALL SUMMARY
    # ═══════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("1. OVERALL SUMMARY")
    p("=" * 80)
    p("")

    wins = sum(1 for t in parsed if t.is_win)
    draws = sum(1 for t in parsed if t.is_draw)
    losses = n - wins - draws
    p(f"  Win rate:  {wins:>4} ({wins/n*100:>5.1f}%)")
    p(f"  Draw rate: {draws:>4} ({draws/n*100:>5.1f}%)")
    p(f"  Loss rate: {losses:>4} ({losses/n*100:>5.1f}%)")
    p("")

    # Score distribution
    p("  Score distribution:")
    bins = [(i / 10, (i + 1) / 10) for i in range(10)]
    max_count = 0
    bin_counts = []
    for lo, hi in bins:
        cnt = sum(1 for t in parsed if lo <= t.score < hi or (hi == 1.0 and t.score >= 0.9))
        if hi < 1.0:
            cnt = sum(1 for t in parsed if lo <= t.score < hi)
        else:
            cnt = sum(1 for t in parsed if lo <= t.score <= hi)
        bin_counts.append(cnt)
        max_count = max(max_count, cnt)
    for i, (lo, hi) in enumerate(bins):
        cnt = bin_counts[i]
        bar_len = int(cnt / max(max_count, 1) * 20)
        bar = "\u2588" * bar_len
        p(f"    [{lo:.1f}-{hi:.1f}): {cnt:>4} ({cnt/n*100:>5.1f}%) {bar}")
    p("")

    # Per-game breakdown
    p("  Per-game breakdown:")
    p(f"  {'Game':<18} {'Count':>5} {'Avg':>7} {'Win%':>5} {'Draw%':>6} {'Loss%':>6}   {'Opponent'}")
    p("  " + "\u2500" * 62)
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        gc = len(tasks)
        gavg = statistics.mean([t.score for t in tasks])
        gw = sum(1 for t in tasks if t.is_win)
        gd = sum(1 for t in tasks if t.is_draw)
        gl = gc - gw - gd
        mcts = MCTS_CONFIGS.get(game)
        opp = f"{mcts[0]}x{mcts[1]}" if mcts else "random"
        p(f"  {game:<18} {gc:>5} {gavg:>6.3f} {gw/gc*100:>5.1f}% {gd/gc*100:>5.1f}% {gl/gc*100:>5.1f}%   {opp:>8}")
    p("")

    # Per-game score distribution
    p("  Per-game score distribution:")
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        scores = [t.score for t in tasks]
        unique = sorted(set(round(s, 3) for s in scores))
        if len(unique) <= 2:
            counts_str = ", ".join(f"{v}={sum(1 for s in scores if round(s, 3) == v)}" for v in unique)
            p(f"    {game:<18}: binary ({counts_str})")
        else:
            q1 = scores[len(scores) // 4] if len(scores) > 3 else min(scores)
            q3 = scores[3 * len(scores) // 4] if len(scores) > 3 else max(scores)
            sorted_scores = sorted(scores)
            q1 = sorted_scores[len(sorted_scores) // 4]
            med = sorted_scores[len(sorted_scores) // 2]
            q3 = sorted_scores[3 * len(sorted_scores) // 4]
            p(f"    {game:<18}: min={min(scores):.3f} Q1={q1:.3f} med={med:.3f} Q3={q3:.3f} max={max(scores):.3f} ({len(unique)} unique values)")
    p("")

    # Actual opponent strength
    random_tasks = [t for t in parsed if MCTS_CONFIGS.get(t.game_name) is None]
    mcts_tasks = [t for t in parsed if MCTS_CONFIGS.get(t.game_name) is not None]
    p("  Actual opponent strength (corrected):")
    if random_tasks:
        rw = sum(1 for t in random_tasks if t.is_win) / len(random_tasks) * 100
        random_games = set(t.game_name for t in random_tasks)
        p(f"    Random bot:  {len(random_tasks):>4} tasks, win rate {rw:.1f}% ({', '.join(sorted(random_games))})")
    if mcts_tasks:
        mw = sum(1 for t in mcts_tasks if t.is_win) / len(mcts_tasks) * 100
        p(f"    MCTS:        {len(mcts_tasks):>4} tasks, win rate {mw:.1f}%")
    p("")

    # Token usage stats
    total_toks = [t.total_tokens for t in parsed if t.total_tokens > 0]
    prompt_toks = [t.prompt_tokens for t in parsed if t.prompt_tokens > 0]
    comp_toks = [t.completion_tokens for t in parsed if t.completion_tokens > 0]
    p("  Token usage stats:")
    if total_toks:
        p(f"    Total tokens: avg={statistics.mean(total_toks):.1f}, median={int(statistics.median(total_toks))}, min={min(total_toks)}, max={max(total_toks)}")
    if prompt_toks:
        p(f"    Prompt tokens: avg={statistics.mean(prompt_toks):.1f}, median={int(statistics.median(prompt_toks))}, min={min(prompt_toks)}, max={max(prompt_toks)}")
    if comp_toks:
        p(f"    Completion tokens: avg={statistics.mean(comp_toks):.1f}, median={int(statistics.median(comp_toks))}, min={min(comp_toks)}, max={max(comp_toks)}")
    p("")

    # Model family fingerprint
    p(f"  Model family fingerprint: {family} \u2014 {family_desc}")
    p(f"    comp_tokens median={comp_med}, max={comp_max}")
    p("")

    # Game length stats
    all_moves = [t.total_moves for t in parsed if t.total_moves > 0]
    llm_moves = [t.llm_moves for t in parsed if t.llm_moves > 0]
    if all_moves:
        p("  Game length stats:")
        p(f"    Total moves: avg={statistics.mean(all_moves):.1f}, median={int(statistics.median(all_moves))}, min={min(all_moves)}, max={max(all_moves)}")
    if llm_moves:
        p(f"    LLM moves: avg={statistics.mean(llm_moves):.1f}, median={int(statistics.median(llm_moves))}, min={min(llm_moves)}, max={max(llm_moves)}")
    p("")

    # Player position analysis
    p0_tasks = [t for t in parsed if t.llm_player_id == 0]
    p1_tasks = [t for t in parsed if t.llm_player_id == 1]
    p("  Player position analysis (win rate by player ID):")
    if p0_tasks:
        p0_wr = sum(1 for t in p0_tasks if t.is_win) / len(p0_tasks) * 100
        p(f"    Player 0 (first):  {len(p0_tasks):>4} tasks, win rate {p0_wr:.1f}%")
    if p1_tasks:
        p1_wr = sum(1 for t in p1_tasks if t.is_win) / len(p1_tasks) * 100
        p(f"    Player 1 (second): {len(p1_tasks):>4} tasks, win rate {p1_wr:.1f}%")
    p("")

    # Per-game player position breakdown
    p("  Per-game player position breakdown:")
    p(f"  {'Game':<18} {'P0 cnt':>6} {'P0 win%':>8} {'P1 cnt':>6} {'P1 win%':>8} {'Bias':>8}")
    p("  " + "\u2500" * 58)
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        gp0 = [t for t in tasks if t.llm_player_id == 0]
        gp1 = [t for t in tasks if t.llm_player_id == 1]
        p0w = sum(1 for t in gp0 if t.is_win) / len(gp0) * 100 if gp0 else 0
        p1w = sum(1 for t in gp1 if t.is_win) / len(gp1) * 100 if gp1 else 0
        bias = abs(p0w - p1w)
        flag = " !!" if bias > 30 else ""
        p0_s = f"{p0w:.1f}%" if gp0 else "-"
        p1_s = f"{p1w:.1f}%" if gp1 else "-"
        p(f"  {game:<18} {len(gp0):>6} {p0_s:>8} {len(gp1):>6} {p1_s:>8} {bias:>7.1f}%{flag}")
    p("")

    # Hex board size breakdown
    hex_tasks = game_groups.get("hex", [])
    if hex_tasks:
        p("  Hex board size breakdown (first-player advantage is inherent to hex):")
        p(f"    {'Size':>4} {'Count':>5} {'Avg':>7} {'P0 win%':>8} {'P1 win%':>8} {'Note'}")
        p("  " + "\u2500" * 50)
        hex_by_size = defaultdict(list)
        for t in hex_tasks:
            if t.board_size > 0:
                hex_by_size[t.board_size].append(t)
        for sz in sorted(hex_by_size.keys()):
            ts = hex_by_size[sz]
            gavg = statistics.mean([t.score for t in ts])
            hp0 = [t for t in ts if t.llm_player_id == 0]
            hp1 = [t for t in ts if t.llm_player_id == 1]
            hp0w = f"{sum(1 for t in hp0 if t.is_win)/len(hp0)*100:.0f}%" if hp0 else "-"
            hp1w = f"{sum(1 for t in hp1 if t.is_win)/len(hp1)*100:.0f}%" if hp1 else "-"
            note = "larger board = harder" if sz >= 9 else ""
            p(f"    {sz:>3}x{sz:<1} {len(ts):>5} {gavg:>6.3f} {hp0w:>8} {hp1w:>8} {note}")
        p("")

        # Hex opening x board size (P0 only)
        hex_p0 = [t for t in hex_tasks if t.llm_player_id == 0 and t.first_llm_action]
        if hex_p0:
            p("  Hex opening \u00d7 board size (P0 only, win rate):")
            # Group by opening
            opening_data: Dict[str, Dict[int, List[TrajectoryData]]] = defaultdict(lambda: defaultdict(list))
            for t in hex_p0:
                opening = _hex_action_to_str(t.first_llm_action, t.board_size) if t.board_size > 0 else str(t.first_llm_action)
                if t.board_size > 0:
                    opening_data[opening][t.board_size].append(t)

            sizes = sorted(set(t.board_size for t in hex_p0 if t.board_size > 0))
            header = f"  {'Opening':<8}"
            for sz in sizes:
                header += f" {sz}x{sz:>2}"
            header += "   Total  Quality"
            p(header)
            p("  " + "\u2500" * 62)

            for opening in sorted(opening_data.keys()):
                row = f"  {opening:<8}"
                total_w = 0
                total_n = 0
                for sz in sizes:
                    ts = opening_data[opening].get(sz, [])
                    if ts:
                        wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                        row += f" {wr:.0f}%/{len(ts)}"
                        total_w += sum(1 for t in ts if t.is_win)
                        total_n += len(ts)
                    else:
                        row += "     -"
                if total_n > 0:
                    total_wr = total_w / total_n * 100
                    qual = _hex_opening_quality(opening, sizes[0] if len(sizes) == 1 else max(sz for sz in sizes if opening_data[opening].get(sz)))
                    row += f"   {total_wr:.0f}%/{total_n}  {qual}"
                p(row)
            p("")

    # Clobber board size breakdown
    clob_tasks = game_groups.get("clobber", [])
    if clob_tasks:
        p("  Clobber board size breakdown:")
        p(f"    {'Size':>4} {'Count':>5} {'Avg':>7} {'Win%':>7} {'P0 win%':>8} {'P1 win%':>8}")
        p("  " + "\u2500" * 50)
        clob_by_size = defaultdict(list)
        for t in clob_tasks:
            if t.board_size > 0:
                clob_by_size[t.board_size].append(t)
        for sz in sorted(clob_by_size.keys()):
            ts = clob_by_size[sz]
            gavg = statistics.mean([t.score for t in ts])
            gwr = sum(1 for t in ts if t.is_win) / len(ts) * 100
            cp0 = [t for t in ts if t.llm_player_id == 0]
            cp1 = [t for t in ts if t.llm_player_id == 1]
            cp0w = f"{sum(1 for t in cp0 if t.is_win)/len(cp0)*100:.1f}%" if cp0 else "-"
            cp1w = f"{sum(1 for t in cp1 if t.is_win)/len(cp1)*100:.1f}%" if cp1 else "-"
            p(f"    {sz:>3}x{sz:<1} {len(ts):>5} {gavg:>6.3f} {gwr:>6.1f}% {cp0w:>8} {cp1w:>8}")
        p("")

        # Clobber opening x board size
        clob_openings: Dict[str, Dict[int, List[TrajectoryData]]] = defaultdict(lambda: defaultdict(list))
        for t in clob_tasks:
            if t.first_llm_action and t.board_size > 0:
                clob_openings[str(t.first_llm_action)[:6]][t.board_size].append(t)

        if clob_openings:
            csizes = sorted(set(t.board_size for t in clob_tasks if t.board_size > 0))
            p("  Clobber opening \u00d7 board size (win rate):")
            header = f"  {'Opening':<10}"
            for sz in csizes:
                header += f" {sz}x{sz:>2}"
            header += "   Total"
            p(header)
            p("  " + "\u2500" * 40)
            for opening in sorted(clob_openings.keys()):
                row = f"  {opening:<10}"
                total_w = 0
                total_n = 0
                for sz in csizes:
                    ts = clob_openings[opening].get(sz, [])
                    if ts:
                        wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                        row += f" {wr:.0f}%/{len(ts)}"
                        total_w += sum(1 for t in ts if t.is_win)
                        total_n += len(ts)
                    else:
                        row += "     -"
                if total_n > 0:
                    total_wr = total_w / total_n * 100
                    row += f"   {total_wr:.0f}%/{total_n}"
                p(row)
            p("")

    # Goofspiel num_cards breakdown
    goof_tasks = game_groups.get("goofspiel", [])
    if goof_tasks:
        goof_by_cards = defaultdict(list)
        for t in goof_tasks:
            if t.num_cards > 0:
                goof_by_cards[t.num_cards].append(t)
        if goof_by_cards:
            p("  Goofspiel num_cards breakdown (vs random bot):")
            p(f"   {'Cards':>5} {'Count':>5} {'Avg':>7} {'Win%':>7}")
            p("  " + "\u2500" * 30)
            for nc in sorted(goof_by_cards.keys()):
                ts = goof_by_cards[nc]
                gavg = statistics.mean([t.score for t in ts])
                gwr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                p(f"   {nc:>5} {len(ts):>5} {gavg:>6.3f} {gwr:>6.1f}%")
            p("")

    # Gin rummy hand_size breakdown
    gin_tasks = game_groups.get("gin_rummy", [])
    if gin_tasks:
        gin_by_hand = defaultdict(list)
        for t in gin_tasks:
            if t.hand_size > 0:
                gin_by_hand[t.hand_size].append(t)
        if gin_by_hand:
            p("  Gin rummy hand_size breakdown:")
            p(f"   {'Hand':>4} {'Count':>5} {'Avg':>7} {'Win%':>7}")
            p("  " + "\u2500" * 30)
            for hs in sorted(gin_by_hand.keys()):
                ts = gin_by_hand[hs]
                gavg = statistics.mean([t.score for t in ts])
                gwr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                p(f"   {hs:>4} {len(ts):>5} {gavg:>6.3f} {gwr:>6.1f}%")
            p("")

    # Game coverage
    present_games = set(game_groups.keys())
    total_games = len(AVAILABLE_GAMES)
    p(f"  Game coverage: {len(present_games)}/{total_games} games present in sampling")
    tier_missing: Dict[str, List[str]] = defaultdict(list)
    for g in AVAILABLE_GAMES:
        if g not in present_games:
            tier = GAME_TIERS.get(g, "unknown")
            tier_missing[tier].append(g)
    for tier in sorted(tier_missing.keys()):
        games_str = ", ".join(sorted(tier_missing[tier]))
        p(f"    Missing from {tier}: {games_str}")
    p("")

    # ═══════════════════════════════════════════════════════════════════
    # Section 2: WINNING / LOSS PATTERN ANALYSIS
    # ═══════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("2. WINNING / LOSS PATTERN ANALYSIS")
    p("=" * 80)
    p("")

    win_tasks = [t for t in parsed if t.is_win]
    loss_tasks = [t for t in parsed if t.is_loss]

    p("  Wins vs Losses comparative:")
    p(f"  {'Metric':<40} {'Wins':>8} {'Losses':>8}")
    p("  " + "\u2500" * 50)
    p(f"  {'Count':<40} {len(win_tasks):>8} {len(loss_tasks):>8}")
    if win_tasks and loss_tasks:
        w_toks = [t.total_tokens for t in win_tasks if t.total_tokens > 0]
        l_toks = [t.total_tokens for t in loss_tasks if t.total_tokens > 0]
        if w_toks and l_toks:
            p(f"  {'Avg tokens':<40} {statistics.mean(w_toks):>8.0f} {statistics.mean(l_toks):>8.0f}")
        w_moves = [t.total_moves for t in win_tasks if t.total_moves > 0]
        l_moves = [t.total_moves for t in loss_tasks if t.total_moves > 0]
        if w_moves and l_moves:
            p(f"  {'Avg moves':<40} {statistics.mean(w_moves):>8.1f} {statistics.mean(l_moves):>8.1f}")
        w_llm = [t.llm_moves for t in win_tasks if t.llm_moves > 0]
        l_llm = [t.llm_moves for t in loss_tasks if t.llm_moves > 0]
        if w_llm and l_llm:
            p(f"  {'Avg LLM moves':<40} {statistics.mean(w_llm):>8.1f} {statistics.mean(l_llm):>8.1f}")
        w_pf = [t.parse_failures for t in win_tasks]
        l_pf = [t.parse_failures for t in loss_tasks]
        p(f"  {'Avg parse failures':<40} {statistics.mean(w_pf):>8.1f} {statistics.mean(l_pf):>8.1f}")
    p("")

    # Per-game win rates sorted
    p("  Per-game win rates (sorted by win%):")
    p(f"  {'Game':<18} {'Count':>5} {'Win%':>6} {'Tier':<20}")
    p("  " + "\u2500" * 50)
    game_wrs = []
    for game, tasks in game_groups.items():
        wr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
        game_wrs.append((game, len(tasks), wr))
    game_wrs.sort(key=lambda x: -x[2])
    for game, cnt, wr in game_wrs:
        tier = GAME_TIERS.get(game, "")
        p(f"  {game:<18} {cnt:>5} {wr:>5.1f}% {tier:<20}")
    p("")

    # Opponent type impact
    p("  Opponent type impact per game (actual):")
    p(f"  {'Game':<18} {'Actual opp':>10} {'Win%':>7} {'MCTS cfg':>10}")
    p("  " + "\u2500" * 50)
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        wr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
        mcts = MCTS_CONFIGS.get(game)
        opp_type = "MCTS" if mcts else "random"
        cfg_str = f"{mcts[0]}x{mcts[1]}" if mcts else "-"
        p(f"  {game:<18} {opp_type:>10} {wr:>6.1f}% {cfg_str:>10}")
    p("")

    # Game tier analysis
    tier_groups: Dict[str, List[TrajectoryData]] = defaultdict(list)
    for t in parsed:
        tier = GAME_TIERS.get(t.game_name, "unknown")
        tier_groups[tier].append(t)
    p("  Game tier analysis:")
    p(f"  {'Tier':<22} {'Count':>5} {'Avg':>7} {'Win%':>7}")
    p("  " + "\u2500" * 42)
    for tier in sorted(tier_groups.keys()):
        ts = tier_groups[tier]
        tavg = statistics.mean([t.score for t in ts])
        twr = sum(1 for t in ts if t.is_win) / len(ts) * 100
        p(f"  {tier:<22} {len(ts):>5} {tavg:>6.3f} {twr:>6.1f}%")
    p("")

    # Parse failure analysis
    pf_tasks = [t for t in parsed if t.parse_failures > 0]
    nopf_tasks = [t for t in parsed if t.parse_failures == 0]
    p(f"  Parse failure analysis: {len(pf_tasks)}/{n} tasks had parse errors")
    if pf_tasks and nopf_tasks:
        pf_wr = sum(1 for t in pf_tasks if t.is_win) / len(pf_tasks) * 100
        nopf_wr = sum(1 for t in nopf_tasks if t.is_win) / len(nopf_tasks) * 100
        p(f"    Win rate WITH parse errors:    {pf_wr:.1f}%")
        p(f"    Win rate WITHOUT parse errors: {nopf_wr:.1f}%")
        if pf_wr > nopf_wr + 5:
            p("    ** Parse failure paradox: errors correlate with HIGHER win rate **")
            pf_games = Counter(t.game_name for t in pf_tasks)
            p("    Per-game breakdown (parse error tasks):")
            for g, cnt in pf_games.most_common():
                gw = sum(1 for t in pf_tasks if t.game_name == g and t.is_win) / cnt * 100
                p(f"      {g:<18}: {cnt} tasks with errors, win rate {gw:.0f}%")
            p("    Likely cause: parse errors occur in games with naturally high win rates")
            p("    (e.g., goofspiel vs random bot), not because errors help win.")
    p("")

    # Token efficiency
    if win_tasks and loss_tasks:
        p("  Token efficiency (tokens per move):")
        w_tpm = [t.total_tokens / max(t.total_moves, 1) for t in win_tasks if t.total_tokens > 0 and t.total_moves > 0]
        l_tpm = [t.total_tokens / max(t.total_moves, 1) for t in loss_tasks if t.total_tokens > 0 and t.total_moves > 0]
        if w_tpm and l_tpm:
            p(f"    Wins:   avg={statistics.mean(w_tpm):.0f}, median={int(statistics.median(w_tpm))}")
            p(f"    Losses: avg={statistics.mean(l_tpm):.0f}, median={int(statistics.median(l_tpm))}")
        p("")

    # Action diversity
    p("  Action diversity per game:")
    p(f"  {'Game':<18} {'Unique actions':>14} {'Total LLM moves':>15}")
    p("  " + "\u2500" * 50)
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        all_acts = []
        total_llm = 0
        for t in tasks:
            all_acts.extend(t.llm_actions)
            total_llm += t.llm_moves
        p(f"  {game:<18} {len(set(all_acts)):>14} {total_llm:>15}")
    p("")

    # Temporal analysis
    ts_tasks = sorted([t for t in parsed if t.timestamp and t.timestamp > 0], key=lambda t: t.timestamp)
    if len(ts_tasks) >= 10:
        p("  Temporal analysis (win rate by chronological quintile):")
        p(f"  {'Quintile':<14} {'Count':>5} {'Avg':>7} {'Win%':>7}")
        p("  " + "\u2500" * 32)
        q_size = len(ts_tasks) // 5
        for qi in range(5):
            start = qi * q_size
            end = (qi + 1) * q_size if qi < 4 else len(ts_tasks)
            qts = ts_tasks[start:end]
            qavg = statistics.mean([t.score for t in qts])
            qwr = sum(1 for t in qts if t.is_win) / len(qts) * 100
            label = ["Q1 (oldest)", "Q2", "Q3", "Q4", "Q5 (newest)"][qi]
            p(f"  {label:<14} {len(qts):>5} {qavg:>6.3f} {qwr:>6.1f}%")

        mid = len(ts_tasks) // 2
        first_wr = sum(1 for t in ts_tasks[:mid] if t.is_win) / mid * 100
        second_wr = sum(1 for t in ts_tasks[mid:] if t.is_win) / (len(ts_tasks) - mid) * 100
        ts_trend = second_wr - first_wr

        # Task-ID trend (independent of completion order — cross-check for artifacts)
        tid_tasks = sorted(parsed, key=lambda t: t.task_id)
        tid_mid = len(tid_tasks) // 2
        tid_first_wr = sum(1 for t in tid_tasks[:tid_mid] if t.is_win) / tid_mid * 100
        tid_second_wr = sum(1 for t in tid_tasks[tid_mid:] if t.is_win) / (len(tid_tasks) - tid_mid) * 100
        tid_trend = tid_second_wr - tid_first_wr

        # Spearman rank correlation between timestamp and task_id
        rho = _spearman_rho(
            [t.timestamp for t in ts_tasks],
            [t.task_id for t in ts_tasks],
        )

        # Determine trend and artifact status
        if abs(ts_trend) < 5:
            trend_str = f"stable ({ts_trend:+.1f}% from first to second half)"
        elif ts_trend > 0:
            trend_str = f"improving {ts_trend:+.1f}%"
        else:
            trend_str = f"declining {ts_trend:+.1f}%"
        p(f"  Timestamp trend: {trend_str}")
        p(f"  Task-ID trend:   {tid_trend:+.1f}% (cross-check)")
        if rho is not None:
            p(f"  Timestamp-TaskID rank correlation: rho={rho:.3f}")

        # Artifact detection
        if abs(ts_trend) > 5 and abs(tid_trend) < 5:
            p(f"  ** ARTIFACT DETECTED: timestamp trend ({ts_trend:+.1f}%) is completion-order artifact (task-ID trend={tid_trend:+.1f}%) **")
        elif abs(ts_trend) > 5 and abs(tid_trend) > 5 and (ts_trend > 0) != (tid_trend > 0):
            p(f"  ** CONTRADICTORY: timestamp ({ts_trend:+.1f}%) vs task-ID ({tid_trend:+.1f}%) diverge — investigate **")
        elif abs(ts_trend) > 10 and abs(tid_trend) > 10:
            p(f"  ** GENUINE TREND: both timestamp ({ts_trend:+.1f}%) and task-ID ({tid_trend:+.1f}%) agree **")

        # Game-mix-adjusted trend: separate task distribution shift from capability change
        # For each game, compute WR in first vs second half by task_id, then weight by game frequency
        if len(parsed) >= 20:
            per_game_trends = {}
            game_weights = {}
            for game, tasks in game_groups.items():
                if len(tasks) < 6:
                    continue
                by_tid = sorted(tasks, key=lambda t: t.task_id)
                gmid = len(by_tid) // 2
                g_first_wr = sum(1 for t in by_tid[:gmid] if t.is_win) / gmid * 100
                g_second_wr = sum(1 for t in by_tid[gmid:] if t.is_win) / (len(by_tid) - gmid) * 100
                per_game_trends[game] = g_second_wr - g_first_wr
                game_weights[game] = len(tasks)

            if per_game_trends:
                total_w = sum(game_weights.values())
                mix_adj = sum(per_game_trends[g] * game_weights[g] for g in per_game_trends) / total_w
                p(f"  Game-mix-adjusted trend: {mix_adj:+.1f}% (controls for task distribution)")

                # Show per-game breakdown for significant trends
                sig_games = {g: t for g, t in per_game_trends.items() if abs(t) > 20}
                if sig_games:
                    p("  Per-game trend breakdown (significant |>20%|):")
                    for g in sorted(sig_games, key=lambda g: sig_games[g]):
                        marker = " **" if abs(sig_games[g]) > 30 else ""
                        p(f"    {g:<18}: {sig_games[g]:+.1f}% (n={game_weights[g]}){marker}")

                # Diagnosis
                if abs(tid_trend) > 10 and abs(mix_adj) < 5:
                    p("  \u2192 Decline is TASK DISTRIBUTION SHIFT, not model degradation (mix-adj near zero)")
                elif abs(tid_trend) > 10 and abs(mix_adj) > 10:
                    p(f"  \u2192 Decline is GENUINE across games (mix-adj={mix_adj:+.1f}% confirms)")
    p("")

    # ═══════════════════════════════════════════════════════════════════
    # Section 3: OVERFITTING / MEMORIZATION DETECTION
    # ═══════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("3. OVERFITTING / MEMORIZATION DETECTION")
    p("=" * 80)
    p("")

    # Per-game score consistency
    p("  Per-game score consistency:")
    p(f"  {'Game':<18} {'Count':>5} {'Avg':>7} {'Std':>5} {'Suspicious'}")
    p("  " + "\u2500" * 46)
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        scores = [t.score for t in tasks]
        gavg = statistics.mean(scores)
        gstd = statistics.stdev(scores) if len(scores) > 1 else 0
        suspicious = ""
        if gstd < 0.05 and len(scores) >= 5:
            suspicious = "LOW VARIANCE"
        p(f"  {game:<18} {len(tasks):>5} {gavg:>6.3f} {gstd:>5.3f} {suspicious}")
    p("")

    # Action sequence repetition (Jaccard)
    p("  Action sequence repetition (per game, Jaccard similarity):")
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        if len(tasks) < 2:
            continue
        action_sets = [set(t.llm_actions) for t in tasks if t.llm_actions]
        if len(action_sets) < 2:
            continue
        jaccards = []
        pairs = list(combinations(range(len(action_sets)), 2))
        for i, j in pairs[:200]:  # limit pairs for performance
            a, b = action_sets[i], action_sets[j]
            if a or b:
                jacc = len(a & b) / len(a | b) if (a | b) else 0
                jaccards.append(jacc)
        if jaccards:
            avg_j = statistics.mean(jaccards)
            note = ""
            if game in SMALL_ACTION_SPACE:
                note = f" (expected: action space={SMALL_ACTION_SPACE[game]})"
            p(f"    {game:<18}: avg Jaccard = {avg_j:.3f} (n={len(tasks)} tasks){note}")
    p("")

    # First-move analysis
    def _opening_key(action_str: str, game: str) -> str:
        """Extract a clean, groupable opening key from first LLM action."""
        s = str(action_str)
        # gin_rummy: "Player: N Action: <actual_action>" → extract after "Action: "
        if game == "gin_rummy" and "Action:" in s:
            return s.split("Action:")[-1].strip()[:25]
        return s[:20]

    p("  First-move analysis:")
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        first_moves = [_opening_key(t.first_llm_action, game) for t in tasks if t.first_llm_action]
        if not first_moves:
            continue
        counter = Counter(first_moves)
        top_move, top_count = counter.most_common(1)[0]
        top_move_display = top_move if len(top_move) <= 22 else top_move[:21] + "\u2026"
        p(f"    {game:<18}: {len(counter)} unique, top=\"{top_move_display}\" ({top_count/len(first_moves)*100:.0f}% of {len(first_moves)} tasks)")
    p("")

    # First-move win rate
    p("  First-move win rate by opening (games with multiple common openings):")
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        opening_groups: Dict[str, List[TrajectoryData]] = defaultdict(list)
        for t in tasks:
            if t.first_llm_action:
                opening_groups[_opening_key(t.first_llm_action, game)].append(t)

        common = {k: v for k, v in opening_groups.items() if len(v) >= 3}
        if len(common) >= 2:
            p(f"    {game}:")
            for opening in sorted(common.keys(), key=lambda k: -sum(1 for t in common[k] if t.is_win) / len(common[k])):
                ts = common[opening]
                wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                display = opening if len(opening) <= 22 else opening[:21] + "\u2026"
                p(f"      \"{display}\" : {wr:>5.1f}% win ({len(ts)} tasks)")
    p("")

    # Config_id range skew
    p("  Win rate vs config_id range:")
    signals = []
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        if len(tasks) < 6:
            continue
        sorted_by_config = sorted(tasks, key=lambda t: t.config_id)
        mid = len(sorted_by_config) // 2
        low_wr = sum(1 for t in sorted_by_config[:mid] if t.is_win) / mid * 100
        high_wr = sum(1 for t in sorted_by_config[mid:] if t.is_win) / (len(sorted_by_config) - mid) * 100
        diff = abs(low_wr - high_wr)
        flag = " <-- SKEW" if diff > 25 and len(tasks) >= 20 else ""
        p(f"    {game:<18}: low={low_wr:.1f}%, high={high_wr:.1f}%, diff={diff:.1f}%{flag}")
        if diff > 25 and len(tasks) >= 20:
            signals.append(f"{game}: config_id range skew ({diff:.1f}%, n={len(tasks)})")
    p("")

    # Token anomalies
    complex_short_wins = [t for t in parsed if t.is_win and t.total_tokens < 1000 and t.game_name in ("gin_rummy", "othello", "chess")]
    p(f"  Token anomalies (complex game wins with <1000 tokens): {len(complex_short_wins)}")
    p("")

    # Short game wins
    short_wins = [t for t in win_tasks if t.llm_moves <= 3]
    p(f"  Short game wins (<=3 moves, score>0.5): {len(short_wins)}/{len(win_tasks)} wins")
    p("")

    # Conversation templating
    p("  Conversation templating (first assistant message uniqueness):")
    for game in sorted(game_groups.keys()):
        tasks = game_groups[game]
        first_msgs = [str(t.first_llm_action) for t in tasks if t.first_llm_action]
        unique = len(set(first_msgs))
        total = len(first_msgs)
        if total > 0:
            pct = unique / total * 100
            p(f"    {game:<18}: {unique}/{total} unique ({pct:.0f}%)")
    p("")

    # Cross-seed consistency
    config_groups: Dict[Tuple[str, int], List[TrajectoryData]] = defaultdict(list)
    for t in parsed:
        config_groups[(t.game_name, t.config_id)].append(t)
    multi_seed = {k: v for k, v in config_groups.items() if len(v) >= 2}
    if multi_seed:
        p(f"  Cross-seed consistency: {len(multi_seed)} multi-seed configs found")
    else:
        p("  Cross-seed consistency: no multi-seed configs found")
    p("")

    # Signals summary
    if signals:
        p(f"    SIGNALS: {'; '.join(signals)}")
    else:
        p("    SIGNALS: none")
    p("")

    # ═══════════════════════════════════════════════════════════════════
    # Section 4: WORST GAME DEEP DIVE
    # ═══════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("4. WORST GAME DEEP DIVE")
    p("=" * 80)
    p("")

    # Find 2 worst games by WR
    worst_games = sorted(game_groups.items(), key=lambda kv: sum(1 for t in kv[1] if t.is_win) / len(kv[1]))[:2]

    for game, tasks in worst_games:
        wr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
        p(f"  --- {game} (win rate: {wr:.1f}%, {len(tasks)} samples) ---")

        # Sample loss
        loss_samples = [t for t in tasks if t.is_loss]
        win_samples = [t for t in tasks if t.is_win]

        if loss_samples:
            t = loss_samples[0]
            p(f"  Sample LOSS (task={t.task_id}, player={t.llm_player_id}):")
            for i, act in enumerate(t.llm_actions[:5]):
                p(f"    LLM[{i}]: {act}")
            if len(t.llm_actions) > 5:
                p(f"    ... ({len(t.llm_actions) - 5} more messages)")
            if t.all_actions:
                actions_str = " -> ".join(t.all_actions[:8])
                if len(t.all_actions) > 8:
                    actions_str += " ..."
                p(f"    Actions: {actions_str}")

        if win_samples:
            t = win_samples[0]
            p(f"  Sample WIN  (task={t.task_id}, player={t.llm_player_id}):")
            for i, act in enumerate(t.llm_actions[:5]):
                p(f"    LLM[{i}]: {act}")
            if len(t.llm_actions) > 5:
                p(f"    ... ({len(t.llm_actions) - 5} more messages)")
            if t.all_actions:
                actions_str = " -> ".join(t.all_actions[:8])
                p(f"    Actions: {actions_str}")

        # Opening pattern analysis
        if loss_samples:
            loss_openings = Counter()
            for t in loss_samples:
                if len(t.all_actions) >= 3:
                    pattern = " -> ".join(t.all_actions[:3])
                    loss_openings[pattern] += 1
            if loss_openings:
                top_pattern, top_cnt = loss_openings.most_common(1)[0]
                pct = top_cnt / len(loss_samples) * 100
                p(f"  Loss opening pattern: {top_pattern} ({top_cnt}/{len(loss_samples)} losses, {pct:.0f}%)")
                # Check same opening in wins
                win_with_same = sum(1 for t in win_samples if len(t.all_actions) >= 3 and " -> ".join(t.all_actions[:3]) == top_pattern)
                p(f"  Same opening in wins: {win_with_same}/{len(win_samples)} ({win_with_same/max(len(win_samples),1)*100:.0f}%)")

        # Mid-game divergence
        if win_samples and loss_samples:
            min_len = min(
                min(len(t.llm_actions) for t in win_samples if t.llm_actions) if any(t.llm_actions for t in win_samples) else 99,
                min(len(t.llm_actions) for t in loss_samples if t.llm_actions) if any(t.llm_actions for t in loss_samples) else 99,
            )
            for move_idx in range(min(min_len, 5)):
                win_moves = Counter(t.llm_actions[move_idx] for t in win_samples if len(t.llm_actions) > move_idx)
                loss_moves = Counter(t.llm_actions[move_idx] for t in loss_samples if len(t.llm_actions) > move_idx)
                win_top = win_moves.most_common(1)[0] if win_moves else None
                loss_top = loss_moves.most_common(1)[0] if loss_moves else None
                if win_top and loss_top and win_top[0] != loss_top[0]:
                    p(f"  Mid-game divergence (first at move {move_idx}):")
                    p(f"    Wins favor: \"{win_top[0]}\" ({win_top[1]/sum(win_moves.values())*100:.0f}%)")
                    p(f"    Losses favor: \"{loss_top[0]}\" ({loss_top[1]/sum(loss_moves.values())*100:.0f}%)")
                    break

        # Average LLM moves
        if win_samples and loss_samples:
            w_lm = [t.llm_moves for t in win_samples if t.llm_moves > 0]
            l_lm = [t.llm_moves for t in loss_samples if t.llm_moves > 0]
            if w_lm and l_lm:
                p(f"  Avg LLM moves: wins={statistics.mean(w_lm):.1f}, losses={statistics.mean(l_lm):.1f}")
        p("")

    # Othello strategy path analysis
    oth_tasks = game_groups.get("othello", [])
    if oth_tasks:
        p("  Othello strategy path analysis (opening -> move 2):")
        p(f"  {'Path':<20} {'Count':>5} {'Win%':>7} {'Note'}")
        p("  " + "\u2500" * 45)
        paths: Dict[str, List[TrajectoryData]] = defaultdict(list)
        for t in oth_tasks:
            if len(t.llm_actions) >= 2:
                path = f"{t.llm_actions[0]}->{t.llm_actions[1]}"
                paths[path].append(t)
        for path in sorted(paths.keys()):
            ts = paths[path]
            if len(ts) >= 3:
                wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                p(f"  {path:<20} {len(ts):>5} {wr:>6.1f}% ")
        p("")

    # Liars Dice bid strategy analysis
    ld_tasks = game_groups.get("liars_dice", [])
    if ld_tasks and len(ld_tasks) >= 10:
        p("  Liars Dice bid strategy analysis:")
        p("  Opening bid quantity distribution:")
        p(f"   {'Qty':>3} {'Count':>5} {'Win%':>7}  {'Assessment'}")
        p("  " + "\u2500" * 42)

        qty_groups: Dict[int, List[TrajectoryData]] = defaultdict(list)
        liar_calls = 0
        total_llm_actions = 0
        for t in ld_tasks:
            if t.first_llm_action:
                bid_str = str(t.first_llm_action)
                parts = bid_str.split("-")
                if len(parts) == 2:
                    try:
                        qty = int(parts[0])
                        qty_groups[qty].append(t)
                    except ValueError:
                        pass
            for act in t.llm_actions:
                total_llm_actions += 1
                if "liar" in str(act).lower():
                    liar_calls += 1

        for qty in sorted(qty_groups.keys()):
            ts = qty_groups[qty]
            pct = len(ts) / len(ld_tasks) * 100
            wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
            assess = "conservative (optimal range)" if qty <= 4 else "aggressive (over-bid risk)"
            p(f"   {qty:>3} {len(ts):>5} ({pct:>4.0f}%) {wr:>5.1f}%  {assess}")

        conservative = [t for qty, ts in qty_groups.items() for t in ts if qty <= 4]
        aggressive = [t for qty, ts in qty_groups.items() for t in ts if qty >= 5]
        if conservative and aggressive:
            cwr = sum(1 for t in conservative if t.is_win) / len(conservative) * 100
            awr = sum(1 for t in aggressive if t.is_win) / len(aggressive) * 100
            p(f"  Conservative (qty\u22644): {cwr:.1f}% win ({len(conservative)} games, {len(conservative)/len(ld_tasks)*100:.0f}% of openings)")
            p(f"  Aggressive  (qty\u22655): {awr:.1f}% win ({len(aggressive)} games)")
            diff = cwr - awr
            direction = "outperform" if diff > 0 else "underperform"
            p(f"  \u2192 Conservative openings {direction} ({diff:+.0f}%) \u2014 consider shifting to qty 3-4 bids")

        if total_llm_actions > 0:
            p(f"  Liar call rate: {liar_calls}/{total_llm_actions} LLM actions ({liar_calls/total_llm_actions*100:.0f}%)")
        p("")

    # Leduc Poker round-by-round strategy analysis
    lp_tasks = game_groups.get("leduc_poker", [])
    if lp_tasks and len(lp_tasks) >= 10:
        p("  Leduc Poker round-by-round strategy analysis:")

        # Classify by R1 opening (first LLM action)
        r1_raise: List[TrajectoryData] = []
        r1_call: List[TrajectoryData] = []
        seq_groups: Dict[str, List[TrajectoryData]] = defaultdict(list)
        fold_by_llm: List[TrajectoryData] = []
        fold_by_opp: List[TrajectoryData] = []

        for t in lp_tasks:
            if not t.llm_actions:
                continue
            r1_open = t.llm_actions[0]
            if r1_open == "Raise":
                r1_raise.append(t)
            elif r1_open == "Call":
                r1_call.append(t)

            # Full LLM sequence abbreviation (R/C/F)
            seq = "-".join(a[0] for a in t.llm_actions)
            seq_groups[seq].append(t)

            # Fold detection
            has_fold = any("Fold" in str(a) for a in t.all_actions)
            llm_folded = any("Fold" in str(a) for a in t.llm_actions)
            if llm_folded:
                fold_by_llm.append(t)
            elif has_fold:
                fold_by_opp.append(t)

        # R1 opening comparison
        if r1_raise and r1_call:
            r_wr = sum(1 for t in r1_raise if t.is_win) / len(r1_raise) * 100
            r_avg = statistics.mean([t.score for t in r1_raise])
            c_wr = sum(1 for t in r1_call if t.is_win) / len(r1_call) * 100
            c_avg = statistics.mean([t.score for t in r1_call])
            p(f"    R1 opening: Raise→{r_wr:.0f}% win, avg={r_avg:.3f} (n={len(r1_raise)}) | Call→{c_wr:.0f}% win, avg={c_avg:.3f} (n={len(r1_call)})")
            better = "Raise" if r_avg > c_avg else "Call"
            p(f"    → {better} is stronger R1 opening (delta={abs(r_avg-c_avg):.3f} avg score)")

        # R2 strategy (second+ LLM actions)
        r2_agg: List[TrajectoryData] = []  # has Raise in R2
        r2_pas: List[TrajectoryData] = []  # only Call in R2
        for t in lp_tasks:
            if len(t.llm_actions) >= 2:
                r2_actions = t.llm_actions[1:]  # actions after R1 opening
                if any(a == "Raise" for a in r2_actions):
                    r2_agg.append(t)
                else:
                    r2_pas.append(t)
        if r2_agg and r2_pas:
            a_wr = sum(1 for t in r2_agg if t.is_win) / len(r2_agg) * 100
            a_avg = statistics.mean([t.score for t in r2_agg])
            pa_wr = sum(1 for t in r2_pas if t.is_win) / len(r2_pas) * 100
            pa_avg = statistics.mean([t.score for t in r2_pas])
            p(f"    R2 aggression: Raise in R2→{a_wr:.0f}% win, avg={a_avg:.3f} (n={len(r2_agg)}) | Call-only R2→{pa_wr:.0f}% win, avg={pa_avg:.3f} (n={len(r2_pas)})")

        # Sequence patterns (sorted by frequency)
        sorted_seqs = sorted(seq_groups.items(), key=lambda kv: -len(kv[1]))
        p(f"    Action sequence patterns (LLM actions, R=Raise C=Call F=Fold):")
        p(f"    {'Seq':<12} {'Count':>5} {'Win%':>5} {'Avg':>6}")
        p("    " + "\u2500" * 32)
        for seq, ts in sorted_seqs:
            if len(ts) >= 2:
                wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                avg = statistics.mean([t.score for t in ts])
                p(f"    {seq:<12} {len(ts):>5} {wr:>4.0f}% {avg:>6.3f}")

        # Fold analysis
        if fold_by_llm or fold_by_opp:
            parts = []
            if fold_by_opp:
                opp_avg = statistics.mean([t.score for t in fold_by_opp])
                parts.append(f"opponent folds: {len(fold_by_opp)} games, avg={opp_avg:.3f}")
            if fold_by_llm:
                llm_avg = statistics.mean([t.score for t in fold_by_llm])
                parts.append(f"LLM folds: {len(fold_by_llm)} games, avg={llm_avg:.3f}")
            p(f"    Fold analysis: {' | '.join(parts)}")

        # Position-dependent play
        lp_p0 = [t for t in lp_tasks if t.llm_player_id == 0 and t.llm_actions]
        lp_p1 = [t for t in lp_tasks if t.llm_player_id == 1 and t.llm_actions]
        if lp_p0 and lp_p1:
            p0_raise_pct = sum(1 for t in lp_p0 if t.llm_actions[0] == "Raise") / len(lp_p0) * 100
            p1_raise_pct = sum(1 for t in lp_p1 if t.llm_actions[0] == "Raise") / len(lp_p1) * 100
            p0_avg = statistics.mean([t.score for t in lp_p0])
            p1_avg = statistics.mean([t.score for t in lp_p1])
            p(f"    Position play: P0 raise_rate={p0_raise_pct:.0f}%, avg={p0_avg:.3f}(n={len(lp_p0)}) | P1 raise_rate={p1_raise_pct:.0f}%, avg={p1_avg:.3f}(n={len(lp_p1)})")
            if abs(p0_raise_pct - p1_raise_pct) > 15:
                p(f"    → Position-dependent strategy detected (raise rate gap {abs(p0_raise_pct-p1_raise_pct):.0f}%)")
        p("")

    # Gin rummy opening strategy analysis
    gin_tasks = game_groups.get("gin_rummy", [])
    if gin_tasks and len(gin_tasks) >= 10:
        p("  Gin Rummy opening strategy analysis:")
        gin_opens: Dict[str, List[TrajectoryData]] = defaultdict(list)
        for t in gin_tasks:
            if t.llm_actions:
                key = _opening_key(str(t.llm_actions[0]), "gin_rummy")
                gin_opens[key].append(t)

        p(f"    {'Opening':<20} {'Count':>5} {'Win%':>5} {'Avg':>6}")
        p("    " + "\u2500" * 40)
        for key in sorted(gin_opens.keys(), key=lambda k: -statistics.mean([t.score for t in gin_opens[k]]) if gin_opens[k] else 0):
            ts = gin_opens[key]
            if len(ts) >= 2:
                wr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                avg = statistics.mean([t.score for t in ts])
                pct = len(ts) / len(gin_tasks) * 100
                p(f"    {key:<20} {len(ts):>5} {wr:>4.0f}% {avg:>6.3f}  ({pct:.0f}% of games)")

        # Flag passive opening bias (>50% Pass)
        pass_ts = gin_opens.get("Pass", [])
        upcard_ts = gin_opens.get("Draw upcard", [])
        stock_ts = gin_opens.get("Draw stock", [])
        if pass_ts and len(pass_ts) / len(gin_tasks) > 0.4:
            pass_wr = sum(1 for t in pass_ts if t.is_win) / len(pass_ts) * 100
            draw_wr = 0
            draw_n = 0
            for ts in [upcard_ts, stock_ts]:
                if ts:
                    draw_n += len(ts)
                    draw_wr += sum(1 for t in ts if t.is_win)
            if draw_n > 0:
                draw_wr = draw_wr / draw_n * 100
                p(f"    \u26a0 Passive opening bias: Pass={len(pass_ts)/len(gin_tasks)*100:.0f}% of games, {pass_wr:.0f}% WR")
                p(f"      Draw openings: {draw_wr:.0f}% WR ({draw_n} games) \u2014 consider shifting to Draw upcard/stock")
        p("")

    # Goofspiel bid strategy
    if goof_tasks and len(goof_tasks) >= 10:
        p("  Goofspiel bid strategy analysis (vs random bot):")
        w_goof = [t for t in goof_tasks if t.is_win]
        l_goof = [t for t in goof_tasks if t.is_loss]

        def _extract_bid(action_str):
            """Extract numeric bid from action string."""
            try:
                parts = str(action_str).split(":")
                if len(parts) >= 2:
                    return int(parts[-1].strip())
                return int(str(action_str).strip())
            except (ValueError, TypeError):
                return None

        w_first_bids = [_extract_bid(t.first_llm_action) for t in w_goof if t.first_llm_action]
        l_first_bids = [_extract_bid(t.first_llm_action) for t in l_goof if t.first_llm_action]
        w_first_bids = [b for b in w_first_bids if b is not None]
        l_first_bids = [b for b in l_first_bids if b is not None]

        if w_first_bids:
            p(f"    Avg first bid (wins):   {statistics.mean(w_first_bids):.1f} (n={len(w_first_bids)})")
        if l_first_bids:
            p(f"    Avg first bid (losses): {statistics.mean(l_first_bids):.1f} (n={len(l_first_bids)})")

        # All bids
        all_w_bids = [_extract_bid(a) for t in w_goof for a in t.llm_actions]
        all_l_bids = [_extract_bid(a) for t in l_goof for a in t.llm_actions]
        all_w_bids = [b for b in all_w_bids if b is not None]
        all_l_bids = [b for b in all_l_bids if b is not None]
        if all_w_bids:
            p(f"    Avg bid across all rounds (wins):   {statistics.mean(all_w_bids):.1f}")
        if all_l_bids:
            p(f"    Avg bid across all rounds (losses): {statistics.mean(all_l_bids):.1f}")

        all_first = w_first_bids + l_first_bids
        if all_first:
            high_bids = sum(1 for b in all_first if b >= 6)
            low_bids = sum(1 for b in all_first if b <= 3)
            p(f"    First-bid distribution: high(\u22656)={high_bids}/{len(all_first)} ({high_bids/len(all_first)*100:.0f}%), low(\u22643)={low_bids}/{len(all_first)} ({low_bids/len(all_first)*100:.0f}%)")

        # Bid stdev per game
        per_game_stdevs = []
        for t in goof_tasks:
            bids = [_extract_bid(a) for a in t.llm_actions]
            bids = [b for b in bids if b is not None]
            if len(bids) > 1:
                per_game_stdevs.append(statistics.stdev(bids))
        if per_game_stdevs:
            p(f"    Avg bid stdev per game: {statistics.mean(per_game_stdevs):.1f} (higher = more varied bidding)")
        p("")

    # Standout strength deep dive (games where miner is >15% above landscape avg)
    LANDSCAPE_WR = {"goofspiel": 82, "gin_rummy": 51, "hex": 50, "othello": 26,
                    "clobber": 15, "liars_dice": 22, "leduc_poker": 32}
    standout_games = []
    for game, tasks in game_groups.items():
        baseline = LANDSCAPE_WR.get(game)
        if baseline is None or len(tasks) < 5:
            continue
        wr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
        if wr - baseline > 15:
            standout_games.append((game, tasks, wr, baseline))
    standout_games.sort(key=lambda x: -(x[2] - x[3]))

    if standout_games:
        p("  " + "\u2500" * 60)
        p("  STANDOUT STRENGTHS (vs landscape average)")
        p("  " + "\u2500" * 60)
        for game, tasks, wr, baseline in standout_games:
            p(f"\n  --- {game}: {wr:.0f}% WR (landscape avg {baseline:.0f}%, delta +{wr-baseline:.0f}%) ---")
            w = [t for t in tasks if t.is_win]
            l = [t for t in tasks if t.is_loss]

            # Win vs loss action length
            if w and l:
                wm = [t.llm_moves for t in w if t.llm_moves > 0]
                lm = [t.llm_moves for t in l if t.llm_moves > 0]
                if wm and lm:
                    p(f"  Avg LLM moves: wins={statistics.mean(wm):.1f}, losses={statistics.mean(lm):.1f}")

            # Opening analysis for this standout game
            opening_groups: Dict[str, List[TrajectoryData]] = defaultdict(list)
            for t in tasks:
                if t.first_llm_action:
                    opening_groups[str(t.first_llm_action)[:12]].append(t)
            common = {k: v for k, v in opening_groups.items() if len(v) >= 3}
            if common:
                p(f"  Key openings:")
                for op in sorted(common, key=lambda k: -sum(1 for t in common[k] if t.is_win)/len(common[k])):
                    ts = common[op]
                    owr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                    p(f"    \"{op}\": {owr:.0f}% ({len(ts)} games)")

            # Board size / config breakdown if applicable
            if game in ("hex", "clobber") and any(t.board_size > 0 for t in tasks):
                by_sz = defaultdict(list)
                for t in tasks:
                    if t.board_size > 0:
                        by_sz[t.board_size].append(t)
                p(f"  Board size breakdown:")
                for sz in sorted(by_sz):
                    ts = by_sz[sz]
                    swr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                    p(f"    {sz}x{sz}: {swr:.0f}% ({len(ts)} games)")

            if game == "goofspiel" and any(t.num_cards > 0 for t in tasks):
                by_nc = defaultdict(list)
                for t in tasks:
                    if t.num_cards > 0:
                        by_nc[t.num_cards].append(t)
                p(f"  Num_cards breakdown:")
                for nc in sorted(by_nc):
                    ts = by_nc[nc]
                    ncwr = sum(1 for t in ts if t.is_win) / len(ts) * 100
                    p(f"    {nc} cards: {ncwr:.0f}% ({len(ts)} games)")

            # Player position
            gp0 = [t for t in tasks if t.llm_player_id == 0]
            gp1 = [t for t in tasks if t.llm_player_id == 1]
            if gp0 and gp1:
                p0w = sum(1 for t in gp0 if t.is_win) / len(gp0) * 100
                p1w = sum(1 for t in gp1 if t.is_win) / len(gp1) * 100
                p(f"  Player position: P0={p0w:.0f}%({len(gp0)}) P1={p1w:.0f}%({len(gp1)})")

        p("")

    # ═══════════════════════════════════════════════════════════════════
    # Section 5: ENVIRONMENT OPTIMIZATION RECOMMENDATIONS
    # ═══════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("5. ENVIRONMENT OPTIMIZATION RECOMMENDATIONS")
    p("=" * 80)
    p("")

    opts = []

    # OPT-1: Opponent fairness
    if random_tasks and mcts_tasks:
        r_wr = sum(1 for t in random_tasks if t.is_win) / len(random_tasks) * 100
        m_wr = sum(1 for t in mcts_tasks if t.is_win) / len(mcts_tasks) * 100
        delta = r_wr - m_wr
        if delta > 20:
            random_pct = len(random_tasks) / n * 100
            inflate = delta * (len(random_tasks) / n) / 100
            random_game_names = ", ".join(sorted(set(t.game_name for t in random_tasks)))
            p(f"  [OPT-1] Opponent fairness imbalance:")
            p(f"    Games vs random bot: {random_game_names} ({len(random_tasks)} tasks, {random_pct:.0f}% of total)")
            p(f"    Win rate vs random: {r_wr:.1f}% vs MCTS: {m_wr:.1f}% (delta={delta:+.1f}%)")
            p(f"    Impact: random-bot games inflate avg score by ~{inflate*100:.1f}%")
            p("    Suggestion: implement MCTS for goofspiel (simultaneous-move support)")
            p("    or weight random-bot game scores lower in aggregation")
            p("")
            opts.append("OPT-1: opponent fairness (random vs MCTS)")

    # OPT-2: Hex first-player advantage
    if hex_tasks:
        hp0 = [t for t in hex_tasks if t.llm_player_id == 0]
        hp1 = [t for t in hex_tasks if t.llm_player_id == 1]
        hp0_wr = sum(1 for t in hp0 if t.is_win) / len(hp0) * 100 if hp0 else 0
        hp1_wr = sum(1 for t in hp1 if t.is_win) / len(hp1) * 100 if hp1 else 0
        hex_bias = abs(hp0_wr - hp1_wr)
        if hex_bias > 20:
            p(f"  [OPT-2] Hex first-player advantage:")
            p(f"    P0 win rate: {hp0_wr:.1f}% vs P1: {hp1_wr:.1f}% (bias={hex_bias:.1f}%)")
            p("    This is inherent to hex (strategy stealing argument)")
            p("    Suggestion: score hex games relative to expected win rate by position,")
            p("    or ensure equal P0/P1 distribution and average position-adjusted scores")
            p("")
            opts.append("OPT-2: hex position fairness")

    # OPT-3: MCTS difficulty spread
    mcts_game_wrs = {}
    for game in game_groups:
        if MCTS_CONFIGS.get(game):
            tasks = game_groups[game]
            mcts_game_wrs[game] = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
    if len(mcts_game_wrs) >= 2:
        max_wr = max(mcts_game_wrs.values())
        min_wr = min(mcts_game_wrs.values())
        spread = max_wr - min_wr
        if spread > 30:
            easiest = max(mcts_game_wrs, key=mcts_game_wrs.get)
            hardest = min(mcts_game_wrs, key=mcts_game_wrs.get)
            e_cfg = MCTS_CONFIGS[easiest]
            h_cfg = MCTS_CONFIGS[hardest]
            p(f"  [OPT-3] MCTS difficulty spread too wide ({spread:.0f}%):")
            p(f"    Easiest MCTS: {easiest} ({mcts_game_wrs[easiest]:.0f}% win, strength={e_cfg[0]*e_cfg[1]})")
            p(f"    Hardest MCTS: {hardest} ({mcts_game_wrs[hardest]:.0f}% win, strength={h_cfg[0]*h_cfg[1]})")
            p("    Suggestion: calibrate MCTS configs to target ~40-60% win rate")
            p(f"    for each game, reducing {hardest} MCTS strength or")
            p(f"    increasing {easiest} MCTS strength")
            p("")
            opts.append("OPT-3: MCTS difficulty calibration")

    # OPT-4: Low game coverage
    if len(present_games) < len(AVAILABLE_GAMES):
        missing = set(AVAILABLE_GAMES) - present_games
        missing_tiers = set(GAME_TIERS.get(g, "?").split()[0] for g in missing)
        p(f"  [OPT-4] Low game coverage ({len(present_games)}/{len(AVAILABLE_GAMES)} games sampled):")
        p(f"    Only {', '.join(sorted(set(GAME_TIERS.get(g,'?').split()[0] for g in present_games)))} games in sampling list, {', '.join(sorted(missing_tiers))} absent")
        p("    Suggestion: expand sampling list to include T3-T7 games")
        p("    for broader LLM capability assessment (multi-player, high complexity,")
        p("    single-player reasoning)")
        p("")
        opts.append("OPT-4: game coverage expansion")

    # OPT-6: Clobber board size cliff
    if clob_tasks:
        clob_by_sz = defaultdict(list)
        for t in clob_tasks:
            if t.board_size > 0:
                clob_by_sz[t.board_size].append(t)
        zero_sizes = [sz for sz, ts in clob_by_sz.items() if sum(1 for t in ts if t.is_win) == 0 and len(ts) >= 3]
        if zero_sizes and any(sum(1 for t in ts if t.is_win) / len(ts) > 0.1 for sz, ts in clob_by_sz.items() if sz == 5):
            c5_wr = sum(1 for t in clob_by_sz.get(5, []) if t.is_win) / max(len(clob_by_sz.get(5, [])), 1) * 100
            p(f"  [OPT-6] Clobber board size performance cliff:")
            p(f"    5x5: {c5_wr:.0f}% win rate vs {', '.join(f'{s}x{s}' for s in sorted(zero_sizes))}: 0% win rate")
            p(f"    0% win rate on: {', '.join(f'{s}x{s}' for s in sorted(zero_sizes))}")
            p("    Suggestion: reduce MCTS strength for larger boards or")
            p("    score by board-size-adjusted expected win rate")
            p("")
            opts.append("OPT-6: clobber board size fairness")

    # OPT-7: Leduc poker determinism (cross-miner identical behavior)
    lp_opt_tasks = game_groups.get("leduc_poker", [])
    if lp_opt_tasks and len(lp_opt_tasks) >= 10:
        # Check if action sequences are highly deterministic
        lp_seqs = []
        for t in lp_opt_tasks:
            if t.llm_actions:
                lp_seqs.append("-".join(t.llm_actions))
        unique_seqs = len(set(lp_seqs))
        total_seqs = len(lp_seqs)
        # With only 3 actions and short games, low diversity is expected
        # Flag when unique sequences are very few relative to tasks
        if total_seqs > 0 and unique_seqs <= 10:
            # Check dominant sequence share
            seq_counts = Counter(lp_seqs)
            top_seq, top_count = seq_counts.most_common(1)[0]
            top_pct = top_count / total_seqs * 100
            p(f"  [OPT-7] Leduc poker low discriminative power:")
            p(f"    Only {unique_seqs} unique LLM action sequences across {total_seqs} tasks")
            p(f"    Dominant: \"{top_seq}\" = {top_pct:.0f}% of games")
            p(f"    Action space = 3 (Raise/Call/Fold) with MCTS(3000,200)")
            p(f"    Group A miners produce near-identical outputs (same tasks → same actions)")
            p(f"    Group B shows different (more passive) strategy but lower WR")
            p(f"    Suggestion: reduce MCTS strength from 3000x200 to ~1000x50")
            p(f"    to allow more model-differentiating outcomes, or reduce leduc weight")
            opts.append("OPT-7: leduc poker low discriminative power")

    if opts:
        p(f"  Summary: {len(opts)} recommendations")
        for opt in opts:
            p(f"    - {opt}")
    else:
        p("  No significant optimization recommendations at current data level.")
    p("")

    # ═══════════════════════════════════════════════════════════════════
    # Section 6: ALL TASKS (only with --verbose / include_task_list)
    # ═══════════════════════════════════════════════════════════════════
    if include_task_list:
        p("=" * 80)
        p("6. ALL TASKS")
        p("=" * 80)
        p("")

        p(f"{'task':>14} {'game':<18} {'score':>8} {'R':>1} {'opponent':>8} {'moves':>5} {'llm':>4} {'tokens':>7} {'player':>6}")
        p("  " + "\u2500" * 75)

        for t in sorted(parsed, key=lambda t: t.task_id):
            result = "W" if t.is_win else ("D" if t.is_draw else "L")
            opp = f"MCTS" if MCTS_CONFIGS.get(t.game_name) else "random"
            p(f"  {t.task_id:>12} {t.game_name:<18} {t.score:>8.3f} {result} {opp:>8} {t.total_moves:>5} {t.llm_moves:>4} {t.total_tokens:>7} {t.llm_player_id:>6}")
    else:
        p(f"\n  (Use --verbose to show all {len(parsed)} task details)")

    return "\n".join(lines)


# ── Brief Report ────────────────────────────────────────────────────────────

def generate_brief_report(
    miner_info: Dict[str, Any],
    raw_trajectories: List[Dict[str, Any]],
) -> str:
    """Generate ~10-line brief summary."""
    parsed = []
    for t in raw_trajectories:
        try:
            parsed.append(TrajectoryData(t))
        except Exception:
            pass

    if not parsed:
        return "No valid trajectories."

    n = len(parsed)
    avg_score = statistics.mean([t.score for t in parsed])
    family, family_desc, comp_med, comp_max = classify_model_family(parsed)
    matched = miner_info.get("matched", n)
    sl_size = miner_info.get("sampling_list_size", n)
    match_pct = matched / max(sl_size, 1) * 100

    # Win rates
    wins = sum(1 for t in parsed if t.is_win)
    wr = wins / n * 100
    mcts_tasks = [t for t in parsed if MCTS_CONFIGS.get(t.game_name) is not None]
    mcts_wr = sum(1 for t in mcts_tasks if t.is_win) / len(mcts_tasks) * 100 if mcts_tasks else 0

    # Per-game WR
    game_groups = defaultdict(list)
    for t in parsed:
        game_groups[t.game_name].append(t)

    game_wrs = {}
    for game, tasks in game_groups.items():
        game_wrs[game] = sum(1 for t in tasks if t.is_win) / len(tasks) * 100

    # Temporal trend (timestamp-based + mix-adjusted cross-check)
    ts_tasks = sorted([t for t in parsed if t.timestamp and t.timestamp > 0], key=lambda t: t.timestamp)
    trend_str = "?"
    if len(ts_tasks) >= 10:
        mid = len(ts_tasks) // 2
        first_wr = sum(1 for t in ts_tasks[:mid] if t.is_win) / mid * 100
        second_wr = sum(1 for t in ts_tasks[mid:] if t.is_win) / (len(ts_tasks) - mid) * 100
        trend = second_wr - first_wr
        trend_str = "stable" if abs(trend) < 5 else f"{trend:+.0f}%"

        # Mix-adjusted trend: per-game trend weighted by game share
        per_game_trends = {}
        for g, tasks in game_groups.items():
            g_ts = sorted([t for t in tasks if t.timestamp and t.timestamp > 0], key=lambda t: t.timestamp)
            if len(g_ts) >= 6:
                g_mid = len(g_ts) // 2
                g_first = sum(1 for t in g_ts[:g_mid] if t.is_win) / g_mid * 100
                g_second = sum(1 for t in g_ts[g_mid:] if t.is_win) / (len(g_ts) - g_mid) * 100
                per_game_trends[g] = g_second - g_first
        if per_game_trends:
            total_w = sum(len(game_groups[g]) for g in per_game_trends)
            if total_w > 0:
                mix_adj = sum(per_game_trends[g] * len(game_groups[g]) / total_w for g in per_game_trends)
                # Flag if mix-adjusted tells a different story
                if abs(mix_adj - trend) > 8:
                    trend_str += f"(mix-adj:{mix_adj:+.0f}%)"

    # Anomalies
    anomalies = []
    hex_tasks = game_groups.get("hex", [])
    hex_p0 = [t for t in hex_tasks if t.llm_player_id == 0 and t.first_llm_action and t.board_size > 0]
    if len(hex_p0) >= 3:
        subopt = sum(1 for t in hex_p0 if _hex_opening_quality(t.first_llm_action, t.board_size) == "suboptimal (edge/corner)")
        if subopt > 0:
            anomalies.append(f"hex subopt {subopt}/{len(hex_p0)}")

    goof16 = [t for t in game_groups.get("goofspiel", []) if t.num_cards == 16]
    if goof16:
        gwr = sum(1 for t in goof16 if t.is_win) / len(goof16) * 100
        if gwr < 70:
            anomalies.append(f"gs16={gwr:.0f}%")

    # Signals
    sig = []
    for game, tasks in game_groups.items():
        if len(tasks) < 20:
            continue
        sorted_by_config = sorted(tasks, key=lambda t: t.config_id)
        mid_idx = len(sorted_by_config) // 2
        low_wr = sum(1 for t in sorted_by_config[:mid_idx] if t.is_win) / mid_idx * 100
        high_wr = sum(1 for t in sorted_by_config[mid_idx:] if t.is_win) / (len(sorted_by_config) - mid_idx) * 100
        if abs(low_wr - high_wr) > 25:
            sig.append(f"{game} config_skew")

    lines = []
    lines.append(f"UID {miner_info.get('uid', '?')} | {family} | N={n} | avg={avg_score:.3f} | WR={wr:.1f}% | MCTS={mcts_wr:.1f}% | match={match_pct:.0f}% | trend={trend_str}")

    abbrevs = {"goofspiel": "goofs", "gin_rummy": "gin", "hex": "hex", "othello": "oth", "clobber": "clob", "liars_dice": "liars", "leduc_poker": "leduc"}
    wr_parts = []
    for game in ["goofspiel", "gin_rummy", "hex", "othello", "clobber", "liars_dice", "leduc_poker"]:
        if game in game_wrs:
            wr_parts.append(f"{abbrevs.get(game, game)}={game_wrs[game]:.0f}%")
    lines.append("  " + " ".join(wr_parts))

    anom_str = ", ".join(anomalies) if anomalies else "none"
    lines.append(f"  anomalies: {anom_str}")

    sig_str = ", ".join(sig) if sig else "none"
    lines.append(f"  signals: {sig_str}")

    return "\n".join(lines)


# ── Compare Report ──────────────────────────────────────────────────────────

async def generate_compare_report(
    primary_uid: int,
    compare_uids: List[int],
    source: str = "sampling",
) -> str:
    """Generate cross-miner comparison report."""
    lines: List[str] = []
    p = lines.append

    all_uids = [primary_uid] + compare_uids

    # Fetch all miners
    miner_data: Dict[int, Tuple[Dict, List[TrajectoryData]]] = {}
    for uid in all_uids:
        mi, raw = await fetch_trajectories(uid, "GAME", source=source)
        if not raw:
            p(f"UID {uid}: no data")
            continue
        parsed = [TrajectoryData(t) for t in raw]
        miner_data[uid] = (mi, parsed)

    if len(miner_data) < 2:
        return "Need at least 2 miners with data to compare."

    p("=" * 90)
    p(f"GAME CROSS-MINER COMPARISON — UIDs: {', '.join(str(u) for u in all_uids)}")
    p("=" * 90)
    p("")

    # Header table
    header = f"{'Metric':<22}"
    for uid in all_uids:
        header += f" {'UID '+str(uid):>12}"
    p(header)
    p("\u2500" * (22 + 13 * len(all_uids)))

    # Basic metrics
    def _row(label, fn):
        row = f"{label:<22}"
        for uid in all_uids:
            if uid in miner_data:
                row += f" {fn(uid):>12}"
            else:
                row += f" {'N/A':>12}"
        p(row)

    _row("Samples", lambda u: str(len(miner_data[u][1])))
    _row("Match %", lambda u: f"{miner_data[u][0].get('matched', 0)/max(miner_data[u][0].get('sampling_list_size',1),1)*100:.0f}%")
    _row("Avg score", lambda u: f"{statistics.mean([t.score for t in miner_data[u][1]]):.3f}")
    _row("Win rate", lambda u: f"{sum(1 for t in miner_data[u][1] if t.is_win)/len(miner_data[u][1])*100:.1f}%")

    _row("Family", lambda u: classify_model_family(miner_data[u][1])[0] if u in miner_data else "?")

    # MCTS WR
    def _mcts_wr(uid):
        tasks = miner_data[uid][1]
        m = [t for t in tasks if MCTS_CONFIGS.get(t.game_name) is not None]
        return f"{sum(1 for t in m if t.is_win)/len(m)*100:.1f}%" if m else "N/A"
    _row("MCTS WR", _mcts_wr)
    p("")

    # Per-game comparison
    all_games = set()
    for uid in miner_data:
        for t in miner_data[uid][1]:
            all_games.add(t.game_name)

    p("Per-game win rates:")
    game_header = f"{'Game':<18}"
    for uid in all_uids:
        game_header += f" {'UID '+str(uid):>10}"
    game_header += "     Delta"
    p(game_header)
    p("\u2500" * (18 + 11 * len(all_uids) + 10))

    for game in sorted(all_games):
        row = f"{game:<18}"
        wrs = []
        for uid in all_uids:
            if uid not in miner_data:
                row += f" {'N/A':>10}"
                continue
            tasks = [t for t in miner_data[uid][1] if t.game_name == game]
            if tasks:
                wr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
                row += f" {wr:>9.0f}%"
                wrs.append(wr)
            else:
                row += f" {'-':>10}"
        if len(wrs) >= 2:
            delta = wrs[0] - wrs[-1]
            marker = " **" if abs(delta) > 15 else ""
            row += f"  {delta:>+6.0f}%{marker}"
        p(row)

    p("")

    # Hex opening comparison
    p("Hex opening comparison (P0 only):")
    hex_header = f"{'Opening':<10}"
    for uid in all_uids:
        hex_header += f" {'UID '+str(uid):>10}"
    p(hex_header)
    p("\u2500" * (10 + 11 * len(all_uids)))

    all_openings = set()
    hex_data: Dict[int, Dict[str, Tuple[int, int]]] = {}
    for uid in miner_data:
        hex_data[uid] = {}
        for t in miner_data[uid][1]:
            if t.game_name == "hex" and t.llm_player_id == 0 and t.first_llm_action:
                opening = _hex_action_to_str(t.first_llm_action, t.board_size) if t.board_size > 0 else str(t.first_llm_action)
                if opening not in hex_data[uid]:
                    hex_data[uid][opening] = [0, 0]
                hex_data[uid][opening][1] += 1
                if t.is_win:
                    hex_data[uid][opening][0] += 1
                all_openings.add(opening)

    for opening in sorted(all_openings):
        row = f"{opening:<10}"
        for uid in all_uids:
            if uid in hex_data and opening in hex_data[uid]:
                w, n = hex_data[uid][opening]
                row += f" {w/n*100:>5.0f}%/{n:<3}"
            else:
                row += f" {'':>10}"
        p(row)

    p("")

    # Othello strategy comparison
    p("Othello opening comparison:")
    oth_header = f"{'Opening':<10}"
    for uid in all_uids:
        oth_header += f" {'UID '+str(uid):>10}"
    p(oth_header)
    p("\u2500" * (10 + 11 * len(all_uids)))

    all_oth_opens = set()
    oth_data: Dict[int, Dict[str, Tuple[int, int]]] = {}
    for uid in miner_data:
        oth_data[uid] = {}
        for t in miner_data[uid][1]:
            if t.game_name == "othello" and t.first_llm_action:
                opening = str(t.first_llm_action)
                if opening not in oth_data[uid]:
                    oth_data[uid][opening] = [0, 0]
                oth_data[uid][opening][1] += 1
                if t.is_win:
                    oth_data[uid][opening][0] += 1
                all_oth_opens.add(opening)

    for opening in sorted(all_oth_opens):
        row = f"{opening:<10}"
        for uid in all_uids:
            if uid in oth_data and opening in oth_data[uid]:
                w, n = oth_data[uid][opening]
                row += f" {w/n*100:>5.0f}%/{n:<3}"
            else:
                row += f" {'':>10}"
        p(row)

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(description="GAME (OpenSpiel) trajectory analysis")
    parser.add_argument("--uid", type=int, required=True, help="Miner UID (0-255)")
    parser.add_argument("--all", action="store_true", help="Use all historical data (default: active sampling list)")
    parser.add_argument("--brief", action="store_true", help="Brief ~10-line summary")
    parser.add_argument("--limit", type=int, default=None, help="Limit to most recent N trajectories")
    parser.add_argument("--recent", type=int, default=None, help="Alias for --limit")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file")
    parser.add_argument("--verbose", action="store_true", help="Include full task list in report (Section 6)")
    parser.add_argument("--inspect", action="store_true", help="Dump raw trajectory data")
    parser.add_argument("--json", action="store_true", help="Dump raw JSON")
    parser.add_argument("--compare", nargs="+", type=int, help="Compare with other UIDs")
    args = parser.parse_args()

    source = "all" if args.all else "sampling"
    limit = args.limit or args.recent

    print(f"Fetching trajectories for UID={args.uid} env=GAME source={source} ...", file=sys.stderr)
    miner_info, raw_trajectories = await fetch_trajectories(args.uid, "GAME", source=source)

    if not raw_trajectories:
        print(f"No trajectories found for UID={args.uid}", file=sys.stderr)
        return

    hotkey = miner_info.get("hotkey", "?")[:16]
    revision = miner_info.get("model_revision", "?")[:12]
    sl_size = miner_info.get("sampling_list_size", 0)
    matched = miner_info.get("matched", len(raw_trajectories))
    match_pct = matched / max(sl_size, 1) * 100
    print(f"  Hotkey: {hotkey}...  Revision: {revision}...", file=sys.stderr)
    print(f"  Sampling list: {sl_size} task_ids, {matched} matched ({match_pct:.1f}%)", file=sys.stderr)

    if limit:
        # Sort by timestamp descending and take most recent N
        sorted_trajs = sorted(raw_trajectories, key=lambda t: t.get("timestamp", 0) or 0, reverse=True)
        raw_trajectories = sorted_trajs[:limit]
        print(f"  Limited to {len(raw_trajectories)} most recent trajectories", file=sys.stderr)

    if args.inspect:
        for t in raw_trajectories[:5]:
            safe = {k: v for k, v in t.items() if k != "extra"}
            extra = t.get("extra", {})
            if extra:
                safe["extra_keys"] = list(extra.keys()) if isinstance(extra, dict) else "non-dict"
                if isinstance(extra, dict) and "conversation" in extra:
                    safe["conversation_len"] = len(extra["conversation"])
                if isinstance(extra, dict) and "action_history" in extra:
                    safe["action_history_len"] = len(extra.get("action_history", []) or [])
            print(json.dumps(safe, indent=2, default=str))
        return

    if args.json:
        print(json.dumps(raw_trajectories[:3], indent=2, default=str, ensure_ascii=False))
        return

    miner_info["uid"] = args.uid

    if args.compare:
        report = await generate_compare_report(args.uid, args.compare, source=source)
    elif args.brief:
        report = generate_brief_report(miner_info, raw_trajectories)
    else:
        report = generate_report(miner_info, raw_trajectories, include_task_list=args.verbose)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report + "\n")
        print(f"Report written to {args.output} ({len(report)} chars)", file=sys.stderr)
    else:
        print(report)

    print(f"\n  Fetched {len(raw_trajectories)} trajectories", file=sys.stderr)
    await close_db()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
