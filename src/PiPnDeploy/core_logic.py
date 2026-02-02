# core_logic.py — Shared logic for CLI and GUI

import ast
import site
import os
import sys
import re
import subprocess
import shutil
import urllib.request
import urllib.error
import textwrap
import configparser
from pathlib import Path
import typer
import importlib.util
import json

try:
    import tomllib
except ImportError:
    raise ImportError("❌ Python 3.11+ is required for TOML support.")


SCRIPT_NAME = Path(__file__).name

_STDLIB_LIST_PATH = Path(__file__).parent / 'stnd_lib.json'
_STANDARD_LIBRARY_MODULES = None

def load_standard_library_modules():
    """Loads the list of standard library modules from a JSON file."""
    global _STANDARD_LIBRARY_MODULES
    if _STANDARD_LIBRARY_MODULES is not None:
        return

    if not _STDLIB_LIST_PATH.exists():
        raise FileNotFoundError(f"❌ The required standard library list file was not found at: {_STDLIB_LIST_PATH}")

    try:
        with open(_STDLIB_LIST_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Convert all module names to lowercase for case-insensitive matching
            _STANDARD_LIBRARY_MODULES = {m.lower() for m in data.get('python_standard_library', [])}
    except json.JSONDecodeError:
        raise ValueError(f"❌ Failed to parse JSON from file: {_STDLIB_LIST_PATH}")

def run_hook(hook_name: str):
    PROJECT_ROOT = Path.cwd()
    hook_path = PROJECT_ROOT / "hooks" / f"{hook_name}.py"
    if hook_path.exists():
        subprocess.run([sys.executable, "-m", "python", str(hook_path)], check=False)

def _is_taken_via_json(package_name: str, base_url: str) -> bool | None:
    url = f"{base_url}/{package_name}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipndeploy/2.2"})
        with urllib.request.urlopen(req) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
    return None

def _is_taken_via_html(package_name: str, base_url: str) -> bool | None:
    url = f"{base_url}/{package_name}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipndeploy/2.2"})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode("utf-8", errors="ignore")
            not_found = re.search(r"We looked everywhere but couldn['’']t find this page", html, re.IGNORECASE)
            return False if not_found else True
    except Exception:
        pass
    return None

def check_name_availability(name: str) -> tuple[bool | None, bool | None]:
    pypi = _is_taken_via_json(name, "https://pypi.org/pypi") or _is_taken_via_html(name, "https://pypi.org/project")
    test = _is_taken_via_json(name, "https://test.pypi.org/pypi") or _is_taken_via_html(name, "https://test.pypi.org/project")
    return (pypi, test)

def create_virtualenv():
    VENV_DIR = Path.cwd() / ".venv"
    if not VENV_DIR.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

def install_build_tools(python: str = None):
    if not python:
        python = sys.executable
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "build", "twine"], check=True)

def build_package(use_venv: bool = False):
    run_hook("pre_build")
    PROJECT_ROOT = Path.cwd()
    VENV_DIR = PROJECT_ROOT / ".venv"
    python = (VENV_DIR / "Scripts" / "python.exe" if os.name == "nt" else VENV_DIR / "bin" / "python") if use_venv else sys.executable
    install_build_tools(python)
    subprocess.run([str(python), "-m", "build"], check=True)

def upload_to_pypi(use_testpypi: bool = False, dry_run: bool = False):
    run_hook("post_deploy")
    if dry_run:
        return "🧪 Dry run only — build complete, skipping upload."

    repo_args = ["--repository", "testpypi"] if use_testpypi else []
    subprocess.run([sys.executable, "-m", "twine", "upload"] + repo_args + ["dist/*"], check=True)
    return None

