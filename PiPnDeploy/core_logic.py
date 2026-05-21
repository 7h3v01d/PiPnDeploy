# core_logic.py — PiPnDeploy shared logic (single source of truth)
# All CLI and GUI code imports from here. Nothing is duplicated.

import ast
import configparser
import logging
import os
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib
except ImportError:
    raise ImportError("❌ Python 3.11+ is required for TOML support.")

try:
    import tomlkit
except ImportError:
    raise ImportError("❌ tomlkit is required: pip install tomlkit")

# ─── Logging ─────────────────────────────────────────────────────────────────
# One logger for the whole package. GUI/CLI configure handlers on their side.
# Using print() in core is gone — everything goes through this logger so
# consumers can route output wherever they like.

log = logging.getLogger("pipndeploy")

if not log.handlers:
    # Default: emit to stdout so the CLI works out-of-the-box without config.
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.DEBUG)


# ─── Constants ────────────────────────────────────────────────────────────────

SCRIPT_NAME = Path(__file__).name
#: Seconds to wait for a PyPI HTTP response before giving up.
NAME_CHECK_TIMEOUT = 8

LICENSE_OPTIONS = [
    "MIT",
    "Apache-2.0",
    "GPL-3.0",
    "LGPL-3.0",
    "BSD-3-Clause",
    "BSD-2-Clause",
    "Mozilla Public License 2.0",
    "Eclipse Public License 2.0",
    "The Unlicense",
    "ISC",
    "Creative Commons Zero v1.0 Universal",
    "Freeware",
]

# import alias → PyPI package name
_IMPORT_NAME_MAP: dict[str, str] = {
    "PIL":       "Pillow",
    "bs4":       "beautifulsoup4",
    "yaml":      "PyYAML",
    "cv2":       "opencv-python",
    "sklearn":   "scikit-learn",
    "dotenv":    "python-dotenv",
    "dateutil":  "python-dateutil",
    "attr":      "attrs",
    "typer":     "typer",
    "requests":  "requests",
    "numpy":     "numpy",
    "pandas":    "pandas",
}


# ─── Standard library detection ──────────────────────────────────────────────

# Build the stdlib set once at import time using sys.stdlib_module_names
# (available since Python 3.10; we target 3.11+ so this is always present).
# Eliminates the bundled stnd_lib.json file and the FileNotFoundError it caused
# when the wheel was installed without the data file.
_STDLIB_MODULES: frozenset[str] = frozenset(
    m.lower() for m in sys.stdlib_module_names
)


def is_standard_library(module_name: str) -> bool:
    """Return True if *module_name* is part of the Python standard library."""
    base = module_name.split(".")[0].lower()
    return base in sys.builtin_module_names or base in _STDLIB_MODULES


# ─── PyPI name availability ───────────────────────────────────────────────────

def _check_via_json_api(package_name: str, base_url: str) -> bool | None:
    """Query the PyPI JSON API for a package.

    Returns:
        True  — package exists (HTTP 200)
        False — package does not exist (HTTP 404)
        None  — result is indeterminate (network error, rate-limit, auth wall, etc.)

    Note: The HTML fallback was removed. PyPI now serves a JavaScript
    challenge page ('Client Challenge') for bot requests, so HTML scraping
    always returns a 200 with no useful content and falsely signals the name
    as taken. JSON API is the only reliable signal.

    TestPyPI returns HTTP 403 for all JSON API requests regardless of whether
    a package exists — treated as None (indeterminate) rather than True/False.
    """
    url = f"{base_url}/{package_name}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipndeploy/2.2"})
        with urllib.request.urlopen(req, timeout=NAME_CHECK_TIMEOUT) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False   # definitive: package does not exist
        # 403 = TestPyPI auth wall; 429 = rate limited; 5xx = server error
        # None of these mean "taken" — treat as indeterminate
        log.debug("Name check HTTP %s for %s at %s", exc.code, package_name, base_url)
    except Exception as exc:
        log.debug("Name check failed for %s: %s", package_name, exc)
    return None


def check_name_availability(name: str) -> tuple[bool | None, bool | None]:
    """Return (taken_on_pypi, taken_on_testpypi).

    Values: True = taken, False = available, None = could not determine.
    """
    pypi = _check_via_json_api(name, "https://pypi.org/pypi")
    test = _check_via_json_api(name, "https://test.pypi.org/pypi")
    return (pypi, test)


# ─── Dependency detection ─────────────────────────────────────────────────────

#: Directories skipped when purging __pycache__ and .pyc files.
#: These subtrees are either not project-owned source code or are
#: managed by external tools that should not be mutated by clean.
_CLEAN_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",           # version control internals
    ".venv", "venv", "env", ".env",  # virtual environments
    "node_modules",                  # JS tooling sometimes present
})


#: Directory names never treated as importable packages during dep scanning.
_IGNORED_PACKAGE_DIRS: frozenset[str] = frozenset({
    "tests", "test", "docs", "doc", "examples", "example",
    "build", "dist", ".venv", "venv", "env", ".env",
    "scripts", "tools", "benchmark", "benchmarks",
    "__pycache__",
})

#: File names excluded from import scanning (fixtures, stubs, legacy setup).
_DEP_SCAN_EXCLUDES: frozenset[str] = frozenset({
    "dummy.py", "conftest.py", "setup.py",
})


