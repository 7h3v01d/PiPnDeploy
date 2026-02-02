# pipndeploy_v2.2_alpha.py
#!/usr/bin/env python3

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
import ast
import site
from pathlib import Path
from core_logic import get_package_name_from_pyproject
import typer

try:
    import tomllib  # Python 3.11+
except ImportError:
    print("❌ Python 3.11+ is required for TOML support.")
    sys.exit(1)

app = typer.Typer()
PROJECT_ROOT = Path.cwd()
SCRIPT_NAME = Path(__file__).name
VENV_DIR = PROJECT_ROOT / ".venv"

# -----------------------
# Utility Functions
# -----------------------

def run_hook(hook_name: str):
    """Run pre/post build or deploy hooks if present."""
    hook_path = PROJECT_ROOT / "hooks" / f"{hook_name}.py"
    if hook_path.exists():
        typer.echo(f"🔁 Running hook: {hook_name}.py")
        subprocess.run([sys.executable, str(hook_path)], check=False)

def _is_taken_via_json(package_name: str, base_url: str) -> bool | None:
    """Try JSON API to check for package existence."""
    url = f"{base_url}/{package_name}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipndeploy/2.2"})
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
    except Exception:
        pass
    return None

def _is_taken_via_html(package_name: str, base_url: str) -> bool | None:
    """Fallback: use regex on the HTML page."""
    url = f"{base_url}/{package_name}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipndeploy/2.2"})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode("utf-8", errors="ignore")
            not_found = re.search(r"We looked everywhere but couldn['’]t find this page", html, re.IGNORECASE)
            return False if not_found else True
    except Exception:
        pass
    return None

def check_name_availability(name: str) -> tuple[bool | None, bool | None]:
    """Check if package name is taken on PyPI/TestPyPI using both JSON and HTML fallback."""
    pypi = _is_taken_via_json(name, "https://pypi.org/pypi") or _is_taken_via_html(name, "https://pypi.org/project")
    test = _is_taken_via_json(name, "https://test.pypi.org/pypi") or _is_taken_via_html(name, "https://test.pypi.org/project")
    return (pypi, test)

def create_virtualenv():
    """Create an isolated .venv if not exists."""
    if not VENV_DIR.exists():
        typer.echo("🧪 Creating local virtual environment (.venv)...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    else:
        typer.echo("📦 Virtualenv already exists.")

def install_build_tools(venv: bool = False):
    python = VENV_DIR / "Scripts" / "python.exe" if os.name == "nt" and venv else \
             VENV_DIR / "bin" / "python" if venv else sys.executable
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "build", "twine"], check=True)

def build_package(venv: bool = False):
    run_hook("pre_build")
    typer.echo("📦 Building package...")
    python = VENV_DIR / "Scripts" / "python.exe" if os.name == "nt" and venv else \
             VENV_DIR / "bin" / "python" if venv else sys.executable
    subprocess.run([str(python), "-m", "build"], check=True)

def upload_to_pypi(use_testpypi: bool = False, dry_run: bool = False):
    run_hook("post_deploy")
    if dry_run:
        typer.echo("🧪 Dry run only — build complete, skipping upload.")
        return

    repo_args = ["--repository", "testpypi"] if use_testpypi else []
    typer.echo(f"🚀 Uploading to {'TestPyPI' if use_testpypi else 'PyPI'}...")
    subprocess.run([sys.executable, "-m", "twine", "upload"] + repo_args + ["dist/*"], check=True)

def generate_pyproject(name, version, description, author, email, dependencies):
    content = textwrap.dedent(f"""
    [project]
    name = "{name}"
    version = "{version}"
    description = "{description}"
    authors = [{{ name="{author}", email="{email}" }}]
    readme = "README.md"
    requires-python = ">=3.7"
    dependencies = [{', '.join(f'"{dep}"' for dep in dependencies)}]

    [build-system]
    requires = ["setuptools", "wheel"]
    build-backend = "setuptools.build_meta"
    """).strip()
    with open("pyproject.toml", "w") as f:
        f.write(content)
    typer.echo("✅ Generated pyproject.toml")

def create_readme():
    with open("README.md", "w") as f:
        f.write("# Project Title\n\nDescribe your project here.")
    typer.echo("✅ Created README.md")

def is_standard_library(module_name: str) -> bool:
    if module_name in sys.builtin_module_names:
        return True
    try:
        spec = __import__(module_name, fromlist=[""]).__spec__
        if spec and spec.origin and any(path in spec.origin for path in site.getsitepackages()):
            return False
        return True
    except ImportError:
        return False
    except AttributeError:
        return True
    except Exception:
        return False