def generate_pyproject(name, version, description, author, email, dependencies, license_text, keywords, classifiers, homepage, cli_script_value):
    if keywords:
        quoted_keywords = [f'"{k}"' for k in keywords]
        keywords_str = f"[{', '.join(quoted_keywords)}]"
    else:
        keywords_str = "[]"
    
    if classifiers:
        quoted_classifiers = [f'"{c}"' for c in classifiers]
        classifiers_str = f"[{', '.join(quoted_classifiers)}]"
    else:
        classifiers_str = "[]"
    
    command_name = name.lower().replace('_', '-')

    content = textwrap.dedent(f"""
    [project]
    name = "{name}"
    version = "{version}"
    description = "{description}"
    readme = "README.md"
    requires-python = ">=3.7"
    license = {{text = "{license_text}"}}
    authors = [
      {{name="{author}", email="{email}"}}
    ]
    dependencies = [{', '.join(f'"{dep}"' for dep in dependencies)}]
    keywords = {keywords_str}
    classifiers = {classifiers_str}

    [project.urls]
    Homepage = "{homepage}"
    Repository = "{homepage}"
    Issues = "{homepage}/issues"

    [project.scripts]
    {command_name} = "{cli_script_value}"

    [build-system]
    requires = ["setuptools", "wheel"]
    build-backend = "setuptools.build_meta"
    """).strip()
    with open("pyproject.toml", "w") as f:
        f.write(content)

def create_readme():
    with open("README.md", "w") as f:
        f.write("# Project Title\n\nDescribe your project here.")

def is_standard_library(module_name: str) -> bool:
    """
    Checks if a module is part of the standard library using a predefined list.
    """
    load_standard_library_modules()
    
    # 1. Check for built-in modules first (always accurate)
    if module_name in sys.builtin_module_names:
        return True

    # 2. Check against the predefined JSON list (case-insensitive)
    return module_name.lower() in _STANDARD_LIBRARY_MODULES


def get_package_folder_path(project_root: Path) -> Path | None:
    """Finds the package folder within the project root."""
    for item in project_root.iterdir():
        if item.is_dir() and (item / '__init__.py').exists():
            return item
    return None

def detect_dependencies() -> list[str]:
    PROJECT_ROOT = Path.cwd()
    package_folder = get_package_folder_path(PROJECT_ROOT)
    if not package_folder:
        return []

    dependencies = set()
    name_map = {
        "PIL": "Pillow", 
        "bs4": "beautifulsoup4", 
        "typer": "typer", 
        "tomllib": "tomllib",
        "requests": "requests",
        "yaml": "PyYAML",
        "numpy": "numpy",
        "pandas": "pandas"
    }
    
    # Use rglob to recursively find all .py files in the package folder and its subfolders
    for path in package_folder.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        module_name = a.name.split('.')[0]
                        if not is_standard_library(module_name):
                            dependencies.add(name_map.get(module_name, module_name))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    if node.module:
                        module_name = node.module.split('.')[0]
                        if node.module == "__future__": # Special case for __future__
                            continue
                        if not is_standard_library(module_name):
                            dependencies.add(name_map.get(module_name, module_name))
        except Exception:
            # Skip files that can't be parsed (e.g., syntax errors)
            pass
            
    return sorted(dependencies)


def read_pyproject_toml() -> dict | None:
    """Reads and parses the pyproject.toml file."""
    PROJECT_ROOT = Path.cwd()
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                pyproject = tomllib.load(f)
                # Flatten some common structures for easier access in GUI
                project_data = pyproject.get("project", {})
                
                # Handle authors
                authors = project_data.get("authors", [])
                if authors:
                    project_data["author_name"] = authors[0].get("name", "")
                    project_data["author_email"] = authors[0].get("email", "")
                
                # Handle URLs
                urls = project_data.get("urls", {})
                project_data["homepage_url"] = urls.get("Homepage", "")

                # Handle CLI scripts
                scripts = project_data.get("scripts", {})
                if scripts:
                    # Assuming only one CLI script for simplicity, take the first one
                    cli_script_key = list(scripts.keys())[0]
                    project_data["cli_script_value"] = scripts[cli_script_key]
                else:
                    project_data["cli_script_value"] = ""


                return project_data
        except Exception as e:
            print(f"❌ Error reading pyproject.toml: {e}")
            return None
    return None


def get_package_name_from_pyproject() -> str:
    PROJECT_ROOT = Path.cwd()
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)
            return pyproject.get("project", {}).get("name", PROJECT_ROOT.name)
    return PROJECT_ROOT.name

def clean_project(uninstall: bool = True, purge_pyc: bool = True, interactive: bool = False):
    PROJECT_ROOT = Path.cwd()
    name = get_package_name_from_pyproject()
    def confirm(msg): return input(msg + " [y/N] ").lower().startswith("y") if interactive else True
    if uninstall and confirm(f"Uninstall {name}?"):
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", name])
    for folder in ["build", "dist"]:
        p = PROJECT_ROOT / folder
        if p.exists() and confirm(f"Remove {folder}/?"):
            shutil.rmtree(p)
    for egg in PROJECT_ROOT.glob("*.egg-info"):
        if egg.is_dir() and confirm(f"Remove {egg.name}/?"):
            shutil.rmtree(egg)
    if purge_pyc and confirm("Remove pycache and .pyc?"):
        for pc in PROJECT_ROOT.rglob("__pycache__"): shutil.rmtree(pc)
        for pyc in PROJECT_ROOT.rglob("*.pyc"):
            try: pyc.unlink()
            except: pass

