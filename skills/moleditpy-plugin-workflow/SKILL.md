---
name: moleditpy-plugin-workflow
description: End-to-end workflow for creating, testing, publishing, and registering a new MoleditPy plugin repo (modeled on the Gaussian Input Generator Pro build, 2026-07-11). Use when creating a new plugin repo, adding a release, or registering a plugin into moleditpy-plugins.
---

# MoleditPy Plugin Repo Workflow

Proven end-to-end flow, executed for `moleditpy_gaussian_input_generator_pro` (v0.1.0).
Reference implementations: `moleditpy_orca_input_generator_pro` (architecture gold
standard), `moleditpy-plugins/plugins/*` (single-file plugins).

## 1. Scaffold from the ORCA Pro template

New repo layout (sibling dir under DEV_MAIN, name `moleditpy_<snake_name>`):

```
<pkg_name>/            # package: __init__.py, constants.py, highlighter.py,
                       #   keyword_builder.py, main_dialog.py, mixins.py
tests/                 # headless suite (see §3)
.github/workflows/     # tests.yml + release.yml (copy from ORCA Pro, rename pkg)
README.md LICENSE .gitignore CODE_OF_CONDUCT.md CONTRIBUTING.md SECURITY.md
```

`__init__.py` metadata (exactly this set — registry scripts read them):

```python
PLUGIN_NAME = "..."
PLUGIN_VERSION = "0.1.0"          # semver; keep the version string ONLY here
PLUGIN_AUTHOR = "HiroYokoyama"
PLUGIN_DESCRIPTION = "..."
PLUGIN_CATEGORY = "Export"        # or Visualization / Optimization / ...
PLUGIN_TAGS = ["...", "..."]      # minimal; flows into registry
PLUGIN_DEPENDENCIES = []          # only pip extras beyond host (PyQt6/rdkit = host)
PLUGIN_SUPPORTED_MOLEDITPY_VERSION = ">=4.0.0, <5.0.0"
```

Architecture contract (see ORCA Pro `__init__.py` for the canonical shape):
- module-level `current_settings` / `_dialog_opened` / `_context`
- `initialize(context)`: `add_export_action`, `register_save_handler` (gated on
  `_dialog_opened`), `register_load_handler` (strip charge/mult), 
  `register_document_reset_handler` with the deferred-reset-on-cancelled-close guard
- `run(mw)`: singleton dialog via `context.get_window/register_window`
- main dialog: presets in `settings.json` beside the package + "Global" pseudo-preset,
  persistent-settings sync inside `update_preview`, dirty tracking + Ctrl+S +
  Save/Discard/Cancel closeEvent, `_resolve_live_mol`, `custom_symbol`-aware coords

## 2. Domain keyword lists — verify against official docs

Never trust generated keyword lists. Fetch the vendor docs and diff programmatically
(example: Gaussian SCRF solvents from https://gaussian.com/scrf/ — cached copy in the
session scratchpad `cache/gaussian16_scrf_solvents_official.txt`).
Known traps: Gaussian has `PBE1PBE` not `PBE0`; no `def2SV(P)`; no `LanL08` built-in;
n-alkane solvents are `n-` prefixed (but plain `Heptane` IS official).

## 3. Headless tests

- Every test file installs its own PyQt6/rdkit stubs via `types.ModuleType` + MagicMock
  BEFORE importing the package (pattern: any `tests/test_metadata.py` in a plugin repo).
- **Stub-superset rule**: pytest loads test modules alphabetically and the first
  `_install_stubs()` wins process-wide. Every stub list must cover the entire import
  chain. After adding a Qt class to the package, add it to EVERY test file's stub list,
  then verify each file standalone: `for f in tests/test_*.py; do pytest "$f"; done`.
- **No module-level heavy imports in the package**: CI installs only pytest.
  `import numpy` must be guarded (`try/except ImportError: np = None`). Simulate CI
  locally with a sitecustomize meta-path hook that blocks the import.
- Qt-logic testing technique: bind unbound methods to `SimpleNamespace` with small
  stateful fake widgets; guard `self.<widget>` access in product code with `getattr`.
- Windows: use the full interpreter path
  `C:/Users/hiro2/AppData/Local/Programs/Python/Python313/python.exe -m pytest`.

## 4. Publish repo

```bash
git init -b main && git add -A && git commit
export GH_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n "s/^password=//p")
gh repo create HiroYokoyama/<repo> --public --source . --push --description "..."
```

`gh` is not logged in on this machine — the `GH_TOKEN`-from-git-credential trick above
is required (do NOT `gh auth login --with-token`; the gho_ token lacks read:org).
Commit small chunks; push to main is fine once the repo exists, but tags/releases wait
for the user's explicit word.

## 5. Release + registry registration (only when user says "push tag")

1. Tag must equal `PLUGIN_VERSION`: `git tag v0.1.0 && git push origin v0.1.0`.
2. release.yml verifies the version, zips the package (README+LICENSE copied in),
   creates the GitHub release with asset `<pkg>_<ver>.zip`.
3. Registry auto-dispatch requires the `REGISTRY_PAT` secret; new repos DON'T have it.
   Dispatch manually after the release succeeds:
   ```bash
   echo '{"event_type":"plugin_release","client_payload":{"repo":"HiroYokoyama/<repo>","tag":"v0.1.0"}}' \
     | gh api repos/HiroYokoyama/moleditpy-plugins/dispatches --input -
   ```
4. The Auto-Register workflow commits to `REGISTRY/plugins.json`. **Pull the local
   moleditpy-plugins clone (`git pull --ff-only`) before any local registry work** —
   never edit plugins.json manually anyway (script-maintained).
5. Verify the entry: version, tags, dependencies, sha256, downloadUrl.