def detect_dependencies() -> list[str]:
    """Detects dependencies from import statements in Python files."""
    typer.echo("🔎 Automatically detecting dependencies...")
    dependencies = set()
    name_map = {
        "PIL": "Pillow",
        "bs4": "beautifulsoup4",
        "typer": "typer",
        "tomllib": "tomllib",
        # Add more mappings here as needed
    }
    
    for path in PROJECT_ROOT.rglob("*.py"):
        if path.is_file() and path.name != SCRIPT_NAME:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=path)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                if not is_standard_library(alias.name):
                                    dependencies.add(name_map.get(alias.name, alias.name))
                        elif isinstance(node, ast.ImportFrom) and node.level == 0:
                            if not is_standard_library(node.module):
                                dependencies.add(name_map.get(node.module, node.module))
            except Exception as e:
                typer.echo(f"⚠️ Could not parse file {path}: {e}")
    
    return sorted(list(dependencies))

# -----------------------
# CLI Commands
# -----------------------

@app.command()
def init(
    name: str = typer.Option(..., help="Package name"),
    version: str = typer.Option("0.1.0", help="Initial version"),
    description: str = typer.Option("A handy Python utility", help="Short description"),
    author: str = typer.Option(..., help="Author name"),
    email: str = typer.Option(..., help="Author email"),
    deps: str = typer.Option("", help="Comma-separated dependencies"),
    auto_deps: bool = typer.Option(False, "--auto-deps", help="Auto-detect dependencies"),
):
    """
    🛠 Initialize a new pyproject.toml and README.md
    """
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        typer.secho("❌ Invalid email format.", fg=typer.colors.RED)
        raise typer.Exit(1)

    taken_pypi, taken_test = check_name_availability(name)
    typer.echo(f"🔎 Checking availability for '{name}'...")
    if taken_pypi is True:
        typer.echo(f"❌ Already taken on PyPI: https://pypi.org/project/{name}/")
    elif taken_pypi is False:
        typer.echo("✅ Available on PyPI")

    if taken_test is True:
        typer.echo(f"❌ Already taken on TestPyPI: https://test.pypi.org/project/{name}/")
    elif taken_test is False:
        typer.echo("✅ Available on TestPyPI")

    if taken_pypi or taken_test:
        typer.echo("💡 Consider using a suffix:")
        typer.echo(f"   → {name}-dev / {name}-toolkit / {name}-yourname")

    dependencies = []
    if auto_deps:
        dependencies = detect_dependencies()
        typer.echo(f"✨ Detected: {', '.join(dependencies)}")
    else:
        dependencies = [d.strip() for d in deps.split(",") if d.strip()]

    create_readme()
    generate_pyproject(name, version, description, author, email, dependencies)

@app.command()
def build(
    use_venv: bool = typer.Option(True, "--venv", help="Build inside a local virtualenv if available")
):
    """
    📦 Build the package (wheel and sdist)
    """
    run_hook("pre_build")

    if use_venv and not Path(".venv").exists():
        typer.secho("⚠️ No .venv detected. Run 'pipndeploy create-venv' to initialize.", fg=typer.colors.YELLOW)
    else:
        activate_path = Path(".venv/Scripts/activate") if os.name == "nt" else Path(".venv/bin/activate")
        if not activate_path.exists():
            typer.secho("⚠️ No activate script found in .venv", fg=typer.colors.RED)
        else:
            typer.echo(f"✅ Using virtualenv: {activate_path.parent}")
    install_build_tools()
    build_package()

@app.command()
def deploy(
    testpypi: bool = typer.Option(False, "--test", "-t", help="Deploy to TestPyPI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate the upload process"),
):
    """
    🚀 Upload the built package to PyPI or TestPyPI
    """
    run_hook("post_deploy")
    upload_to_pypi(use_testpypi=testpypi, dry_run=dry_run)