def find_package_roots(project_root: Path) -> list[Path]:
    """Return all real package directories under *project_root*.

    Searches both the root level and a ``src/`` sub-directory so that both
    flat and src-layout projects are handled correctly:

        Flat layout:    project/mypkg/__init__.py   → [project/mypkg]
        src layout:     project/src/mypkg/__init__.py → [project/src/mypkg]
        Multi-package:  project/pkgA/ + project/pkgB/ → [pkgA, pkgB]

    Directories in ``_IGNORED_PACKAGE_DIRS`` are never returned even if they
    contain an ``__init__.py`` (e.g. ``tests/__init__.py``).
    """
    candidates: list[Path] = []
    search_roots = [project_root]
    src_dir = project_root / "src"
    if src_dir.is_dir():
        search_roots.append(src_dir)

    for base in search_roots:
        for item in sorted(base.iterdir()):   # sorted → deterministic across OSes
            if not item.is_dir():
                continue
            if item.name in _IGNORED_PACKAGE_DIRS or item.name.startswith("."):
                continue
            if (item / "__init__.py").exists():
                candidates.append(item)

    return candidates


def get_package_folder_path(project_root: Path) -> Path | None:
    """Return the first package root found (backward-compat wrapper).

    Prefer ``find_package_roots()`` for new code.
    """
    roots = find_package_roots(project_root)
    return roots[0] if roots else None


def detect_dependencies(project_root: Path | None = None) -> list[str]:
    """AST-scan all package roots and return a sorted list of third-party deps.

    Improvements over the original single-folder scan:

    * Supports flat layout ``mypkg/`` and src layout ``src/mypkg/``.
    * Scans *all* package roots (multi-package projects).
    * Excludes directories in ``_IGNORED_PACKAGE_DIRS`` (tests, docs, etc.).
    * Excludes the project's own package names from the results so that
      intra-project imports like ``from mypkg.utils import x`` are not
      misclassified as third-party dependencies.
    * Skips files listed in ``_DEP_SCAN_EXCLUDES`` (dummy.py, conftest.py…).
    * Gracefully skips files with parse errors.
    """
    root = project_root or Path.cwd()
    package_roots = find_package_roots(root)

    if not package_roots:
        log.warning("⚠️  No package folder (directory with __init__.py) found — skipping dep scan.")
        return []

    # Build the set of local package names so we can exclude self-imports.
    # Both the directory name and the hyphen↔underscore variant are included
    # because ``import my_pkg`` and ``import my-pkg`` both refer to the same
    # local package regardless of how the directory is named.
    local_names: set[str] = set()
    for pkg in package_roots:
        n = pkg.name.lower()
        local_names.add(n)
        local_names.add(n.replace("-", "_"))
        local_names.add(n.replace("_", "-"))

    log.debug("🔎 Scanning package roots: %s", [p.name for p in package_roots])
    log.debug("🔎 Excluding local package names: %s", sorted(local_names))

    found: set[str] = set()
    for package_root in package_roots:
        for path in package_root.rglob("*.py"):
            if path.name in _DEP_SCAN_EXCLUDES:
                log.debug("🔎 Skipping excluded file: %s", path.name)
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("⚠️  Skipping %s — parse error: %s", path.name, exc)
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        raw = alias.name.split(".")[0]       # original case
                        mod = raw.lower()                    # normalised for checks
                        if is_standard_library(mod) or mod in local_names:
                            continue
                        # Alias map keys may be mixed-case (PIL, bs4, yaml…)
                        found.add(_IMPORT_NAME_MAP.get(raw, raw))
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    if node.module == "__future__":
                        continue
                    raw = node.module.split(".")[0]          # original case
                    mod = raw.lower()                        # normalised for checks
                    if is_standard_library(mod) or mod in local_names:
                        continue
                    found.add(_IMPORT_NAME_MAP.get(raw, raw))

    return sorted(found)


# ─── pyproject.toml generation ───────────────────────────────────────────────

def _distribution_name(name: str) -> str:
    """Return the canonical distribution name: lowercase, hyphens, not underscores.

    E.g.  my_package  →  my-package   (correct for PyPI / [project] name)
    """
    return name.lower().replace("_", "-")


def _module_name(name: str) -> str:
    """Return the importable module name: lowercase, underscores, not hyphens.

    E.g.  my-package  →  my_package   (correct for Python imports)
    """
    return name.lower().replace("-", "_")


def _cli_command_name(name: str) -> str:
    """Return the CLI command name: lowercase, hyphens (conventional for shell tools)."""
    return name.lower().replace("_", "-")


_ENTRY_POINT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)


def validate_entry_point(value: str) -> str | None:
    """Validate a PEP 517 entry point string of the form ``module.path:callable``.

    Returns None if valid.  Returns an error message string if invalid.

    Valid examples:   mypkg.main:main   mypkg.cli:app
    Invalid examples: my-pkg.main:main  (hyphen in module path)
                      mypkg.main        (missing colon + callable)
    """
    if not value:
        return "Entry point cannot be empty."
    if not _ENTRY_POINT_RE.match(value):
        return (
            f"Invalid entry point: {value!r}. "
            "Expected format: module.path:callable  "
            "(underscores only — hyphens are not valid in Python import paths)."
        )
    return None


def make_default_entry_point(name: str) -> str:
    """Return a valid default entry point derived from the package name.

    E.g.  my-package  →  my_package.main:main
    """
    return f"{_module_name(name)}.main:main"


