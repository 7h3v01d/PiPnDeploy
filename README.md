# 🚀 PiPnDeploy (pipndeploy) — Python Packaging Made Human (Archived)

A CLI + GUI tool that guides Python projects from **idea → package → PyPI**, without the usual pain.

PiPnDeploy is currently **on ice**, preserved as a fully functional prototype with ambitious scope and real-world usefulness.

---

## 🧠 What is PiPnDeploy?

Packaging Python projects is deceptively hard.

PiPnDeploy was built to tame the entire workflow:
- project initialization
- dependency detection
- build isolation
- PyPI/TestPyPI deployment
- authentication validation
- cleanup and maintenance

All from **one tool**, usable via **CLI or GUI**.

---

## ✨ Key features

### 🧩 Full lifecycle support
- `init` — generate `pyproject.toml` and README
- `build` — wheel + sdist
- `deploy` — PyPI / TestPyPI upload
- `clean` — remove artifacts and uninstall
- `full` — guided end-to-end pipeline

### 🔍 Smart dependency detection
- AST-based import analysis
- Ignores Python standard library (curated JSON list)
- Maps common import aliases (e.g. `PIL → Pillow`)
- Optional auto-detection during init

### 🧪 Sandbox builds
- Optional isolated `.venv` builds
- Reduces risk of polluted environments
- Safer packaging workflow

### ⚙️ Hook system
- `hooks/pre_build.py`
- `hooks/post_deploy.py`

Extend the pipeline without touching core logic.

### 🔐 Auth validation & generation
- Validates `.pypirc` configuration
- Checks token format and repositories
- GUI-assisted `.pypirc` generation

### 🖥️ Dual interface
- **CLI** (Typer-based, scriptable)
- **GUI** (Tkinter, tabbed workflow)

Both powered by the same core logic.

---

## 🗂️ Project layout
```text
pipndeploy/
├── PiPnDeploy/
│ ├── core_logic.py # Shared logic (CLI + GUI)
│ ├── stnd_lib.json # Standard library definitions
│ └── Utils/
├── cli_main.py # CLI entry point
├── gui_main.py # Tkinter GUI
├── Features.md # Feature manifest
├── profile.json # Saved user profile
└── dummy.py # Dependency detection test file
```

---

## ▶️ Usage (CLI)

```bash
python cli_main.py init
python cli_main.py build
python cli_main.py deploy --test
```
Or run the full guided pipeline:

```bash
python cli_main.py full
```

### 🖥️ Usage (GUI)

```bash
python gui_main.py
```
Includes:

- project profile
- init wizard
- build/deploy controls
- auth token helper
- console output view

### ⚠️ Status & limitations

- Archived / prototype
- No installer or PyPI release of PiPnDeploy itself
- Limited automated test coverage
- Some overlap between early and newer workflows

The logic is sound — polish and consolidation would be the next step.

### 💡 If revived later…
Clear upgrade paths:

- split CLI & GUI into separate packages
- formal plugin architecture
- richer error handling
- automated tests
- PyPI release of PiPnDeploy itself

### 📜 License
Unlicensed (personal archive).

### 🏷️ Status
Archived — but highly usable.

This project represents a serious attempt to make Python packaging less fragile, less manual, and more humane.
