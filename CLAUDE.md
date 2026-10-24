# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Overview

`DEV_MAIN` is a multi-repo workspace for the **MoleditPy** project ecosystem — a PySide6/RDKit/PyVista molecular editor for DFT preparation. Each subdirectory is an independent Git repository.

| Directory | Role |
|---|---|
| `python_molecular_editor/` | Main application — see `python_molecular_editor/CLAUDE.md` for full guidance |
| `moleditpy-plugins/` | Official plugin collection; canonical API checker in `api-checker/` |
| `moleditpy-common-tools/` | Versioned canonical Zenodo, plugin release and materialization scripts |
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

MoleditPy 5 uses only `moleditpy/` on every OS. The old `moleditpy-linux/` source tree and synchronization process have been retired.

## Plugin Repos (moleditpy-plugins, *_pro, *_analyzer, *_pyscf-calculator)

### Testing

Every plugin repo has its own headless test suite in `tests/` (PySide6/RDKit/PySCF fully mocked), typically with a `plugin_api_checker.py` + `.moleditpy-api-allowlist` for static API validation against the main app:

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
- Use `PYTEST_QT_API=pyside6` and `QT_API=pyside6` for GUI tests; all migrated plugins use PySide6.

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

## Shared Maintenance Scripts

### Canonical ownership and versions

- **API checker stays in `moleditpy-plugins/api-checker/`.** Do not move its canonical engine to the common-tools repository. The engine has its own semantic version (`__version__`, currently 1.1.3); lint and format it with Ruff before copying it. `check_api.py` is a registry-aware wrapper around that engine, not a second implementation.
- **Zenodo, ordinary plugin release helpers and materialization live in `moleditpy-common-tools/scripts/`.** The common tool bundle uses SemVer in `VERSION` (initial version 1.0.0): patch for compatible fixes, minor for compatible additions and major for breaking CLI/config changes.
- Consumers copy only tested source revisions. `scripts/common-tools.lock.json` records the bundle version, immutable source commit and LF-normalized SHA-256 hashes. `scripts/api-checker.lock.json` records the API checker's separate canonical version, commit and hash. Never silently follow upstream `main`, edit copied scripts independently or reformat them under a consumer's different Ruff rules.
- Repository settings belong in `scripts/zenodo-config.json`, `release-config.json` and `materialize-config.json`, not in patched copies of shared code. Preserve existing production/Sandbox record IDs, artifact names, notice files, destination packages and pinned periodic submodule revisions.
- Update maintenance copies from a clean, tested common-tools checkout with `python tools/sync_consumers.py --repo <repository> --write`. Consult `scripts/COMMON_TOOLS.md` in each consumer. The plugin template follows the same conventions, including its separate single-file example.

### Minimal testing

Common script logic is tested only in its canonical repository. Do not duplicate mocked Zenodo tests or API-engine unit tests into every plugin, and do not run an application-wide suite merely for a copied maintenance-script update.

- Maintenance-script tests: `moleditpy-common-tools/tests/`, one path-filtered CI job on Python 3.9 / Ubuntu 24.04.
- API-engine tests: `moleditpy-plugins/tests_api_checker/`, one path-filtered Python 3.9 job, separate from the plugin test matrix.
- Consumers retain their own API compatibility and integration checks against MoleditPy. These validate the consuming plugin, rather than retesting the shared engine. Select checks relevant to the change and avoid repeated slow runs.

### Release formats and boundaries

- Single-file plugins attach the `.py` and required notices directly; packaged plugins distribute their existing ZIP layout. Keep the distinction in release configuration.
- Distribute wheels only for products published to PyPI. A native Rust build may use an intermediate wheel internally without distributing it as a separate release asset.
- Keep exceptional native/server builds and independent PyPI publishing jobs local. Materialization copies only the configured modules from the existing pinned submodule.
- **Do not unify or replace the main application's release workflow.** `python_molecular_editor/.github/workflows/release.yml`, its application builds and PyPI flow remain independent. Sharing its Zenodo helper is a separate concern.
- Maintenance-only changes do not require plugin runtime version bumps or releases. Do not create a collection "final tag" merely because plugin work finished; a collection tag/release must be explicitly requested. Verify relevant CI and artifacts before a requested publication.

### Publishing workspace documentation

Stage only intended files. Do not commit investigation scripts, caches, local settings, credentials, user job lists or calculation data. When asked to update only this guide in `moleditpy_workspace-files`, copy and commit only `CLAUDE.md`; do not run the full workspace backup allowlist implicitly.

## Line Endings

