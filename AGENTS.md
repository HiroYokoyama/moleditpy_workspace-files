# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Workspace Overview

`DEV_MAIN` is a multi-repo workspace for the **MoleditPy** project ecosystem — a PyQt6/RDKit/PyVista molecular editor for DFT preparation. Each subdirectory is an independent Git repository.

| Directory | Role |
|---|---|
| `python_molecular_editor/` | Main application — see `python_molecular_editor/AGENTS.md` for full guidance |
| `moleditpy-plugins/` | Official plugin collection (distributed separately) |
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

**Never edit `moleditpy-linux/`** inside `python_molecular_editor/` — it is synced separately.

## Plugin Repos (moleditpy-plugins, *_pro, *_analyzer, *_pyscf-calculator)

### Testing

Each plugin repo has its own test suite. All run headlessly with PyQt6/RDKit/PySCF fully mocked:

```bash
# moleditpy-plugins
cd moleditpy-plugins && python -m pytest tests/ -v

# moleditpy_pyscf-calculator
cd moleditpy_pyscf-calculator && python -m pytest tests/ -v

# With coverage (pyscf-calculator)
python -m pytest tests/ --cov=pyscf_calculator --cov-report=term-missing

# Single test file
python -m pytest tests/test_worker_pyscf_availability.py -v
```

`moleditpy_orca_input_generator_pro` and `moleditpy_orca_result_analyzer_plugin` do not currently have independent test suites — testing is done via the main app plugin integration path.

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
- `context.register_save_handler / register_load_handler / register_reset_handler` for session persistence
- Access to the host via `context.main_window`, `context.current_molecule`, etc.

See `python_molecular_editor/docs/PLUGIN_DEVELOPMENT_MANUAL_V4.md` for the full API.

## Cross-Repo Dependency

When the main app's `PluginContext` API changes, all plugin repos may need updates. The `moleditpy_pyscf-calculator` CI (`test-integration` job) clones the main app from GitHub to catch these regressions automatically. Other plugin repos rely on manual verification.
