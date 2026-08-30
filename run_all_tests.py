#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MoleditPy Workspace Test Runner

Discovers and runs every MoleditPy test suite in DEV_MAIN: the main
application, all plugin repos and the installer. The other projects that share
the workspace (pymatgen-core, Cerberus-Retro, chem_db_web, ...) are out of
scope and only run with --outside.

Two things the naive "pytest tests/ in every directory" approach misses, and
that this runner handles:

* a repo can hold more than one suite (moleditpy-plugins has tests/ *and*
  tests_gui/; matplotlib_graph_app keeps its tests under hygrapher/tests/);
* a repo that ships its own runner script is invoked through it, because that
  script is what makes a local run match CI -- it pins the Qt binding, or sets
  PYTEST_DISABLE_PLUGIN_AUTOLOAD so a locally installed pytest-qt does not
  import a real PyQt6 over the tests' module-level stubs.

Usage:
    python run_all_tests.py                 # every MoleditPy suite
    python run_all_tests.py --list          # show what would run, run nothing
    python run_all_tests.py --only orca     # only suites whose name matches
    python run_all_tests.py --skip job      # drop matching suites
    python run_all_tests.py -j 4            # run 4 suites concurrently
    python run_all_tests.py --full-gui      # add the main app's full_gui tier
    python run_all_tests.py --outside       # include the non-MoleditPy projects