Line endings matter in exactly one repo: **`moleditpy-plugins`**. It ships plugin files
as-is (raw `.py` from the repo; package ZIPs generated as release assets) and `REGISTRY/plugins.json`
records a `sha256` over those exact bytes, which the Plugin Installer verifies after
download. A CRLF/LF flip changes the bytes, breaks the hash, and aborts the install. That
is why it is the only repo carrying a `.gitattributes` with `* -text` — keep it, and
preserve each file's existing endings when editing there.

**Everywhere else, do not spend any effort on line endings.** No other repo has a
`.gitattributes`, so the global `core.autocrlf=true` and GitHub normalise whatever you
write and nothing downstream depends on the bytes. Do not check a file's existing endings
before editing it, do not preserve them, and do not add line-ending constraints to task
or sub-agent briefs — it is wasted work, not diff hygiene.

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

## Outstanding Work Across the Repos

One command surveys every repo for things still open — open issues and PRs (two
`gh search` calls, not one per repo) plus what each sibling checkout is holding that
GitHub has not seen: uncommitted files, unpushed commits, a branch behind origin, a
detached HEAD, a missing upstream.

```bash
python G:/DEV_MAIN/check_issues_prs.py
```

`--local-only` / `--remote-only` run one half. `--fail-on-open` exits non-zero when
anything is outstanding, so it works as a pre-push gate. `--tags` additionally looks for
unpushed tags, but that costs a network round trip per repo (2.5s → ~45s), so it is off
by default. Authentication comes from `gh`; the script never reads or stores a token.

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

## Backing Up the GitHub Repositories

A full off-GitHub copy of every moleditpy repository — `moleditpy*` plus
`python_molecular_editor*`, wikis included:

```bash
python G:/DEV_MAIN/backup_github_repos.py
```

A plain run produces four things per repository, all of them on by default:

| Directory | What |
|---|---|
| `repos/<name>.git` | bare `--mirror` clone — every branch, tag and note (plus `<name>.wiki.git`) |
| `bundles/<name>.bundle` | the same history as one file, for copying onto external media |
| `releases/<name>/<tag>/` | the **latest** release's assets — they are not in git |
| `metadata/<name>/` | `issues.json`, `pulls.json`, `releases.json` — also not in git |

Recovery is `git clone backup_github/repos/<name>.git` or `git clone <name>.bundle <dir>`.
`manifest.json` records each mirror's HEAD, ref count, bundle state and release tag.

Each run **deletes the existing backup and fetches it again**, so nothing stale — a
superseded release, a repository that no longer exists on GitHub — survives into the new
copy. The wipe refuses to touch a directory that is not one of ours (no `manifest.json`,
unfamiliar contents), which is the guard against a mistyped `--dest`. `--incremental`
keeps what is there and updates it in place instead: mirrors do `remote update --prune`,
a bundle is rewritten only when its refs differ, an already-downloaded release is skipped.

Use `--resume` after a failure or interruption. It never wipes the destination:
completed repositories with the same requested components and present artifacts are
skipped, and failed/pending repositories are retried. `manifest.json` is replaced
atomically after each repository, with a `complete` flag for the run. Old backups
without completion information are reused and checked/updated on their first resume.
Use `--incremental` when you want every mirror refreshed, rather than a resumed snapshot.

Transient network failures retry three times by default, with exponential backoff;
`--retries 5 --timeout 300` changes the retry count and per-command timeout. Failed
clones use fresh staging directories. Bundles and release assets are published
atomically, asset sizes and available SHA-256 digests are checked, and an unfinished
asset directory is never treated as complete. Metadata pagination produces valid
JSON arrays. A metadata, asset or wiki-bundle failure marks that repository failed
without stopping other repositories. An empty repository needs no bundle.

`--dest` picks another location (or set `MOLEDITPY_BACKUP_DIR`), `--dry-run` lists the
selection and deletes nothing, `--all-releases` takes every release instead of just the
latest, and `--no-bundle` / `--no-releases` / `--no-metadata` / `--no-wiki` trim a run down.

## Cross-Repo Dependency

When the main app's `PluginContext` API changes, all plugin repos may need updates. The `moleditpy_pyscf-calculator` CI (`test-integration` job) clones the main app from GitHub to catch these regressions automatically. Most other plugin repos ship a `tests/plugin_api_checker.py` (with a `.moleditpy-api-allowlist`) that statically verifies every `mw.*`/`context.*` access against the main-app source when the repos are checked out as siblings (`tests/test_api.py`; skipped if the main app is absent).
