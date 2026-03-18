#!/usr/bin/env python3
"""
SWE-SYNTH (software engineering) trajectory analysis engine.

Provides single-miner deep analysis with full report mode,
plus exports used by batch_analyze.py.

Usage:
    python3 scripts/analyze_swe.py --uid 42
    python3 scripts/analyze_swe.py --uid 42 --all -o reports/swe_uid42_all.txt
    python3 scripts/analyze_swe.py --uid 42 --limit 50
    python3 scripts/analyze_swe.py --uid 42 --recent 20
    python3 scripts/analyze_swe.py --uid 42 --inspect
    python3 scripts/analyze_swe.py --uid 42 --json
    python3 scripts/analyze_swe.py --compare 120,162,248
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Constants ────────────────────────────────────────────────────────────────

_PROJECT_LANG_MAP = {
    "internetarchive/openlibrary": "Python",
    "protonmail/webclients": "TypeScript",
    "element-hq/element-web": "TypeScript",
    "ansible/ansible": "Python",
    "django/django": "Python",
    "pallets/flask": "Python",
    "psf/requests": "Python",
    "pypa/pip": "Python",
    "scikit-learn/scikit-learn": "Python",
    "numpy/numpy": "Python",
    "pandas-dev/pandas": "Python",
    "matplotlib/matplotlib": "Python",
    "pytest-dev/pytest": "Python",
    "sympy/sympy": "Python",
    "sphinx-doc/sphinx": "Python",
    "pylint-dev/pylint": "Python",
    "astropy/astropy": "Python",
    "mwaskom/seaborn": "Python",
    "psf/black": "Python",
    "python/mypy": "Python",
    "huggingface/transformers": "Python",
    "facebook/react": "TypeScript",
    "microsoft/vscode": "TypeScript",
    "angular/angular": "TypeScript",
    "vercel/next.js": "TypeScript",
    "nestjs/nest": "TypeScript",
    "spring-projects/spring-framework": "Java",
    "spring-projects/spring-boot": "Java",
    "elastic/elasticsearch": "Java",
    "apache/kafka": "Java",
    "google/guava": "Java",
    "rust-lang/rust": "Rust",
    "servo/servo": "Rust",
    "tokio-rs/tokio": "Rust",
    "denoland/deno": "Rust",
    "golang/go": "Go",
    "kubernetes/kubernetes": "Go",
    "hashicorp/terraform": "Go",
    "docker/cli": "Go",
    "gravitational/teleport": "Go",
    "nicbarker/clay": "C",
    "qutebrowser/qutebrowser": "Python",
    "NodeBB/NodeBB": "JavaScript",
}

_EXT_LANG_MAP = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".jsx": "JavaScript", ".java": "Java",
    ".rs": "Rust", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".cpp": "C++", ".h": "C/C++", ".cs": "C#",
    ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala",
    ".sh": "Shell", ".yml": "YAML", ".yaml": "YAML",
    ".json": "JSON", ".toml": "TOML", ".xml": "XML",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".md": "Markdown",
}

_IGNORED_EXTS = {
    ".backup", ".bak", ".orig", ".tmp", ".log", ".lock",
    ".png", ".jpg", ".gif", ".svg", ".ico", ".woff", ".ttf",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll",
}

_IDENTITY_PATTERNS = [
    "i cannot execute", "i'm a text-based ai", "i don't have access to",
    "i cannot run", "i'm unable to execute", "i can't execute",
    "i can't run", "as an ai language model",
    "i don't have the ability to run", "i cannot directly execute",
    "i'm not able to run", "i cannot directly run",
    "i do not have access", "i'm an ai assistant",
    "i cannot access the file system", "i don't have the capability",
    "i cannot interact with", "i'm unable to access the file",
    "unable to access the file system", "i can't access the file",
    "i cannot access files", "i'm unable to run",
]

_LABEL_ABBREV = {
    "explore_only": "explore", "edit_no_test": "ed_nt",
    "edit_churn": "churn", "fix_test_loop": "ftl",
    "identity_confusion": "id_cf", "env_blocked": "env_bl",
    "shallow_bail": "bail", "localization": "local",
    "target+regress": "t+reg", "regression_only": "reg_on", "identified_no_action": "id_na",
    "false_completion": "f_cmp",
    "target_fail_only": "tgt_fl", "partial": "partial",
    "target_pass+minor_regress": "tp+mr", "partial_progress": "p_prog",
}

_NEAR_WIN_THRESHOLD = 0.8


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_result(result_str):
    """Parse 'N/M' result string to (passed, total)."""
    if not result_str or not isinstance(result_str, str):
        return (0, 0)
    parts = result_str.strip().split("/")
    if len(parts) != 2:
        return (0, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        return (0, 0)


def _extract_project(swe_instance_id):
    """Extract project name from swe_instance_id.
    Format: instance_<owner>__<repo>-<commit_hash>-v<version_hash> -> <owner>/<repo>
    Example: instance_ansible__ansible-29aea9ff...-vba6da65a... -> ansible/ansible
    """
    if not swe_instance_id or not isinstance(swe_instance_id, str):
        return "unknown"
    s = swe_instance_id
    if s.startswith("instance_"):
        s = s[len("instance_"):]
    parts = s.split("__", 1)
    if len(parts) != 2:
        return s
    owner = parts[0]
    repo_hash = parts[1]
    # Strip all trailing hash-like segments: -<hex8+>, -v<hex+>, -vnan, etc.
    # Strategy: split on '-' and take segments until we hit a hex-like token
    segments = repo_hash.split("-")
    repo_parts = []
    for seg in segments:
        # Stop at first segment that looks like a hash (8+ hex chars) or version ref (v<hex>)
        if re.match(r'^[0-9a-f]{8,}$', seg):
            break
        if re.match(r'^v[0-9a-f]{4,}$', seg) or seg in ("vnan",):
            break
        repo_parts.append(seg)
    repo = "-".join(repo_parts) if repo_parts else repo_hash
    return f"{owner}/{repo}"


def _infer_language(project, patch_files):
    """Infer language from project name or patch file extensions."""
    if project in _PROJECT_LANG_MAP:
        return _PROJECT_LANG_MAP[project]
    proj_lower = project.lower()
    for k, v in _PROJECT_LANG_MAP.items():
        if k.lower() == proj_lower:
            return v
    return _detect_language_from_files(patch_files)


def _detect_language_from_files(files):
    """Detect primary language from file paths."""
    if not files:
        return "unknown"
    lang_counts = Counter()
    skip_langs = {"JSON", "YAML", "XML", "TOML", "Markdown", "HTML", "CSS", "Shell"}
    for f in files:
        _, ext = os.path.splitext(f)
        ext = ext.lower()
        if ext in _IGNORED_EXTS:
            continue
        lang = _EXT_LANG_MAP.get(ext)
        if lang and lang not in skip_langs:
            lang_counts[lang] += 1
    if not lang_counts:
        return "unknown"
    return lang_counts.most_common(1)[0][0]


def _parse_patch_files(patch):
    """Extract file paths modified in a diff/patch string."""
    if not patch:
        return []
    files = []
    for line in patch.split("\n"):
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
        elif line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[-1]
                if b_path.startswith("b/"):
                    files.append(b_path[2:])
    return list(dict.fromkeys(files))


def _count_patch_lines(patch):
    """Count added/removed lines in a patch."""
    if not patch:
        return 0
    count = 0
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            count += 1
        elif line.startswith("-") and not line.startswith("---"):
            count += 1
    return count


def _classify_patch(patch, patch_files, patch_lines):
    """Classify patch semantically."""
    if not patch or patch_lines == 0:
        return "empty"
    if patch_lines > 200:
        return "brute_force"

    added_lines = []
    removed_lines = []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:].strip())

    all_changed = added_lines + removed_lines
    import_patterns = ["import ", "from ", "require(", "require ", "#include"]
    non_empty = [l for l in all_changed if l.strip()]
    if non_empty and all(any(l.startswith(p) for p in import_patterns) for l in non_empty):
        return "import_only"

    config_exts = {".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf",
                   ".xml", ".properties", ".env"}
    config_names = {"setup.py", "setup.cfg", "pyproject.toml", "package.json",
                    "tsconfig.json", "webpack.config.js", "Makefile",
                    "CMakeLists.txt", ".eslintrc", ".prettierrc", "tox.ini"}
    if patch_files and all(
        os.path.splitext(f)[1].lower() in config_exts or os.path.basename(f) in config_names
        for f in patch_files
    ):
        return "config_only"

    if patch_files and all(
        "test" in f.lower() or "spec" in f.lower() or "__tests__" in f
        for f in patch_files
    ):
        return "test_only"

    comment_markers = ["#", "//", "/*", "*/", "*", "<!--", "-->", '"""', "'''"]
    if non_empty and all(
        any(l.startswith(m) for m in comment_markers) or l == ""
        for l in non_empty
    ):
        return "comment_only"

    return "functional"


def _ngram_jaccard(text_a, text_b, n=3):
    """Compute n-gram Jaccard similarity between two texts."""
    if not text_a or not text_b:
        return 0.0
    words_a = text_a.lower().split()
    words_b = text_b.lower().split()
    if len(words_a) < n or len(words_b) < n:
        return 0.0
    ngrams_a = set(tuple(words_a[i:i + n]) for i in range(len(words_a) - n + 1))
    ngrams_b = set(tuple(words_b[i:i + n]) for i in range(len(words_b) - n + 1))
    if not ngrams_a or not ngrams_b:
        return 0.0
    intersection = len(ngrams_a & ngrams_b)
    union = len(ngrams_a | ngrams_b)
    return intersection / union if union > 0 else 0.0


def _detect_loops(conversation, window=10, threshold=0.5):
    """Detect conversation loops using n-gram Jaccard similarity."""
    assistant_msgs = [
        str(m.get("content", ""))
        for m in conversation
        if m.get("role") == "assistant" and m.get("content")
    ]
    if len(assistant_msgs) < 4:
        return False
    recent = assistant_msgs[-window:]
    high_sim_count = 0
    total_pairs = 0
    for i in range(len(recent)):
        for j in range(i + 1, len(recent)):
            sim = _ngram_jaccard(recent[i], recent[j])
            if sim >= threshold:
                high_sim_count += 1
            total_pairs += 1
    if total_pairs == 0:
        return False
    return high_sim_count / total_pairs >= 0.3


def _count_conversation_stats(conversation):
    """Count various conversation statistics.

    IMPORTANT: Only counts actual commands inside ```bash blocks,
    not keyword mentions in discussion text.
    """
    stats = {
        "total_turns": len(conversation), "assistant_turns": 0,
        "user_turns": 0, "system_turns": 0, "edit_commands": 0,
        "read_commands": 0, "test_commands": 0, "search_commands": 0,
    }

    for msg in conversation:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))
        if role == "assistant":
            stats["assistant_turns"] += 1
            # Extract actual bash commands from code blocks
            cmds = re.findall(r'```(?:bash|sh|shell)?\n(.*?)```', content, re.DOTALL)
            for block in cmds:
                for line in block.strip().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    low = line.lower()
                    # Edit commands (actual file modifications)
                    if any(kw in low for kw in ["sed -i", "sed 's/", "cat >", "cat >>",
                                                 "tee ", "patch ", "vi ", "vim ", "nano "]):
                        stats["edit_commands"] += 1
                    elif re.search(r"(echo|printf)\s+.*>", low):
                        stats["edit_commands"] += 1
                    elif "python" in low and ("-c" in low or "<<" in low) and ">" in low:
                        stats["edit_commands"] += 1
                    # Test commands
                    elif any(kw in low for kw in ["pytest", "python -m pytest",
                                                   "npm test", "yarn test", "make test",
                                                   "cargo test", "go test", "mvn test",
                                                   "python -m unittest", "tox ", "nosetests"]):
                        stats["test_commands"] += 1
                    # Search/grep commands
                    elif any(low.startswith(kw) or (" " + kw) in low
                             for kw in ["grep ", "rg ", "ag ", "ack "]):
                        stats["search_commands"] += 1
                    # Read commands (file content inspection)
                    elif any(low.startswith(kw) or (" " + kw) in low
                             for kw in ["cat ", "head ", "tail ", "less ", "more "]):
                        stats["read_commands"] += 1
                    elif any(low.startswith(kw) for kw in ["find ", "ls ", "tree "]):
                        stats["read_commands"] += 1
            # Also check for tool_use patterns in text (str_replace_editor etc.)
            content_lower = content.lower()
            if any(p in content_lower for p in ["str_replace_editor", "write_to_file",
                                                 "insert_content", "create_file", "apply_diff"]):
                stats["edit_commands"] += 1
            if any(p in content_lower for p in ["read_file", "view_file"]):
                stats["read_commands"] += 1
        elif role == "user":
            stats["user_turns"] += 1
        elif role == "system":
            stats["system_turns"] += 1
    return stats


def _find_claim_turn(conversation):
    """Find the earliest assistant turn where model claims to have found the bug.

    Returns (claim_turn_index, total_assistant_turns) or (None, total) if no claim found.
    claim_turn_index is 0-based index among assistant turns.
    """
    found_bug_phrases = [
        "i found the bug", "i've found the bug", "i identified the bug",
        "i've identified the bug", "the bug is", "the issue is",
        "root cause", "found the root cause", "i see the problem",
        "i found the issue", "i've found the issue",
    ]
    assistant_idx = 0
    total_assistant = 0
    claim_turn = None
    for msg in conversation:
        if msg.get("role") == "assistant" and msg.get("content"):
            total_assistant += 1
            if claim_turn is None:
                msg_lower = str(msg.get("content", "")).lower()
                if any(phrase in msg_lower for phrase in found_bug_phrases):
                    claim_turn = assistant_idx
            assistant_idx += 1
    return claim_turn, total_assistant


def _classify_explore_only(conversation):
    """Sub-classify explore_only failures."""
    if not conversation:
        return "analysis_paralysis"
    assistant_msgs = [
        str(m.get("content", ""))
        for m in conversation
        if m.get("role") == "assistant" and m.get("content")
    ]
    if not assistant_msgs:
        return "analysis_paralysis"

    # Count genuine tool errors (non-zero returncode + error keywords)
    # Exclude normal empty-result output from grep/find
    tool_error_count = 0
    for msg in conversation:
        if msg.get("role") == "user":
            content = str(msg.get("content", ""))
            content_lower = content.lower()
            # Only count as error if returncode is non-zero
            has_nonzero_rc = bool(re.search(r'<returncode>[1-9]\d*</returncode>', content))
            if has_nonzero_rc:
                # Check for real errors, not just grep returning 1 (no matches)
                if any(kw in content_lower for kw in [
                    "permission denied", "syntax error", "traceback",
                    "command not found", "modulenotfounderror", "importerror",
                    "segmentation fault", "killed", "cannot execute",
                ]):
                    tool_error_count += 1
    if tool_error_count >= 3:
        return "tool_struggling"

    # Check if model runs echo/print commands declaring "completion" without actual edits
    # Pattern: `echo 'Completed code review...'` or `echo "Fix applied successfully"`
    # These are declarative echos (no file redirection >) that claim task completion
    false_completion_phrases = [
        "completed", "done", "fixed", "applied", "implemented",
        "successfully", "resolved", "patched", "corrected",
        "finish", "complete the", "task complete",
    ]
    false_completion_cmds = []
    for msg_text in assistant_msgs:
        # Extract bash code blocks
        blocks = re.findall(r'```(?:bash|sh|shell)?\n(.*?)```', msg_text, re.DOTALL)
        for block in blocks:
            for line in block.strip().splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                low = line_stripped.lower()
                # Match echo/printf without file redirection (no > after the string)
                # e.g., echo 'Completed code review...' but NOT echo 'text' > file
                is_echo = low.startswith("echo ") or low.startswith("printf ")
                if not is_echo:
                    continue
                # Skip if it writes to a file (has > outside of quoted strings)
                # Simple heuristic: check if > appears after closing quote/end
                has_redirect = bool(re.search(r'>\s*\S', line_stripped))
                if has_redirect:
                    continue
                # Check if the echo content claims completion
                if any(phrase in low for phrase in false_completion_phrases):
                    false_completion_cmds.append(line_stripped)
    if false_completion_cmds:
        return "false_completion"

    # Check if model identified the bug but didn't act (last 3 assistant msgs)
    last_3 = assistant_msgs[-3:] if len(assistant_msgs) >= 3 else assistant_msgs
    found_bug_phrases = [
        "i found the bug", "i've found the bug", "i identified the bug",
        "i've identified the bug", "the bug is", "the issue is",
        "root cause", "found the root cause", "i see the problem",
        "i found the issue", "i've found the issue",
    ]
    for msg in last_3:
        msg_lower = msg.lower()
        if any(phrase in msg_lower for phrase in found_bug_phrases):
            return "identified_no_action"

    read_files = []
    for msg in assistant_msgs:
        for m in re.finditer(r'(?:read_file|view_file|cat|head|tail)\s+["\']?([^\s"\']+)', msg):
            read_files.append(m.group(1))
        for m in re.finditer(r'(?:grep|find|rg|ag)\s+.*?([/\w]+\.\w+)', msg):
            read_files.append(m.group(1))

    if len(read_files) >= 3:
        unique_files = len(set(read_files))
        diversity = unique_files / len(read_files) if read_files else 0
        if unique_files >= 8 and diversity >= 0.5:
            return "wide_scatter"
        else:
            return "deep_stuck"

    last_msgs = " ".join(assistant_msgs[-3:]).lower()
    if any(p in last_msgs for p in [
        "i'm not sure", "i cannot determine", "unable to identify",
        "don't see", "can't find", "not clear",
    ]):
        return "cant_locate"

    return "analysis_paralysis"


