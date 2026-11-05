# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Workspace Overview

`DEV_MAIN` is a multi-repo workspace for the **MoleditPy** project ecosystem — a PySide6/RDKit/PyVista molecular editor for DFT preparation. Each subdirectory is an independent Git repository.

| Directory | Role |
|---|---|
| `python_molecular_editor/` | Main application — see `python_molecular_editor/AGENTS.md` for full guidance |
| `moleditpy-plugins/` | Official plugin collection; canonical API checker in `api-checker/` |
| `moleditpy-common-tools/` | Versioned canonical Zenodo, plugin release and materialization scripts |
| `moleditpy_orca_input_generator_pro/` | ORCA Input Generator Pro plugin |
| `moleditpy_orca_result_analyzer_plugin/` | ORCA Result Analyzer plugin |
| `moleditpy_pyscf-calculator/` | PySCF Calculator plugin |
| `other/` | Scratch space / dev artifacts — not a repo |

**The main app is the source of truth.** All plugins depend on the `PluginContext` API defined in `python_molecular_editor/moleditpy/src/moleditpy/plugins/plugin_interface.py`.

## Main Application

See **`python_molecular_editor/AGENTS.md`** for the full development guide, including build/test/lint commands and the full architecture. Key quick-reference:

```bash
# Install for development (from python_molecular_editor/)
pip install -e moleditpy/

# Run full test suite
MOLEDITPY_HEADLESS=1 QT_QPA_PLATFORM=offscreen python tests/run_all_tests.py --no-cov --no-report --unit --integration

# Lint
pylint moleditpy/src/moleditpy/
```

MoleditPy 5 uses only `moleditpy/` on every OS. The old `moleditpy-linux/` source tree and synchronization process have been retired.

## Plugin Repos (moleditpy-plugins, *_pro, *_analyzer, *_pyscf-calculator)

### Testing

Every plugin repo has its own headless test suite in `tests/`, with PySide6/RDKit/PySCF fully mocked:

```bash
# General pattern (any plugin repo)
cd <plugin_repo> && python -m pytest tests/ -v

# With coverage (pyscf-calculator)
python -m pytest tests/ --cov=pyscf_calculator --cov-report=term-missing

# Single test file
python -m pytest tests/test_worker_pyscf_availability.py -v
```

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
- Entry point: a `.py` file or package exposing an `initialize(context: PluginContext)` function
- `context.add_menu_action(path, callback)` registers menu items
- `context.register_save_handler / register_load_handler / register_document_reset_handler` for session persistence
- Access to the host via `context.main_window`, `context.current_molecule`, etc.

See `python_molecular_editor/docs/PLUGIN_DEVELOPMENT_MANUAL_V5.md` for the full API.

## Cross-Repo Dependency

When the main app's `PluginContext` API changes, all plugin repos may need updates. The `moleditpy_pyscf-calculator` CI (`test-integration` job) clones the main app from GitHub to catch these regressions automatically. Most other plugin repos ship a `tests/plugin_api_checker.py` that statically verifies `mw.*`/`context.*` access against the main-app source when the repos are siblings.