def generate_pyproject(
    name: str,
    version: str,
    description: str,
    author: str,
    email: str,
    dependencies: list[str],
    license_text: str = "MIT",
    keywords: list[str] | None = None,
    classifiers: list[str] | None = None,
    homepage: str = "",
    cli_script_value: str = "",
    project_root: Path | None = None,
) -> None:
    """Update (or create) pyproject.toml in *project_root* using tomlkit.

    SURGICAL MODE (file exists): only PiPnDeploy-owned fields inside
    [project] are touched. Every other section ([tool.hatch], [tool.pytest],
    [build-system], optional-dependencies, gui-scripts, custom classifiers,
    comments, formatting) is preserved exactly as-is.  Values are serialised
    by tomlkit so quotes/special characters in strings are always safe.

    CREATE MODE (no file): writes a minimal PEP 621-compliant pyproject.toml.

    PEP 639: license is a plain SPDX string.  Any ``License ::`` classifiers
    are stripped — mutually exclusive with the SPDX field in setuptools 69+.
    """
    root      = project_root or Path.cwd()
    toml_path = root / "pyproject.toml"
    kw_list   = keywords or []

    # Strip License classifiers per PEP 639
    raw_cls  = list(classifiers) if classifiers else [
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ]
    cls_list = [c for c in raw_cls if not c.startswith("License ::")]

    if toml_path.exists():
        # ── SURGICAL MODE ─────────────────────────────────────────────────────
        doc  = tomlkit.parse(toml_path.read_text(encoding="utf-8"))
        proj = doc.get("project")
        if proj is None:
            # Malformed file — add a [project] table rather than crash
            log.warning("⚠️  No [project] table found — adding one.")
            doc["project"] = tomlkit.table()
            proj = doc["project"]

        # Scalar fields — tomlkit handles escaping automatically
        # Normalise distribution name: lowercase, hyphens (PEP 625 / PyPI convention).
        proj["name"]        = _distribution_name(name)
        proj["version"]     = version
        proj["description"] = description
        proj["license"]     = license_text   # replaces dict form too

        # Authors array
        author_item = tomlkit.inline_table()
        author_item.append("name",  author)
        author_item.append("email", email)
        proj["authors"] = [author_item]

        # Array fields — assign as plain Python lists; tomlkit serialises safely
        proj["dependencies"] = list(dependencies)
        proj["keywords"]     = list(kw_list)

        # Classifiers — only update if caller explicitly passed them
        if classifiers is not None:
            proj["classifiers"] = list(cls_list)

        # Homepage URL only — leave Repository, Bug Tracker, etc. untouched.
        # Only write/update when the user actually provided a URL.
        if homepage:
            if "urls" not in proj:
                urls_tbl = tomlkit.table()
                urls_tbl.add("Homepage", homepage)
                proj.add("urls", urls_tbl)
            else:
                proj["urls"]["Homepage"] = homepage

        toml_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        log.info("✅ Surgically updated pyproject.toml (license: %s)", license_text)

    else:
        # ── CREATE MODE ───────────────────────────────────────────────────────
        doc = tomlkit.document()

        # [project]
        proj = tomlkit.table()
        # Normalise distribution name: lowercase, hyphens (PEP 625 / PyPI convention).
        proj.add("name",           _distribution_name(name))
        proj.add("version",        version)
        proj.add("description",    description)
        proj.add("readme",         "README.md")
        proj.add("requires-python",">=3.11")
        proj.add("license",        license_text)

        author_item = tomlkit.inline_table()
        author_item.append("name",  author)
        author_item.append("email", email)
        proj.add("authors", [author_item])

        dep_arr = tomlkit.array()
        for d in dependencies:
            dep_arr.append(d)
        proj.add("dependencies", dep_arr)

        kw_arr = tomlkit.array()
        for k in kw_list:
            kw_arr.append(k)
        proj.add("keywords", kw_arr)

        cls_arr = tomlkit.array()
        for c in cls_list:
            cls_arr.append(c)
        proj.add("classifiers", cls_arr)

        doc.add("project", proj)

        # [project.urls] — only written when the user provided a homepage URL.
        # Omitting it avoids injecting placeholder URLs into new projects.
        if homepage:
            urls = tomlkit.table()
            urls.add("Homepage",   homepage)
            urls.add("Repository", homepage)
            urls.add("Issues",     f"{homepage}/issues")
            doc.add(tomlkit.nl())
            doc["project"].add("urls", urls)

        # [project.scripts]
        # Distribution name uses hyphens (PyPI convention).
        # The module path in the entry point must use underscores (Python import).
        cmd   = _cli_command_name(name)          # shell command: my-package
        ep    = cli_script_value or make_default_entry_point(name)
        err   = validate_entry_point(ep)
        if err:
            log.warning("⚠️  Entry point may be invalid: %s — %s", ep, err)
        scripts = tomlkit.table()
        scripts.add(cmd, ep)
        doc["project"].add("scripts", scripts)

        # [build-system]
        build = tomlkit.table()
        build.add("requires",       ["setuptools>=68", "wheel"])
        build.add("build-backend",  "setuptools.build_meta")
        doc.add(tomlkit.nl())
        doc.add("build-system", build)

        toml_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        log.info("✅ Created pyproject.toml (license: %s)", license_text)


GITIGNORE_TEMPLATE = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg
*.egg-info/
dist/
build/
eggs/
parts/
var/
sdist/
develop-eggs/
.installed.cfg
lib/
lib64/
wheels/
share/python-wheels/
MANIFEST

# Virtual environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# Testing
.tox/
.nox/
.coverage
.coverage.*
.cache
.pytest_cache/
nosetests.xml
coverage.xml
*.cover
*.py,cover
htmlcov/

# Packaging / distribution
.Python
pip-wheel-metadata/
.eggs/

# IDEs
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
desktop.ini

