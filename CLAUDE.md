自我迭代 — 训练线程
# currentDate
Today's date is 2026-03-17.

      IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.

# Analysis Scripts

## Batch Analysis (recommended)

Run all 4 environments (GAME, SWE-SYNTH, LIVEWEB, NAVWORLD) for given UIDs.

Output structure: `<outdir>/<model_name>/<env>/uid<UID>_{sampling,all}.txt`

### Options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--uids` | yes | — | Comma-separated UIDs to analyze |
| `--source` | no | `sampling` | `sampling` = active sampling list, `all` = all historical data |
| `--envs` | no | `game,swe,liveweb,navworld` | Comma-separated subset of envs to run |
| `--outdir` | no | `runs/<timestamp>` | Custom output directory |

### Skills

```bash
# ── Single UID, active sampling list (default) ──
python3 scripts/batch_analyze.py --uids 45

# ── Single UID, all historical data ──
python3 scripts/batch_analyze.py --uids 45 --source all

# ── Multiple UIDs, active sampling list ──
python3 scripts/batch_analyze.py --uids 30,60,228

# ── Multiple UIDs, all historical data ──
python3 scripts/batch_analyze.py --uids 30,60,228 --source all

# ── Single UID, specific envs only ──
python3 scripts/batch_analyze.py --uids 45 --envs game,swe

# ── Multiple UIDs, specific envs, all historical ──
python3 scripts/batch_analyze.py --uids 30,60 --envs game,swe --source all

# ── Custom output directory ──
python3 scripts/batch_analyze.py --uids 30,60,228 --outdir runs/2026-03-17

# ── Full combo: multiple UIDs, subset envs, all historical, custom outdir ──
python3 scripts/batch_analyze.py --uids 30,60,228 --envs swe,navworld --source all --outdir runs/custom
```

## Individual Analysis Scripts

Each script supports `--output/-o` to write to file, `--all` for all historical data (default: active sampling list only), `--inspect` to dump raw data, and `--json` to also dump raw JSON.

```bash
# GAME (OpenSpiel board games)
python3 scripts/analyze_game.py --uid 42
python3 scripts/analyze_game.py --uid 42 --all -o reports/game_uid42_all.txt

# SWE-SYNTH (software engineering tasks)
python3 scripts/analyze_swe.py --uid 42
python3 scripts/analyze_swe.py --uid 42 --all -o reports/swe_uid42_all.txt

# LIVEWEB (web interaction / browser automation)
python3 scripts/analyze_liveweb.py --uid 42
python3 scripts/analyze_liveweb.py --uid 42 --all -o reports/liveweb_uid42_all.txt

# NAVWORLD (travel planning / routing)
python3 scripts/analyze_navworld.py --uid 42
python3 scripts/analyze_navworld.py --uid 42 --all -o reports/navworld_uid42_all.txt
```

### Additional flags per script

| Flag | game | swe | liveweb | navworld |
|------|------|-----|---------|----------|
| `--all` | yes | yes | yes | yes |
| `--brief` | yes | - | - | - |
| `--limit N` | yes | yes | yes | - |
| `--recent N` | - | yes | yes | yes |
| `--compare` | - | `--compare 120,162` | `--compare 30 60` | `--compare 78` |
| `--multi-compare` | - | - | - | `--multi-compare 57,78,142` |
| `--verbose` | - | - | yes | - |
| `--deep TASK_ID` | - | - | - | yes |