@app.command()
def clean(
    uninstall: bool = typer.Option(True, help="Uninstall the package if installed"),
    purge_pyc: bool = typer.Option(True, help="Remove __pycache__ and .pyc files"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Prompt before each destructive action")
):
    """
    🧹 Clean build artifacts and optionally uninstall the installed package
    """
    package_name = get_package_name_from_pyproject()
    typer.echo(f"📦 Cleaning package: {package_name}")

    def confirm(message: str) -> bool:
        return typer.confirm(message) if interactive else True

    if uninstall and confirm(f"Uninstall '{package_name}' from current environment?"):
        typer.echo(f"🔧 Uninstalling '{package_name}'...")
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", package_name])

    for folder in ["build", "dist"]:
        path = PROJECT_ROOT / folder
        if path.exists() and confirm(f"Remove folder: {folder}/?"):
            shutil.rmtree(path)
            typer.echo(f"🗑️  Removed {folder}/")

    for item in PROJECT_ROOT.glob("*.egg-info"):
        if item.is_dir() and confirm(f"Remove folder: {item.name}/?"):
            shutil.rmtree(item)
            typer.echo(f"🗑️  Removed {item.name}/")

    if purge_pyc and confirm("Remove __pycache__ and .pyc files?"):
        for pycache in PROJECT_ROOT.rglob("__pycache__"):
            shutil.rmtree(pycache)
            typer.echo(f"🧼  Removed {pycache}")
        for pyc in PROJECT_ROOT.rglob("*.pyc"):
            try:
                pyc.unlink()
                typer.echo(f"🧽  Removed {pyc}")
            except Exception:
                pass

    typer.echo("✅ Clean complete.")

@app.command()
def create_venv():
    """
    🧪 Create a local virtualenv (.venv) for building and testing
    """
    if Path(".venv").exists():
        typer.echo("✅ Virtualenv already exists.")
        return

    typer.echo("📦 Creating virtualenv...")
    subprocess.run([sys.executable, "-m", "venv", ".venv"], check=True)
    typer.echo("✅ Virtualenv created at .venv")


@app.command()
def name_check(name: str = typer.Argument(..., help="Package name to check")):
    """
    🔍 Check if a name is taken on PyPI/TestPyPI
    """
    taken_pypi, taken_test = check_name_availability(name)
    if taken_pypi is True:
        typer.echo(f"❌ {name} is taken on PyPI")
    elif taken_pypi is False:
        typer.echo(f"✅ {name} is available on PyPI")
    else:
        typer.echo("⚠️ Could not determine availability on PyPI")

    if taken_test is True:
        typer.echo(f"❌ {name} is taken on TestPyPI")
    elif taken_test is False:
        typer.echo(f"✅ {name} is available on TestPyPI")
    else:
        typer.echo("⚠️ Could not determine availability on TestPyPI")


@app.command("auth-check")
def auth_check():
    """
    🔐 Validate .pypirc token format
    """
    pypirc_path = Path.home() / ".pypirc"
    if not pypirc_path.exists():
        typer.echo("❌ .pypirc not found.")
        return

    typer.echo(f"✅ Found: {pypirc_path}")
    config = configparser.ConfigParser()
    config.read(pypirc_path)

    if "distutils" not in config or "index-servers" not in config["distutils"]:
        typer.echo("⚠️ Invalid .pypirc structure")
        return

    servers = config["distutils"]["index-servers"].split()
    for server in servers:
        if server not in config:
            typer.echo(f"❌ Section [{server}] missing.")
            continue
        user = config[server].get("username", "")
        pw = config[server].get("password", "")
        typer.echo(f"🔑 {server} – Token Valid: {user == '__token__' and pw.startswith('pypi-')}")


@app.command("full")
def full_pipeline():
    """
    🌀 Run init → build → deploy with interactive prompts
    """
    typer.secho("--- pipndeploy FULL PIPELINE ---", fg=typer.colors.CYAN)
    name = typer.prompt("Package name")
    version = typer.prompt("Version", default="0.1.0")
    description = typer.prompt("Description")
    author = typer.prompt("Author name")
    email = typer.prompt("Author email")

    auto_deps = typer.confirm("Auto-detect dependencies?", default=True)
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        typer.secho("❌ Invalid email.", fg=typer.colors.RED)
        raise typer.Exit(1)

    taken_pypi, taken_test = check_name_availability(name)
    if taken_pypi or taken_test:
        typer.secho("❌ Name taken. Choose another.", fg=typer.colors.RED)
        raise typer.Exit(1)

    deps = detect_dependencies() if auto_deps else []
    typer.echo(f"Dependencies: {', '.join(deps) or 'None'}")

    create_readme()
    generate_pyproject(name, version, description, author, email, deps)

    create_venv()
    build(use_venv=True)

    dry_run = typer.confirm("Run dry-run?", default=True)
    deploy_choice = typer.confirm("Deploy to TestPyPI?", default=True)
    if dry_run:
        upload_to_pypi(use_testpypi=deploy_choice, dry_run=True)
        proceed = typer.confirm("Continue with live deploy?", default=True)
        if not proceed:
            typer.secho("Aborted.", fg=typer.colors.YELLOW)
            return

    upload_to_pypi(use_testpypi=deploy_choice, dry_run=False)
    typer.secho("✅ Done!", fg=typer.colors.GREEN)


# -----------------------
# Entry point
# -----------------------

if __name__ == "__main__":
    app()
