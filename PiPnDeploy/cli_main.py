#!/usr/bin/env python3
# cli_main.py — PiPnDeploy CLI (thin Typer wrapper around core_logic)

import logging
import os
import re
import sys
from pathlib import Path

import typer

try:
    from . import core_logic          # installed / python -m PiPnDeploy.gui_main
except ImportError:
    import core_logic                 # python PiPnDeploy/gui_main.py (direct run)

# ─── Logger ───────────────────────────────────────────────────────────────────
# Wire the package logger to Typer-style output so emoji lines print cleanly.

class _TyperHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if record.levelno >= logging.ERROR:
            typer.secho(msg, fg=typer.colors.RED)
        elif record.levelno >= logging.WARNING:
            typer.secho(msg, fg=typer.colors.YELLOW)
        else:
            typer.echo(msg)

_log = logging.getLogger("pipndeploy")
_log.handlers.clear()
_log.addHandler(_TyperHandler())
_log.setLevel(logging.DEBUG)

# ─── App ─────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="pipndeploy",
    help="🚀 Python packaging made human — init → build → deploy in one tool.",
    no_args_is_help=True,
)


def _cwd() -> Path:
    return Path.cwd()


# ─── Commands ─────────────────────────────────────────────────────────────────

@app.command()
def init(
    name: str = typer.Option(..., prompt=True, help="Package name"),
    version: str = typer.Option("0.1.0", help="Initial version"),
    description: str = typer.Option("A handy Python utility", prompt=True, help="Short description"),
    author: str = typer.Option(..., prompt=True, help="Author name"),
    email: str = typer.Option(..., prompt=True, help="Author email"),
    license_text: str = typer.Option("MIT", help=f"SPDX licence identifier. Options: {', '.join(core_logic.LICENSE_OPTIONS)}"),
    homepage: str = typer.Option("", help="Project homepage URL (optional)"),
    keywords: str = typer.Option("", help="Comma-separated keywords"),
    cli_script: str = typer.Option("", help="CLI entry point, e.g. mypackage.main:main"),
    deps: str = typer.Option("", help="Comma-separated dependencies (ignored when --auto-deps is set)"),
    auto_deps:      bool = typer.Option(False, "--auto-deps",       help="Auto-detect dependencies via AST scan"),
    create_package: bool = typer.Option(False, "--create-package",  help="Create a minimal package skeleton (module/__init__.py + module/main.py)"),
    project_dir:    str  = typer.Option("",    "--project-dir", "-d", help="Project directory (default: cwd)"),
) -> None:
    """🛠  Initialise a new pyproject.toml and README.md.

    Use --create-package to also scaffold a minimal package folder when
    starting a brand-new project. Safe to omit for existing projects.
    """
    try:
        root = core_logic.resolve_project_root(project_dir)
    except (FileNotFoundError, NotADirectoryError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        typer.secho("❌ Invalid email format.", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"🔎 Checking name availability for '{name}'…")
    taken_pypi, taken_test = core_logic.check_name_availability(name)

    for label, taken, url in [
        ("PyPI",     taken_pypi,  f"https://pypi.org/project/{name}/"),
        ("TestPyPI", taken_test,  f"https://test.pypi.org/project/{name}/"),
    ]:
        if taken is True:
            typer.echo(f"❌ Already taken on {label}: {url}")
        elif taken is False:
            typer.echo(f"✅ Available on {label}")
        else:
            typer.echo(f"⚠️  Could not determine availability on {label}")

    if taken_pypi or taken_test:
        typer.echo(f"💡 Suggestions: {name}-dev  /  {name}-toolkit  /  {name}-yourname")

    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    dependencies = (
        core_logic.detect_dependencies(root)
        if auto_deps
        else [d.strip() for d in deps.split(",") if d.strip()]
    )
    if auto_deps:
        typer.echo(f"✨ Detected deps: {', '.join(dependencies) or 'none'}")

    try:
        core_logic.init_project_command(
            name=name,
            version=version,
            description=description,
            author=author,
            email=email,
            dependencies=dependencies,
            license_text=license_text,
            keywords=kw_list,
            homepage=homepage,
            # Pass cli_script raw — let init_project_command apply
            # make_default_entry_point(name) so hyphens become underscores.
            cli_script_value=cli_script,
            project_root=root,
            gen_package=create_package,
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def build(
    use_venv: bool = typer.Option(False, "--venv", help="Build inside .venv if present"),
    project_dir: str = typer.Option("", "--project-dir", "-d", help="Project directory (default: cwd)"),
) -> None:
    """📦 Build wheel + sdist (runs pre_build hook if present)."""
    try:
        root = core_logic.resolve_project_root(project_dir)
    except (FileNotFoundError, NotADirectoryError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    venv = root / ".venv"
    if use_venv and not venv.exists():
        typer.secho("⚠️  No .venv found — run 'pipndeploy create-venv' first.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    try:
        core_logic.build_package(use_venv=use_venv, project_root=root)
        # Note: the standalone build command doesn't chain into deploy,
        # so we don't need to capture the returned interpreter here.
    except Exception as exc:
        typer.secho(f"❌ Build failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def deploy(
    testpypi:    bool = typer.Option(False, "--test", "-t",   help="Upload to TestPyPI"),
    dry_run:     bool = typer.Option(False, "--dry-run",       help="Simulate upload only"),
    use_venv:    bool = typer.Option(False, "--venv",          help="Use the project .venv interpreter for twine"),
    python_path: str  = typer.Option("",   "--python",        help="Explicit interpreter path for twine (e.g. .venv/Scripts/python.exe)"),
    project_dir: str  = typer.Option("",   "--project-dir", "-d", help="Project directory (default: cwd)"),
) -> None:
    """🚀 Upload dist/* to PyPI or TestPyPI.

    Use --venv or --python to target the same interpreter used during build,
    ensuring twine is looked up in the correct environment.

    Examples:
        pipndeploy build --venv && pipndeploy deploy --venv
        pipndeploy deploy --python .venv/Scripts/python.exe
    """
    try:
        root = core_logic.resolve_project_root(project_dir)
    except (FileNotFoundError, NotADirectoryError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    # Resolve interpreter — explicit path beats --venv beats sys.executable
    from pathlib import Path as _Path
    if python_path:
        py: str | None = str(_Path(python_path).resolve())
    elif use_venv:
        venv_py = root / ".venv" / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
        if not venv_py.exists():
            typer.secho(f"❌ No .venv found at {root / '.venv'}. Run: pipndeploy create-venv", fg=typer.colors.RED)
            raise typer.Exit(1)
        py = str(venv_py)
    else:
        py = None   # upload_to_pypi defaults to sys.executable

    try:
        result = core_logic.upload_to_pypi(
            use_testpypi=testpypi, dry_run=dry_run, project_root=root, python=py,
        )
        if result:
            typer.echo(result)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def clean(
    uninstall:   bool = typer.Option(False, "--uninstall", help="Also uninstall the package from the active Python interpreter (opt-in)"),
    purge_pyc:   bool = typer.Option(True,  help="Remove __pycache__ and .pyc files"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Prompt before each delete"),
    project_dir: str  = typer.Option("", "--project-dir", "-d", help="Project directory (default: cwd)"),
) -> None:
    """🧹 Remove build artifacts. Use --uninstall to also remove the package."""
    try:
        root = core_logic.resolve_project_root(project_dir)
    except (FileNotFoundError, NotADirectoryError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    core_logic.clean_project(
        uninstall=uninstall,
        purge_pyc=purge_pyc,
        interactive=interactive,
        project_root=root,
    )


@app.command("create-venv")
def create_venv() -> None:
    """🧪 Create a local .venv for isolated builds."""
    core_logic.create_virtualenv()


@app.command("name-check")
def name_check(name: str = typer.Argument(..., help="Package name to check")) -> None:
    """🔍 Check if a name is available on PyPI and TestPyPI."""
    typer.echo(f"🔎 Checking '{name}'…")
    taken_pypi, taken_test = core_logic.check_name_availability(name)
    for label, taken in [("PyPI", taken_pypi), ("TestPyPI", taken_test)]:
        if taken is True:
            typer.echo(f"❌ {name} is taken on {label}")
        elif taken is False:
            typer.echo(f"✅ {name} is available on {label}")
        else:
            typer.echo(f"⚠️  Could not determine availability on {label}")


@app.command("bump")
def bump(
    part:        str = typer.Argument("patch", help="Version segment to increment: patch, minor, or major"),
    set_version: str = typer.Option("", "--set", "-s", help="Set an exact version instead of bumping (e.g. 2.0.0)"),
    project_dir: str = typer.Option("", "--project-dir", "-d", help="Project directory (default: cwd)"),
) -> None:
    """🔢 Bump the version in pyproject.toml (patch / minor / major)."""
    try:
        root = core_logic.resolve_project_root(project_dir)
    except (FileNotFoundError, NotADirectoryError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    try:
        old_v, new_v = core_logic.bump_version(
            part=part,
            project_root=root,
            set_version=set_version or None,
        )
        typer.secho(f"✅ {old_v} → {new_v}", fg=typer.colors.GREEN)
    except (FileNotFoundError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command("auth-gen")
def auth_gen(
    pypi_token:     str  = typer.Option("", "--pypi",     help="PyPI API token", prompt=False),
    testpypi_token: str  = typer.Option("", "--testpypi", help="TestPyPI API token", prompt=False),
    overwrite:      bool = typer.Option(False, "--overwrite", help="Overwrite existing ~/.pypirc"),
) -> None:
    """🔑 Generate ~/.pypirc from API tokens.

    Pass at least one token. Prompts interactively if neither is provided.

    Examples:
        pipndeploy auth-gen --pypi pypi-abc123
        pipndeploy auth-gen --pypi pypi-abc --testpypi pypi-def --overwrite
    """
    if not pypi_token and not testpypi_token:
        pypi_token     = typer.prompt("PyPI API token (leave blank to skip)",     default="")
        testpypi_token = typer.prompt("TestPyPI API token (leave blank to skip)", default="")

    if not pypi_token and not testpypi_token:
        typer.secho("❌ At least one token is required.", fg=typer.colors.RED)
        raise typer.Exit(1)

    from pathlib import Path as _Path
    pypirc = _Path.home() / ".pypirc"
    if pypirc.exists() and not overwrite:
        typer.secho(
            f"⚠️  ~/.pypirc already exists at {pypirc}\n"
            "Use --overwrite to replace it (a backup will be saved automatically).",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    try:
        out = core_logic.generate_pypirc(
            pypi_token=pypi_token,
            testpypi_token=testpypi_token,
            overwrite=overwrite,
            backup=True,
        )
        typer.secho(f"✅ .pypirc written to {out}", fg=typer.colors.GREEN)
    except (ValueError, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command("auth-check")
def auth_check() -> None:
    """🔐 Validate ~/.pypirc token configuration."""
    success, messages = core_logic.auth_check()
    for msg in messages:
        typer.echo(msg)
    raise typer.Exit(0 if success else 1)


@app.command("full")
def full_pipeline() -> None:
    """🌀 Interactive init → build → deploy pipeline."""
    typer.secho("─── PiPnDeploy Full Pipeline ───", fg=typer.colors.CYAN)

    name        = typer.prompt("Package name")
    version     = typer.prompt("Version", default="0.1.0")
    description = typer.prompt("Description")
    author      = typer.prompt("Author name")
    email       = typer.prompt("Author email")
    license_txt = typer.prompt("Licence", default="MIT")
    homepage    = typer.prompt("Homepage URL (optional, press Enter to skip)", default="", show_default=False)
    kw_raw      = typer.prompt("Keywords (comma-separated)", default="")
    auto_deps   = typer.confirm("Auto-detect dependencies?", default=True)

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        typer.secho("❌ Invalid email.", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo(f"🔎 Checking name '{name}'…")
    taken_pypi, taken_test = core_logic.check_name_availability(name)
    if taken_pypi or taken_test:
        typer.secho(
            f"⚠️  '{name}' may already be taken. Proceed carefully.",
            fg=typer.colors.YELLOW,
        )
        if not typer.confirm("Continue anyway?", default=False):
            raise typer.Exit(0)

    kw_list     = [k.strip() for k in kw_raw.split(",") if k.strip()]
    gen_package = typer.confirm(
        "Create package skeleton? (module/__init__.py + module/main.py)",
        default=False,
    )
    root = core_logic.resolve_project_root("")
    deps = core_logic.detect_dependencies(root) if auto_deps else []
    typer.echo(f"📦 Dependencies: {', '.join(deps) or 'none'}")

    try:
        core_logic.init_project_command(
            name=name, version=version, description=description,
            author=author, email=email, dependencies=deps,
            license_text=license_txt, keywords=kw_list, homepage=homepage,
            # Empty string — let init_project_command derive the default safely.
            cli_script_value="",
            project_root=root,
            gen_package=gen_package,
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    use_venv = typer.confirm("Build inside .venv?", default=False)
    if use_venv:
        core_logic.create_virtualenv(root)
    # Capture the interpreter used for build so twine runs in the same env.
    build_py = core_logic.build_package(use_venv=use_venv, project_root=root)

    dry_run      = typer.confirm("Dry run first?", default=True)
    use_testpypi = typer.confirm("Target TestPyPI?", default=True)

    try:
        result = core_logic.upload_to_pypi(
            use_testpypi=use_testpypi, dry_run=dry_run,
            project_root=root, python=build_py,
        )
        if result:
            typer.echo(result)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if dry_run:
        if not typer.confirm("Dry run done — proceed with live upload?", default=False):
            typer.secho("Aborted.", fg=typer.colors.YELLOW)
            raise typer.Exit(0)
        try:
            core_logic.upload_to_pypi(
                use_testpypi=use_testpypi, dry_run=False,
                project_root=root, python=build_py,
            )
        except RuntimeError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)

    typer.secho("✅ Full pipeline complete!", fg=typer.colors.GREEN)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess  # noqa: F811 — needed by build() error handler above
    app()