def auth_check() -> tuple[bool, list[str]]:
    """
    Checks .pypirc file for correct PyPI/TestPyPI token config.
    Returns (success_status: bool, messages: list[str]).
    """
    messages = []
    pypirc_path = Path.home() / ".pypirc"

    if not pypirc_path.exists():
        messages.append("❌ .pypirc file not found in your home directory.")
        messages.append(f"   Expected at: {pypirc_path} or C:\\Users\\<user>\\.pypirc")
        return False, messages

    messages.append(f"✅ Found .pypirc at: {pypirc_path}")
    config = configparser.ConfigParser()
    config.read(pypirc_path)

    if "distutils" not in config or "index-servers" not in config["distutils"]:
        messages.append("⚠️  Missing [distutils] section or index-servers list.")
        return False, messages

    servers = config["distutils"]["index-servers"].split()
    if not servers:
        messages.append("⚠️  No repositories listed under index-servers.")
        return False, messages

    messages.append("📦 Repositories configured:")
    all_servers_ok = True
    for server in servers:
        messages.append(f"  • [{server}]")
        if server not in config:
            messages.append(f"    ❌ Section [{server}] missing.")
            all_servers_ok = False
            continue
        
        repo = config[server].get("repository", "")
        user = config[server].get("username", "")
        pw = config[server].get("password", "")
        
        messages.append(f"      Repository: {repo}")
        
        if user != "__token__":
            messages.append(f"      ⚠️ Username is not '__token__': {user}")
            all_servers_ok = False
        else:
            messages.append(f"      Username: {user} (OK)")

        if not pw.startswith("pypi-"):
            messages.append(f"      ⚠️ Password does not look like a valid token (should start with 'pypi-'): {pw[:10]}...")
            all_servers_ok = False
        else:
            messages.append(f"      Password: {'pypi-****' if len(pw) > 5 else pw} (looks like token)")

    if all_servers_ok:
        messages.append("✅ Auth config check complete: All configured servers look good.")
    else:
        messages.append("⚠️ Auth config check complete: Some issues detected. Please review warnings/errors above.")
    
    return all_servers_ok, messages


def init_project_command(name, version, description, author, email, dependencies, license_text="MIT", keywords=[], classifiers=[], homepage="https://github.com/yourusername/your-package", cli_script_value=""):
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise ValueError("❌ Invalid email format.")
    create_readme()
    generate_pyproject(name, version, description, author, email, dependencies, license_text, keywords, classifiers, homepage, cli_script_value)
    return dependencies

def check_package_name(name):
    return check_name_availability(name)

def run_full_pipeline(name, version, description, author, email, auto_deps=True, dry_run=True, use_testpypi=True, license_text="MIT", keywords=[], classifiers=[], homepage="https://github.com/yourusername/your-package", cli_script_value=""):
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise ValueError("❌ Invalid email format.")
    if check_name_availability(name)[0]:
        raise ValueError("❌ Package name already taken.")
    deps = detect_dependencies() if auto_deps else []
    create_readme()
    generate_pyproject(name, version, description, author, email, deps, license_text, keywords, classifiers, homepage, cli_script_value)
    create_virtualenv()
    build_package(use_venv=True)
    return upload_to_pypi(use_testpypi=use_testpypi, dry_run=dry_run)

# Expose CLI-compatible functions for GUI

def build_package_command():
    return build_package()

def deploy_package_command(testpypi=False, dry_run=False):
    # This function is now a wrapper that calls build_package and then upload_to_pypi
    # It's kept for backward compatibility with existing calls in the GUI,
    # but the direct call to upload_to_pypi is preferred when build is handled separately.
    build_package() # Ensure package is built before deployment
    return upload_to_pypi(use_testpypi=testpypi, dry_run=dry_run)

def clean_project_command(uninstall=True, purge_pyc=True, interactive=False):
    return clean_project(uninstall, purge_pyc, interactive)