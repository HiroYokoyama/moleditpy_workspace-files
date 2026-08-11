# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Overview

`DEV_MAIN` is a multi-repo workspace for the **MoleditPy** project ecosystem — a PyQt6/RDKit/PyVista molecular editor for DFT preparation. Each subdirectory is an independent Git repository.

| Directory | Role |
|---|---|
| `python_molecular_editor/` | Main application — see `python_molecular_editor/CLAUDE.md` for full guidance |
| `moleditpy-plugins/` | Official plugin collection (distributed separately) |
| `moleditpy_orca_input_generator_pro/` | ORCA Input Generator Pro plugin |
| `moleditpy_orca_result_analyzer_plugin/` | ORCA Result Analyzer plugin |
| `moleditpy_pyscf-calculator/` | PySCF Calculator plugin |
| `other/` | Scratch space / dev artifacts — not a repo |

**The main app is the source of truth.** All plugins depend on the `PluginContext` API defined in `python_molecular_editor/moleditpy/src/moleditpy/plugins/plugin_interface.py`.

## Main Application

See **`python_molecular_editor/CLAUDE.md`** for the full development guide, including build/test/lint commands and the full architecture. Key quick-reference:

```bash
# Install for development (from python_molecular_editor/)
pip install -e moleditpy/

# Run full test suite
MOLEDITPY_HEADLESS=1 QT_QPA_PLATFORM=offscreen python tests/run_all_tests.py --no-cov --no-report --unit --integration

# Lint
pylint moleditpy/src/moleditpy/
```

**Never edit `moleditpy-linux/`** inside `python_molecular_editor/` — it is synced separately.

## Plugin Repos (moleditpy-plugins, *_pro, *_analyzer, *_pyscf-calculator)

### Testing

Every plugin repo has its own headless test suite in `tests/` (PyQt6/RDKit/PySCF fully mocked), typically with a `plugin_api_checker.py` + `.moleditpy-api-allowlist` for static API validation against the main app:

```bash
# General pattern (any plugin repo)
cd <plugin_repo> && python -m pytest tests/ -v

# With coverage (example: pyscf-calculator)
python -m pytest tests/ --cov=pyscf_calculator --cov-report=term-missing

# Single test file
python -m pytest tests/test_worker_pyscf_availability.py -v
```

Notes:
- On Windows, `python` may resolve to the Store alias — use the full path to the real interpreter if `pytest` fails to launch.
- `moleditpy_cif_viewer` needs `PYTEST_QT_API=pyqt6` (or its `test_all.py` runner), otherwise pytest-qt's binding auto-detection loads PySide6 first and crashes the process when both bindings are installed.

### Integration with the Main App

Plugins are validated against the real `PluginContext` contract. The `moleditpy_pyscf-calculator` integration tests auto-detect the main app when the repos are siblings:

```
DEV_MAIN/
    python_molecular_editor/   ← main app
    moleditpy_pyscf-calculator/ ← plugin sees ../python_molecular_editor/moleditpy/src
```

Running `python -m pytest tests/test_plugin_integration.py -v` locally will exercise both stub and real-context tiers when the main app is present.

### Plugin Architecture Pattern

Every plugin follows the same contract:
- Entry point: a single `.py` file with an `initialize(context: PluginContext)` function
- `context.add_menu_action(path, callback)` registers menu items
- `context.register_save_handler / register_load_handler / register_document_reset_handler` for session persistence
- Access to the host via `context.main_window`, `context.current_molecule`, etc.

See `python_molecular_editor/docs/PLUGIN_DEVELOPMENT_MANUAL_V4.md` for the full API.

## Comparing Versions

A plugin's version is written down in three places: `PLUGIN_VERSION` in its source, its
`REGISTRY/plugins.json` entry in `moleditpy-plugins`, and the footer of its
`moleditpy-plugins.wiki` page. One command compares all three (and flags registry plugins
missing from the wiki catalogue), exiting non-zero on any disagreement:

```bash
python G:/DEV_MAIN/check_wiki_versions.py
```

Source ahead of the registry is normal for an unreleased bump; the registry ahead of the
wiki means the wiki page needs updating. Wiki pages deliberately carry no version at the
top — only a footer stating which version the page documents and when it was written.

## Backing Up the Root Files

The workspace's own files — the root scripts and docs, plus `.claude/agents/` and
`.claude/skills/` — are backed up in the `moleditpy_workspace-files` repo. One command
copies the allowlist across, commits, and pushes:

```bash
python G:/DEV_MAIN/backup_workspace_files.py --push
```

Drop `--push` to commit only, `--dry-run` to preview. The allowlist is the `ALLOWLIST`
table at the top of the script — add new root files there or they are not backed up.
Everything outside it (the plugin repos, `note/`, `other/`, scratch directories) is never
read. Files that exist only in the backup, like the Codex `AGENTS.md`, are left alone
unless you pass `--prune`.

## Cross-Repo Dependency

When the main app's `PluginContext` API changes, all plugin repos may need updates. The `moleditpy_pyscf-calculator` CI (`test-integration` job) clones the main app from GitHub to catch these regressions automatically. Most other plugin repos ship a `tests/plugin_api_checker.py` (with a `.moleditpy-api-allowlist`) that statically verifies every `mw.*`/`context.*` access against the main-app source when the repos are checked out as siblings (`tests/test_api.py`; skipped if the main app is absent).
