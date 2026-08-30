# DEV_MAIN Workspace

`DEV_MAIN` is the multi-repository workspace for the **MoleditPy** ecosystem — a modular PyQt6 / RDKit / PyVista molecular editor and quantum chemistry (DFT) calculation preparation toolkit.

Each directory in `DEV_MAIN` represents an independent Git repository, including the main desktop application, MCP server, web interface, installer, and official plugins.

---

## Workspace Tools & Scripts

The root directory provides unified scripts to manage, test, and maintain all repositories in the workspace.

### 1. PAT Secret Rotation Tool
Rotates the `REGISTRY_PAT` GitHub Actions secret across all plugin repositories using masked, hidden terminal input (`getpass`).

- **Script**: `roll_registry_pat.py` (with `roll_registry_pat.bat` and `roll_registry_pat.ps1` wrappers)
- **Features**:
  - Masked input (characters hidden during entry for security)
  - Confirmation prompt before execution
  - Automatic discovery of repositories requiring `REGISTRY_PAT`
  - Direct stdin piping to `gh secret set` without exposing tokens in command arguments
- **Usage**:
  ```powershell
  python roll_registry_pat.py
  # or via wrappers:
  .\roll_registry_pat.ps1
  roll_registry_pat.bat
  ```

### 2. Workspace Test Runner
Discovers and executes test suites across all repositories in `DEV_MAIN` in a single command with headless Qt/X-server environment variables pre-configured.

- **Script**: `run_all_tests.py` (with `run_all.bat`, `run_all.ps1`, and `run_all` wrappers)
- **Features**:
  - Automatically discovers all directories containing a `tests/` folder
  - Handles environment variables (`MOLEDITPY_HEADLESS=1`, `QT_QPA_PLATFORM=offscreen`, `PYTEST_QT_API=pyqt6`) to prevent Qt binding collisions
  - Runs main app test suite and pytest suites for all plugins
  - Outputs per-suite execution timing and failure summaries
- **Usage**:
  ```powershell
  python run_all_tests.py
  # or via wrappers:
  .\run_all.ps1
  run_all.bat
  ```

---

## Repositories & Ecosystem

| Repository / Directory | Description |
|---|---|
| `python_molecular_editor/` | **Main Desktop Application** — Core MoleditPy app |
| `moleditpy-mcp_server/` | **MCP Server** — Model Context Protocol integration |
| `moleditpy-plugins/` | **Plugin Registry** & official plugin manifest |
| `python_molecular_editor_installer/` | **Installer Toolkit** — Desktop installer & shortcuts |
| `moleditpy_3d-molecule-on-2d/` | Plugin: 3D molecule overlay on 2D sketch |
| `moleditpy_auto_rotator/` | Plugin: Auto rotator |
| `moleditpy_blender-export-pro/` | Plugin: Blender 3D Export Pro |
| `moleditpy_cif_viewer/` | Plugin: CIF File Viewer |
| `moleditpy_DECIMER_plugin/` | Plugin: DECIMER Optical Structure Recognition |
| `moleditpy_gaussian_input_generator_pro/` | Plugin: Gaussian Input Generator Pro |
| `moleditpy_nics_placer/` | Plugin: NICS Probe Placer |
| `moleditpy_nmr_predicator_nmrshiftdb2/` | Plugin: NMR Predictor (NMRShiftDB2) |
| `moleditpy_orca_input_generator_pro/` | Plugin: ORCA Input Generator Pro |
| `moleditpy_orca_result_analyzer_plugin/` | Plugin: ORCA Result Analyzer |
| `moleditpy_orca_result_analyzer_rust/` | Plugin: ORCA Result Analyzer (Rust Accelerated) |
| `moleditpy_pmeff-plugin/` | Plugin: PMEFF Forcefield |
| `moleditpy_pyscf-calculator/` | Plugin: PySCF Calculator |
| `moleditpy_reaction_sketcher_plugin/` | Plugin: Reaction Sketcher |
| `moleditpy_rotation_giffer/` | Plugin: Rotation Animated GIF Creator |
| `moleditpy_strain_homodesmotic_reaction_generator/` | Plugin: Strain Homodesmotic Reaction Generator |

---

## CI / CD Workflows

Every plugin repository contains GitHub Actions workflows under `.github/workflows/`:
- **`tests.yml`**: Automated unit and integration testing. Standardized to single-pass test execution with coverage collection (`pytest --cov=...`).
- **`release.yml`**: Automated packaging and release publishing triggered on tag pushes, utilizing `REGISTRY_PAT`.