def _extract_false_completion_cmds(conversation):
    """Extract echo/printf commands that falsely declare task completion."""
    false_completion_phrases = [
        "completed", "done", "fixed", "applied", "implemented",
        "successfully", "resolved", "patched", "corrected",
        "finish", "complete the", "task complete",
    ]
    cmds = []
    assistant_msgs = [
        str(m.get("content", ""))
        for m in conversation
        if m.get("role") == "assistant" and m.get("content")
    ]
    for msg_text in assistant_msgs:
        blocks = re.findall(r'```(?:bash|sh|shell)?\n(.*?)```', msg_text, re.DOTALL)
        for block in blocks:
            for line in block.strip().splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                low = line_stripped.lower()
                is_echo = low.startswith("echo ") or low.startswith("printf ")
                if not is_echo:
                    continue
                has_redirect = bool(re.search(r'>\s*\S', line_stripped))
                if has_redirect:
                    continue
                if any(phrase in low for phrase in false_completion_phrases):
                    cmds.append(line_stripped)
    return cmds


def _extract_module_name(path):
    """Extract a normalized module name from a file path for alignment comparison.
    Strips test prefixes/suffixes, extensions, and common directory prefixes."""
    if not path:
        return ""
    # Take file part before | or :: (for test names like 'test/Foo-test.tsx | describe')
    path = path.split("|")[0].split("::")[0].strip()
    # Get basename
    base = os.path.basename(path)
    # Strip extension
    base = re.sub(r'\.(tsx?|jsx?|py|go|rs|java|rb|php|c|cpp|h|cs|kt|scala)$', '', base, flags=re.IGNORECASE)
    # Strip test prefixes and suffixes (order matters: strip suffix first, then prefix)
    base = re.sub(r'[-_.]?(test|spec|tests)$', '', base, flags=re.IGNORECASE)
    base = re.sub(r'^(test_|test-|tests_)', '', base, flags=re.IGNORECASE)
    return base.lower()


def _extract_parent_dir(path):
    """Extract the meaningful parent directory path, stripping common roots.
    Uses full parent path for precise area comparison."""
    path = path.split("|")[0].split("::")[0].strip()
    # Remove leading /app/ if present
    path = re.sub(r'^/app/', '', path)
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    # Remove the filename (last part)
    dir_parts = parts[:-1]
    # Skip common root prefixes
    skip = {"src", "lib", "app", "test", "tests", "spec", "packages"}
    filtered = [p for p in dir_parts if p.lower() not in skip]
    return "/".join(filtered).lower()


def _compute_patch_target_alignment(patch_files, target_tests):
    """Compute alignment between patched files and target test files.
    Returns: 'match' | 'related' | 'mismatch' | 'no_data'
    - match: patch module == target test module (right file, wrong logic)
    - related: same specific directory area but different module (right area, wrong file)
    - mismatch: completely different module and area (wrong location)
    """
    if not patch_files or not target_tests:
        return "no_data"

    patch_modules = {_extract_module_name(f) for f in patch_files if _extract_module_name(f)}
    test_modules = {_extract_module_name(t) for t in target_tests if _extract_module_name(t)}

    if not patch_modules or not test_modules:
        return "no_data"

    # Exact module match
    if patch_modules & test_modules:
        return "match"

    # Check containment (e.g., 'roomlist' in 'roomlistview' or vice versa)
    for pm in patch_modules:
        for tm in test_modules:
            if len(pm) >= 4 and len(tm) >= 4:
                if pm in tm or tm in pm:
                    return "match"

    # Directory/area match
    patch_dirs = [_extract_parent_dir(f) for f in patch_files]
    test_dirs = [_extract_parent_dir(t) for t in target_tests]

    for pd in patch_dirs:
        if not pd:
            continue
        pd_parts = pd.split("/")
        for td in test_dirs:
            if not td:
                # Flat test structure (e.g., test/user.js → dir="")
                # Fall back: check if test module name matches any patch dir segment
                # e.g., patch dir "user" contains test module "user" → related
                for tm in test_modules:
                    if tm and len(tm) >= 3 and tm in pd_parts:
                        return "related"
                continue
            td_parts = td.split("/")
            # Check if paths share a specific prefix of >=3 segments
            shared = 0
            for a, b in zip(pd_parts, td_parts):
                if a == b:
                    shared += 1
                else:
                    break
            if shared >= 3:
                return "related"
            # Also check if one is a child of the other (same subdir)
            if len(pd_parts) >= 3 and len(td_parts) >= 3:
                if pd.startswith(td + "/") or td.startswith(pd + "/"):
                    return "related"

    # Reverse check: patch dir is empty but test dir has depth
    for td in test_dirs:
        if not td:
            continue
        td_parts = td.split("/")
        for pd in patch_dirs:
            if pd:
                continue  # already checked above
            for pm in patch_modules:
                if pm and len(pm) >= 3 and pm in td_parts:
                    return "related"

    return "mismatch"


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


# ── TrajectoryData ───────────────────────────────────────────────────────────

class TrajectoryData:
    """Parsed trajectory wrapper for SWE-SYNTH environment."""

    def __init__(self, raw):
        self.raw = raw
        self.task_id = int(raw.get("task_id", 0))
        self.score = float(raw.get("score", 0))
        self.is_win = self.score >= 0.5
        self.timestamp = raw.get("timestamp", 0) or 0
        if isinstance(self.timestamp, str):
            self.timestamp = int(self.timestamp) if self.timestamp else 0
        if self.timestamp and self.timestamp > 1e12:
            self.timestamp = self.timestamp / 1000

        extra = raw.get("extra", {}) or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        self.extra = extra

        self.all_passed = bool(extra.get("all_passed", False))
        all_result = extra.get("all_result", "") or ""
        self.all_passed_count, self.all_total = _parse_result(all_result)
        self.all_result_str = all_result

        self.target_passed = bool(extra.get("target_passed", False))
        target_result = extra.get("target_result", "") or ""
        self.target_passed_count, self.target_total = _parse_result(target_result)
        self.target_result_str = target_result

        swe_instance_id = str(extra.get("swe_instance_id", ""))
        self.swe_instance_id = swe_instance_id
        self.project = _extract_project(swe_instance_id)

        fix_patch = extra.get("fix_patch", "") or ""
        self.fix_patch = fix_patch
        self.has_patch = bool(fix_patch and fix_patch.strip())
        self.patch_files = _parse_patch_files(fix_patch) if self.has_patch else []
        self.patch_lines = _count_patch_lines(fix_patch) if self.has_patch else 0
        self.patch_class = _classify_patch(fix_patch, self.patch_files, self.patch_lines)

        self.language = _infer_language(self.project, self.patch_files)

        bug_types = extra.get("bug_types", []) or []
        if isinstance(bug_types, str):
            bug_types = [b.strip() for b in bug_types.split(",") if b.strip()]
        self.bug_types = bug_types

        self.conversation = extra.get("conversation", []) or []
        self.model_calls = int(extra.get("model_calls", 0) or 0)
        self.problem_statement = str(extra.get("problem_statement", ""))

        usage = extra.get("usage", {}) or {}
        self.total_tokens = int(usage.get("total_tokens", 0) or 0)
        self.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        self.fixer_agent = str(extra.get("fixer_agent", ""))
        self.image = str(extra.get("image", ""))
        self.target_tests = extra.get("target_tests", []) or []
        self.missing_tests = extra.get("missing_tests", []) or []

        # Patch-target alignment: does the patch modify the right module?
        self.patch_target_alignment = _compute_patch_target_alignment(
            self.patch_files, self.target_tests
        ) if self.has_patch and self.target_tests else "no_data"

        self._conv_stats = _count_conversation_stats(self.conversation)
        self.has_loop = _detect_loops(self.conversation)

        # Turn-of-claim: when did the model first claim to have found the bug?
        self.claim_turn, self.total_assistant_turns = _find_claim_turn(self.conversation)
        self.claim_position = None  # 0.0=very early, 1.0=very late
        if self.claim_turn is not None and self.total_assistant_turns > 0:
            self.claim_position = self.claim_turn / self.total_assistant_turns

        self.no_patch_stage = ""
        self.failure_category = ""
        self.explore_only_subtype = ""
        self.false_completion_cmds = []  # populated if explore_only_subtype == "false_completion"
        if not self.is_win:
            self._classify_failure()
            if self.explore_only_subtype == "false_completion":
                self.false_completion_cmds = _extract_false_completion_cmds(self.conversation)

    def _classify_failure(self):
        if not self.has_patch:
            self._classify_no_patch()
        else:
            self._classify_patched_failure()

    def _classify_no_patch(self):
        for msg in self.conversation:
            if msg.get("role") == "assistant":
                content = str(msg.get("content", "")).lower()
                for pattern in _IDENTITY_PATTERNS:
                    if pattern in content:
                        self.no_patch_stage = "identity_confusion"
                        return

        # Check for environment/setup errors (permission denied, missing deps, etc.)
        env_error_keywords = ["permission denied", "command not found", "no such file",
                              "syntax error", "traceback", "modulenotfounderror",
                              "importerror", "connection refused"]
        env_error_count = 0
        for msg in self.conversation:
            if msg.get("role") == "user":
                content = str(msg.get("content", "")).lower()
                if any(kw in content for kw in env_error_keywords):
                    env_error_count += 1
        if env_error_count >= 3:
            self.no_patch_stage = "env_blocked"
            return

        has_edits = self._conv_stats["edit_commands"] > 0
        has_tests = self._conv_stats["test_commands"] > 0

        if not has_edits:
            if len(self.conversation) <= 6:
                self.no_patch_stage = "shallow_bail"
            else:
                self.no_patch_stage = "explore_only"
                self.explore_only_subtype = _classify_explore_only(self.conversation)
        elif has_edits and not has_tests:
            if self._conv_stats["edit_commands"] > 5:
                self.no_patch_stage = "edit_churn"
            else:
                self.no_patch_stage = "edit_no_test"
        elif has_edits and has_tests:
            if self.has_loop:
                self.no_patch_stage = "fix_test_loop"
            else:
                self.no_patch_stage = "edit_churn"
        else:
            self.no_patch_stage = "edit_churn"

    def _classify_patched_failure(self):
        t_pass = self.target_passed_count
        t_total = self.target_total
        a_pass = self.all_passed_count
        a_total = self.all_total

        if t_total == 0 and a_total == 0:
            self.failure_category = "partial_progress"
            return

        target_ok = self.target_passed or (t_total > 0 and t_pass == t_total)
        non_target_total = a_total - t_total
        non_target_pass = a_pass - t_pass
        non_target_rate = non_target_pass / non_target_total if non_target_total > 0 else 1.0

        if not target_ok and non_target_rate >= 0.9:
            self.failure_category = "target_fail_only"
        elif target_ok and non_target_rate < 0.9:
            self.failure_category = "regression_only"
        elif not target_ok and non_target_rate < 0.9:
            self.failure_category = "target+regress"
        else:
            # target_ok=True AND non_target_rate >= 0.9: target bug fixed but still a loss
            # Split: target all passed → target_pass+minor_regress (high SFT value)
            #        target partially passed → partial_progress
            t_rate = t_pass / t_total if t_total > 0 else 0.0
            if target_ok:
                self.failure_category = "target_pass+minor_regress"
            elif t_rate > 0:
                self.failure_category = "partial_progress"
            else:
                self.failure_category = "target_fail_only"

    @property
    def failure_label(self):
        if self.is_win:
            return "win"
        if not self.has_patch:
            return self.no_patch_stage or "unknown"
        return self.failure_category or "unknown"

    @property
    def explore_before_edit_ratio(self):
        total = self._conv_stats["assistant_turns"]
        if total == 0:
            return 0.0
        reads = self._conv_stats["read_commands"] + self._conv_stats["search_commands"]
        return reads / total


# ── Data Fetching ────────────────────────────────────────────────────────────

async def fetch_trajectories(uid, env_name="SWE-SYNTH", source="sampling"):
    """Fetch trajectories for a miner UID.

    Returns: (miner_info, raw_trajectories)
    """
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
        return {
            "matched": len(results), "sampling_list_size": sl_size,
            "hotkey": hotkey, "model_revision": revision,
        }, results


_db_initialized = False
_db_init_lock = None


async def _ensure_db():
    """Ensure DB client is initialized exactly once (safe for concurrent calls)."""
    global _db_initialized, _db_init_lock
    if _db_initialized:
        return
    if _db_init_lock is None:
        _db_init_lock = asyncio.Lock()
    async with _db_init_lock:
        if _db_initialized:
            return
        from affine.database.client import init_client
        await init_client()
        _db_initialized = True


async def _fetch_via_db(uid, env_name, source):
    """Fallback: fetch via direct DB access. Safe for concurrent calls."""
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
    if env_key not in environments and ":" not in env_key:
        matches = [e for e in environments if e.endswith(f":{env_key}")]
        if len(matches) == 1:
            env_key = matches[0]

    if source == "all":
        task_ids = sorted(await sample_dao.get_completed_task_ids(hotkey, revision, env_key))
    else:
        env_config = environments.get(env_key, {})
        task_ids = sorted(get_task_id_set_from_config(env_config))

    # Concurrent fetch with semaphore to limit DB pressure
    sem = asyncio.Semaphore(20)
    results = []
    fetched = [0]

    async def _get_one(task_id):
        async with sem:
            try:
                item = await sample_dao.get_sample_by_task_id(
                    miner_hotkey=hotkey, model_revision=revision,
                    env=env_key, task_id=str(task_id), include_extra=True,
                )
                if item:
                    results.append(item)
            except Exception:
                pass
            fetched[0] += 1
            if fetched[0] % 50 == 0:
                print(f"  UID={uid}: {fetched[0]}/{len(task_ids)} ...", file=sys.stderr)

    await asyncio.gather(*[_get_one(tid) for tid in task_ids])

    return {
        "matched": len(results), "sampling_list_size": len(task_ids),
        "hotkey": hotkey, "model_revision": revision,
    }, results


# ── Report Generation ────────────────────────────────────────────────────────