# PiPnDeploy
*.pyc
"""


def create_gitignore(project_root: Path | None = None) -> None:
    """Write a .gitignore if one does not already exist."""
    root = project_root or Path.cwd()
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
        log.info("✅ Created .gitignore")
    else:
        log.info("🔎 .gitignore already exists — skipping.")


# SPDX id → badge label + colour + OSI URL for the README licence badge.
_LICENSE_BADGES: dict[str, tuple[str, str, str]] = {
    "MIT":                        ("MIT",        "yellow",     "https://opensource.org/licenses/MIT"),
    "Apache-2.0":                 ("Apache%202.0","blue",      "https://opensource.org/licenses/Apache-2.0"),
    "GPL-3.0":                    ("GPL%20v3",   "blue",       "https://www.gnu.org/licenses/gpl-3.0"),
    "LGPL-3.0":                   ("LGPL%20v3",  "blue",       "https://www.gnu.org/licenses/lgpl-3.0"),
    "BSD-3-Clause":               ("BSD%203--Clause","blue",   "https://opensource.org/licenses/BSD-3-Clause"),
    "BSD-2-Clause":               ("BSD%202--Clause","blue",   "https://opensource.org/licenses/BSD-2-Clause"),
    "Mozilla Public License 2.0": ("MPL%202.0",  "brightgreen","https://opensource.org/licenses/MPL-2.0"),
    "ISC":                        ("ISC",        "blue",       "https://opensource.org/licenses/ISC"),
    "The Unlicense":              ("Unlicense",  "blue",       "https://unlicense.org/"),
}


def create_readme(
    project_root: Path | None = None,
    name: str = "",
    description: str = "",
    license_text: str = "MIT",
    homepage: str = "",
) -> None:
    """Write a README.md with correct badges if one does not already exist.

    Uses the normalised distribution name (slug), module name (underscores),
    actual license identifier, and homepage from the caller — not hardcoded values.
    """
    root    = project_root or Path.cwd()
    readme  = root / "README.md"
    if readme.exists():
        log.info("🔎 README.md already exists — skipping.")
        return

    # Normalise names using the same helpers as generate_pyproject
    raw_name    = name or root.name
    slug        = _distribution_name(raw_name)   # my-package  (PyPI/URL)
    module      = _module_name(raw_name)          # my_package  (Python import)
    desc        = description or "A Python package."
    repo_url    = homepage  # empty string → git clone line omitted

    # Build the licence badge — fall back gracefully for unlisted licences
    if license_text in _LICENSE_BADGES:
        lic_label, lic_colour, lic_url = _LICENSE_BADGES[license_text]
    else:
        lic_label  = license_text.replace(" ", "%20")
        lic_colour = "lightgrey"
        lic_url    = "https://opensource.org/licenses/"

    dev_section = (
        f"## Development\n\n"
        f"```bash\n"
        f"git clone {repo_url}\n"
        f"cd {slug}\n"
        f"pip install -e .\n"
        f"```\n\n"
    ) if repo_url else ""

    content = (
        f"# {slug}\n\n"
        f"{desc}\n\n"
        f"[![PyPI version](https://badge.fury.io/py/{slug}.svg)](https://pypi.org/project/{slug}/)\n"
        f"[![Python versions](https://img.shields.io/pypi/pyversions/{slug}.svg)](https://pypi.org/project/{slug}/)\n"
        f"[![License: {license_text}](https://img.shields.io/badge/License-{lic_label}-{lic_colour}.svg)]({lic_url})\n\n"
        f"## Installation\n\n"
        f"```bash\n"
        f"pip install {slug}\n"
        f"```\n\n"
        f"## Usage\n\n"
        f"```python\n"
        f"import {module}\n"
        f"```\n\n"
        f"{dev_section}"
        f"## License\n\n"
        f"{license_text}\n"
    )
    readme.write_text(content, encoding="utf-8")
    log.info("✅ Created README.md")


# ─── pyproject.toml reading ───────────────────────────────────────────────────

def read_pyproject_toml(project_root: Path | None = None) -> dict | None:
    """Parse pyproject.toml and return a flattened dict suitable for the GUI."""
    root = project_root or Path.cwd()
    path = root / "pyproject.toml"
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except Exception as exc:
        log.error("❌ Failed to read pyproject.toml: %s", exc)
        return None

    project = raw.get("project", {})

    # Flatten authors
    authors = project.get("authors", [])
    if authors:
        project["author_name"] = authors[0].get("name", "")
        project["author_email"] = authors[0].get("email", "")

    # Flatten URLs
    urls = project.get("urls", {})
    project["homepage_url"] = urls.get("Homepage", "")

    # Flatten scripts
    scripts = project.get("scripts", {})
    project["cli_script_value"] = next(iter(scripts.values()), "") if scripts else ""

    return project


def get_package_name_from_pyproject(project_root: Path | None = None) -> str:
    """Return the project name from pyproject.toml, or the directory name."""
    root = project_root or Path.cwd()
    data = read_pyproject_toml(root)
    if data:
        return data.get("name", root.name)
    return root.name


# ─── Build / deploy / clean ──────────────────────────────────────────────────

def run_hook(
    hook_name: str,
    project_root: Path | None = None,
    python: str | None = None,
) -> bool:
    """Run a lifecycle hook script if it exists.

    Args:
        hook_name:    Name of the hook (e.g. "pre_build", "post_deploy").
        project_root: Project directory containing the hooks/ folder.
        python:       Interpreter to run the hook with. Pass the same
                      interpreter used for building so hooks can import
                      project-local dev tools installed in .venv.
                      Defaults to sys.executable.

    Returns True if the hook ran successfully or did not exist.
    Returns False (and logs an error) if the hook script exited non-zero.
    Unlike the old behaviour, failures are never silently swallowed.
    """
    root = project_root or Path.cwd()
    py   = python or sys.executable
    hook = root / "hooks" / f"{hook_name}.py"
    if not hook.exists():
        return True
    log.info("🔁 Running hook: %s (interpreter: %s)", hook.name, py)
    result = subprocess.run(
        [py, str(hook)],
        cwd=root,
        capture_output=False,
    )
    if result.returncode != 0:
        log.error("❌ Hook %s exited with code %d", hook.name, result.returncode)
        return False
    log.info("✅ Hook %s completed.", hook.name)
    return True


def create_virtualenv(project_root: Path | None = None) -> None:
    root = project_root or Path.cwd()
    venv = root / ".venv"
    if not venv.exists():
        log.info("🧪 Creating .venv…")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        log.info("✅ .venv created.")
    else:
        log.info("📦 .venv already exists.")


def _venv_python(project_root: Path) -> Path:
    venv = project_root / ".venv"
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _tool_is_available(python: str, tool: str) -> bool:
    """Return True if *tool* is importable by the given Python interpreter."""
    result = subprocess.run(
        [python, "-m", tool, "--version"],
        capture_output=True,
    )
    return result.returncode == 0


def _ensure_tool(tool: str, python: str) -> None:
    """Install *tool* via pip into *python* if it is not already available."""
    if _tool_is_available(python, tool):
        log.debug("🔎 %s already present — skipping install.", tool)
        return
    log.info("📦 Installing missing tool: %s", tool)
    subprocess.run([python, "-m", "pip", "install", tool], check=True)


def ensure_build_tool(python: str | None = None) -> None:
    """Ensure the ``build`` package is available for the given interpreter.

    Called by ``build_package()`` only — does not install twine unnecessarily.
    """
    _ensure_tool("build", python or sys.executable)


def ensure_twine_tool(python: str | None = None) -> None:
    """Ensure ``twine`` is available for the given interpreter.

    Called by ``upload_to_pypi()`` only — does not install build unnecessarily.
    """
    _ensure_tool("twine", python or sys.executable)


def install_build_tools(python: str | None = None) -> None:
    """Ensure both build and twine are available.

    Kept for backward compatibility. Prefer ``ensure_build_tool()`` and
    ``ensure_twine_tool()`` in new code so each step installs only what it needs.
    """
    py = python or sys.executable
    ensure_build_tool(py)
    ensure_twine_tool(py)


def build_package(
    use_venv: bool = False,
    project_root: Path | None = None,
    python: str | None = None,
) -> str:
    """Build wheel + sdist. Returns the Python interpreter path that was used.

    The returned interpreter should be passed to ``upload_to_pypi(python=...)``
    so that build and deploy always use the same Python environment — avoids
    the mismatch where build uses .venv but twine is looked up on sys.executable.

    Args:
        use_venv: If True, locate and use the project .venv interpreter.
        project_root: Project directory (default: cwd).
        python: Explicit interpreter path. Overrides use_venv when provided.
    """
    root = project_root or Path.cwd()
    # Resolve interpreter before running the hook so both steps use the same env.
    if python:
        py = python
    elif use_venv:
        py = str(_venv_python(root))
    else:
        py = sys.executable
    if not run_hook("pre_build", root, python=py):
        raise RuntimeError("❌ pre_build hook failed — aborting build.")
    log.info("📦 Building package…")
    ensure_build_tool(py)   # only build is needed here; twine is for upload
    subprocess.run([py, "-m", "build"], check=True, cwd=root)
    log.info("📦 Build complete (interpreter: %s)", py)
    return py


def upload_to_pypi(
    use_testpypi: bool = False,
    dry_run: bool = False,
    project_root: Path | None = None,
    python: str | None = None,
) -> str | None:
    """Upload dist/* to PyPI or TestPyPI.

    Args:
        use_testpypi: Upload to TestPyPI instead of PyPI.
        dry_run: Skip the actual upload (post_deploy hook also skipped).
        project_root: Project directory (default: cwd).
        python: Interpreter to use for twine. Pass the value returned by
                ``build_package()`` so build and deploy always use the same
                Python environment. Defaults to sys.executable.

    Hook lifecycle:
      - post_deploy runs AFTER a successful upload only.
      - post_deploy is SKIPPED entirely on dry-run.
      - pre_build is handled by build_package, not here.
    """
    root   = project_root or Path.cwd()
    py     = python or sys.executable
    target = "TestPyPI" if use_testpypi else "PyPI"

    if dry_run:
        msg = f"🧪 Dry run — skipping upload to {target}. (post_deploy hook not run)"
        log.info(msg)
        return msg

    # Pre-flight auth check — fail fast before twine can prompt interactively
    ok, err_msg = auth_check_for_target(use_testpypi)
    if not ok:
        raise RuntimeError(err_msg)

    ensure_twine_tool(py)   # only twine is needed here; build is for build_package
    repo_args = ["--repository", "testpypi"] if use_testpypi else []
    log.info("🚀 Uploading to %s (interpreter: %s)…", target, py)
    subprocess.run(
        [py, "-m", "twine", "upload", "--non-interactive"]
        + repo_args + ["dist/*"],
        check=True,
        cwd=root,
    )
    log.info("✅ Upload to %s complete.", target)

    # post_deploy runs only after a confirmed successful upload,
    # using the same interpreter as the build step.
    if not run_hook("post_deploy", root, python=py):
        log.warning("⚠️  post_deploy hook failed — upload succeeded but hook did not.")

    return None


def _purge_pyc(root: Path) -> None:
    """Recursively remove __pycache__ dirs and .pyc files under *root*.

    Skips:
    - Directories in ``_CLEAN_EXCLUDE_DIRS`` (virtual environments, VCS internals).
    - Any dot-directory (e.g. ``.mypy_cache``, ``.tox``) — these are always
      managed by external tools and must not be mutated by clean.
    """
    for item in root.iterdir():
        if not item.is_dir() and not (item.is_file() and item.suffix == ".pyc"):
            continue
        if item.is_dir() and (
            item.name in _CLEAN_EXCLUDE_DIRS or item.name.startswith(".")
        ):
            log.debug("🔎 Skipping excluded dir during purge: %s", item.name)
            continue
        if item.is_dir():
            if item.name == "__pycache__":
                shutil.rmtree(item)
                log.debug("🗑️  Removed %s", item)
            else:
                _purge_pyc(item)   # recurse into project-owned dirs
        elif item.is_file() and item.suffix == ".pyc":
            try:
                item.unlink()
                log.debug("🗑️  Removed %s", item)
            except Exception:
                pass


def clean_project(
    uninstall: bool = False,
    purge_pyc: bool = True,
    interactive: bool = False,
    project_root: Path | None = None,
) -> None:
    """Remove build artefacts and optionally uninstall the package.

    Default changed: uninstall=False.  Uninstalling is destructive and
    should always be an explicit opt-in, not the default behaviour.
    """
    root = project_root or Path.cwd()
    name = get_package_name_from_pyproject(root)

    def confirm(msg: str) -> bool:
        if not interactive:
            return True
        answer = input(f"{msg} [y/N] ").strip().lower()
        return answer.startswith("y")

    if uninstall:
        # Always show exactly what will be uninstalled and from which interpreter
        log.info(
            "⚠️  About to uninstall '%s' from interpreter: %s",
            name, sys.executable,
        )
        if confirm(f"Uninstall '{name}' from {sys.executable}?"):
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", name])
            log.info("🗑️  Uninstalled %s", name)
        else:
            log.info("🔎 Uninstall skipped.")

    for folder in ("build", "dist"):
        p = root / folder
        if p.exists() and confirm(f"Remove {folder}/?"):
            shutil.rmtree(p)
            log.info("🗑️  Removed %s/", folder)

    for egg in root.glob("*.egg-info"):
        if egg.is_dir() and confirm(f"Remove {egg.name}/?"):
            shutil.rmtree(egg)
            log.info("🗑️  Removed %s", egg.name)

    if purge_pyc and confirm("Remove __pycache__ and .pyc files?"):
        _purge_pyc(root)
        log.info("🧼  Purged .pyc and __pycache__")


def auth_check() -> tuple[bool, list[str]]:
    """Validate ~/.pypirc token configuration.

    Returns (success, list_of_human_readable_messages).
    """
    messages: list[str] = []
    pypirc = Path.home() / ".pypirc"

    if not pypirc.exists():
        messages.append(f"❌ .pypirc not found (expected: {pypirc})")
        return False, messages

    messages.append(f"✅ Found .pypirc at: {pypirc}")
    config = configparser.ConfigParser()
    config.read(pypirc)

    if "distutils" not in config or "index-servers" not in config["distutils"]:
        messages.append("⚠️  Missing [distutils] section or index-servers key.")
        return False, messages

    servers = config["distutils"]["index-servers"].split()
    if not servers:
        messages.append("⚠️  No repositories listed under index-servers.")
        return False, messages

    messages.append("📦 Configured repositories:")
    all_ok = True

    for server in servers:
        messages.append(f"  • [{server}]")
        if server not in config:
            messages.append(f"    ❌ Section [{server}] missing.")
            all_ok = False
            continue

        repo = config[server].get("repository", "")
        user = config[server].get("username", "")
        pw   = config[server].get("password", "")
        messages.append(f"    Repository : {repo}")

        if user != "__token__":
            messages.append(f"    ⚠️  Username should be '__token__', got: {user!r}")
            all_ok = False
        else:
            messages.append("    Username   : __token__ ✅")

        if not pw.startswith("pypi-"):
            messages.append("    ⚠️  Password does not look like a valid API token (should start with 'pypi-')")
            all_ok = False
        else:
            messages.append(f"    Password   : pypi-{'*' * 8} ✅")

    summary = "✅ Auth check passed." if all_ok else "⚠️  Auth check found issues — review above."
    messages.append(summary)
    return all_ok, messages



def auth_check_for_target(use_testpypi: bool = False) -> tuple[bool, str]:
    """Focused pre-flight: does .pypirc have valid auth for the target repo?

    Returns (ok, error_message). If ok is True, error_message is empty.
    Used by upload_to_pypi before spawning twine — prevents interactive
    token prompts when config is missing or malformed.
    """
    target_section = "testpypi" if use_testpypi else "pypi"
    target_label   = "TestPyPI" if use_testpypi else "PyPI"
    pypirc = Path.home() / ".pypirc"

    if not pypirc.exists():
        return False, f"❌ .pypirc not found. Use the Auth Gen tab to create it."

    config = configparser.ConfigParser()
    config.read(pypirc)

    # Check the section exists
    if target_section not in config:
        return False, (
            f"❌ [{target_section}] section missing from .pypirc. "
            f"Add your {target_label} API token via the Auth Gen tab."
        )

    user = config[target_section].get("username", "")
    pw   = config[target_section].get("password", "")

    if user != "__token__":
        return False, f"❌ [{target_section}] username should be '__token__', got: {user!r}"

    if not pw.startswith("pypi-"):
        return False, (
            f"❌ [{target_section}] password does not look like a valid API token "
            f"(should start with 'pypi-'). Re-enter your token in the Auth Gen tab."
        )

    return True, ""

# ─── Version management ───────────────────────────────────────────────────────

def get_current_version(project_root: Path | None = None) -> str | None:
    """Return the version string from pyproject.toml, or None if not found."""
    data = read_pyproject_toml(project_root)
    if data:
        return data.get("version") or None
    return None


def bump_version(
    part: str,
    project_root: Path | None = None,
    set_version: str | None = None,
) -> tuple[str, str]:
    """Increment the version in pyproject.toml and return (old_version, new_version).

    Args:
        part:         "patch", "minor", or "major" — which segment to increment.
                      Ignored when *set_version* is provided.
        project_root: Project directory (default: cwd).
        set_version:  If given, write this exact version string instead of bumping.

    Raises:
        FileNotFoundError: No pyproject.toml in project_root.
        ValueError:        Version string is missing or not semver-shaped,
                           or *part* is not one of patch/minor/major,
                           or *set_version* is not a valid semver string.
    """
    root = project_root or Path.cwd()
    toml_path = root / "pyproject.toml"

    if not toml_path.exists():
        raise FileNotFoundError(f"❌ No pyproject.toml found in {root}")

    current = get_current_version(root)
    if not current:
        raise ValueError("❌ Could not read current version from pyproject.toml")

    # Parse semver — accept "1.2.3" or "1.2.3.post1" etc. but only bump major.minor.patch
    semver_re = re.compile(r"^(\d+)\.(\d+)\.(\d+)(.*)?$")
    m = semver_re.match(current)
    if not m:
        raise ValueError(
            f"❌ Version '{current}' is not semver-shaped (expected X.Y.Z). "
            "Edit it manually in pyproject.toml first."
        )

    major, minor, patch, suffix = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or ""

    if set_version is not None:
        if not semver_re.match(set_version):
            raise ValueError(f"❌ '{set_version}' is not a valid semver string (expected X.Y.Z)")
        new_version = set_version
    else:
        part = part.lower()
        if part == "patch":
            new_version = f"{major}.{minor}.{patch + 1}"
        elif part == "minor":
            new_version = f"{major}.{minor + 1}.0"
        elif part == "major":
            new_version = f"{major + 1}.0.0"
        else:
            raise ValueError(f"❌ Unknown part '{part}' — use 'patch', 'minor', or 'major'")

    # Use tomlkit for safe in-place version update — preserves all formatting
    content = toml_path.read_text(encoding="utf-8")
    doc     = tomlkit.parse(content)
    proj    = doc.get("project")
    if proj is None or "version" not in proj:
        raise ValueError("❌ Could not locate [project].version in pyproject.toml")
    proj["version"] = new_version
    toml_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    log.info("✅ Version bumped: %s → %s", current, new_version)
    return current, new_version

# ─── Package skeleton creation ───────────────────────────────────────────────

def create_package_skeleton(
    name: str,
    project_root: Path | None = None,
) -> bool:
    """Create a minimal importable package skeleton if it does not already exist.

    Creates:
        <project_root>/<module_name>/__init__.py
        <project_root>/<module_name>/main.py

    Returns True if files were created, False if the package already existed.
    This means ``pipndeploy init`` can be used on both brand-new projects
    (where it creates the scaffold) and existing projects (where it only
    generates packaging metadata).
    """
    root   = project_root or Path.cwd()
    module = _module_name(name)
    pkg    = root / module

    dist = _distribution_name(name)

    if pkg.exists():
        # Folder exists — check whether it is complete.
        # Create any missing files without touching existing ones.
        created_any = False
        if not (pkg / "__init__.py").exists():
            (pkg / "__init__.py").write_text(
                f'''"""Top-level package for {dist}."""\n''',
                encoding="utf-8",
            )
            log.info("✅ Created missing %s/__init__.py", module)
            created_any = True
        if not (pkg / "main.py").exists():
            (pkg / "main.py").write_text(
                f'''"""Entry point for {dist}."""\n\n\ndef main() -> None:\n    print("Hello from {dist}")\n\n\nif __name__ == "__main__":\n    main()\n''',
                encoding="utf-8",
            )
            log.info("✅ Created missing %s/main.py", module)
            created_any = True
        if not created_any:
            log.info("🔎 Package folder %s/ already complete — skipping.", module)
        return created_any

    pkg.mkdir(parents=True)

    (pkg / "__init__.py").write_text(
        f'''"""Top-level package for {dist}."""\n''',
        encoding="utf-8",
    )

    (pkg / "main.py").write_text(
        f'''"""Entry point for {dist}."""\n\n\ndef main() -> None:\n    print("Hello from {dist}")\n\n\nif __name__ == "__main__":\n    main()\n''',
        encoding="utf-8",
    )

    log.info("✅ Created package skeleton: %s/__init__.py + %s/main.py", module, module)
    return True


# ─── Project root resolver ───────────────────────────────────────────────────

def resolve_project_root(project_dir: str = "") -> Path:
    """Resolve and validate a project directory path.

    Args:
        project_dir: String path from CLI ``--project-dir`` option.
                     Empty string means "use the current working directory".

    Returns the resolved, validated Path.

    Raises:
        FileNotFoundError:  The path does not exist.
        NotADirectoryError: The path exists but is not a directory.
    """
    root = Path(project_dir).resolve() if project_dir else Path.cwd()
    if not root.exists():
        raise FileNotFoundError(
            f"❌ Project directory does not exist: {root}"
        )
    if not root.is_dir():
        raise NotADirectoryError(
            f"❌ Project path is not a directory: {root}"
        )
    return root


# ─── .pypirc generation ──────────────────────────────────────────────────────

def generate_pypirc(
    pypi_token: str = "",
    testpypi_token: str = "",
    overwrite: bool = False,
    backup: bool = True,
) -> Path:
    """Write a ``~/.pypirc`` file with the supplied API tokens.

    Args:
        pypi_token:     PyPI API token (starts with ``pypi-``). Omitted if empty.
        testpypi_token: TestPyPI API token. Omitted if empty.
        overwrite:      If False (default) and ``~/.pypirc`` already exists,
                        raises ``FileExistsError`` instead of overwriting.
        backup:         If True (default) and an existing file is being overwritten,
                        a backup is saved as ``~/.pypirc.bak`` first.

    Returns the Path to the written file.

    Raises:
        ValueError:      Neither token was supplied.
        FileExistsError: ``~/.pypirc`` exists and ``overwrite=False``.
    """
    if not pypi_token and not testpypi_token:
        raise ValueError("❌ At least one API token (pypi or testpypi) is required.")

    pypirc = Path.home() / ".pypirc"

    if pypirc.exists() and not overwrite:
        raise FileExistsError(
            f"❌ ~/.pypirc already exists at {pypirc}. "
            "Pass overwrite=True to replace it (a backup will be saved automatically)."
        )

    if pypirc.exists() and backup:
        bak = pypirc.with_name(".pypirc.bak")
        shutil.copy2(pypirc, bak)
        log.info("🔎 Backed up existing .pypirc → %s", bak)

    # Only list servers that actually have a token
    servers: list[str] = []
    if pypi_token:
        servers.append("pypi")
    if testpypi_token:
        servers.append("testpypi")

    config = configparser.ConfigParser()
    config["distutils"] = {"index-servers": "\n    " + "\n    ".join(servers)}

    if pypi_token:
        config["pypi"] = {
            "repository": "https://upload.pypi.org/legacy/",
            "username":   "__token__",
            "password":   pypi_token,
        }
    if testpypi_token:
        config["testpypi"] = {
            "repository": "https://test.pypi.org/legacy/",
            "username":   "__token__",
            "password":   testpypi_token,
        }

    with open(pypirc, "w") as fh:
        config.write(fh)

    # Restrict permissions on Unix-like systems
    if os.name != "nt":
        os.chmod(pypirc, 0o600)
        log.info("🔎 Set .pypirc permissions to 600 (owner read/write only).")

    log.info("✅ .pypirc generated at %s", pypirc)
    log.warning("⚠️  API tokens are stored in plaintext. Keep this file private.")
    return pypirc


# ─── High-level command wrappers (used by GUI + CLI) ─────────────────────────
# These are the only symbols the GUI and CLI need to import.

def init_project_command(
    name: str,
    version: str,
    description: str,
    author: str,
    email: str,
    dependencies: list[str],
    license_text: str = "MIT",
    keywords: list[str] | None = None,
    classifiers: list[str] | None = None,
    homepage: str = "",
    cli_script_value: str = "",
    project_root: Path | None = None,
    gen_gitignore: bool = True,
    gen_package: bool = False,
) -> list[str]:
    """Initialise packaging metadata for a Python project.

    Args:
        gen_package: If True, create a minimal package skeleton
                     (<module>/__init__.py + <module>/main.py) when it does
                     not already exist. Safe to pass True for both new and
                     existing projects — skeleton creation is skipped if the
                     package folder already exists.
    """
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise ValueError("❌ Invalid email format.")

    # Normalise the entry point — catch the common mistake of using hyphens
    # in the module path (e.g. my-package.main:main is not valid Python).
    ep = cli_script_value or make_default_entry_point(name)
    err = validate_entry_point(ep)
    if err:
        raise ValueError(f"❌ {err}")
    cli_script_value = ep

    if gen_package:
        create_package_skeleton(name, project_root)
    create_readme(project_root, name=name, description=description,
                 license_text=license_text, homepage=homepage)
    if gen_gitignore:
        create_gitignore(project_root)
    generate_pyproject(
        name, version, description, author, email, dependencies,
        license_text, keywords, classifiers, homepage, cli_script_value,
        project_root=project_root,
    )
    return dependencies


def build_package_command(project_root: Path | None = None) -> None:
    build_package(project_root=project_root)


def deploy_package_command(
    testpypi: bool = False,
    dry_run: bool = False,
    project_root: Path | None = None,
    use_venv: bool = False,
) -> str | None:
    """Build then upload, using the same interpreter for both steps."""
    py = build_package(use_venv=use_venv, project_root=project_root)
    return upload_to_pypi(
        use_testpypi=testpypi, dry_run=dry_run,
        project_root=project_root, python=py,
    )


def clean_project_command(
    uninstall: bool = False,
    purge_pyc: bool = True,
    interactive: bool = False,
    project_root: Path | None = None,
) -> None:
    clean_project(uninstall, purge_pyc, interactive, project_root)


def run_full_pipeline(
    name: str,
    version: str,
    description: str,
    author: str,
    email: str,
    auto_deps: bool = True,
    dry_run: bool = True,
    use_testpypi: bool = True,
    license_text: str = "MIT",
    keywords: list[str] | None = None,
    classifiers: list[str] | None = None,
    homepage: str = "",
    cli_script_value: str = "",
    project_root: Path | None = None,
    gen_package: bool = False,
) -> str | None:
    """Run the full init → build → deploy pipeline.

    Delegates init to ``init_project_command()`` so the CLI, GUI, and
    programmatic API all share the same logic rather than duplicating it here.
    """
    taken_pypi, _ = check_name_availability(name)
    if taken_pypi:
        raise ValueError(f"❌ Package name '{name}' is already taken on PyPI.")
    deps = detect_dependencies(project_root) if auto_deps else []
    init_project_command(
        name=name, version=version, description=description,
        author=author, email=email, dependencies=deps,
        license_text=license_text, keywords=keywords, classifiers=classifiers,
        homepage=homepage, cli_script_value=cli_script_value,
        project_root=project_root,
        gen_gitignore=True, gen_package=gen_package,
    )
    create_virtualenv(project_root)
    py = build_package(use_venv=True, project_root=project_root)
    return upload_to_pypi(
        use_testpypi=use_testpypi, dry_run=dry_run,
        project_root=project_root, python=py,
    )
