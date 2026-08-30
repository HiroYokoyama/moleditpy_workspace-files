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
PLUGIN_OPTIONAL_DEPENDENCIES = [] # extra-feature packages; installer never gates install on these
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
  (e.g. `%LOCALAPPDATA%/Programs/Python/Python313/python.exe -m pytest`) if the python alias fails.

## 4. Publish repo

```bash
git init -b main && git add -A && git commit
gh repo create HiroYokoyama/<repo> --public --source . --push --description "..."
```

`gh` is now authenticated on this machine (user logged in 2026-07-22) — just call
`gh`/`gh api`/`gh run` directly, no token export needed. (Historical note: before
that, `gh` was logged out and required a `GH_TOKEN=$(… git credential fill …)` trick;
that is no longer necessary.)
Commit small chunks; push to main is fine once the repo exists, but tags/releases wait
for the user's explicit word.

## 5. Release + registry registration (only when user says "push tag")

0. **Push commits to `main` and watch the Tests CI go green BEFORE pushing any tag.**
   A tag cannot be un-released cleanly, so never tag on red or unverified CI. After
   `git push origin main`, wait for the run and require success:
   ```bash
   gh run watch <run-id> --repo HiroYokoyama/<repo> --exit-status
   ```
   CI installs **pytest only** (no PyQt6/RDKit/numpy), so any test file that imports
   host deps at module load MUST `pytest.skip(..., allow_module_level=True)` when they
   are absent — otherwise it errors at *collection* (not skip) and reds the run.
   Simulate CI locally before pushing with a `sys.meta_path` finder that raises
   `ModuleNotFoundError` for PyQt6/rdkit/numpy, run under
   `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (drops pytest-qt/pytest-cov so their own PyQt6
   import doesn't mask the test), and confirm the files report *skipped*, not *error*.
   Note the Release workflow triggers on the tag independently of the Tests workflow —
   a green release job does NOT imply Tests passed, so check Tests explicitly.
1. Tag must equal `PLUGIN_VERSION`: `git tag v0.1.0 && git push origin v0.1.0`.
   If host source code changed since the last release, the version MUST already be
   bumped (tests-only changes do not bump). Never move/re-point an existing tag.
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

Gotchas seen registering the Auto Rotator (2026-07-22):
- `register_remote_plugin.py`'s **new-entry** path historically dropped `supported_os`
  (never copied it from `PLUGIN_SUPPORTED_OS` nor applied `DEFAULT_OS_LIST`), so the
  first registration of a brand-new remote plugin failed `test_registry`
  (`supported_os must be a non-empty list, got None`). Fixed to emit `supported_os`
  AND to build new entries in the canonical field order (`projectUrl` right after
  `authorUrl`; `supported_python_version` + `supported_os` trailing). If a new-plugin
  registration reds on `supported_os`, that fix regressed.
- `REGISTRY/plugins.json` is committed **LF** (`.gitattributes: * -text` = no git eol
  conversion). The script writes LF, so a clean run = a ~30-line append diff. If you
  ever see the *whole file* diff, you flipped line endings (e.g. a stray CRLF pass) —
  normalize back to LF (`d.replace(b'\r\n', b'\n')`), don't commit the flip.
- When the plugin's release repo lacks the `REGISTRY_PAT` secret you can register
  locally instead of dispatching: run `register_remote_plugin.py <release-asset-url>`
  (no `--dry-run`) in the moleditpy-plugins clone, then `update_intra_repo_metadata.py`
  (must report 0 changes), run `pytest tests/test_registry.py`, and commit+push.