def generate_report(miner_info, raw_trajectories):
    """Generate full SWE-SYNTH analysis report."""
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
    wins = [t for t in parsed if t.is_win]
    losses = [t for t in parsed if not t.is_win]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / n * 100

    matched = miner_info.get("matched", n)
    sl_size = miner_info.get("sampling_list_size", n)
    match_pct = matched / max(sl_size, 1) * 100

    project_groups = defaultdict(list)
    for t in parsed:
        project_groups[t.project].append(t)

    lang_groups = defaultdict(list)
    for t in parsed:
        lang_groups[t.language].append(t)

    bug_type_groups = defaultdict(list)
    for t in parsed:
        for bt in t.bug_types:
            bug_type_groups[bt].append(t)

    # ═══════════════════════════════════════════════════════════════════════
    # Header
    # ═══════════════════════════════════════════════════════════════════════
    p("ENVIRONMENT: SWE-SYNTH")
    p("=" * 80)
    p(f"  Samples: {n}")
    if matched > sl_size:
        # source=all: matched exceeds sampling list (fetched all completed)
        p(f"  Completed tasks: {matched} (sampling list: {sl_size})")
    else:
        p(f"  Sampling list: {sl_size} task_ids, {matched} matched ({match_pct:.1f}%)")
    p(f"  Avg score: {avg_score:.3f}")
    p(f"  Projects: {len(project_groups)}")
    p(f"  Languages: {', '.join(sorted(lang_groups.keys()))}")
    p("")

    sec = [0]  # mutable counter for section numbering
    def section(title):
        sec[0] += 1
        p("=" * 80)
        p(f"{sec[0]}. {title}")
        p("=" * 80)
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    section("EXECUTIVE SUMMARY")
    p(f"  Total tasks:  {n}")
    p(f"  Win rate:     {win_count}/{n} ({win_rate:.1f}%)")
    p(f"  Avg score:    {avg_score:.3f}")
    p("")

    p("  Top bottlenecks:")
    bottlenecks = []
    if project_groups:
        worst_proj, worst_proj_loss = None, 0
        for proj, tasks in project_groups.items():
            pl = sum(1 for t in tasks if not t.is_win)
            if pl > worst_proj_loss and len(tasks) >= 3:
                worst_proj_loss = pl
                worst_proj = proj
        if worst_proj:
            pt = project_groups[worst_proj]
            pwr = sum(1 for t in pt if t.is_win) / len(pt) * 100
            bottlenecks.append(f"{worst_proj}: {pwr:.0f}% win rate ({worst_proj_loss} losses)")

    patched_losses = [t for t in losses if t.has_patch]
    unpatched_losses = [t for t in losses if not t.has_patch]
    near_wins = [t for t in losses if t.all_total > 0 and t.all_passed_count / t.all_total >= _NEAR_WIN_THRESHOLD]
    ztw = sum(1 for t in wins if t._conv_stats["test_commands"] == 0)

    if losses:
        fc = Counter(t.failure_label for t in losses)
        tf, tc = fc.most_common(1)[0]
        bottlenecks.append(f"{tf}: {tc}/{loss_count} losses ({tc / loss_count * 100:.0f}%)")
    if unpatched_losses:
        bottlenecks.append(f"No patch submitted: {len(unpatched_losses)}/{loss_count} losses ({len(unpatched_losses) / loss_count * 100:.0f}%)")

    for b in bottlenecks:
        p(f"    - {b}")
    p("")

    p("  Language breakdown:")
    for lang in sorted(lang_groups.keys()):
        tasks = lang_groups[lang]
        lwr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
        p(f"    {lang:<15}: {len(tasks):>3} tasks, {lwr:.0f}% win rate")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # TOP FINDINGS — high-value insights (goal #6: 最开始给我 top findings)
    # ═══════════════════════════════════════════════════════════════════════
    top_findings = []

    # Finding: scoring anomalies (reward gaming)
    scoring_anomalies = [t for t in parsed if t.is_win and t.target_total > 0 and t.target_passed_count / t.target_total < 0.5]
    if scoring_anomalies:
        top_findings.append(
            f"⚠ REWARD GAMING: {len(scoring_anomalies)} wins with <50% target tests passed — "
            f"env scores on all_passed (not target_passed), allowing wins without fixing the target bug"
        )

    # Finding: patch-target alignment + explore_only localization signal
    aligned_losses = [t for t in losses if t.patch_target_alignment != "no_data"]
    explore_only_tasks = [t for t in losses if t.no_patch_stage == "explore_only"]
    wide_scatter_cnt = sum(1 for t in explore_only_tasks if t.explore_only_subtype == "wide_scatter")
    if aligned_losses:
        mismatch_cnt = sum(1 for t in aligned_losses if t.patch_target_alignment == "mismatch")
        match_cnt = sum(1 for t in aligned_losses if t.patch_target_alignment == "match")
        # Include explore_only wide_scatter as additional localization signal
        loc_suffix = ""
        if wide_scatter_cnt >= 2:
            loc_suffix = f" + {wide_scatter_cnt} explore_only/wide_scatter (can't find target at all)"
        if mismatch_cnt / len(aligned_losses) >= 0.3:
            top_findings.append(
                f"LOCALIZATION: {mismatch_cnt}/{len(aligned_losses)} ({mismatch_cnt * 100 // len(aligned_losses)}%) patched losses "
                f"modify the wrong file{loc_suffix}"
            )
        elif match_cnt / len(aligned_losses) >= 0.5:
            top_findings.append(
                f"FIX QUALITY: {match_cnt}/{len(aligned_losses)} ({match_cnt * 100 // len(aligned_losses)}%) patched losses "
                f"modify the right file but wrong logic{loc_suffix}"
            )
    elif wide_scatter_cnt >= 3:
        # No alignment data but significant wide_scatter
        top_findings.append(
            f"LOCALIZATION: {wide_scatter_cnt} explore_only tasks are wide_scatter — model can't find target file at all"
        )

    # Finding: near-win opportunity
    if near_wins and loss_count > 0 and len(near_wins) / loss_count >= 0.3:
        nw_far = [t for t in near_wins if not (t.target_total and t.target_total > 0 and t.target_passed_count / t.target_total > 0.5)]
        top_findings.append(
            f"NEAR-WINS: {len(near_wins)}/{loss_count} losses ({len(near_wins) * 100 // loss_count}%) pass >=80% of all tests — "
            f"{len(nw_far)} are target-far (wrong fix direction)"
        )

    # Finding: dominant failure mode
    if losses:
        fc = Counter(t.failure_label for t in losses)
        dom, dom_cnt = fc.most_common(1)[0]
        if dom_cnt / loss_count >= 0.4:
            top_findings.append(
                f"BOTTLENECK: {dom} accounts for {dom_cnt}/{loss_count} ({dom_cnt * 100 // loss_count}%) of losses"
            )

    # Finding: test-free wins
    if win_count >= 3 and ztw / max(win_count, 1) >= 0.9:
        top_findings.append(
            f"PATTERN MATCHING: {ztw}/{win_count} wins ({ztw * 100 // win_count}%) use zero test commands — "
            f"model wins by pattern matching, never validates"
        )

    # Finding: target_pass+minor_regress (scoring gap)
    tp_mr_list = [t for t in losses if t.failure_category == "target_pass+minor_regress"]
    if tp_mr_list:
        top_findings.append(
            f"SCORING GAP: {len(tp_mr_list)} tasks fixed the target bug (target tests pass) but scored 0.0 "
            f"due to minor regressions — highest SFT correction value"
        )

    if top_findings:
        p("  TOP FINDINGS:")
        for i, finding in enumerate(top_findings, 1):
            p(f"    {i}. {finding}")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 2: SCORE DISTRIBUTION (skip for binary 0/1 scores)
    # ═══════════════════════════════════════════════════════════════════════
    unique_scores = sorted(set(round(s, 3) for s in scores))
    is_binary = len(unique_scores) <= 2 and all(s in (0.0, 1.0) for s in unique_scores)
    if not is_binary:
        section("SCORE DISTRIBUTION")
        p(f"  Wins:   {win_count:>4} ({win_rate:>5.1f}%)")
        p(f"  Losses: {loss_count:>4} ({loss_count / n * 100:>5.1f}%)")
        p("")
        p("  Score values:")
        max_cnt = max(sum(1 for s in scores if round(s, 3) == sv) for sv in unique_scores) if unique_scores else 1
        bw = 40
        for sv in unique_scores:
            cnt = sum(1 for s in scores if round(s, 3) == sv)
            bar_len = int(cnt / max(max_cnt, 1) * bw)
            p(f"    {sv:.3f}: {cnt:>4} ({cnt / n * 100:>5.1f}%) {chr(9608) * bar_len}")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 3: PROJECT & LANGUAGE BREAKDOWN
    # ═══════════════════════════════════════════════════════════════════════
    section("PROJECT & LANGUAGE BREAKDOWN")
    p("  Per-project win rate:")
    p(f"  {'Project':<40} {'Count':>5} {'Wins':>5} {'Win%':>6} {'Language':<15}")
    p("  " + chr(9472) * 75)
    proj_wrs = []
    for proj in sorted(project_groups.keys()):
        tasks = project_groups[proj]
        pw = sum(1 for t in tasks if t.is_win)
        pwr = pw / len(tasks) * 100
        lang = tasks[0].language if tasks else "unknown"
        proj_wrs.append((proj, len(tasks), pw, pwr, lang))
    proj_wrs.sort(key=lambda x: -x[3])
    for proj, cnt, pw, pwr, lang in proj_wrs:
        p(f"  {proj[:40]:<40} {cnt:>5} {pw:>5} {pwr:>5.1f}% {lang:<15}")
    p("")

    p("  Per-language win rate:")
    p(f"  {'Language':<15} {'Count':>5} {'Wins':>5} {'Win%':>6} {'Projects'}")
    p("  " + chr(9472) * 70)
    for lang in sorted(lang_groups.keys()):
        tasks = lang_groups[lang]
        lw = sum(1 for t in tasks if t.is_win)
        lwr = lw / len(tasks) * 100
        lp = sorted(set(t.project for t in tasks))
        ps = ", ".join(lp[:3])
        if len(lp) > 3:
            ps += f" +{len(lp) - 3} more"
        p(f"  {lang:<15} {len(tasks):>5} {lw:>5} {lwr:>5.1f}% {ps}")
    p("")

    # Project-language mapping omitted (already visible in per-project table)

    # ═══════════════════════════════════════════════════════════════════════
    # Section 4: BUG TYPE ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    section("BUG TYPE ANALYSIS")
    p("  Per-bug-type win rate:")
    p(f"  {'Bug Type':<25} {'Count':>5} {'Wins':>5} {'Win%':>6}")
    p("  " + chr(9472) * 45)
    bwrs = sorted([(bt, len(ts), sum(1 for t in ts if t.is_win), sum(1 for t in ts if t.is_win) / len(ts) * 100) for bt, ts in bug_type_groups.items()], key=lambda x: -x[3])
    for bt, cnt, bw, bwr in bwrs:
        p(f"  {bt:<25} {cnt:>5} {bw:>5} {bwr:>5.1f}%")
    p("")

    no_bt = [t for t in parsed if not t.bug_types]
    if no_bt:
        p(f"  Tasks with no bug_types: {len(no_bt)} ({sum(1 for t in no_bt if t.is_win) / len(no_bt) * 100:.1f}% win rate)")
        p("")

    cooccur = Counter()
    for t in parsed:
        if len(t.bug_types) >= 2:
            for i in range(len(t.bug_types)):
                for j in range(i + 1, len(t.bug_types)):
                    cooccur[tuple(sorted([t.bug_types[i], t.bug_types[j]]))] += 1
    sig_cooccur = {pair: cnt for pair, cnt in cooccur.items() if cnt >= 2}
    if sig_cooccur:
        p("  Bug type co-occurrence (>=2 tasks):")
        for pair, cnt in sorted(sig_cooccur.items(), key=lambda x: -x[1])[:8]:
            ptasks = [t for t in parsed if pair[0] in t.bug_types and pair[1] in t.bug_types]
            pwr = sum(1 for t in ptasks if t.is_win) / len(ptasks) * 100 if ptasks else 0
            p(f"    {pair[0]} + {pair[1]}: {cnt} tasks ({pwr:.0f}% win rate)")
        p("")

    # Bug type x failure stage cross-analysis
    if losses:
        p("  BUG TYPE x FAILURE STAGE CROSS-ANALYSIS:")
        all_stages = sorted(set(t.failure_label for t in losses))
        loss_bt = sorted(set(bt for t in losses for bt in t.bug_types))
        if loss_bt and all_stages:
            sa = [_LABEL_ABBREV.get(s, s[:7]) for s in all_stages]
            cw = max(max(len(a) for a in sa), 6) + 1
            btw = 22
            header = f"    {'bug_type':<{btw}}"
            for a in sa:
                header += f" {a:>{cw}}"
            header += f" {'total':>{cw}}"
            p(header)
            p("    " + chr(9472) * (btw + (cw + 1) * (len(all_stages) + 1)))
            for bt in loss_bt:
                btl = [t for t in losses if bt in t.bug_types]
                row = f"    {bt:<{btw}}"
                for stage in all_stages:
                    cnt = sum(1 for t in btl if t.failure_label == stage)
                    row += f" {cnt:>{cw}}" if cnt > 0 else f" {'.':>{cw}}"
                row += f" {len(btl):>{cw}}"
                p(row)
            p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 5: FAILURE ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    section("FAILURE ANALYSIS")
    if not losses:
        p("  No losses to analyze!")
        p("")
    else:
        p(f"  Total losses: {loss_count}")
        p(f"  With patch:   {len(patched_losses)} ({len(patched_losses) / loss_count * 100:.0f}%)")
        p(f"  No patch:     {len(unpatched_losses)} ({len(unpatched_losses) / loss_count * 100:.0f}%)")
        p("")

        if unpatched_losses:
            p("  NO-PATCH FAILURE STAGES:")
            npc = Counter(t.no_patch_stage for t in unpatched_losses)
            for stage, cnt in npc.most_common():
                p(f"    {stage:<22} {cnt:>3} ({cnt / len(unpatched_losses) * 100:>4.0f}%) {_stage_description(stage)}")
            p("")

        if patched_losses:
            p("  PATCHED FAILURE CATEGORIES:")
            pc = Counter(t.failure_category for t in patched_losses)
            for cat, cnt in pc.most_common():
                p(f"    {cat:<22} {cnt:>3} ({cnt / len(patched_losses) * 100:>4.0f}%) {_category_description(cat)}")
            p("")

            # Patch-target alignment analysis
            aligned_tasks = [t for t in patched_losses if t.patch_target_alignment != "no_data"]
            if aligned_tasks:
                ac = Counter(t.patch_target_alignment for t in aligned_tasks)
                total_aligned = len(aligned_tasks)
                p("  PATCH-TARGET ALIGNMENT (does patch modify the right module?):")
                for label, desc in [("match", "right file, wrong logic"),
                                    ("related", "right area, wrong file"),
                                    ("mismatch", "wrong location entirely")]:
                    cnt = ac.get(label, 0)
                    pct = cnt / total_aligned * 100 if total_aligned else 0
                    p(f"    {label:<12} {cnt:>3} ({pct:>4.0f}%) {desc}")
                no_data_cnt = sum(1 for t in patched_losses if t.patch_target_alignment == "no_data")
                if no_data_cnt:
                    p(f"    no_data      {no_data_cnt:>3}        (target_tests field empty)")

                # Show mismatch examples (most actionable)
                mismatches = [t for t in patched_losses if t.patch_target_alignment == "mismatch"]
                if mismatches:
                    p(f"    MISMATCH DETAIL ({len(mismatches)} tasks patched wrong module):")
                    for t in mismatches[:5]:
                        pmod = ", ".join(_extract_module_name(f) for f in t.patch_files[:2])
                        tmod = ", ".join(set(_extract_module_name(x) for x in t.target_tests[:3]))
                        p(f"      task={t.task_id}: patched [{pmod}] but target tests in [{tmod}]")
                    if len(mismatches) > 5:
                        p(f"      ... and {len(mismatches) - 5} more")

                # SFT implications
                match_pct = ac.get("match", 0) / total_aligned * 100 if total_aligned else 0
                mismatch_pct = ac.get("mismatch", 0) / total_aligned * 100 if total_aligned else 0
                if mismatch_pct >= 30:
                    p(f"    SFT: {mismatch_pct:.0f}% mismatch → model needs better bug LOCALIZATION training")
                elif match_pct >= 50:
                    p(f"    SFT: {match_pct:.0f}% match → model finds right file but needs better FIX QUALITY training")
                p("")

            # Regression detail (for target+regress and regression_only)
            regress_tasks = [t for t in patched_losses if t.failure_category in ("target+regress", "regression_only")]
            if len(regress_tasks) >= 2:
                p("  REGRESSION DETAIL:")
                # Severity distribution
                severities = []
                for t in regress_tasks:
                    if t.all_total and t.all_total > 0:
                        broken = t.all_total - t.all_passed_count
                        severities.append(broken)
                if severities:
                    p(f"    Tests broken per regression: avg={_safe_mean(severities):.0f}, median={_safe_median(severities):.0f}, max={max(severities)}")

                # Catastrophic vs minor
                catastrophic = [t for t in regress_tasks if t.all_total and t.all_passed_count / max(t.all_total, 1) < 0.1]
                minor = [t for t in regress_tasks if t.all_total and t.all_total > 0 and t.all_passed_count / t.all_total >= 0.8]
                if catastrophic:
                    p(f"    Catastrophic (<10% tests pass): {len(catastrophic)} tasks")
                    for t in catastrophic[:3]:
                        p(f"      task={t.task_id}: {t.all_result_str}, patch={t.patch_lines}L, bugs={','.join(t.bug_types[:2])}")
                if minor:
                    p(f"    Minor (>=80% tests still pass): {len(minor)} tasks")

                # Patch size correlation
                reg_patch_sizes = [t.patch_lines for t in regress_tasks if t.patch_lines > 0]
                nonreg = [t for t in patched_losses if t.failure_category not in ("target+regress", "regression_only")]
                nonreg_sizes = [t.patch_lines for t in nonreg if t.patch_lines > 0]
                win_sizes = [t.patch_lines for t in wins if t.patch_lines > 0]
                if reg_patch_sizes and win_sizes:
                    p(f"    Avg patch size: regressing={_safe_mean(reg_patch_sizes):.0f}L, wins={_safe_mean(win_sizes):.0f}L"
                      + (f", non-regressing={_safe_mean(nonreg_sizes):.0f}L" if nonreg_sizes else ""))

                # By project
                reg_projs = Counter(t.project for t in regress_tasks)
                if len(reg_projs) > 1:
                    p(f"    By project: {', '.join(f'{p}({c})' for p, c in reg_projs.most_common())}")

                # Regression-prone code areas (file path analysis)
                reg_files = Counter()
                win_files = set()
                for t in regress_tasks:
                    for f in t.patch_files:
                        # Use directory + filename for grouping
                        reg_files[f] += 1
                for t in wins:
                    for f in t.patch_files:
                        win_files.add(f)

                # Files that appear in regressions but NOT in wins = dangerous areas
                danger_files = {f: c for f, c in reg_files.items() if f not in win_files and c >= 2}
                shared_files = {f: c for f, c in reg_files.items() if f in win_files}

                if reg_files:
                    # Multi-level directory aggregation for cumulative risk
                    # Aggregate at multiple depths and show the most informative level
                    reg_dirs_by_depth = {}
                    for depth in [2, 3]:
                        rd = Counter()
                        for f, c in reg_files.items():
                            parts = f.split("/")
                            d = "/".join(parts[:depth]) if len(parts) >= depth else "/".join(parts[:-1]) if len(parts) > 1 else f
                            rd[d] += c
                        reg_dirs_by_depth[depth] = rd

                    # Pick depth where top dirs have highest cumulative risk
                    # Prefer shallower depth if it captures more regressions in fewer dirs
                    best_depth = 3
                    for depth in [2, 3]:
                        rd = reg_dirs_by_depth[depth]
                        if rd:
                            top3_sum = sum(c for _, c in rd.most_common(3))
                            total = sum(rd.values())
                            if top3_sum / max(total, 1) >= 0.7 and depth < best_depth:
                                best_depth = depth

                    reg_dirs = reg_dirs_by_depth[best_depth]
                    if reg_dirs:
                        p(f"    Regression-prone areas (depth-{best_depth} dirs, cumulative file risk):")
                        for d, c in reg_dirs.most_common(5):
                            in_wins = sum(1 for f in win_files if f.startswith(d + "/") or f == d)
                            n_files = sum(1 for f in reg_files if f.startswith(d + "/") or f == d)
                            tag = f" (also in wins)" if in_wins else " ⚠ NEVER in wins"
                            p(f"      {d}: {c} regressions across {n_files} files{tag}")
                if danger_files:
                    p(f"    ⚠ Files modified ONLY in regressions (never in wins):")
                    for f, c in sorted(danger_files.items(), key=lambda x: -x[1])[:5]:
                        p(f"      {f}: {c}x")
                p("")

        explore_only_tasks = [t for t in losses if t.no_patch_stage == "explore_only"]
        if explore_only_tasks:
            p("  EXPLORE-ONLY DEEP ANALYSIS:")
            sc = Counter(t.explore_only_subtype for t in explore_only_tasks)
            for sub, cnt in sc.most_common():
                p(f"    {sub:<22} {cnt:>3} ({cnt / len(explore_only_tasks) * 100:>4.0f}%) {_explore_subtype_description(sub)}")
            p("")

            # Turn-of-claim analysis for identified_no_action tasks
            id_na_tasks = [t for t in explore_only_tasks if t.explore_only_subtype == "identified_no_action"]
            if id_na_tasks:
                early_claim = [t for t in id_na_tasks if t.claim_position is not None and t.claim_position < 0.5]
                late_claim = [t for t in id_na_tasks if t.claim_position is not None and t.claim_position >= 0.5]
                no_claim = [t for t in id_na_tasks if t.claim_position is None]

                p("    IDENTIFIED-NO-ACTION DETAIL (turn-of-claim):")
                if early_claim:
                    p(f"      Early diagnosis (claim <50% into conv): {len(early_claim)} tasks — diagnosed but had budget to act")
                    for t in early_claim:
                        remaining = t.total_assistant_turns - t.claim_turn - 1
                        p(f"        task={t.task_id}: claim at turn {t.claim_turn + 1}/{t.total_assistant_turns} "
                          f"({t.claim_position:.0%}), {remaining} turns unused after diagnosis")
                if late_claim:
                    p(f"      Late diagnosis (claim >=50% into conv): {len(late_claim)} tasks — diagnosed too late to act")
                    for t in late_claim:
                        remaining = t.total_assistant_turns - t.claim_turn - 1
                        p(f"        task={t.task_id}: claim at turn {t.claim_turn + 1}/{t.total_assistant_turns} "
                          f"({t.claim_position:.0%}), {remaining} turns left")
                if early_claim and late_claim:
                    p(f"      SFT implication: {len(early_claim)} early-claim tasks need AGENCY training "
                      f"(model knows what to fix but won't act), "
                      f"{len(late_claim)} late-claim tasks need EFFICIENCY training (find bug faster)")
                elif early_claim:
                    p(f"      SFT implication: all {len(early_claim)} are early-claim — AGENCY is the bottleneck, not localization")
                p("")

            # False completion analysis
            fc_tasks = [t for t in explore_only_tasks if t.explore_only_subtype == "false_completion"]
            if fc_tasks:
                p("    FALSE-COMPLETION DETAIL:")
                p(f"      {len(fc_tasks)} tasks where model ran echo/printf declaring 'completed' without actual code edits")
                for t in fc_tasks:
                    p(f"      task={t.task_id} project={t.project} bug_types={','.join(t.bug_types[:3])}")
                    for cmd in t.false_completion_cmds[:3]:
                        p(f"        cmd: {cmd[:120]}")
                    # Show claim info if available
                    if t.claim_position is not None:
                        p(f"        claim@{t.claim_position:.0%} — model also claimed to have found the bug")
                p(f"      SFT implication: model has learned to simulate task completion instead of solving — "
                  f"needs training on distinguishing DECLARATION from ACTION")
                p("")

            p("    Sample explore_only tasks:")
            for t in explore_only_tasks[:3]:
                last_msg = ""
                for msg in reversed(t.conversation):
                    if msg.get("role") == "assistant":
                        raw = str(msg.get("content", ""))
                        # Strip ```bash blocks and ``` markers to prevent markdown leaking into report
                        raw = re.sub(r'```\w*', '', raw)  # strip ```bash, ```python, etc.
                        raw = raw.replace('```', '')       # strip closing ```
                        # Replace newlines with spaces for single-line display
                        raw = raw.replace('\n', ' ').replace('\r', ' ')
                        # Collapse multiple spaces
                        raw = re.sub(r'  +', ' ', raw).strip()
                        last_msg = raw[:120]
                        break
                claim_info = ""
                if t.claim_position is not None:
                    claim_info = f" claim@{t.claim_position:.0%}"
                p(f"      task={t.task_id} project={t.project} subtype={t.explore_only_subtype}{claim_info}")
                if last_msg:
                    p(f"        last msg: {last_msg}")
            p("")

        id_conf = [t for t in losses if t.no_patch_stage == "identity_confusion"]
        if id_conf:
            p("  IDENTITY CONFUSION DETAIL:")
            for t in id_conf:
                p(f"    task={t.task_id} project={t.project}")
                for msg in t.conversation:
                    if msg.get("role") == "assistant":
                        content = str(msg.get("content", "")).lower()
                        for pattern in _IDENTITY_PATTERNS:
                            if pattern in content:
                                p(f"      matched: \"{str(msg.get('content', ''))[:150]}\"")
                                break
                        break
            p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 6: NEAR-WIN ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    section("NEAR-WIN ANALYSIS")
    # near_wins already computed at top of generate_report
    p(f"  Near-wins (>=80% all tests passing but still losing): {len(near_wins)}/{loss_count} losses")
    p("")
    if near_wins:
        # Classify proximity
        target_close = []
        target_far = []
        for t in near_wins:
            if t.target_total and t.target_total > 0 and t.target_passed_count / t.target_total > 0.5:
                target_close.append(t)
            else:
                target_far.append(t)

        # Single consolidated table with proximity tag
        high_nw_count = sum(1 for t in near_wins if t.all_total > 0 and t.all_passed_count / t.all_total >= 0.95)
        p(f"  {len(near_wins)} near-wins | {high_nw_count} high-confidence (>=95%) | {len(target_close)} target-close | {len(target_far)} target-far")
        p("")
        p(f"  {'task':>7} {'project':<30} {'target':>8} {'all':>10} {'pass%':>6} {'prox':<7} {'align':<8} {'bug_types'}")
        p("  " + chr(9472) * 100)
        for t in sorted(near_wins, key=lambda x: -x.all_passed_count / max(x.all_total, 1)):
            pp = t.all_passed_count / t.all_total * 100
            prox = "CLOSE" if t in target_close else "far"
            align = t.patch_target_alignment if t.patch_target_alignment != "no_data" else "-"
            bts = ",".join(t.bug_types[:3]) if t.bug_types else "-"
            if len(bts) > 25:
                bts = bts[:24] + chr(8230)
            p(f"  {t.task_id:>7} {t.project[:30]:<30} {t.target_result_str:>8} {t.all_result_str:>10} {pp:>5.0f}% {prox:<7} {align:<8} {bts}")
        p("")

        if target_close:
            p(f"  SFT priority: {len(target_close)} target-close tasks (patch nearly correct, minor fix needed)")
        if target_far and not target_close:
            zero_target = sum(1 for t in target_far if t.target_passed_count == 0)
            if zero_target == len(target_far):
                p(f"  Note: all {len(target_far)} near-wins are target-far (0% target pass) — 'wrong fix' pattern, not 'almost right'")
            else:
                p(f"  Note: all {len(target_far)} near-wins are target-far (<=50% target pass) — most are 'wrong fix' pattern, not 'almost right'")
        p("")

        nwp = Counter(t.project for t in near_wins)
        if len(nwp) > 1:
            p("  Near-win by project:")
            for proj, cnt in nwp.most_common():
                ptot = len([t for t in losses if t.project == proj])
                p(f"    {proj:<35}: {cnt}/{ptot} losses are near-wins")
            p("")
    else:
        p("  No near-wins found.")
        p("")

    anomalies = []
    for t in parsed:
        if t.is_win and t.target_total and t.target_total > 0:
            tpr = t.target_passed_count / t.target_total
            if tpr < 0.5:  # WIN but <50% target tests passed
                anomalies.append(t)
        elif not t.is_win and t.target_passed and t.all_passed:
            anomalies.append(t)
    if anomalies:
        p("  SCORING ANOMALIES:")
        for t in anomalies:
            tpr = t.target_passed_count / t.target_total * 100 if t.target_total else 0
            p(f"    task={t.task_id}: score={t.score}, target={t.target_result_str} ({tpr:.0f}%), all={t.all_result_str}, project={t.project}")
            if t.is_win:
                p("      -> WIN despite low target pass rate — env scores on ALL tests passing, not target tests")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 7: CONVERSATION ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    section("CONVERSATION ANALYSIS")
    wt = [t._conv_stats["assistant_turns"] for t in wins if t._conv_stats["assistant_turns"] > 0]
    lt = [t._conv_stats["assistant_turns"] for t in losses if t._conv_stats["assistant_turns"] > 0]
    p("  Average assistant turns:")
    if wt: p(f"    Wins:   {_safe_mean(wt):.1f} (median {_safe_median(wt):.0f})")
    if lt: p(f"    Losses: {_safe_mean(lt):.1f} (median {_safe_median(lt):.0f})")
    p("")

    wtk = [t.total_tokens for t in wins if t.total_tokens > 0]
    ltk = [t.total_tokens for t in losses if t.total_tokens > 0]
    p("  Token usage:")
    if wtk: p(f"    Wins:   avg={_safe_mean(wtk):.0f}, median={_safe_median(wtk):.0f}")
    if ltk: p(f"    Losses: avg={_safe_mean(ltk):.0f}, median={_safe_median(ltk):.0f}")
    atk = [t.total_tokens for t in parsed if t.total_tokens > 0]
    if atk: p(f"    All:    avg={_safe_mean(atk):.0f}, median={_safe_median(atk):.0f}, min={min(atk)}, max={max(atk)}")
    p("")

    wmc = [t.model_calls for t in wins if t.model_calls > 0]
    lmc = [t.model_calls for t in losses if t.model_calls > 0]
    p("  Model calls:")
    if wmc: p(f"    Wins:   avg={_safe_mean(wmc):.1f}")
    if lmc: p(f"    Losses: avg={_safe_mean(lmc):.1f}")
    p("")

    loop_tasks = [t for t in parsed if t.has_loop]
    wl = [t for t in wins if t.has_loop]
    ll = [t for t in losses if t.has_loop]
    p("  Loop detection (n-gram Jaccard >=50%):")
    p(f"    Total:  {len(loop_tasks)}/{n} ({len(loop_tasks) / n * 100:.0f}%)")
    if wins: p(f"    Wins:   {len(wl)}/{win_count} ({len(wl) / win_count * 100:.0f}%)")
    if losses: p(f"    Losses: {len(ll)}/{loss_count} ({len(ll) / loss_count * 100:.0f}%)")
    p("")

    we = [t.explore_before_edit_ratio for t in wins if t._conv_stats["assistant_turns"] > 0]
    le = [t.explore_before_edit_ratio for t in losses if t._conv_stats["assistant_turns"] > 0]
    p("  Explore-before-edit ratio (read+search / total assistant turns):")
    if we: p(f"    Wins:   {_safe_mean(we):.2f}")
    if le: p(f"    Losses: {_safe_mean(le):.2f}")
    if we and le:
        diff = _safe_mean(le) - _safe_mean(we)
        if diff > 0.1:
            p(f"    -> Losses spend {diff:.0%} more time exploring before editing")
    p("")

    wtst = [t._conv_stats["test_commands"] for t in wins]
    ltst = [t._conv_stats["test_commands"] for t in losses]
    p("  Test command usage:")
    if wtst: p(f"    Wins:   avg={_safe_mean(wtst):.1f} test commands per task")
    if ltst: p(f"    Losses: avg={_safe_mean(ltst):.1f} test commands per task")
    ztw = sum(1 for v in wtst if v == 0)
    if win_count > 0:
        test_free_pct = ztw / max(win_count, 1)
        p(f"    Test-free wins: {ztw}/{win_count} ({test_free_pct * 100:.0f}%)")
        if test_free_pct >= 0.8:
            p("    -> Model predominantly wins by pattern matching without testing")
        elif test_free_pct <= 0.5 and _safe_mean(wtst) > _safe_mean(ltst) * 2:
            p(f"    -> Testing is key differentiator: winners avg {_safe_mean(wtst):.1f} tests vs losers {_safe_mean(ltst):.1f}")
        elif test_free_pct >= 0.5:
            p("    -> Mixed: some wins use testing, most rely on pattern matching")
    p("")

    wedt = [t._conv_stats["edit_commands"] for t in wins]
    ledt = [t._conv_stats["edit_commands"] for t in losses]
    p("  Edit command usage:")
    if wedt: p(f"    Wins:   avg={_safe_mean(wedt):.1f}")
    if ledt: p(f"    Losses: avg={_safe_mean(ledt):.1f}")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 8: TEMPORAL TREND ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    timestamped = [t for t in parsed if t.timestamp > 0]
    if len(timestamped) >= 6:
        section("TEMPORAL TREND ANALYSIS")
        timestamped.sort(key=lambda x: x.timestamp)

        # Split into batches (min 3 per batch, aim for 3-5 batches)
        batch_count = min(5, max(2, len(timestamped) // 5))
        batch_size = len(timestamped) // batch_count
        batches = []
        for i in range(batch_count):
            start = i * batch_size
            end = start + batch_size if i < batch_count - 1 else len(timestamped)
            batch = timestamped[start:end]
            if batch:
                batches.append(batch)

        import datetime
        p("  Win rate over time (chronological batches):")
        p(f"  {'Batch':<8} {'Period':<25} {'Count':>5} {'Win%':>6} {'Patch%':>7} {'AvgTurns':>9} {'NearWin':>8}")
        p("  " + chr(9472) * 72)

        # Decide time format: if all same day, show HH:MM; otherwise show MM-DD
        first_day = datetime.datetime.fromtimestamp(timestamped[0].timestamp).strftime("%Y-%m-%d")
        last_day = datetime.datetime.fromtimestamp(timestamped[-1].timestamp).strftime("%Y-%m-%d")
        same_day = first_day == last_day
        time_fmt = "%H:%M" if same_day else "%m-%d %H:%M"

        batch_wrs = []
        for idx, batch in enumerate(batches):
            bw = sum(1 for t in batch if t.is_win)
            bn = len(batch)
            bwr = bw / bn * 100
            batch_wrs.append(bwr)
            bp = sum(1 for t in batch if t.has_patch) / bn * 100
            bat = _safe_mean([t._conv_stats["assistant_turns"] for t in batch if t._conv_stats["assistant_turns"] > 0])
            bnw = sum(1 for t in batch if not t.is_win and t.all_total > 0 and t.all_passed_count / t.all_total >= _NEAR_WIN_THRESHOLD)
            ts_start = datetime.datetime.fromtimestamp(batch[0].timestamp).strftime(time_fmt)
            ts_end = datetime.datetime.fromtimestamp(batch[-1].timestamp).strftime(time_fmt)
            period = f"{ts_start} to {ts_end}"
            p(f"  {idx + 1:<8} {period:<25} {bn:>5} {bwr:>5.1f}% {bp:>6.0f}% {bat:>9.1f} {bnw:>8}")

        # Trend detection
        if len(batch_wrs) >= 3:
            first_half = _safe_mean(batch_wrs[:len(batch_wrs) // 2])
            second_half = _safe_mean(batch_wrs[len(batch_wrs) // 2:])
            delta = second_half - first_half
            p("")
            if abs(delta) < 5:
                p(f"  Trend: STABLE (delta={delta:+.1f}pp between halves)")
            elif delta > 0:
                p(f"  Trend: IMPROVING (delta={delta:+.1f}pp, {first_half:.0f}%→{second_half:.0f}%)")
            else:
                p(f"  Trend: DEGRADING (delta={delta:+.1f}pp, {first_half:.0f}%→{second_half:.0f}%)")

            # Overfitting signal: win rate spike then decline
            if len(batch_wrs) >= 4:
                peak_idx = batch_wrs.index(max(batch_wrs))
                if 0 < peak_idx < len(batch_wrs) - 1:
                    post_peak = _safe_mean(batch_wrs[peak_idx + 1:])
                    if max(batch_wrs) - post_peak > 20:
                        p(f"  ⚠ OVERFITTING SIGNAL: peak {max(batch_wrs):.0f}% at batch {peak_idx + 1}, "
                          f"then decline to {post_peak:.0f}%")

            # Late collapse: last batch 0% but some earlier batch >=30%
            if batch_wrs[-1] == 0:
                peak_earlier = max(batch_wrs[:-1])
                if peak_earlier >= 30:
                    peak_batch_idx = batch_wrs[:-1].index(peak_earlier)
                    p(f"  ⚠ LATE COLLAPSE: last batch 0% win rate, but batch {peak_batch_idx + 1} "
                      f"was {peak_earlier:.0f}% — sudden end-of-window degradation")

            # Monotonic check for memorization
            strictly_improving = all(batch_wrs[i] <= batch_wrs[i + 1] for i in range(len(batch_wrs) - 1))
            if strictly_improving and batch_wrs[-1] > batch_wrs[0] + 20:
                p(f"  Note: monotonically improving ({batch_wrs[0]:.0f}%→{batch_wrs[-1]:.0f}%) — "
                  "could indicate progressive memorization if task pool is small")

        # Per-project temporal trend (only for projects with >=5 tasks)
        proj_ts = defaultdict(list)
        for t in timestamped:
            proj_ts[t.project].append(t)
        big_projs = {p: ts for p, ts in proj_ts.items() if len(ts) >= 5}
        if big_projs:
            p("")
            p("  Per-project trends:")
            for proj in sorted(big_projs.keys()):
                pts = big_projs[proj]
                pts.sort(key=lambda x: x.timestamp)
                half = len(pts) // 2
                first_wr = sum(1 for t in pts[:half] if t.is_win) / half * 100
                second_wr = sum(1 for t in pts[half:] if t.is_win) / len(pts[half:]) * 100
                d = second_wr - first_wr
                tag = ""
                if abs(d) > 15:
                    tag = " ↑" if d > 0 else " ↓"
                p(f"    {proj[:35]:<35}: {first_wr:.0f}% → {second_wr:.0f}% ({d:+.0f}pp){tag}")

        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 9: PATCH ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    section("PATCH ANALYSIS")
    all_patched = [t for t in parsed if t.has_patch]
    p(f"  Patch submission rate: {len(all_patched)}/{n} ({len(all_patched) / n * 100:.0f}%)")
    if wins:
        wp = [t for t in wins if t.has_patch]
        p(f"    Wins with patch:   {len(wp)}/{win_count} ({len(wp) / win_count * 100:.0f}%)")
    if losses:
        p(f"    Losses with patch: {len(patched_losses)}/{loss_count} ({len(patched_losses) / loss_count * 100:.0f}%)")
    p("")

    wps = [t.patch_lines for t in wins if t.has_patch]
    lps = [t.patch_lines for t in losses if t.has_patch]
    p("  Patch size (added + removed lines):")
    if wps: p(f"    Wins:   avg={_safe_mean(wps):.1f}, median={_safe_median(wps):.0f}, max={max(wps)}")
    if lps: p(f"    Losses: avg={_safe_mean(lps):.1f}, median={_safe_median(lps):.0f}, max={max(lps)}")
    p("")

    wfc = [len(t.patch_files) for t in wins if t.has_patch]
    lfc = [len(t.patch_files) for t in losses if t.has_patch]
    p("  Files modified per patch:")
    if wfc: p(f"    Wins:   avg={_safe_mean(wfc):.1f}")
    if lfc: p(f"    Losses: avg={_safe_mean(lfc):.1f}")
    p("")

    p("  PATCH SEMANTIC ANALYSIS:")
    pcg = defaultdict(list)
    for t in all_patched:
        pcg[t.patch_class].append(t)
    p(f"  {'Category':<15} {'Count':>5} {'Win%':>6} {'Avg lines':>10}")
    p("  " + chr(9472) * 40)
    for cls in sorted(pcg.keys()):
        tasks = pcg[cls]
        cwr = sum(1 for t in tasks if t.is_win) / len(tasks) * 100
        cl = _safe_mean([t.patch_lines for t in tasks])
        p(f"  {cls:<15} {len(tasks):>5} {cwr:>5.1f}% {cl:>10.1f}")
    p("")

    brute = [t for t in all_patched if t.patch_class == "brute_force"]
    if brute:
        p("  BRUTE FORCE PATCHES (>200 lines):")
        for t in sorted(brute, key=lambda x: -x.patch_lines):
            r = "WIN" if t.is_win else "LOSS"
            p(f"    task={t.task_id}: {t.patch_lines} lines, {r}, target={t.target_result_str}, project={t.project}")
        p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 9: ENVIRONMENT OPTIMIZATION SUGGESTIONS
    # ═══════════════════════════════════════════════════════════════════════
    section("ENVIRONMENT OPTIMIZATION SUGGESTIONS")
    opts = []

    for lang in sorted(lang_groups.keys()):
        tasks = lang_groups[lang]
        if len(tasks) >= 3 and sum(1 for t in tasks if t.is_win) == 0:
            projs = sorted(set(t.project for t in tasks))
            p(f"  [OPT-1] LANGUAGE GAP: {lang} at 0% win rate ({len(tasks)} tasks)")
            p(f"    Projects: {', '.join(projs)}")
            p("    Suggestion: investigate language-specific tooling requirements")
            p("")
            opts.append(f"OPT-1: {lang} language gap")

    for proj, tasks in project_groups.items():
        if len(tasks) >= 5 and sum(1 for t in tasks if t.is_win) == 0:
            pbt = Counter(bt for t in tasks for bt in t.bug_types)
            p(f"  [OPT-2] PROJECT DIFFICULTY: {proj} at 0% win rate ({len(tasks)} tasks)")
            if pbt:
                p(f"    Top bug types: {', '.join(f'{bt}({c})' for bt, c in pbt.most_common(3))}")
            p("    Suggestion: review project-specific build/test requirements")
            p("")
            opts.append(f"OPT-2: {proj} 0% win rate")

    if losses and len(unpatched_losses) / loss_count > 0.5:
        p(f"  [OPT-3] HIGH NO-PATCH RATE: {len(unpatched_losses)}/{loss_count} losses ({len(unpatched_losses) / loss_count * 100:.0f}%) had no patch")
        p("    Suggestion: encourage always submitting a patch; increase max_iterations")
        p("")
        opts.append("OPT-3: high no-patch rate")

    if near_wins and losses and len(near_wins) / loss_count >= 0.2:
        p(f"  [OPT-4] NEAR-WIN OPPORTUNITY: {len(near_wins)}/{loss_count} losses ({len(near_wins) / loss_count * 100:.0f}%) are near-wins")
        p("    Note: env scores on ALL tests passing (not just target tests)")
        p("    Near-wins pass >=80% of all_required tests but fail on remaining few")
        p("    Suggestion: consider partial credit scoring; investigate why remaining tests fail")
        p("")
        opts.append("OPT-4: near-win conversion opportunity")

    if win_count > 0 and ztw / max(win_count, 1) >= 0.8:
        p(f"  [OPT-5] TEST-FREE WINS: {ztw}/{win_count} wins ({ztw / win_count * 100:.0f}%) used no test commands")
        p("    Suggestion: encourage test-before-submit workflow in system prompt")
        p("")
        opts.append("OPT-5: test-free wins pattern")

    if losses and len(ll) / loss_count > 0.3:
        p(f"  [OPT-6] HIGH LOOP RATE: {len(ll)}/{loss_count} losses ({len(ll) / loss_count * 100:.0f}%) detected as loops")
        p("    Suggestion: implement loop detection in agent harness, auto-pivot strategy")
        p("")
        opts.append("OPT-6: high loop rate")

    id_conf = [t for t in losses if t.no_patch_stage == "identity_confusion"]
    if id_conf:
        p(f"  [OPT-7] IDENTITY CONFUSION: {len(id_conf)} tasks where model thinks it cannot execute commands")
        p("    Suggestion: strengthen system prompt; clarify full shell/filesystem access")
        p("")
        opts.append("OPT-7: identity confusion")

    env_bl = [t for t in losses if t.no_patch_stage == "env_blocked"]
    if len(env_bl) >= 2:
        projs = Counter(t.project for t in env_bl)
        proj_str = ", ".join(f"{p}({c})" for p, c in projs.most_common(3))
        p(f"  [OPT-8] ENV BLOCKED: {len(env_bl)} tasks blocked by environment issues")
        p(f"    Projects: {proj_str}")
        p("    Suggestion: verify project build/test setup works; check for missing dependencies")
        p("")
        opts.append("OPT-8: environment setup issues")

    # Test suite size analysis
    tasks_with_tests = [t for t in parsed if t.all_total > 0]
    if len(tasks_with_tests) >= 10:
        size_buckets = [
            ("tiny(1-10)", lambda t: t.all_total <= 10),
            ("small(11-50)", lambda t: 11 <= t.all_total <= 50),
            ("medium(51-200)", lambda t: 51 <= t.all_total <= 200),
            ("large(201+)", lambda t: t.all_total > 200),
        ]
        has_multiple = sum(1 for name, fn in size_buckets if sum(1 for t in tasks_with_tests if fn(t)) >= 2) >= 2
        if has_multiple:
            p("  TEST SUITE SIZE vs WIN RATE:")
            p(f"  {'Size':<16} {'Count':>6} {'Win%':>6} {'NearWin%':>9} {'AvgTests':>9}")
            p("  " + chr(9472) * 50)
            for name, fn in size_buckets:
                bucket = [t for t in tasks_with_tests if fn(t)]
                if len(bucket) < 2:
                    continue
                bn = len(bucket)
                bw = sum(1 for t in bucket if t.is_win)
                bwr = bw / bn * 100
                bl = [t for t in bucket if not t.is_win]
                bnw = sum(1 for t in bl if t.all_total > 0 and t.all_passed_count / t.all_total >= _NEAR_WIN_THRESHOLD) if bl else 0
                bnw_pct = bnw / len(bl) * 100 if bl else 0
                avg_total = _safe_mean([t.all_total for t in bucket])
                p(f"  {name:<16} {bn:>6} {bwr:>5.1f}% {bnw_pct:>8.1f}% {avg_total:>9.0f}")

            # Statistical insight
            win_totals = [t.all_total for t in tasks_with_tests if t.is_win]
            loss_totals = [t.all_total for t in tasks_with_tests if not t.is_win]
            if win_totals and loss_totals:
                p(f"  Wins avg suite size:   {_safe_mean(win_totals):>6.0f} tests (median {_safe_median(win_totals):.0f})")
                p(f"  Losses avg suite size: {_safe_mean(loss_totals):>6.0f} tests (median {_safe_median(loss_totals):.0f})")
                ratio = _safe_mean(loss_totals) / max(_safe_mean(win_totals), 1)
                if ratio >= 1.3:
                    p(f"  ⚠ Losses have {ratio:.1f}x larger test suites — larger suites are harder to satisfy")
            p("")

    # Scoring mechanism analysis
    tp_mr = [t for t in losses if t.failure_category == "target_pass+minor_regress"]
    if tp_mr:
        p(f"  [OPT-9] SCORING GAP: {len(tp_mr)} tasks fixed target bug but scored 0.0 due to minor regressions")
        p("    Env requires ALL tests to pass (f2p ∪ p2p). Target tests are informational only.")
        for t in tp_mr[:3]:
            broken = t.all_total - t.all_passed_count
            p(f"      task={t.task_id}: target {t.target_result_str} OK, {broken} non-target tests broken")
        p("    These are highest-value SFT candidates — model solved the bug but needs regression awareness")
        p("")
        opts.append("OPT-9: target-fixed-but-regression scoring gap")

    # Alignment-based insight
    aligned_losses = [t for t in losses if t.patch_target_alignment != "no_data"]
    if aligned_losses:
        mismatch_cnt = sum(1 for t in aligned_losses if t.patch_target_alignment == "mismatch")
        mismatch_pct = mismatch_cnt / len(aligned_losses) * 100
        if mismatch_pct >= 40:
            p(f"  [OPT-10] LOCALIZATION GAP: {mismatch_cnt}/{len(aligned_losses)} ({mismatch_pct:.0f}%) patched losses modify the wrong file entirely")
            p("    The problem_statement may not provide sufficient localization hints")
            p("    Suggestion: include file path hints or narrow the problem scope in task generation")
            p("")
            opts.append("OPT-10: patch-target localization gap")

    if opts:
        p(f"  Summary: {len(opts)} recommendations")
        for opt in opts:
            p(f"    - {opt}")
    else:
        p("  No significant optimization recommendations at current data level.")
    p("")

    # ═══════════════════════════════════════════════════════════════════════
    # Section 10: SFT STRATEGY
    # ═══════════════════════════════════════════════════════════════════════
    section("SFT STRATEGY")
    p("  TRAINING DATA CANDIDATES:")
    p("")

    clean_wins = [t for t in wins if t.patch_class == "functional" and t.patch_lines > 0]

    # Memorization/contamination flagging
    # Criteria: trivial patch + perfect results + very fast edit (low explore-before-edit)
    # A model that barely reads code before producing the exact fix may have memorized it
    suspicious_wins = []
    genuine_wins = []
    for t in clean_wins:
        edit_ratio = t.explore_before_edit_ratio
        test_cmds = t._conv_stats.get("test_commands", 0)
        is_suspicious = (
            t.patch_lines <= 3
            and t.all_total and t.all_total > 10
            and t.all_passed_count == t.all_total
            and edit_ratio < 0.15  # edits within first 15% of conversation
            and test_cmds == 0     # never tested — pure pattern match
        )
        if is_suspicious:
            suspicious_wins.append(t)
        else:
            genuine_wins.append(t)

    p(f"  1. CLEAN WINS (functional patches): {len(clean_wins)}")
    if suspicious_wins:
        p(f"     ⚠ {len(suspicious_wins)} wins flagged as POTENTIAL MEMORIZATION:")
        p(f"       (<=3 lines, 100% tests, edit <15% into conv, no testing)")
        for t in suspicious_wins:
            bugs = ",".join(t.bug_types[:2]) if t.bug_types else "-"
            pct = f"{t.explore_before_edit_ratio:.0%}" if t.explore_before_edit_ratio else "0%"
            p(f"       task={t.task_id}: {t.patch_lines} lines, edit@{pct}, project={t.project}, bugs={bugs}")
    if genuine_wins:
        p(f"     {len(genuine_wins)} genuine wins (recommended for SFT):")
        for t in sorted(genuine_wins, key=lambda x: -x.patch_lines)[:5]:
            bugs = ",".join(t.bug_types[:2]) if t.bug_types else "-"
            p(f"       task={t.task_id}: {t.patch_lines} lines, project={t.project}, bugs={bugs}")
    p("")

    p(f"  2. NEAR-WINS (for learning from mistakes): {len(near_wins)}")
    # Split near-wins by target proximity for differentiated SFT advice
    nw_close = [t for t in near_wins if t.target_total and t.target_total > 0 and t.target_passed_count / t.target_total > 0.5]
    nw_far = [t for t in near_wins if t not in nw_close]
    if near_wins:
        if nw_close:
            p(f"     Target-close ({len(nw_close)}): patch nearly correct, synthesize minor corrections")
            for t in sorted(nw_close, key=lambda x: -x.target_passed_count / max(x.target_total, 1))[:3]:
                tpr = t.target_passed_count / t.target_total * 100
                p(f"       task={t.task_id}: target {t.target_result_str} ({tpr:.0f}%), all {t.all_result_str}")
        if nw_far:
            p(f"     Target-far ({len(nw_far)}): wrong fix direction, synthesize problem re-analysis trajectories")
            for t in sorted(nw_far, key=lambda x: -x.all_passed_count / max(x.all_total, 1))[:3]:
                pp = t.all_passed_count / t.all_total * 100
                p(f"       task={t.task_id}: {pp:.0f}% all pass but target={t.target_result_str}")
    p("")

    tp_minor_regress = [t for t in losses if t.failure_category == "target_pass+minor_regress"]
    if tp_minor_regress:
        p(f"  3. TARGET-PASS + MINOR-REGRESS (highest SFT correction value): {len(tp_minor_regress)}")
        p("     Target bug FIXED but minor non-target regressions. Teach model to run full test suite.")
        for t in sorted(tp_minor_regress, key=lambda x: -x.all_passed_count / max(x.all_total, 1))[:5]:
            apr = t.all_passed_count / t.all_total * 100 if t.all_total else 0
            broken = t.all_total - t.all_passed_count
            bugs = ",".join(t.bug_types[:2]) if t.bug_types else "-"
            p(f"       task={t.task_id}: target {t.target_result_str} OK, all {t.all_result_str} ({apr:.0f}%), {broken} broken, bugs={bugs}")
    p("")

    explore_only_tasks = [t for t in losses if t.no_patch_stage == "explore_only"]
    if explore_only_tasks:
        eo_num = 4 if tp_minor_regress else 3
        p(f"  {eo_num}. EXPLORE-ONLY FAILURES (negative examples): {len(explore_only_tasks)}")
        p("     Teach model to start editing sooner rather than endlessly reading code.")
    p("")

    p("  IMPROVEMENT PRIORITY RANKING:")
    priorities = []
    if tp_minor_regress:
        priorities.append(("Fix side effects (target_pass+minor_regress)", len(tp_minor_regress),
                           f"{len(tp_minor_regress)} tasks fixed target but broke other tests — teach full test suite execution"))
    if near_wins:
        priorities.append(("Near-win conversion", len(near_wins), f"{len(near_wins)} tasks close to winning"))
    if explore_only_tasks and len(explore_only_tasks) >= 2:
        priorities.append(("Reduce explore_only", len(explore_only_tasks), f"{len(explore_only_tasks)} tasks stuck reading code"))
    if unpatched_losses and len(unpatched_losses) >= 2:
        priorities.append(("Increase patch rate", len(unpatched_losses), f"{len(unpatched_losses)} losses without patch"))
    if ll and len(ll) >= 2:
        priorities.append(("Break loops", len(ll), f"{len(ll)} losses in loops"))
    if id_conf and len(id_conf) >= 2:
        priorities.append(("Fix identity confusion", len(id_conf), f"{len(id_conf)} tasks with identity confusion"))
    priorities.sort(key=lambda x: -x[1])
    for i, (name, count, desc) in enumerate(priorities, 1):
        p(f"    {i}. {name} ({count} tasks): {desc}")
    if not priorities:
        p("    No specific priorities identified.")
    p("")

    p("  SFT DATA SYNTHESIS SUGGESTIONS:")
    if genuine_wins:
        p(f"    Positive examples: {len(genuine_wins)} verified genuine wins")
        p(f"      avg conversation length: {_safe_mean([len(t.conversation) for t in genuine_wins]):.0f} turns")
        p(f"      avg patch size: {_safe_mean([t.patch_lines for t in genuine_wins]):.0f} lines")
        p("      Use these conversations for SFT fine-tuning")
    if suspicious_wins:
        p(f"    ⚠ Excluded: {len(suspicious_wins)} potential memorization wins — verify before including")
    if tp_minor_regress:
        p(f"    ★ Side-effect correction: {len(tp_minor_regress)} target_pass+minor_regress losses")
        p("      HIGHEST SFT correction value — target bug fixed, just needs to learn avoiding side effects")
        p("      Synthesize trajectories that run full test suite before submitting")
    if nw_close:
        p(f"    Corrected examples: {len(nw_close)} target-close near-wins")
        p("      Synthesize corrected trajectories with minor patch adjustments")
    if nw_far:
        p(f"    Re-analysis examples: {len(nw_far)} target-far near-wins")
        p("      Synthesize trajectories that re-read the problem statement and try a different fix direction")
    if explore_only_tasks:
        p(f"    Guided examples: {len(explore_only_tasks)} explore-only failures")
        p("      Create synthetic trajectories that move from reading to editing faster")
    p("")

    # Bug-type × failure-stage targeted SFT recommendations
    if losses:
        bt_stage = defaultdict(lambda: defaultdict(int))
        bt_total = defaultdict(int)
        for t in losses:
            stage = t.failure_label
            for b in t.bug_types:
                bt_stage[b][stage] += 1
                bt_total[b] += 1

        # Also count wins per bug type (for absolute-count trigger)
        bt_wins = defaultdict(int)
        bt_all = defaultdict(int)
        for t in parsed:
            for b in t.bug_types:
                bt_all[b] += 1
                if t.is_win:
                    bt_wins[b] += 1

        # Find bug types with disproportionate concentration in one stage
        targeted_recs = []
        concentrated_bts = set()  # track bug types already covered by concentration trigger
        for bt, stages in bt_stage.items():
            if bt_total[bt] < 3:
                continue
            for stage, cnt in stages.items():
                ratio = cnt / bt_total[bt]
                if ratio >= 0.6 and cnt >= 3:
                    targeted_recs.append((bt, stage, cnt, bt_total[bt], ratio))
                    concentrated_bts.add(bt)

        # Absolute-count trigger: >=5 losses AND <=20% win rate, spread across stages
        systemic_recs = []
        for bt in bt_total:
            if bt in concentrated_bts:
                continue  # already covered by concentration trigger
            loss_count_bt = bt_total[bt]
            total_bt = bt_all.get(bt, loss_count_bt)
            win_rate_bt = bt_wins.get(bt, 0) / total_bt if total_bt > 0 else 0
            if loss_count_bt >= 5 and win_rate_bt <= 0.20:
                # Collect per-stage breakdown for display
                stage_breakdown = sorted(bt_stage[bt].items(), key=lambda x: -x[1])
                systemic_recs.append((bt, loss_count_bt, total_bt, win_rate_bt, stage_breakdown))

        has_any_recs = bool(targeted_recs) or bool(systemic_recs)
        if has_any_recs:
            p("  BUG-SPECIFIC SFT RECOMMENDATIONS:")
            stage_advice = {
                "edit_no_test": "synthesize trajectories that always run tests after editing",
                "explore_only": "provide file-scope hints or narrower problem descriptions",
                "edit_churn": "teach model to stop and test after 2-3 edit attempts",
                "identity_confusion": "strengthen system prompt about shell access",
                "env_blocked": "provide project-specific setup instructions",
                "target_fail_only": "include target test names in problem statement",
                "target+regress": "synthesize cautious edit patterns that preserve existing tests",
                "target_pass+minor_regress": "synthesize trajectories that run full test suite to catch side effects",
                "partial_progress": "include target test names and encourage re-reading problem statement",
                "fix_test_loop": "teach strategic backtracking when tests keep failing",
            }

            if targeted_recs:
                targeted_recs.sort(key=lambda x: (-x[4], -x[2]))  # sort by ratio then count
                # Group by stage to avoid repetitive advice
                stage_groups = defaultdict(list)
                for bt, stage, cnt, total, ratio in targeted_recs:
                    stage_groups[stage].append((bt, cnt, total, ratio))
                for stage in sorted(stage_groups, key=lambda s: -sum(c for _, c, _, _ in stage_groups[s])):
                    items = stage_groups[stage]
                    advice = stage_advice.get(stage, "investigate root cause")
                    total_affected = sum(c for _, c, _, _ in items)
                    bt_list = ", ".join(f"{bt}({c}/{t}={r:.0%})" for bt, c, t, r in items)
                    # Flag 100% concentration as capability gap
                    has_total = any(r >= 0.99 for _, _, _, r in items)
                    severity = " ⚠ CAPABILITY GAP" if has_total else ""
                    p(f"    [{stage}] {total_affected} losses across: {bt_list}{severity}")
                    p(f"      Action: {advice}")

            if systemic_recs:
                systemic_recs.sort(key=lambda x: x[3])  # sort by win rate ascending
                for bt, loss_cnt, total_bt, wr, stage_breakdown in systemic_recs:
                    win_cnt = bt_wins.get(bt, 0)
                    stage_str = ", ".join(f"{s}:{c}" for s, c in stage_breakdown)
                    p(f"    [SYSTEMIC] {bt}: {win_cnt}/{total_bt} wins ({wr:.0%}) — {loss_cnt} losses spread across stages ({stage_str})")
                    # Generate stage-proportional composite advice
                    composite_parts = []
                    for stg, cnt in stage_breakdown:
                        pct = cnt / loss_cnt * 100
                        advice_text = stage_advice.get(stg, "investigate root cause")
                        composite_parts.append(f"{pct:.0f}% {stg} → {advice_text}")
                    if composite_parts:
                        p(f"      Action (composite): {'; '.join(composite_parts)}")
            p("")

    # ═══════════════════════════════════════════════════════════════════════
    # ALL TASKS TABLE
    # ═══════════════════════════════════════════════════════════════════════
    p("=" * 80)
    p("ALL TASKS")
    p("=" * 80)
    p("")
    p(f"  {'task':>7} {'score':>5} {'R':>1} {'project':<35} {'bug_types':<30} {'patch':>5} {'target':>10} {'all':>10} {'failure'}")
    p("  " + chr(9472) * 120)

    for t in sorted(parsed, key=lambda x: x.task_id):
        result = "W" if t.is_win else "L"
        bts = ",".join(t.bug_types[:3]) if t.bug_types else "-"
        if len(bts) > 28:
            bts = bts[:27] + chr(8230)
        patch_str = str(t.patch_lines) if t.has_patch else "-"
        fail_str = ""
        if not t.is_win:
            if t.has_patch:
                fail_str = t.failure_category
            else:
                fail_str = t.no_patch_stage
                if t.no_patch_stage == "explore_only" and t.explore_only_subtype:
                    fail_str += f"/{t.explore_only_subtype}"
        p(f"  {t.task_id:>7} {t.score:>5.1f} {result:>1} {t.project[:35]:<35} {bts:<30} {patch_str:>5} {t.target_result_str:>10} {t.all_result_str:>10} {fail_str}")

    return "\n".join(lines)


# ── Failure description helpers ──────────────────────────────────────────────

def _stage_description(stage):
    return {"explore_only": "never edited, just read code", "edit_no_test": "edited but never ran tests",
            "edit_churn": "edited multiple times without converging", "fix_test_loop": "stuck in edit-test-fix loop",
            "identity_confusion": "model thinks it cannot execute commands", "shallow_bail": "gave up early (<=6 turns)",
            "env_blocked": "blocked by environment issues", "localization": "identified area but did not act"}.get(stage, "")


def _category_description(cat):
    return {"target_fail_only": "target test fails, others pass", "regression_only": "target passes but regressions elsewhere",
            "target+regress": "both target and other tests fail", "partial": "some progress but incomplete",
            "target_pass+minor_regress": "target bug fixed but minor non-target regressions (high SFT value)",
            "partial_progress": "some test progress but incomplete fix"}.get(cat, "")


def _explore_subtype_description(subtype):
    return {"analysis_paralysis": "many calls reading code without acting", "wide_scatter": "reads many unique files, cannot locate target",
            "deep_stuck": "reads same files repeatedly, stuck in wrong area", "cant_locate": "explicitly cannot find the relevant code",
            "tool_struggling": "many tool errors / permission issues", "wrong_direction": "exploring unrelated code areas",
            "identified_no_action": "stated bug found but never edited code",
            "false_completion": "ran echo/printf declaring 'completed' without actual edits"}.get(subtype, "")


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

    p("SWE-SYNTH COMPARISON REPORT")
    p("=" * 80)
    p(f"  UIDs compared: {', '.join(str(u) for u in uids)}")
    p("")

    uid_cols = [f"UID_{u}" for u in uids]
    cw = 9

    p("  OVERVIEW:")
    p(f"  {'UID':>6} {'Count':>6} {'Win%':>6} {'Avg':>6} {'Patch%':>7} {'NearWin':>8} {'Loops':>6} {'Projs':>6} {'DomFailure':<18} {'Gaps'}")
    p("  " + chr(9472) * 100)
    uid_profiles = {}
    for uid in uids:
        ps = uid_parsed[uid]
        if not ps:
            p(f"  {uid:>6} (no data)")
            continue
        nn = len(ps)
        losses = [t for t in ps if not t.is_win]
        wr = sum(1 for t in ps if t.is_win) / nn * 100
        avg = _safe_mean([t.score for t in ps])
        patched = sum(1 for t in ps if t.has_patch) / nn * 100
        nw = sum(1 for t in ps if not t.is_win and t.all_total > 0 and t.all_passed_count / t.all_total >= _NEAR_WIN_THRESHOLD)
        loops = sum(1 for t in ps if t.has_loop)
        projs = len(set(t.project for t in ps))

        # Dominant failure mode
        fail_counts = Counter()
        for t in losses:
            fail_counts[t.failure_label] += 1
        dom_fail = fail_counts.most_common(1)[0][0] if fail_counts else "-"
        dom_fail_pct = fail_counts.most_common(1)[0][1] / len(losses) * 100 if fail_counts and losses else 0

        # Capability gaps (bug types with 100% concentration in one failure stage)
        bt_stage = defaultdict(lambda: defaultdict(int))
        bt_total = defaultdict(int)
        for t in losses:
            for b in t.bug_types:
                bt_stage[b][t.failure_label] += 1
                bt_total[b] += 1
        gaps = []
        for bt, stages in bt_stage.items():
            if bt_total[bt] >= 3:
                for stage, cnt in stages.items():
                    if cnt == bt_total[bt]:
                        gaps.append(bt)
                        break
        gap_str = ",".join(gaps[:2]) if gaps else "-"

        uid_profiles[uid] = {
            "win_rate": wr, "near_wins": nw, "dom_fail": dom_fail,
            "dom_fail_pct": dom_fail_pct, "gaps": gaps, "losses": len(losses),
        }

        p(f"  {uid:>6} {nn:>6} {wr:>5.1f}% {avg:>5.3f} {patched:>6.0f}% {nw:>8} {loops:>6} {projs:>6} {dom_fail:<18} {gap_str}")
    p("")

    # MINER PROFILES — per-UID strengths/weaknesses summary
    if len(uid_profiles) >= 2:
        p("  MINER PROFILES:")
        best_wr = max(uid_profiles.values(), key=lambda x: x["win_rate"])
        for uid in uids:
            prof = uid_profiles.get(uid)
            if not prof:
                continue
            traits = []
            if prof["win_rate"] == best_wr["win_rate"]:
                traits.append("highest win rate")
            if prof["near_wins"] >= 3:
                traits.append(f"{prof['near_wins']} near-wins (conversion opportunity)")
            if prof["dom_fail_pct"] >= 40 and prof["losses"] >= 5:
                traits.append(f"bottleneck: {prof['dom_fail']} ({prof['dom_fail_pct']:.0f}%)")
            if prof["gaps"]:
                traits.append(f"gaps: {', '.join(prof['gaps'][:3])}")
            if not traits and prof["losses"] > 0:
                traits.append(f"primary failure: {prof['dom_fail']}")
            if traits:
                p(f"    UID {uid}: {'; '.join(traits)}")
        p("")

    # Per-project
    p("  PER-PROJECT WIN RATES:")
    all_projs = sorted(set(t.project for uid in uids for t in uid_parsed[uid]))
    pw = 35
    header = f"  {'project':<{pw}}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (pw + (cw + 1) * len(uid_cols)))
    for proj in all_projs:
        row = f"  {proj[:pw]:<{pw}}"
        for uid in uids:
            pt = [t for t in uid_parsed[uid] if t.project == proj]
            if pt:
                wr = sum(1 for t in pt if t.is_win) / len(pt) * 100
                row += f" {wr:>{cw - 1}.0f}%"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Per-language
    p("  PER-LANGUAGE WIN RATES:")
    all_langs = sorted(set(t.language for uid in uids for t in uid_parsed[uid]))
    header = f"  {'language':<15}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (15 + (cw + 1) * len(uid_cols)))
    for lang in all_langs:
        row = f"  {lang:<15}"
        for uid in uids:
            lt2 = [t for t in uid_parsed[uid] if t.language == lang]
            if lt2:
                wr = sum(1 for t in lt2 if t.is_win) / len(lt2) * 100
                row += f" {wr:>{cw - 1}.0f}%"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Failure mode comparison
    p("  FAILURE MODE COMPARISON:")
    all_fl = sorted(set(t.failure_label for uid in uids for t in uid_parsed[uid] if not t.is_win))
    header = f"  {'failure':<20}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("  " + chr(9472) * (20 + (cw + 1) * len(uid_cols)))
    for fl in all_fl:
        row = f"  {fl:<20}"
        for uid in uids:
            lu = [t for t in uid_parsed[uid] if not t.is_win]
            fc = sum(1 for t in lu if t.failure_label == fl)
            if fc > 0:
                pct = fc / len(lu) * 100 if lu else 0
                row += f" {fc:>{cw - 5}}/{pct:>3.0f}%"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # Patch-target alignment comparison
    has_alignment = False
    for uid in uids:
        for t in uid_parsed[uid]:
            if t.patch_target_alignment != "no_data" and not t.is_win:
                has_alignment = True
                break
        if has_alignment:
            break

    if has_alignment:
        p("  PATCH-TARGET ALIGNMENT COMPARISON:")
        # Per-UID alignment distribution
        align_header = f"  {'alignment':<15}"
        for uc in uid_cols:
            align_header += f" {uc:>{cw}}"
        p(align_header)
        p("  " + chr(9472) * (15 + (cw + 1) * len(uid_cols)))
        for label in ["match", "related", "mismatch"]:
            row = f"  {label:<15}"
            for uid in uids:
                aligned_losses = [t for t in uid_parsed[uid] if not t.is_win and t.patch_target_alignment != "no_data"]
                cnt = sum(1 for t in aligned_losses if t.patch_target_alignment == label)
                total = len(aligned_losses)
                if total > 0:
                    row += f" {cnt:>{cw - 5}}/{cnt / total * 100:>3.0f}%"
                else:
                    row += f" {'-':>{cw}}"
            p(row)
        p("")

        # Cross-miner alignment on shared tasks: does one miner localize better?
        uid_task_maps = {uid: {t.task_id: t for t in uid_parsed[uid]} for uid in uids}
        shared_patched = []
        for tid in set.intersection(*(set(t.task_id for t in uid_parsed[uid]) for uid in uids)) if len(uids) >= 2 else set():
            alignments = {}
            for uid in uids:
                t = uid_task_maps[uid].get(tid)
                if t and not t.is_win and t.patch_target_alignment != "no_data":
                    alignments[uid] = t.patch_target_alignment
            if len(alignments) >= 2:
                shared_patched.append((tid, alignments))

        if shared_patched:
            # Count tasks where alignment differs across miners
            align_rank = {"match": 2, "related": 1, "mismatch": 0}
            divergent_align = [(tid, als) for tid, als in shared_patched if len(set(als.values())) > 1]
            if divergent_align:
                p(f"    ALIGNMENT DIVERGENCE ({len(divergent_align)}/{len(shared_patched)} shared patched-loss tasks):")
                # Show who localizes better
                uid_better_count = Counter()
                for tid, als in divergent_align:
                    ranked = sorted(als.items(), key=lambda x: -align_rank.get(x[1], 0))
                    best_uid = ranked[0][0]
                    uid_better_count[best_uid] += 1
                for uid in uids:
                    cnt = uid_better_count.get(uid, 0)
                    if cnt > 0:
                        p(f"      UID {uid} localizes better in {cnt}/{len(divergent_align)} divergent tasks")

                # Show examples
                for tid, als in divergent_align[:5]:
                    proj = "?"
                    for uid in uids:
                        t = uid_task_maps[uid].get(tid)
                        if t:
                            proj = t.project or "?"
                            break
                    parts = " vs ".join(f"UID_{u}={a}" for u, a in sorted(als.items()))
                    p(f"        task={tid} ({proj[:25]}): {parts}")
                if len(divergent_align) > 5:
                    p(f"        ... and {len(divergent_align) - 5} more")
                p("")

            consistent_align = len(shared_patched) - len(divergent_align)
            if consistent_align > 0 and shared_patched:
                p(f"    Consistent alignment: {consistent_align}/{len(shared_patched)} tasks (all miners same localization quality)")
        p("")

    # Head-to-head on shared tasks
    p("  HEAD-TO-HEAD ON SHARED TASKS:")
    uid_task_sets = {uid: set(t.task_id for t in uid_parsed[uid]) for uid in uids}
    shared = set.intersection(*uid_task_sets.values()) if uid_task_sets else set()
    p(f"  Shared tasks: {len(shared)}")

    utm = {uid: {t.task_id: t for t in uid_parsed[uid]} for uid in uids}
    if shared:
        td = {}
        for tid in shared:
            wc = sum(1 for uid in uids if utm[uid].get(tid) and utm[uid][tid].is_win)
            if wc == len(uids): td[tid] = "easy"
            elif wc >= len(uids) // 2 + 1: td[tid] = "medium"
            elif wc > 0: td[tid] = "hard-"
            else: td[tid] = "hard"

        dc = Counter(td.values())
        p("")
        p("  TASK DIFFICULTY DISTRIBUTION:")
        for d in ["easy", "medium", "hard-", "hard"]:
            cnt = dc.get(d, 0)
            p(f"    {d:<8}: {cnt} ({_pct_str(cnt, len(shared))})")
        p("")

        header = f"  {'task':>7} {'diff':>6} {'project':<30}"
        for uc in uid_cols:
            header += f" {uc:>{cw}}"
        p(header)
        p("  " + chr(9472) * (7 + 6 + 30 + (cw + 1) * len(uid_cols) + 5))
        for tid in sorted(shared):
            diff = td.get(tid, "?")
            proj = "?"
            for uid in uids:
                t = utm[uid].get(tid)
                if t:
                    proj = t.project or "?"
                    break
            row = f"  {tid:>7} {diff:>6} {proj[:30]:<30}"
            for uid in uids:
                t = utm[uid].get(tid)
                if t:
                    row += f" {'WIN':>{cw}}" if t.is_win else f" {t.failure_label[:cw]:>{cw}}"
                else:
                    row += f" {'-':>{cw}}"
            p(row)
        p("")

        # Winner vs loser behavior
        wb = {"model_calls": [], "edit_commands": [], "read_commands": [], "test_commands": []}
        lb = {"model_calls": [], "edit_commands": [], "read_commands": [], "test_commands": []}
        for tid in shared:
            for uid in uids:
                t = utm[uid].get(tid)
                if t:
                    tgt = wb if t.is_win else lb
                    tgt["model_calls"].append(t.model_calls)
                    tgt["edit_commands"].append(t._conv_stats["edit_commands"])
                    tgt["read_commands"].append(t._conv_stats["read_commands"])
                    tgt["test_commands"].append(t._conv_stats["test_commands"])

        if wb["model_calls"] and lb["model_calls"]:
            p("  WINNER vs LOSER BEHAVIOR (on shared tasks):")
            p(f"  {'Metric':<25} {'Winners':>10} {'Losers':>10} {'Delta':>10}")
            p("  " + chr(9472) * 55)
            for m in ["model_calls", "edit_commands", "read_commands", "test_commands"]:
                wa = _safe_mean(wb[m])
                la = _safe_mean(lb[m])
                p(f"  {m:<25} {wa:>10.1f} {la:>10.1f} {wa - la:>+10.1f}")

            ws = sum(1 for uid in uids for tid in shared if utm[uid].get(tid) and utm[uid][tid].is_win and utm[uid][tid].has_patch)
            wtot = sum(1 for uid in uids for tid in shared if utm[uid].get(tid) and utm[uid][tid].is_win)
            ls = sum(1 for uid in uids for tid in shared if utm[uid].get(tid) and not utm[uid][tid].is_win and utm[uid][tid].has_patch)
            ltot = sum(1 for uid in uids for tid in shared if utm[uid].get(tid) and not utm[uid][tid].is_win)
            p(f"  {'patch_submit_rate':<25} {_pct_str(ws, wtot):>10} {_pct_str(ls, ltot):>10}")
            p("")

    # Cross-miner patch similarity
    p(_generate_patch_similarity_section(uid_data, uid_parsed, uids, utm, shared))
    p("")
    # Near-win cross-miner consistency
    p(_generate_nearwin_section(uid_data, uid_parsed))
    p("")
    # Failure mode migration analysis
    p(_generate_failure_migration_section(uid_data, uid_parsed))

    return "\n".join(lines)


# ── Cross-miner sections ────────────────────────────────────────────────────

def _normalize_patch(patch):
    """Normalize patch for comparison: strip diff headers, keep only +/- lines."""
    if not patch:
        return ""
    lines = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(line[1:].strip())
    return "\n".join(lines)


def _generate_patch_similarity_section(uid_data, uid_parsed, uids, utm, shared):
    """Compare patches across miners on the same task."""
    lines = []

    def p(line=""):
        lines.append(line)

    # Find tasks where 2+ miners have patches (use all overlapping tasks, not just ALL-shared)
    all_tids = set()
    for uid in uids:
        all_tids.update(utm[uid].keys())
    patch_tasks = []
    for tid in all_tids:
        patched_uids = []
        for uid in uids:
            t = utm[uid].get(tid)
            if t and t.has_patch and t.fix_patch:
                patched_uids.append(uid)
        if len(patched_uids) >= 2:
            patch_tasks.append((tid, patched_uids))

    p("  CROSS-MINER PATCH SIMILARITY:")

    if not patch_tasks:
        p("    No shared tasks with patches from 2+ miners.")
        return "\n".join(lines)

    p(f"    Shared tasks with patches from 2+ miners: {len(patch_tasks)}")
    p("")

    # Compute pairwise similarity
    identical = []  # >95% similarity
    similar = []    # 50-95%
    different = []  # <50%

    for tid, patched_uids in patch_tasks:
        patches = {}
        for uid in patched_uids:
            t = utm[uid].get(tid)
            patches[uid] = _normalize_patch(t.fix_patch)

        # Pairwise similarity
        uid_list = sorted(patches.keys())
        max_sim = 0.0
        all_sims = []
        for i in range(len(uid_list)):
            for j in range(i + 1, len(uid_list)):
                sim = _ngram_jaccard(patches[uid_list[i]], patches[uid_list[j]], n=3)
                all_sims.append((uid_list[i], uid_list[j], sim))
                max_sim = max(max_sim, sim)

        avg_sim = sum(s for _, _, s in all_sims) / len(all_sims) if all_sims else 0
        proj = "?"
        is_win_any = False
        for uid in patched_uids:
            t = utm[uid].get(tid)
            if t:
                proj = t.project or "?"
                if t.is_win:
                    is_win_any = True
                break

        entry = (tid, proj, patched_uids, avg_sim, max_sim, is_win_any)

        if max_sim >= 0.95:
            identical.append(entry)
        elif max_sim >= 0.50:
            similar.append(entry)
        else:
            different.append(entry)

    p(f"    Identical patches (>95% sim): {len(identical)} tasks")
    p(f"    Similar patches (50-95%):     {len(similar)} tasks")
    p(f"    Different patches (<50%):     {len(different)} tasks")
    p("")

    # Detail table
    all_entries = sorted(identical + similar + different, key=lambda x: -x[4])
    cw = 8
    uid_cols = [f"UID_{u}" for u in uids]
    header = f"    {'task':>7} {'sim%':>5} {'cat':<6} {'project':<30}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    p(header)
    p("    " + chr(9472) * (7 + 5 + 6 + 30 + (cw + 1) * len(uids) + 2))

    for tid, proj, patched_uids, avg_sim, max_sim, is_win_any in all_entries:
        cat = "IDENT" if max_sim >= 0.95 else ("SIM" if max_sim >= 0.50 else "DIFF")
        row = f"    {tid:>7} {max_sim:>4.0%} {cat:<6} {proj[:30]:<30}"
        for uid in uids:
            t = utm[uid].get(tid)
            if t and t.has_patch:
                tag = "WIN" if t.is_win else "LOSE"
                row += f" {tag + '/' + str(t.patch_lines) + 'L':>{cw}}"
            elif t:
                row += f" {'no_pat':>{cw}}"
            else:
                row += f" {'-':>{cw}}"
        p(row)
    p("")

    # SFT implications
    if identical:
        p("    SFT IMPLICATIONS:")
        p(f"      {len(identical)} tasks have near-identical patches across miners — these are")
        p("      'obvious' fixes solvable by pattern matching. Lower SFT training value.")
        id_wins = sum(1 for _, _, _, _, _, w in identical if w)
        if id_wins:
            p(f"      {id_wins}/{len(identical)} identical-patch tasks include wins — pattern-match wins.")
    if different:
        diff_wins = sum(1 for _, _, _, _, _, w in different if w)
        if diff_wins:
            p(f"      {len(different)} tasks have divergent patches — miners attempt different strategies.")
            p(f"      {diff_wins} of these include wins — high SFT value (unique problem-solving).")

    return "\n".join(lines)

def _generate_nearwin_section(uid_data, uid_parsed):
    lines = []
    def p(line=""):
        lines.append(line)

    uids = sorted(uid_data.keys())
    uid_cols = [f"UID_{u}" for u in uids]
    nwm = {}  # task_id -> {uid: pass_rate}
    atm = {}  # task_id -> {uid: TrajectoryData}

    for uid in uids:
        for t in uid_parsed[uid]:
            atm.setdefault(t.task_id, {})[uid] = t
            if not t.is_win and t.all_total > 0:
                pr = t.all_passed_count / t.all_total
                if pr >= _NEAR_WIN_THRESHOLD:
                    nwm.setdefault(t.task_id, {})[uid] = pr

    cross_nw = {tid: r for tid, r in nwm.items() if len(r) >= 2}

    p("  NEAR-WIN CROSS-MINER CONSISTENCY:")
    p("    Near-wins: losses with >=80% of all tests passing")
    shared_count = sum(1 for tid in atm if len(atm[tid]) >= 2)

    if not cross_nw:
        p(f"    No tasks with cross-miner near-wins found (of {shared_count} shared tasks).")
        single = {tid: r for tid, r in nwm.items() if len(r) == 1}
        if single:
            p(f"    Single-miner near-wins: {len(single)} tasks (covered in per-miner reports)")
        return "\n".join(lines)

    p(f"    Tasks with cross-miner near-wins: {len(cross_nw)} (of {shared_count} shared tasks)")
    p("")
    cw = 9
    tw = 7
    pw = 35
    header = f"    {'task':<{tw}} {'project':<{pw}}"
    for uc in uid_cols:
        header += f" {uc:>{cw}}"
    header += f" {'avg_rate':>{cw}}"
    p(header)
    p("    " + chr(9472) * (tw + pw + (cw + 1) * (len(uid_cols) + 1)))

    sorted_nw = sorted(cross_nw.items(), key=lambda x: sum(x[1].values()) / len(x[1]), reverse=True)
    for tid, rates in sorted_nw:
        proj = "?"
        for uid in uids:
            if uid in atm.get(tid, {}):
                proj = atm[tid][uid].project or "?"
                break
        row = f"    {tid:<{tw}} {proj[:pw]:<{pw}}"
        for uid in uids:
            if uid in rates:
                row += f" {rates[uid]:>{cw}.0%}"
            elif uid in atm.get(tid, {}):
                row += f" {'WIN':>{cw}}" if atm[tid][uid].is_win else f" {'-':>{cw}}"
            else:
                row += f" {'':>{cw}}"
        row += f" {sum(rates.values()) / len(rates):>{cw}.0%}"
        p(row)

    pnw = {}
    for tid, rates in cross_nw.items():
        proj = "?"
        for uid in uids:
            if uid in atm.get(tid, {}):
                proj = atm[tid][uid].project or "?"
                break
        pnw.setdefault(proj, []).append(sum(rates.values()) / len(rates))
    p("")
    p("    By project:")
    for proj in sorted(pnw, key=lambda x: -len(pnw[x])):
        p(f"      {proj}: {len(pnw[proj])} tasks (avg pass rate {sum(pnw[proj]) / len(pnw[proj]):.0%})")

    hc = [(tid, len(rates), sum(rates.values()) / len(rates)) for tid, rates in sorted_nw if len(rates) >= 2 and sum(rates.values()) / len(rates) >= 0.95]
    if hc:
        p("")
        p("    High-confidence task issues (cross-miner near-win, avg >=95%):")
        for tid, nw, avg in hc:
            p(f"      task {tid}: {nw} miners near-win, avg {avg:.0%} -- target test likely too strict")

    p("")
    total_nw = sum(len(r) for r in nwm.values())
    p(f"    INSIGHT: {len(cross_nw)} tasks show cross-miner near-wins ({total_nw} total near-win instances).")
    p("    Tasks with consistently high pass rates across miners suggest their target tests")
    p("    may be overly strict or testing non-essential behavior.")
    return "\n".join(lines)


def _generate_failure_migration_section(uid_data, uid_parsed):
    lines = []
    def p(line=""):
        lines.append(line)

    uids = sorted(uid_data.keys())
    uid_cols = [f"UID_{u}" for u in uids]
    slm = {}  # task_id -> {uid: failure_label}
    atm = {}  # task_id -> {uid: TrajectoryData}

    for uid in uids:
        for t in uid_parsed[uid]:
            atm.setdefault(t.task_id, {})[uid] = t
            if not t.is_win:
                slm.setdefault(t.task_id, {})[uid] = t.failure_label

    shared = {tid: lbls for tid, lbls in slm.items() if len(lbls) >= 2}

    p("  FAILURE MODE MIGRATION ANALYSIS:")
    if not shared:
        p("    No shared losses found -- miners are on different task pools.")
        return "\n".join(lines)

    consistent = {tid: lbls for tid, lbls in shared.items() if len(set(lbls.values())) == 1}
    divergent = {tid: lbls for tid, lbls in shared.items() if len(set(lbls.values())) > 1}

    p(f"    Shared losses analyzed: {len(shared)} tasks (losses for 2+ miners)")
    p(f"    Consistent failure mode: {len(consistent)} ({_pct_str(len(consistent), len(shared))}) -- same failure across all miners")
    p(f"    Divergent failure mode:  {len(divergent)} ({_pct_str(len(divergent), len(shared))}) -- different miners fail differently")

    if consistent:
        p("")
        p("    CONSISTENT FAILURES (same mode for all):")
        mc = Counter(next(iter(set(lbls.values()))) for lbls in consistent.values())
        for mode, cnt in mc.most_common():
            p(f"      {mode:<22} {cnt:>3} tasks{_mode_description(mode)}")

    if divergent:
        p("")
        p("    DIVERGENT FAILURES (different modes across miners):")
        dcw = 18
        header = f"      {'task':<7} {'project':<35}"
        for uc in uid_cols:
            header += f" {uc:<{dcw}}"
        p(header)
        p("      " + chr(9472) * (7 + 35 + (dcw + 1) * len(uid_cols)))
        for tid in sorted(divergent.keys()):
            lbls = divergent[tid]
            proj = "?"
            for uid in uids:
                if uid in atm.get(tid, {}):
                    proj = atm[tid][uid].project or "?"
                    break
            row = f"      {tid:<7} {proj[:35]:<35}"
            for uid in uids:
                if uid in lbls:
                    row += f" {lbls[uid][:dcw]:<{dcw}}"
                elif uid in atm.get(tid, {}):
                    row += f" {'WIN':<{dcw}}" if atm[tid][uid].is_win else f" {'---':<{dcw}}"
                else:
                    row += f" {'---':<{dcw}}"
            p(row)

        p("")
        p("    FAILURE MIGRATION PATTERNS:")
        p("      (how failure modes shift across miners on the same task)")
        als = sorted(set(l for lbls in divergent.values() for l in lbls.values()))
        if len(als) > 1:
            matrix = {a: {b: 0 for b in als} for a in als}
            for tid, lbls in divergent.items():
                ul = sorted(lbls.keys())
                for i in range(len(ul)):
                    for j in range(i + 1, len(ul)):
                        a, b = lbls[ul[i]], lbls[ul[j]]
                        if a != b:
                            matrix[a][b] += 1
                            matrix[b][a] += 1
            abbrevs = [_LABEL_ABBREV.get(l, l[:7]) for l in als]
            lw = max(max(len(a) for a in abbrevs), 12)
            cellw = max(max(len(a) for a in abbrevs), 5) + 1
            header = f"      {'':>{lw}}"
            for a in abbrevs:
                header += f" {a:>{cellw}}"
            p(header)
            p("      " + chr(9472) * (lw + (cellw + 1) * len(abbrevs)))
            for label, abbr in zip(als, abbrevs):
                row = f"      {abbr:>{lw}}"
                for ol in als:
                    if label == ol:
                        row += f" {'-':>{cellw}}"
                    else:
                        cnt = matrix[label][ol]
                        row += f" {cnt:>{cellw}}" if cnt > 0 else f" {'.':>{cellw}}"
                p(row)

        p("")
        p("    MODEL WEAKNESS SIGNATURES:")
        for uid in uids:
            ul = Counter()
            td = 0
            for tid, lbls in divergent.items():
                if uid in lbls:
                    ul[lbls[uid]] += 1
                    td += 1
            if td == 0:
                continue
            tm = ul.most_common(2)
            ts = "/".join(f"{m}" for m, _ in tm)
            tc = sum(c for _, c in tm[:1])
            desc = _mode_weakness_description(tm[0][0] if tm else "unknown")
            p(f"      UID {uid}: Tends toward {ts} -- {desc}")
            p(f"               {tc}/{td} divergent tasks show dominant pattern.")

    p("")
    if divergent:
        dp = 100 * len(divergent) / len(shared) if shared else 0
        p(f"    INSIGHT: {dp:.0f}% of shared losses show different failure modes across miners.")
        p("    This indicates the failure is model-dependent, not purely task-dependent.")
    else:
        p("    INSIGHT: All shared losses have consistent failure modes across miners.")
        p("    This suggests failures are task-intrinsic rather than model-dependent.")
    return "\n".join(lines)


def _mode_description(mode):
    return {
        "explore_only": " -- task is fundamentally hard to locate",
        "edit_churn": " -- all miners spin editing without progress",
        "edit_no_test": " -- all miners edit without verifying",
        "fix_test_loop": " -- all miners get stuck in test loops",
        "env_blocked": " -- environment blocks all miners equally",
        "identity_confusion": " -- all miners confused about capabilities",
        "shallow_bail": " -- all miners give up early",
        "localization": " -- all miners identify area but don't act",
        "target+regress": " -- all miners cause regressions",
        "regression_only": " -- all miners break other tests",
        "target_fail_only": " -- all miners fail target test only",
        "partial": " -- all miners get partial scores",
        "target_pass+minor_regress": " -- all miners fix target but introduce minor regressions",
        "partial_progress": " -- all miners make partial progress",
    }.get(mode, "")


def _mode_weakness_description(mode):
    return {
        "explore_only": "gets stuck reading code without acting",
        "edit_churn": "edits aggressively but without testing",
        "edit_no_test": "edits then submits without verification",
        "fix_test_loop": "attempts fixes but can't converge on a solution",
        "identity_confusion": "often cannot even begin solving",
        "env_blocked": "frequently blocked by environment issues",
        "shallow_bail": "gives up too quickly",
        "localization": "identifies bugs but lacks confidence to edit",
        "target+regress": "fixes target but breaks other code",
        "regression_only": "causes regressions without fixing target",
        "target_fail_only": "patches don't address the actual bug",
        "partial": "partial progress but incomplete solutions",
        "target_pass+minor_regress": "fixes target bug but introduces minor side effects",
        "partial_progress": "makes partial progress but cannot complete fix",
    }.get(mode, "unknown weakness pattern")


# ── CLI ──────────────────────────────────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(description="SWE-SYNTH trajectory analysis")
    parser.add_argument("--uid", type=int, default=None, help="Miner UID (0-255), required unless --compare")
    parser.add_argument("--env", type=str, default="SWE-SYNTH", help="Environment name (default: SWE-SYNTH)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Write report to file")
    parser.add_argument("--all", action="store_true", help="Fetch all historical data (not just sampling list)")
    parser.add_argument("--recent", type=int, default=None, help="Only analyze N most recent trajectories")
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N trajectories")
    parser.add_argument("--inspect", action="store_true", help="Dump raw extra field structure")
    parser.add_argument("--compare", type=str, default=None, help="Compare multiple UIDs (comma-separated)")
    parser.add_argument("--json", action="store_true", help="Also dump raw JSON")
    args = parser.parse_args()

    env_name = args.env
    source = "all" if args.all else "sampling"
    limit = args.limit or args.recent

    if args.compare:
        uids = [int(u.strip()) for u in args.compare.split(",") if u.strip()]
        print(f"Comparing UIDs: {uids} env={env_name} source={source}", file=sys.stderr)

        # Parallel fetch all UIDs
        async def _fetch_one(uid):
            print(f"  Fetching UID={uid} ...", file=sys.stderr)
            miner_info, trajs = await fetch_trajectories(uid, env_name, source=source)
            if limit and trajs:
                trajs = sorted(trajs, key=lambda t: t.get("timestamp", 0) or 0, reverse=True)[:limit]
            print(f"    UID={uid} -> {len(trajs)} trajectories", file=sys.stderr)
            return uid, miner_info, trajs

        results = await asyncio.gather(*[_fetch_one(uid) for uid in uids])
        uid_data = {}
        for uid, miner_info, trajs in results:
            uid_data[uid] = (miner_info, trajs)

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
    print(f"Fetching trajectories for UID={uid} env={env_name} source={source} ...", file=sys.stderr)
    miner_info, raw_trajectories = await fetch_trajectories(uid, env_name, source=source)

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
        raw_trajectories = sorted(raw_trajectories, key=lambda t: t.get("timestamp", 0) or 0, reverse=True)[:limit]
        print(f"  Limited to {len(raw_trajectories)} most recent trajectories", file=sys.stderr)

    if args.inspect:
        for t in raw_trajectories[:5]:
            safe = {k: v for k, v in t.items() if k != "extra"}
            extra = t.get("extra", {})
            if isinstance(extra, str):
                try: extra = json.loads(extra)
                except Exception: extra = {}
            if isinstance(extra, dict):
                safe["extra_keys"] = list(extra.keys())
                for k in ["conversation", "usage", "bug_types", "swe_instance_id", "target_result", "all_result"]:
                    if k in extra:
                        if k == "conversation":
                            safe["conversation_len"] = len(extra[k]) if isinstance(extra[k], list) else 0
                        else:
                            safe[k] = extra[k]
                if "fix_patch" in extra:
                    fp = extra["fix_patch"]
                    safe["fix_patch_len"] = len(fp) if isinstance(fp, str) else 0
                    safe["fix_patch_preview"] = (fp[:200] + "...") if isinstance(fp, str) and len(fp) > 200 else fp
            print(json.dumps(safe, indent=2, default=str))
        return

    if args.json:
        print(json.dumps(raw_trajectories[:3], indent=2, default=str, ensure_ascii=False))
        return

    miner_info["uid"] = uid
    report = generate_report(miner_info, raw_trajectories)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(report + "\n")
        print(f"Report written to {args.output} ({len(report)} chars)", file=sys.stderr)
    else:
        print(report)

    print(f"\n  Fetched {len(raw_trajectories)} trajectories", file=sys.stderr)


def main():
    async def _run():
        try:
            await async_main()
        finally:
            if _db_initialized:
                try:
                    from affine.database.client import close_client
                    await close_client()
                except Exception:
                    pass
    asyncio.run(_run())


if __name__ == "__main__":
    main()