"""

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

WORKSPACE_DIR = os.path.abspath(os.path.dirname(__file__))

# Directories that are not test-bearing repos (scratch space, notes, wikis).
EXCLUDED_DIRS = {
    "other",
    "note",
    "__pycache__",
    ".git",
    ".github",
    ".claude",
    # Backup mirror of the workspace root files; its run_all_tests.py is a copy
    # of THIS script, so auto-detecting a runner there would recurse.
    "moleditpy_workspace-files",
}

# Only the MoleditPy ecosystem is in scope. Everything else in the workspace is
# a separate project (or vendored upstream, like pymatgen-core) whose suite is
# not ours to keep green -- run those with --outside if you want them.
IN_SCOPE_PREFIXES = ("moleditpy", "python_molecular_editor")

# Runner scripts a repo may ship at its root, in preference order.
REPO_RUNNERS = ("run_tests.py", "test_all.py")

# Suites that need more than the default budget (seconds).
TIMEOUTS = {
    "python_molecular_editor": 3600,
    "python_molecular_editor [full_gui]": 1800,
    "pymatgen-core": 3600,
    "moleditpy-plugins": 1200,
    "moleditpy-plugins [gui]": 1800,
    "moleditpy_job_manager": 1200,
    "moleditpy_orca_result_analyzer_plugin": 900,
    "moleditpy_orca_result_analyzer_rust": 900,
    "moleditpy_pyscf-calculator": 900,
    "moleditpy_cif_viewer": 900,
}
DEFAULT_TIMEOUT = 600

# pytest's tail line, e.g. "5 failed, 120 passed, 3 skipped in 4.2s".
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)\b")
_COUNT_ORDER = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")


class Suite:
    """One runnable test suite: a label, a command, and where to run it."""

    def __init__(self, name, cwd, cmd, env_extra=None):
        self.name = name
        self.cwd = cwd
        self.cmd = cmd
        self.env_extra = env_extra or {}

    @property
    def timeout(self):
        return TIMEOUTS.get(self.name, DEFAULT_TIMEOUT)

    def display_cmd(self):
        return " ".join("python" if c == sys.executable else c for c in self.cmd)


def _pytest(*targets):
    return [sys.executable, "-m", "pytest", *targets, "-v", "--tb=short"]


def _main_app_src(workspace_dir):
    """Path the plugin repos expect for their against-the-real-host tests."""
    return os.path.join(workspace_dir, "python_molecular_editor", "moleditpy", "src")


def discover_suites(workspace_dir, full_gui=False, outside=False):
    """Build the suite list for every test-bearing directory in the workspace."""
    suites = []
    main_app_src = _main_app_src(workspace_dir)

    for item in sorted(os.listdir(workspace_dir)):
        path = os.path.join(workspace_dir, item)
        if not os.path.isdir(path) or item in EXCLUDED_DIRS or item.endswith(".wiki"):
            continue
        if not outside and not item.startswith(IN_SCOPE_PREFIXES):
            continue

        # The main app has a tiered runner; with no tier flag it runs UNIT +
        # INTEGRATION + E2E + GUI. FULL_GUI needs a real display, so it is a
        # separate opt-in suite.
        if item == "python_molecular_editor":
            runner = os.path.join("tests", "run_all_tests.py")
            suites.append(
                Suite(
                    item,
                    path,
                    [sys.executable, runner, "--headless", "--no-cov", "--no-report"],
                )
            )
            if full_gui:
                suites.append(
                    Suite(
                        f"{item} [full_gui]",
                        path,
                        _pytest(
                            "tests/full_gui", "-c", "tests/full_gui/pytest.ini"
                        ),
                    )
                )
            continue

        # A repo-provided runner is the CI-faithful entry point; prefer it.
        runner = next(
            (r for r in REPO_RUNNERS if os.path.isfile(os.path.join(path, r))), None
        )
        if runner:
            suites.append(Suite(item, path, [sys.executable, runner]))
        elif os.path.isdir(os.path.join(path, "tests")):
            suites.append(Suite(item, path, _pytest("tests/")))
        else:
            # Not a repo root layout: look one level down for a package that
            # holds its own tests/ (e.g. matplotlib_graph_app/hygrapher/tests).
            for sub in sorted(os.listdir(path)):
                sub_path = os.path.join(path, sub)
                if sub.startswith((".", "_")) or not os.path.isdir(sub_path):
                    continue
                if os.path.isdir(os.path.join(sub_path, "tests")):
                    suites.append(Suite(f"{item}/{sub}", path, _pytest(f"{sub}/tests/")))

        # Real-Qt GUI suites live beside the headless ones and are never picked
        # up by `pytest tests/`.
        if os.path.isdir(os.path.join(path, "tests_gui")):
            suites.append(Suite(f"{item} [gui]", path, _pytest("tests_gui/")))

    # The ORCA analyzer's host-contract tests read the main app from this var.
    if os.path.isdir(main_app_src):
        for suite in suites:
            if suite.name.startswith("moleditpy_orca_result_analyzer"):
                suite.env_extra["CI_MAIN_APP_SRC"] = main_app_src

    return suites


def summarize(output):
    """Condense pytest output into a 'N passed, M failed' style line."""
    counts = {}
    for line in reversed(output.splitlines()):
        if "passed" not in line and "failed" not in line and "error" not in line:
            continue
        found = _COUNT_RE.findall(line)
        if not found:
            continue
        for number, word in found:
            key = "error" if word.startswith("error") else word
            counts[key] = counts.get(key, 0) + int(number)
        break
    return ", ".join(f"{counts[k]} {k}" for k in _COUNT_ORDER if counts.get(k))


def run_suite(suite, env):
    suite_env = dict(env)
    suite_env.update(suite.env_extra)
    start = time.time()
    try:
        result = subprocess.run(
            suite.cmd,
            cwd=suite.cwd,
            env=suite_env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=suite.timeout,
        )
        elapsed = time.time() - start
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode == 0:
            return "PASSED", elapsed, summarize(output), ""
        lines = output.splitlines()
        detail = "\n".join(lines[-40:]) if len(lines) > 40 else output
        return "FAILED", elapsed, summarize(output), detail
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.time() - start, "", f"exceeded {suite.timeout}s"
    except Exception as exc:  # missing interpreter, unreadable cwd, ...
        return "ERROR", time.time() - start, "", str(exc)


def main():
    parser = argparse.ArgumentParser(
        description="Run every test suite in the DEV_MAIN workspace."
    )
    parser.add_argument(
        "--list", action="store_true", help="list the discovered suites and exit"
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="TEXT",
        help="run only suites whose name contains TEXT (repeatable)",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="TEXT",
        help="skip suites whose name contains TEXT (repeatable)",
    )
    parser.add_argument(
        "--full-gui",
        action="store_true",
        help="also run the main app's full_gui tier (needs a real display)",
    )
    parser.add_argument(
        "--outside",
        action="store_true",
        help="also run the non-MoleditPy projects in the workspace "
        "(pymatgen-core, Cerberus-Retro, chem_db_web, ...)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="run N suites concurrently (default: 1)",
    )
    args = parser.parse_args()

    suites = discover_suites(
        WORKSPACE_DIR, full_gui=args.full_gui, outside=args.outside
    )
    if args.only:
        needles = [n.lower() for n in args.only]
        suites = [s for s in suites if any(n in s.name.lower() for n in needles)]
    if args.skip:
        needles = [n.lower() for n in args.skip]
        suites = [s for s in suites if not any(n in s.name.lower() for n in needles)]

    if not suites:
        print("No test suites found.")
        return 1

    if args.list:
        print(f"{len(suites)} test suites:")
        for suite in suites:
            print(f"  {suite.name:<45} {suite.display_cmd()}")
        return 0

    # Resolve the Windows Qt DLL collision (PySide6 vs PyQt6) for every suite.
    env = os.environ.copy()
    env["MOLEDITPY_HEADLESS"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTEST_QT_API"] = "pyqt6"

    print("=" * 76)
    print("      MOLEDITPY WORKSPACE TEST RUNNER")
    print("=" * 76)
    print(f"Found {len(suites)} test suites to run.\n")

    results = {}
    done = [0]

    def execute(suite):
        outcome = run_suite(suite, env)
        done[0] += 1
        status, elapsed, counts, _ = outcome
        tail = f"  [{counts}]" if counts else ""
        print(
            f"[{done[0]}/{len(suites)}] {suite.name:<45} -> "
            f"{status} ({elapsed:.1f}s){tail}",
            flush=True,
        )
        return suite.name, outcome

    if args.jobs > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for name, outcome in pool.map(execute, suites):
                results[name] = outcome
    else:
        for suite in suites:
            name, outcome = execute(suite)
            results[name] = outcome

    print("\n" + "=" * 76)
    print("             TEST RUN SUMMARY")
    print("=" * 76)

    failed = []
    for suite in suites:
        status, elapsed, counts, _ = results.get(suite.name, ("UNKNOWN", 0.0, "", ""))
        tail = f"  [{counts}]" if counts else ""
        print(f" {suite.name:<45} : {status:<7} ({elapsed:6.1f}s){tail}")
        if status != "PASSED":
            failed.append(suite.name)

    print("=" * 76)

    for name in failed:
        detail = results[name][3]
        if detail:
            print(f"\n--- Failure detail for {name} ---")
            print(detail)
            print("-" * 76)

    if not failed:
        print(f"\nSUCCESS: all {len(suites)} workspace test suites passed!")
        return 0

    print(f"\nFAILURE: {len(failed)} of {len(suites)} suites did not pass:")
    for name in failed:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
