# PiPnDeploy

Python packaging made human — initialise, build, version, and deploy Python packages from one CLI or GUI.

[![PyPI version](https://badge.fury.io/py/pipndeploy.svg)](https://pypi.org/project/pipndeploy/)
[![Python versions](https://img.shields.io/pypi/pyversions/pipndeploy.svg)](https://pypi.org/project/pipndeploy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-126%20passing-brightgreen)](https://github.com/YOUR_USERNAME/PiPnDeploy)

---

## What it does

PiPnDeploy wraps the Python packaging workflow — `pyproject.toml` generation, dependency detection, building, version bumping, and PyPI upload — into a single tool with both a desktop GUI and a CLI.

It is designed for solo developers and small teams who want to stop copy-pasting packaging boilerplate between projects.

---

## Features

- **Init** — generate a PEP 621-compliant `pyproject.toml` from a form or a single command
- **Surgical update** — edit only the fields you own; `[tool.ruff]`, `[tool.pytest]`, `[tool.hatch]`, comments, and custom sections are never touched
- **Dependency detection** — AST scan your package folder; stdlib and self-imports are excluded automatically; supports flat, `src/`, and multi-package layouts
- **Build** — wraps `python -m build` with a pre-build hook gate
- **Deploy** — wraps `twine upload` with a pre-flight auth check so it never hangs waiting for interactive input
- **Version bump** — patch / minor / major from the GUI version tab or `pipndeploy bump`
- **Clean** — removes build artefacts; uninstall is always opt-in
- **Auth check** — validates `~/.pypirc` token configuration before attempting upload
- **Lifecycle hooks** — `hooks/pre_build.py` and `hooks/post_deploy.py` with correct lifecycle (post-deploy runs only after a successful upload, never during dry-run)
- **GUI and CLI** — same core logic, two interfaces

---

## Installation

CLI only (no Qt required):

```bash
pip install pipndeploy
```

CLI + GUI:

```bash
pip install pipndeploy[gui]
```

---

## CLI usage

```bash
# Initialise a new project
pipndeploy init

# Check whether a package name is available on PyPI
pipndeploy name-check my-package

# Build wheel + sdist
pipndeploy build

# Upload to TestPyPI (dry run first)
pipndeploy deploy --test --dry-run

# Upload to PyPI
pipndeploy deploy

# Bump the patch version (1.2.3 → 1.2.4)
pipndeploy bump patch

# Bump minor or major
pipndeploy bump minor
pipndeploy bump major

# Set an exact version
pipndeploy bump --set 2.0.0

# Clean build artefacts (does NOT uninstall by default)
pipndeploy clean

# Clean and uninstall (opt-in)
pipndeploy clean --uninstall

# Validate ~/.pypirc token configuration
pipndeploy auth-check

# Full interactive pipeline (init → build → deploy)
pipndeploy full

# All commands accept --project-dir / -d to target a specific directory
pipndeploy build -d /path/to/my-project
```

---

## GUI usage

Launch the GUI:

```bash
# If installed with [gui] extra
pipndeploy-gui

# Or from the project root
python -m PiPnDeploy.gui_main
```

The GUI provides tabs for every operation. The **Init** tab pre-fills from an existing `pyproject.toml` if one is found in the project directory. The **Version** tab shows a two-step preview before writing anything to disk.

---

## Safety model

PiPnDeploy is designed to be non-destructive by default:

| Operation | Default behaviour | Opt-in to be destructive |
|-----------|-------------------|--------------------------|
| `clean` | Removes `build/`, `dist/`, `*.egg-info` | `--uninstall` to also remove the package |
| `init` on existing project | Warns before overwriting `pyproject.toml` | Confirm in dialog |
| `~/.pypirc` generation | Warns before overwriting, creates `.pypirc.bak` | Confirm in dialog |
| `post_deploy` hook | Runs only after successful upload | — |
| `pre_build` hook | Failure aborts the build | — |
| Surgical TOML update | Only edits `[project]` fields; all other sections preserved | — |

---

## Lifecycle hooks

Place Python scripts in a `hooks/` directory at your project root:

```
my-project/
  hooks/
    pre_build.py     # runs before build; non-zero exit aborts the build
    post_deploy.py   # runs after successful upload; skipped on dry-run
```

Hooks receive no arguments. Use `sys.exit(1)` to signal failure.

---

## Auth / .pypirc

Use the **Auth Gen** tab or configure `~/.pypirc` manually:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-your-token-here

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-your-testpypi-token-here
```

Run `pipndeploy auth-check` to validate your configuration before deploying.

On Unix-like systems, PiPnDeploy sets `~/.pypirc` permissions to `600` (owner read/write only) automatically.

---

## Dependency detection

PiPnDeploy AST-scans your package folder to detect third-party imports. It supports:

- **Flat layout**: `my-project/mypkg/__init__.py`
- **src layout**: `my-project/src/mypkg/__init__.py`
- **Multi-package**: multiple packages in the same project root

The following are always excluded from the scan:

- Python standard library modules
- The project's own package name (self-imports)
- Directories: `tests`, `docs`, `examples`, `build`, `dist`, `.venv`, `venv`
- Files: `conftest.py`, `dummy.py`, `setup.py`

Auto-detected dependencies are a starting point. Review them before publishing.

---

## Known limitations

- Dependency detection is AST-based and may miss dynamic imports (`importlib.import_module`, `__import__`) or conditional imports behind non-trivial logic
- The GUI does not update `[project.scripts]` in surgical mode — use the Init tab to change entry points
- No Git integration (commit, tag, release) — this is intentional; PiPnDeploy handles packaging, not source control
- Pre-release version strings (`1.2.3rc1`, `1.2.3.dev0`) are not incremented by `bump` — use `--set` for those

---

## Development

```bash
git clone https://github.com/YOUR_USERNAME/PiPnDeploy
cd PiPnDeploy
pip install -e ".[gui,dev]"
python -m pytest tests/ -v
```

---

## Project structure

```
PiPnDeploy/
├── PiPnDeploy/
│   ├── __init__.py
│   ├── cli_main.py       # Typer CLI — thin wrapper around core_logic
│   ├── core_logic.py     # All shared logic — the single source of truth
│   ├── gui_main.py       # PyQt6 GUI — thin wrapper around core_logic
│   └── Utils/
│       └── __init__.py
├── tests/
│   ├── test_dep_detection.py
│   ├── test_pyproject_generation.py
│   └── test_version_bump.py
├── hooks/                # Optional lifecycle hooks (user-created)
├── pyproject.toml
└── README.md
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
