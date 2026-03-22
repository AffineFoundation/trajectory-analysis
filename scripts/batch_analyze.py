#!/usr/bin/env python3
"""
Batch-analyze multiple UIDs across all 4 environments (GAME, SWE-SYNTH, LIVEWEB, NAVWORLD).

For each UID, runs both active-sampling-list and all-historical-data analysis,
storing results in a structured directory:

    <output_dir>/
      <model_name>/
        game/
          uid<UID>_sampling.txt
          uid<UID>_all.txt
        swe/
          uid<UID>_sampling.txt
          uid<UID>_all.txt
        liveweb/
          uid<UID>_sampling.txt
          uid<UID>_all.txt
        navworld/
          uid<UID>_sampling.txt
          uid<UID>_all.txt

Usage:
    # Analyze UIDs 30,60,228 with active sampling list (default)
    python3 scripts/batch_analyze.py --uids 30,60,228

    # Analyze with all historical data
    python3 scripts/batch_analyze.py --uids 30,60,228 --source all

    # Custom output directory
    python3 scripts/batch_analyze.py --uids 30,60,228 --outdir runs/2026-03-17

    # Only specific envs
    python3 scripts/batch_analyze.py --uids 30,60 --envs game,swe
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Environment config ──────────────────────────────────────────────────────

ENV_CONFIGS = {
    "game": {
        "env_name": "GAME",
        "script": "scripts/analyze_game.py",
        "module": "scripts.analyze_game",
    },
    "swe": {
        "env_name": "SWE-INFINITE",
        "script": "scripts/analyze_swe.py",
        "module": "scripts.analyze_swe",
    },
    "liveweb": {
        "env_name": "LIVEWEB",
        "script": "scripts/analyze_liveweb.py",
        "module": "scripts.analyze_liveweb",
    },
    "navworld": {
        "env_name": "navworld",
        "script": "scripts/analyze_navworld.py",
        "module": "scripts.analyze_navworld",
    },
}


def sanitize_model_name(model: str) -> str:
    """Convert model name to filesystem-safe directory name."""
    # Replace special chars with underscore, collapse runs
    safe = re.sub(r"[^\w\-.]", "_", model)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "unknown_model"


async def lookup_model_name(uid: int) -> str:
    """Query DB for miner model name."""
    from affine.database.client import init_client, close_client
    from affine.database.dao.miners import MinersDAO

    await init_client()
    try:
        dao = MinersDAO()
        miner = await dao.get_miner_by_uid(uid)
        if not miner:
            print(f"  WARNING: No miner found for UID={uid}")
            return f"uid{uid}"
        return miner.get("model", f"uid{uid}") or f"uid{uid}"
    finally:
        await close_client()


async def run_analysis(uid: int, env_key: str, source: str, output_path: str):
    """Run a single analysis and write to output_path."""
    cfg = ENV_CONFIGS[env_key]
    env_name = cfg["env_name"]

    print(f"  [{env_key}] UID={uid} source={source} -> {output_path}")

    try:
        if env_key == "game":
            from scripts.analyze_game import fetch_trajectories, generate_report, generate_brief_report
            miner_info, trajectories = await fetch_trajectories(uid, env_name, source=source)
            if not trajectories:
                _write(output_path, f"No trajectories found for UID={uid} env={env_name} source={source}\n")
                return
            report = generate_report(miner_info, trajectories)

        elif env_key == "swe":
            from scripts.analyze_swe import fetch_trajectories, generate_report
            miner_info, trajectories = await fetch_trajectories(uid, env_name, source=source)
            if not trajectories:
                _write(output_path, f"No trajectories found for UID={uid} env={env_name} source={source}\n")
                return
            report = generate_report(miner_info, trajectories)

        elif env_key == "liveweb":
            from scripts.analyze_liveweb import fetch_trajectories, generate_report
            mode = "all" if source == "all" else "sampling"
            miner_info, trajectories = await fetch_trajectories(uid, env_name, mode=mode)
            if not trajectories:
                _write(output_path, f"No trajectories found for UID={uid} env={env_name} source={source}\n")
                return
            report = generate_report(miner_info, trajectories)

        elif env_key == "navworld":
            from scripts.analyze_navworld import fetch_trajectories, generate_report
            miner_info, trajectories = await fetch_trajectories(uid, env_name, source=source)
            if not trajectories:
                _write(output_path, f"No trajectories found for UID={uid} env={env_name} source={source}\n")
                return
            report = generate_report(miner_info, trajectories)

        else:
            print(f"  ERROR: unknown env_key={env_key}")
            return

        _write(output_path, report + "\n")
        print(f"    -> wrote {len(report)} chars")

    except Exception as e:
        msg = f"ERROR analyzing UID={uid} env={env_name} source={source}: {e}\n"
        _write(output_path, msg)
        print(f"    -> ERROR: {e}")


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


async def main():
    parser = argparse.ArgumentParser(
        description="Batch-analyze UIDs across GAME / SWE / LIVEWEB / NAVWORLD"
    )
    parser.add_argument(
        "--uids", type=str, required=True,
        help="Comma-separated UIDs (e.g. 30,60,228)"
    )
    parser.add_argument(
        "--outdir", type=str, default=None,
        help="Output root directory (default: runs/<date>)"
    )
    parser.add_argument(
        "--envs", type=str, default="game,swe,liveweb,navworld",
        help="Comma-separated envs to analyze (default: all four)"
    )
    parser.add_argument(
        "--source", type=str, choices=["sampling", "all"], default="sampling",
        help="Data source: 'sampling' = active sampling list (default), 'all' = all historical data"
    )
    args = parser.parse_args()

    uids = [int(u.strip()) for u in args.uids.split(",") if u.strip()]
    envs = [e.strip().lower() for e in args.envs.split(",") if e.strip()]
    for e in envs:
        if e not in ENV_CONFIGS:
            parser.error(f"Unknown env '{e}'. Choose from: {list(ENV_CONFIGS.keys())}")

    outdir = args.outdir or f"runs/{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    source = args.source

    print(f"Batch analysis: {len(uids)} UIDs x {len(envs)} envs, source={source}")
    print(f"Output dir: {outdir}")
    print(f"UIDs: {uids}")
    print(f"Envs: {envs}")
    print()

    # Look up model names for each UID
    uid_models = {}
    for uid in uids:
        model = await lookup_model_name(uid)
        uid_models[uid] = sanitize_model_name(model)
        print(f"  UID={uid} -> model={model} -> dir={uid_models[uid]}")
    print()

    # Run analyses
    total = len(uids) * len(envs)
    done = 0
    for uid in uids:
        model_dir = uid_models[uid]
        for env_key in envs:
            fname = f"uid{uid}_{source}.txt"
            output_path = os.path.join(outdir, model_dir, env_key, fname)
            await run_analysis(uid, env_key, source, output_path)
            done += 1
            print(f"  [{done}/{total}] done\n")

    print(f"\nAll done. Results in: {outdir}/")
    print("Directory structure:")
    for root, dirs, files in os.walk(outdir):
        level = root.replace(outdir, "").count(os.sep)
        indent = "  " * level
        print(f"  {indent}{os.path.basename(root)}/")
        sub_indent = "  " * (level + 1)
        for f in sorted(files):
            print(f"  {sub_indent}{f}")


if __name__ == "__main__":
    asyncio.run(main())
