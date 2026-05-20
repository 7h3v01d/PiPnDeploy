# gui_main.py — PyQt6 GUI for PiPnDeploy
# Fixes applied:
#   - os.chdir() removed from worker threads; project_root passed directly
#   - Logging bridge replaces stdout redirect as primary capture mechanism
#   - StdoutRedirector kept only as a safety net for any stray print() calls

import configparser
import logging
import re
import sys
import json
from pathlib import Path

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
        QTextEdit, QFileDialog, QGroupBox, QGridLayout,
        QStatusBar, QStackedWidget, QMessageBox, QSplitter,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
    from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette
except ImportError:
    print(
        "\n"
        "❌ PyQt6 is not installed — the PiPnDeploy GUI requires it.\n"
        "\n"
        "   Install the GUI extra:\n"
        "       pip install pipndeploy[gui]\n"
        "\n"
        "   Or install PyQt6 directly:\n"
        "       pip install PyQt6\n"
        "\n"
        "   The CLI works without PyQt6:\n"
        "       pipndeploy --help\n",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from . import core_logic          # installed / python -m PiPnDeploy.gui_main
except ImportError:
    import core_logic                 # python PiPnDeploy/gui_main.py (direct run)

WINDOW_TITLE = "PiPnDeploy"
HELP_FILE    = Path(__file__).parent.parent / "Features.md"


def _user_config_dir() -> Path:
    """Return the OS-appropriate user config directory for PiPnDeploy.

    Windows : %APPDATA%/PiPnDeploy/
    macOS   : ~/.config/pipndeploy/
    Linux   : $XDG_CONFIG_HOME/pipndeploy/  (default ~/.config/pipndeploy/)

    The directory is created if it does not exist.
    Using the OS config dir instead of Path(__file__).parent ensures the app
    never tries to write user data into site-packages after pip install.
    """
    import os as _os
    if _os.name == "nt":
        base = Path(_os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(_os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_dir = base / "pipndeploy"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


PROFILE_FILE = _user_config_dir() / "profile.json"


# ─── Console logging bridge ──────────────────────────────────────────────────
# core_logic emits to logging.getLogger("pipndeploy"); this handler forwards
# every record to the GUI console widget via a Qt signal — safe across threads.

class _ConsoleSignals(QObject):
    message = pyqtSignal(str, int)   # (text, logging level)


class _QtLogHandler(logging.Handler):
    """Forwards log records to the GUI console via a thread-safe Qt signal."""

    def __init__(self, signals: _ConsoleSignals) -> None:
        super().__init__()
        self._signals = signals
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            self._signals.message.emit(text + "\n", record.levelno)
        except Exception:
            self.handleError(record)


class _StdoutBridge:
    """Safety-net: catches any stray print() calls not going through logging."""

    def __init__(self, signals: _ConsoleSignals) -> None:
        self._signals = signals

    def write(self, text: str) -> None:
        if text and text != "\n":
            self._signals.message.emit(text, logging.INFO)

    def flush(self) -> None:
        pass


# ─── Worker thread ────────────────────────────────────────────────────────────

class Worker(QThread):
    """Runs a callable in a background thread so the UI stays responsive.

    No os.chdir() here. Callers pass project_root as a Path argument directly
    into the core_logic functions — those functions all accept it explicitly.
    """
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ─── Main window ──────────────────────────────────────────────────────────────

class PipnDeployGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(900, 740)
        self._workers: list[Worker] = []
        self._last_build_python: str | None = None  # set by _full_run_init

        # Signals shared between the log handler and the stdout bridge
        self._con_signals = _ConsoleSignals()

        self._build_ui()                     # console widget must exist first
        self._setup_logging()                # then wire the log handler
        self._load_profile()
        self._try_load_init_from_pyproject() # pre-fill Init tab if pyproject exists
        self._ver_refresh()                  # populate Version tab
        self._set_status(f"Project: {self._project_root()}")

    # ── Logging setup ─────────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        # 1. Qt log handler → pipndeploy logger
        self._log_handler = _QtLogHandler(self._con_signals)
        pkg_log = logging.getLogger("pipndeploy")
        pkg_log.handlers.clear()          # remove the default StreamHandler
        pkg_log.addHandler(self._log_handler)
        pkg_log.setLevel(logging.DEBUG)

        # 2. Connect signal → console append (always runs on main thread)
        self._con_signals.message.connect(self._append_console)

        # 3. stdout/stderr safety net for stray print() calls
        _bridge = _StdoutBridge(self._con_signals)
        sys.stdout = _bridge
        sys.stderr = _bridge

    def _append_console(self, text: str, level: int) -> None:
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = self.console.currentCharFormat()

        if level >= logging.ERROR or "❌" in text:
            fmt.setForeground(QColor("#f87171"))   # red
        elif level >= logging.WARNING or "⚠️" in text:
            fmt.setForeground(QColor("#fb923c"))   # orange
        elif "✅" in text:
            fmt.setForeground(QColor("#4ade80"))   # green
        elif any(e in text for e in ("🔎", "📦", "🔁", "🧪", "🚀")):
            fmt.setForeground(QColor("#60a5fa"))   # blue
        else:
            fmt.setForeground(QColor("#e2e8f0"))   # default near-white

        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    # ── Project root ──────────────────────────────────────────────────────
    # Single point of truth. No os.chdir() anywhere in the GUI.

    def _project_root(self) -> Path:
        return Path(self.project_path.text())

    # ── Thread runner ─────────────────────────────────────────────────────

    def _run_in_thread(self, fn, on_done=None, on_error=None, *args, **kwargs):
        worker = Worker(fn, *args, **kwargs)
        if on_done:
            worker.finished.connect(on_done)

        def _default_err(msg: str) -> None:
            logging.getLogger("pipndeploy").error("❌ %s", msg)
            self._set_status("Failed.")

        worker.error.connect(on_error if on_error else _default_err)
        worker.finished.connect(
            lambda _: self._workers.remove(worker) if worker in self._workers else None
        )
        worker.error.connect(
            lambda _: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(10, 10, 10, 10)
        root_lay.setSpacing(8)

        # Project path bar
        path_box = QGroupBox("Project Directory")
        path_row = QHBoxLayout(path_box)
        self.project_path = QLineEdit(str(Path.cwd()))
        self.project_path.setPlaceholderText("Path to your Python project…")
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._select_project_dir)
        path_row.addWidget(self.project_path)
        path_row.addWidget(browse_btn)
        root_lay.addWidget(path_box)

        # Splitter: tabs / console
        splitter = QSplitter(Qt.Orientation.Vertical)
        root_lay.addWidget(splitter, stretch=1)

        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)

        # Console
        con_box = QGroupBox("Output Console")
        con_lay = QVBoxLayout(con_box)
        con_lay.setContentsMargins(6, 6, 6, 6)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        self.console.setStyleSheet("background:#0f172a; color:#e2e8f0; border:none;")
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self.console.clear)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        con_lay.addWidget(self.console)
        con_lay.addLayout(btn_row)
        splitter.addWidget(con_box)
        splitter.setSizes([480, 240])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.tabs.addTab(self._tab_profile(),  "👤 Profile")
        self.tabs.addTab(self._tab_init(),     "🛠 Init")
        self.tabs.addTab(self._tab_build(),    "📦 Build")
        self.tabs.addTab(self._tab_deploy(),   "🚀 Deploy")
        self.tabs.addTab(self._tab_clean(),    "🧹 Clean")
        self.tabs.addTab(self._tab_full(),     "🌀 Full Pipeline")
        self.tabs.addTab(self._tab_update(),   "🔄 Update")
        self.tabs.addTab(self._tab_version(),  "🔢 Version")
        self.tabs.addTab(self._tab_auth_gen(), "🔑 Auth Gen")
        self.tabs.addTab(self._tab_help(),     "📘 Help")

    # ── Shared helpers ────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self.status_bar.showMessage(msg)

    def _select_project_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Select Project Directory", str(self._project_root())
        )
        if d:
            self.project_path.setText(d)
            self._set_status(f"Project: {d}")
            logging.getLogger("pipndeploy").info("🔎 Project directory: %s", d)
            self._try_load_init_from_pyproject()
            self._ver_refresh()

    @staticmethod
    def _field(grid: QGridLayout, row: int, label: str, widget) -> None:
        grid.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(widget, row, 1)

    def _validate_common(self, name: str, author: str, email: str) -> bool:
        log = logging.getLogger("pipndeploy")
        if not name or not author or not email:
            log.error("❌ Name, Author, and Email are all required.")
            return False
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            log.error("❌ Invalid email format.")
            return False
        return True

    def _browse_cli_script(self, name_widget: QLineEdit, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CLI Script", str(self._project_root()),
            "Python files (*.py);;All files (*.*)",
        )
        if path:
            pkg = name_widget.text().strip()
            if not pkg:
                QMessageBox.warning(self, "Missing Name", "Enter a Package Name first.")
                return
            target.setText(f"{pkg}.{Path(path).stem}:main")
            logging.getLogger("pipndeploy").info("🔎 CLI script: %s", target.text())

    # ── Profile helpers ───────────────────────────────────────────────────

    def _load_profile(self) -> None:
        log = logging.getLogger("pipndeploy")
        if not PROFILE_FILE.exists():
            log.info("🔎 No profile found. Use the Profile tab to save details.")
            return
        try:
            data = json.loads(PROFILE_FILE.read_text())
            for w in (self.init_author, self.full_author, self.profile_author):
                w.setText(data.get("author", ""))
            for w in (self.init_email, self.full_email, self.profile_email):
                w.setText(data.get("email", ""))
            log.info("🔎 Profile loaded.")
            self._set_status("Profile loaded.")
        except Exception as exc:
            log.warning("⚠️ Could not load profile: %s", exc)

    def _save_profile(self) -> None:
        log    = logging.getLogger("pipndeploy")
        author = self.profile_author.text().strip()
        email  = self.profile_email.text().strip()
        if not author or not email:
            log.error("❌ Both Author and Email are required.")
            return
        PROFILE_FILE.write_text(json.dumps({"author": author, "email": email}, indent=4))
        for w in (self.init_author, self.full_author):
            w.setText(author)
        for w in (self.init_email, self.full_email):
            w.setText(email)
        log.info("✅ Profile saved.")
        self._set_status("Profile saved.")

    # ── Tab builders ───────────────────────────────────────────────────────

    def _tab_profile(self) -> QWidget:
        tab  = QWidget()
        lay  = QVBoxLayout(tab)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        box  = QGroupBox("Default Author Details")
        grid = QGridLayout(box)
        self.profile_author = QLineEdit()
        self.profile_email  = QLineEdit()
        self._field(grid, 0, "Author Name:",   self.profile_author)
        self._field(grid, 1, "Email Address:", self.profile_email)
        lay.addWidget(box)
        btn = QPushButton("💾 Save Profile")
        btn.setFixedWidth(160)
        btn.clicked.connect(self._save_profile)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return tab

    def _tab_init(self) -> QWidget:
        tab  = QWidget()
        lay  = QVBoxLayout(tab)
        self.init_box = QGroupBox("Initialise a New Package")
        grid = QGridLayout(self.init_box)
        grid.setColumnStretch(1, 1)

        self.init_name        = QLineEdit()
        self.init_author      = QLineEdit()
        self.init_email       = QLineEdit()
        self.init_description = QLineEdit()
        self.init_license     = QComboBox()
        self.init_license.addItems(core_logic.LICENSE_OPTIONS)
        self.init_homepage    = QLineEdit("https://github.com/yourusername/your-package")
        self.init_keywords    = QLineEdit()
        self.init_cli_script  = QLineEdit()
        self.init_auto_deps   = QCheckBox("Auto-detect dependencies (AST scan)")
        self.init_auto_deps.setChecked(True)
        self.init_gen_gitignore = QCheckBox("Generate .gitignore")
        self.init_gen_gitignore.setChecked(True)

        name_row = QHBoxLayout()
        name_row.addWidget(self.init_name)
        chk = QPushButton("Check Name"); chk.setFixedWidth(110)
        chk.clicked.connect(self._check_name)
        name_row.addWidget(chk)
        name_w = QWidget(); name_w.setLayout(name_row)

        cli_row = QHBoxLayout()
        cli_row.addWidget(self.init_cli_script)
        cli_b = QPushButton("Browse…"); cli_b.setFixedWidth(80)
        cli_b.clicked.connect(lambda: self._browse_cli_script(self.init_name, self.init_cli_script))
        cli_row.addWidget(cli_b)
        cli_w = QWidget(); cli_w.setLayout(cli_row)

        self._field(grid, 0, "Package Name:",         name_w)
        self._field(grid, 1, "Author:",               self.init_author)
        self._field(grid, 2, "Email:",                self.init_email)
        self._field(grid, 3, "Description:",          self.init_description)
        self._field(grid, 4, "License:",              self.init_license)
        self._field(grid, 5, "Homepage URL:",         self.init_homepage)
        self._field(grid, 6, "Keywords (comma-sep):", self.init_keywords)
        self._field(grid, 7, "CLI Script:",           cli_w)
        grid.addWidget(self.init_auto_deps,     8, 0, 1, 2)
        grid.addWidget(self.init_gen_gitignore, 9, 0, 1, 2)

        lay.addWidget(self.init_box)

        # Status label — shows whether form was loaded from existing pyproject.toml
        self.init_status_label = QLabel("")
        self.init_status_label.setStyleSheet("color: #60a5fa; font-size: 11px;")
        lay.addWidget(self.init_status_label)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("🛠 Run Init"); run_btn.setFixedWidth(140)
        run_btn.clicked.connect(self._run_init)
        reload_btn = QPushButton("🔄 Reload from pyproject.toml"); reload_btn.setFixedWidth(230)
        reload_btn.clicked.connect(self._try_load_init_from_pyproject)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return tab

    def _tab_build(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(QLabel(
            "Runs <b>python -m build</b> in the project directory.\n"
            "Produces wheel + sdist in <code>dist/</code>."
        ))
        btn = QPushButton("📦 Build Package"); btn.setFixedWidth(160)
        btn.clicked.connect(self._run_build)
        lay.addWidget(btn)
        lay.addStretch()
        return tab

    def _tab_deploy(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        box = QGroupBox("Deploy Options")
        vb  = QVBoxLayout(box)
        self.deploy_testpypi = QCheckBox("Upload to TestPyPI")
        self.deploy_dry_run  = QCheckBox("Dry Run (no upload)")
        vb.addWidget(self.deploy_testpypi)
        vb.addWidget(self.deploy_dry_run)
        lay.addWidget(box)
        row = QHBoxLayout()
        dep_btn  = QPushButton("🚀 Run Deploy");  dep_btn.setFixedWidth(140)
        auth_btn = QPushButton("🔐 Auth Check"); auth_btn.setFixedWidth(130)
        dep_btn.clicked.connect(self._run_deploy)
        auth_btn.clicked.connect(self._run_auth_check)
        row.addWidget(dep_btn); row.addWidget(auth_btn); row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        return tab

    def _tab_clean(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        box = QGroupBox("Clean Options")
        vb  = QVBoxLayout(box)
        self.clean_uninstall   = QCheckBox("Uninstall local package")  # opt-in only
        self.clean_purge       = QCheckBox("Purge .pyc & __pycache__");       self.clean_purge.setChecked(True)
        self.clean_interactive = QCheckBox("Interactive (prompt before each delete)")
        uninstall_note = QLabel("⚠️  Uninstall will remove the package from the active Python interpreter.")
        uninstall_note.setStyleSheet("color: #fb923c; font-size: 11px;")
        uninstall_note.setWordWrap(True)
        vb.addWidget(self.clean_uninstall)
        vb.addWidget(uninstall_note)
        vb.addWidget(self.clean_purge)
        vb.addWidget(self.clean_interactive)
        lay.addWidget(box)
        btn = QPushButton("🧹 Clean Project"); btn.setFixedWidth(140)
        btn.clicked.connect(self._run_clean)
        lay.addWidget(btn)
        lay.addStretch()
        return tab

    def _tab_full(self) -> QWidget:
        tab = QWidget()
        self._full_stack = QStackedWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(self._full_stack)

        # Step 0 — form
        step0 = QWidget(); s0 = QVBoxLayout(step0)
        box0  = QGroupBox("Step 1 of 3 — Package Details")
        grid0 = QGridLayout(box0); grid0.setColumnStretch(1, 1)

        self.full_name        = QLineEdit()
        self.full_author      = QLineEdit()
        self.full_email       = QLineEdit()
        self.full_description = QLineEdit()
        self.full_license     = QComboBox(); self.full_license.addItems(core_logic.LICENSE_OPTIONS)
        self.full_homepage    = QLineEdit("https://github.com/yourusername/your-package")
        self.full_keywords    = QLineEdit()
        self.full_cli_script  = QLineEdit()
        self.full_auto_deps   = QCheckBox("Auto-detect dependencies"); self.full_auto_deps.setChecked(True)

        cr0 = QHBoxLayout(); cr0.addWidget(self.full_cli_script)
        cb0 = QPushButton("Browse…"); cb0.setFixedWidth(80)
        cb0.clicked.connect(lambda: self._browse_cli_script(self.full_name, self.full_cli_script))
        cr0.addWidget(cb0); cw0 = QWidget(); cw0.setLayout(cr0)

        self._field(grid0, 0, "Package Name:",         self.full_name)
        self._field(grid0, 1, "Author:",               self.full_author)
        self._field(grid0, 2, "Email:",                self.full_email)
        self._field(grid0, 3, "Description:",          self.full_description)
        self._field(grid0, 4, "License:",              self.full_license)
        self._field(grid0, 5, "Homepage URL:",         self.full_homepage)
        self._field(grid0, 6, "Keywords:",             self.full_keywords)
        self._field(grid0, 7, "CLI Script:",           cw0)
        grid0.addWidget(self.full_auto_deps, 8, 0, 1, 2)
        s0.addWidget(box0)
        nxt = QPushButton("Next: Build ▶"); nxt.setFixedWidth(150)
        nxt.clicked.connect(self._full_run_init)
        s0.addWidget(nxt, alignment=Qt.AlignmentFlag.AlignLeft)
        s0.addStretch()
        self._full_stack.addWidget(step0)

        # Step 1 — building indicator
        step1 = QWidget(); s1 = QVBoxLayout(step1)
        s1.addWidget(QLabel("⏳ Init & build running — please wait…"))
        bk1 = QPushButton("◀ Back"); bk1.clicked.connect(lambda: self._full_stack.setCurrentIndex(0))
        s1.addWidget(bk1); s1.addStretch()
        self._full_stack.addWidget(step1)

        # Step 2 — deploy
        step2 = QWidget(); s2 = QVBoxLayout(step2)
        s2.addWidget(QLabel("✅ Build successful!"))
        box2 = QGroupBox("Step 3 of 3 — Deploy"); vb2 = QVBoxLayout(box2)
        self.full_testpypi = QCheckBox("Upload to TestPyPI")
        self.full_dry_run  = QCheckBox("Dry Run (no upload)")
        vb2.addWidget(self.full_testpypi); vb2.addWidget(self.full_dry_run)
        s2.addWidget(box2)
        r2 = QHBoxLayout()
        bk2 = QPushButton("◀ Back"); bk2.clicked.connect(lambda: self._full_stack.setCurrentIndex(0))
        dp2 = QPushButton("🚀 Deploy"); dp2.clicked.connect(self._full_run_deploy)
        r2.addWidget(bk2); r2.addWidget(dp2); r2.addStretch()
        s2.addLayout(r2); s2.addStretch()
        self._full_stack.addWidget(step2)

        return tab

    def _tab_update(self) -> QWidget:
        tab  = QWidget()
        lay  = QVBoxLayout(tab)
        box  = QGroupBox("Update & Redeploy")
        grid = QGridLayout(box); grid.setColumnStretch(1, 1)

        self.upd_name         = QLineEdit(); self.upd_name.setReadOnly(True)
        self.upd_version      = QLineEdit()
        self.upd_description  = QLineEdit()
        self.upd_author       = QLineEdit()
        self.upd_email        = QLineEdit()
        self.upd_license      = QComboBox(); self.upd_license.addItems(core_logic.LICENSE_OPTIONS)
        self.upd_homepage     = QLineEdit()
        self.upd_keywords     = QLineEdit()
        # CLI script is read-only in Update — surgical mode does not rewrite
        # [project.scripts]. Use the Init tab to change the entry point.
        self.upd_cli_script   = QLineEdit(); self.upd_cli_script.setReadOnly(True)
        self.upd_cli_script.setToolTip(
            "CLI script is preserved in surgical update mode.\n"
            "Use the Init tab to change the entry point."
        )
        self.upd_dependencies = QLineEdit()

        self._field(grid, 0, "Package Name (read-only):", self.upd_name)
        self._field(grid, 1, "Version:",                  self.upd_version)
        self._field(grid, 2, "Description:",              self.upd_description)
        self._field(grid, 3, "Author:",                   self.upd_author)
        self._field(grid, 4, "Email:",                    self.upd_email)
        self._field(grid, 5, "License:",                  self.upd_license)
        self._field(grid, 6, "Homepage URL:",             self.upd_homepage)
        self._field(grid, 7, "Keywords (comma-sep):",     self.upd_keywords)
        self._field(grid, 8, "CLI Script (read-only):",   self.upd_cli_script)
        self._field(grid, 9, "Dependencies (comma-sep):", self.upd_dependencies)
        lay.addWidget(box)

        self.upd_clean_first = QCheckBox("Clean before Build")
        self.upd_testpypi    = QCheckBox("Upload to TestPyPI")
        self.upd_dry_run     = QCheckBox("Dry Run (no upload)")
        lay.addWidget(self.upd_clean_first)
        lay.addWidget(self.upd_testpypi)
        lay.addWidget(self.upd_dry_run)

        row = QHBoxLayout()
        ld = QPushButton("📂 Load Project");        ld.setFixedWidth(140); ld.clicked.connect(self._load_project_for_update)
        ru = QPushButton("🔄 Build & Deploy Update"); ru.setFixedWidth(200); ru.clicked.connect(self._run_update)
        row.addWidget(ld); row.addWidget(ru); row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        return tab

    def _tab_version(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Current version display
        cur_box = QGroupBox("Current Version")
        cur_lay = QHBoxLayout(cur_box)
        self.ver_current_label = QLabel("—")
        self.ver_current_label.setFont(QFont("Consolas", 18))
        self.ver_current_label.setStyleSheet("color: #60a5fa; font-weight: bold;")
        reload_ver_btn = QPushButton("🔄 Refresh")
        reload_ver_btn.setFixedWidth(90)
        reload_ver_btn.clicked.connect(self._ver_refresh)
        cur_lay.addWidget(self.ver_current_label)
        cur_lay.addStretch()
        cur_lay.addWidget(reload_ver_btn)
        lay.addWidget(cur_box)

        # Bump buttons
        bump_box = QGroupBox("Bump Version")
        bump_lay = QVBoxLayout(bump_box)

        # Preview line
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview:"))
        self.ver_preview_label = QLabel("—")
        self.ver_preview_label.setStyleSheet("color: #4ade80; font-weight: bold;")
        preview_row.addWidget(self.ver_preview_label)
        preview_row.addStretch()
        bump_lay.addLayout(preview_row)

        # Patch / Minor / Major buttons
        btn_row = QHBoxLayout()
        for label, part in [("Patch  +0.0.1", "patch"), ("Minor  +0.1.0", "minor"), ("Major  +1.0.0", "major")]:
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.clicked.connect(lambda checked, p=part: self._ver_preview(p))
            btn_row.addWidget(b)
        bump_lay.addLayout(btn_row)

        # Confirm bump button
        self.ver_confirm_btn = QPushButton("✅ Apply Bump")
        self.ver_confirm_btn.setFixedWidth(150)
        self.ver_confirm_btn.setEnabled(False)
        self.ver_confirm_btn.clicked.connect(self._ver_apply_bump)
        bump_lay.addWidget(self.ver_confirm_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(bump_box)

        # Manual override
        manual_box = QGroupBox("Set Exact Version")
        manual_lay = QHBoxLayout(manual_box)
        self.ver_manual_input = QLineEdit()
        self.ver_manual_input.setPlaceholderText("e.g. 2.0.0")
        self.ver_manual_input.setMaximumWidth(160)
        set_btn = QPushButton("Set Version")
        set_btn.setFixedWidth(110)
        set_btn.clicked.connect(self._ver_set_manual)
        manual_lay.addWidget(self.ver_manual_input)
        manual_lay.addWidget(set_btn)
        manual_lay.addStretch()
        lay.addWidget(manual_box)

        lay.addStretch()

        # Store pending bump part for confirm step
        self._pending_bump_part: str | None = None

        return tab

    def _ver_refresh(self) -> None:
        """Read current version from pyproject.toml and update the display."""
        ver = core_logic.get_current_version(self._project_root())
        self.ver_current_label.setText(ver or "—")
        self.ver_preview_label.setText("—")
        self.ver_confirm_btn.setEnabled(False)
        self._pending_bump_part = None
        if not ver:
            logging.getLogger("pipndeploy").warning(
                "⚠️ No pyproject.toml found in %s — load a project first.", self._project_root()
            )

    def _ver_preview(self, part: str) -> None:
        """Show what the version will become after bumping, without writing anything."""
        import re as _re
        ver = core_logic.get_current_version(self._project_root())
        if not ver:
            logging.getLogger("pipndeploy").warning("⚠️ No version found — load a project first.")
            return
        m = _re.match(r"^(\d+)\.(\d+)\.(\d+)", ver)
        if not m:
            logging.getLogger("pipndeploy").warning("⚠️ Version '%s' is not semver-shaped.", ver)
            return
        major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if part == "patch":   preview = f"{major}.{minor}.{patch + 1}"
        elif part == "minor": preview = f"{major}.{minor + 1}.0"
        else:                 preview = f"{major + 1}.0.0"
        self.ver_current_label.setText(ver)
        self.ver_preview_label.setText(f"{ver}  →  {preview}")
        self._pending_bump_part = part
        self.ver_confirm_btn.setEnabled(True)

    def _ver_apply_bump(self) -> None:
        """Write the pending bump to pyproject.toml."""
        if not self._pending_bump_part:
            return
        log  = logging.getLogger("pipndeploy")
        root = self._project_root()
        part = self._pending_bump_part

        def task():
            return core_logic.bump_version(part, project_root=root)

        def done(result):
            old_v, new_v = result
            log.info("✅ Version bumped: %s → %s", old_v, new_v)
            self._set_status(f"Version: {old_v} → {new_v}")
            self.ver_current_label.setText(new_v)
            self.ver_preview_label.setText("—")
            self.ver_confirm_btn.setEnabled(False)
            self._pending_bump_part = None

        def err(msg):
            log.error("❌ %s", msg)
            self._set_status("Bump failed.")

        self._run_in_thread(task, on_done=done, on_error=err)

    def _ver_set_manual(self) -> None:
        """Write an exact version string to pyproject.toml."""
        version = self.ver_manual_input.text().strip()
        log  = logging.getLogger("pipndeploy")
        if not version:
            log.warning("⚠️ Enter a version string first.")
            return
        root = self._project_root()

        def task():
            return core_logic.bump_version("patch", project_root=root, set_version=version)

        def done(result):
            old_v, new_v = result
            log.info("✅ Version set: %s → %s", old_v, new_v)
            self._set_status(f"Version set to {new_v}")
            self.ver_current_label.setText(new_v)
            self.ver_preview_label.setText("—")
            self.ver_confirm_btn.setEnabled(False)
            self.ver_manual_input.clear()

        def err(msg):
            log.error("❌ %s", msg)
            self._set_status("Set version failed.")

        self._run_in_thread(task, on_done=done, on_error=err)

    def _tab_auth_gen(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        box = QGroupBox("Generate ~/.pypirc")
        vb  = QVBoxLayout(box)
        vb.addWidget(QLabel("PyPI API Token:"))
        self.auth_pypi = QLineEdit(); self.auth_pypi.setEchoMode(QLineEdit.EchoMode.Password)
        vb.addWidget(self.auth_pypi)
        vb.addWidget(QLabel("TestPyPI API Token:"))
        self.auth_testpypi = QLineEdit(); self.auth_testpypi.setEchoMode(QLineEdit.EchoMode.Password)
        vb.addWidget(self.auth_testpypi)
        note = QLabel("Tokens saved to ~/.pypirc  ·  At least one required.")
        note.setStyleSheet("color:gray; font-size:11px;")
        vb.addWidget(note)
        lay.addWidget(box)
        btn = QPushButton("🔑 Generate .pypirc"); btn.setFixedWidth(170)
        btn.clicked.connect(self._generate_pypirc)
        lay.addWidget(btn)
        lay.addStretch()
        return tab

    def _tab_help(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.help_text = QTextEdit()
        self.help_text.setReadOnly(True)
        self.help_text.setFont(QFont("Consolas", 9))
        self.help_text.setPlainText(
            HELP_FILE.read_text(encoding="utf-8") if HELP_FILE.exists()
            else "❌ Features.md not found."
        )
        lay.addWidget(self.help_text)
        return tab

    # ── Command handlers ──────────────────────────────────────────────────
    # Every handler reads UI values on the main thread, captures project_root
    # as a local Path, then passes it directly to core_logic in the worker.
    # No os.chdir() is used in any handler or worker.

    def _try_load_init_from_pyproject(self) -> None:
        """If a pyproject.toml exists in the project root, pre-fill the Init form."""
        root = self._project_root()
        toml_path = root / "pyproject.toml"
        log = logging.getLogger("pipndeploy")

        if not toml_path.exists():
            self.init_status_label.setText("")
            self.init_box.setTitle("Initialise a New Package")
            return

        data = core_logic.read_pyproject_toml(root)
        if not data:
            log.warning("⚠️ pyproject.toml found but could not be parsed.")
            return

        # Pre-fill every field that has a value — leave blanks alone
        if data.get("name"):
            self.init_name.setText(data["name"])
        if data.get("author_name"):
            self.init_author.setText(data["author_name"])
        if data.get("author_email"):
            self.init_email.setText(data["author_email"])
        if data.get("description"):
            self.init_description.setText(data["description"])
        lic = data.get("license", "")
        if isinstance(lic, str) and lic in core_logic.LICENSE_OPTIONS:
            self.init_license.setCurrentText(lic)
        if data.get("homepage_url"):
            self.init_homepage.setText(data["homepage_url"])
        kw = data.get("keywords", [])
        if kw:
            self.init_keywords.setText(", ".join(kw))
        if data.get("cli_script_value"):
            self.init_cli_script.setText(data["cli_script_value"])

        self.init_box.setTitle("Edit Existing Package  ·  pyproject.toml loaded")
        self.init_status_label.setText(f"📄 Loaded from: {toml_path}")
        log.info("🔎 Init form pre-filled from existing pyproject.toml.")
        self._set_status("pyproject.toml loaded into Init tab.")

    def _check_name(self) -> None:
        name = self.init_name.text().strip()
        log  = logging.getLogger("pipndeploy")
        if not name:
            log.warning("⚠️ Enter a package name first.")
            return
        log.info("🔎 Checking availability for '%s'…", name)
        self._set_status("Checking name…")

        def task():
            return core_logic.check_name_availability(name)

        def done(result):
            if result is None:
                return
            taken_pypi, taken_test = result
            for label, taken in [("PyPI", taken_pypi), ("TestPyPI", taken_test)]:
                if taken is True:
                    log.error("❌ '%s' is taken on %s.", name, label)
                elif taken is False:
                    log.info("✅ '%s' is available on %s.", name, label)
                else:
                    log.warning("⚠️ Could not determine availability on %s.", label)
            self._set_status("Ready.")

        self._run_in_thread(task, on_done=done)

    def _run_init(self) -> None:
        name   = self.init_name.text().strip()
        author = self.init_author.text().strip()
        email  = self.init_email.text().strip()
        if not self._validate_common(name, author, email):
            return

        root = self._project_root()

        # Warn before overwriting an existing pyproject.toml
        if (root / "pyproject.toml").exists():
            msg = f"A pyproject.toml already exists in:\n{root}\n\nOverwrite it?"
            answer = QMessageBox.question(
                self, "Overwrite pyproject.toml?",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        desc = self.init_description.text().strip()
        lic  = self.init_license.currentText()
        home = self.init_homepage.text().strip()
        kw   = [k.strip() for k in self.init_keywords.text().split(",") if k.strip()]
        # Pass cli_script raw — let init_project_command apply
        # make_default_entry_point(name) so hyphens become underscores.
        cli  = self.init_cli_script.text().strip()
        auto = self.init_auto_deps.isChecked()
        log  = logging.getLogger("pipndeploy")
        self._set_status("Initialising…")

        gen_gi = self.init_gen_gitignore.isChecked()

        def task():
            deps = core_logic.detect_dependencies(root) if auto else []
            core_logic.init_project_command(
                name=name, version="0.1.0", description=desc,
                author=author, email=email, dependencies=deps,
                license_text=lic, keywords=kw, homepage=home,
                cli_script_value=cli, project_root=root,
                gen_gitignore=gen_gi,
            )

        def done(_):
            log.info("✅ Init complete.")
            self._set_status("Init complete.")
            self._try_load_init_from_pyproject()  # refresh status label

        self._run_in_thread(task, on_done=done)

    def _run_build(self) -> None:
        root = self._project_root()
        log  = logging.getLogger("pipndeploy")
        self._set_status("Building…")

        def task():
            core_logic.build_package(project_root=root)

        def done(_):
            log.info("✅ Build complete.")
            self._set_status("Build complete.")

        self._run_in_thread(task, on_done=done)

    def _run_deploy(self) -> None:
        root    = self._project_root()
        test    = self.deploy_testpypi.isChecked()
        dry_run = self.deploy_dry_run.isChecked()
        log     = logging.getLogger("pipndeploy")
        self._set_status("Deploying…")

        def task():
            return core_logic.upload_to_pypi(
                use_testpypi=test, dry_run=dry_run, project_root=root
            )

        def done(result):
            if result:
                log.info(result)
            log.info("✅ Deploy complete.")
            self._set_status("Deploy complete.")

        self._run_in_thread(task, on_done=done)

    def _run_clean(self) -> None:
        root = self._project_root()
        log  = logging.getLogger("pipndeploy")
        self._set_status("Cleaning…")

        def task():
            core_logic.clean_project(
                uninstall=self.clean_uninstall.isChecked(),
                purge_pyc=self.clean_purge.isChecked(),
                interactive=self.clean_interactive.isChecked(),
                project_root=root,
            )

        def done(_):
            log.info("✅ Clean complete.")
            self._set_status("Clean complete.")

        self._run_in_thread(task, on_done=done)

    def _run_auth_check(self) -> None:
        log = logging.getLogger("pipndeploy")
        self._set_status("Checking auth…")

        def task():
            return core_logic.auth_check()

        def done(result):
            if result is None:
                return
            success, messages = result
            for m in messages:
                log.info(m)
            self._set_status("Auth OK." if success else "Auth issues — see console.")

        self._run_in_thread(task, on_done=done)

    def _full_run_init(self) -> None:
        name   = self.full_name.text().strip()
        author = self.full_author.text().strip()
        email  = self.full_email.text().strip()
        if not self._validate_common(name, author, email):
            return

        root = self._project_root()
        desc = self.full_description.text().strip()
        lic  = self.full_license.currentText()
        home = self.full_homepage.text().strip()
        kw   = [k.strip() for k in self.full_keywords.text().split(",") if k.strip()]
        # Pass cli_script raw — let init_project_command apply
        # make_default_entry_point(name) so hyphens become underscores.
        cli  = self.full_cli_script.text().strip()
        auto = self.full_auto_deps.isChecked()
        log  = logging.getLogger("pipndeploy")

        self._full_stack.setCurrentIndex(1)
        self._set_status("Initialising & building…")

        def task():
            deps = core_logic.detect_dependencies(root) if auto else []
            core_logic.init_project_command(
                name=name, version="0.1.0", description=desc,
                author=author, email=email, dependencies=deps,
                license_text=lic, keywords=kw, homepage=home,
                cli_script_value=cli, project_root=root,
            )
            log.info("✅ Init complete.")
            # Capture returned interpreter so the deploy step uses the same env.
            py = core_logic.build_package(project_root=root)
            self._last_build_python = py
            log.info("✅ Build complete.")

        def done(_):
            self._full_stack.setCurrentIndex(2)
            self._set_status("Build successful — ready to deploy.")

        def err(msg):
            log.error("❌ %s", msg)
            self._full_stack.setCurrentIndex(0)
            self._set_status("Pipeline failed.")

        self._run_in_thread(task, on_done=done, on_error=err)

    def _full_run_deploy(self) -> None:
        root     = self._project_root()
        test     = self.full_testpypi.isChecked()
        dry_run  = self.full_dry_run.isChecked()
        log      = logging.getLogger("pipndeploy")
        # Use the interpreter that built the package — avoids venv/system mismatch.
        build_py = getattr(self, "_last_build_python", None)
        self._set_status("Deploying…")

        def task():
            return core_logic.upload_to_pypi(
                use_testpypi=test, dry_run=dry_run,
                project_root=root, python=build_py,
            )

        def done(result):
            if result:
                log.info(result)
            log.info("✅ Full pipeline complete.")
            self._full_stack.setCurrentIndex(0)
            self._set_status("Pipeline complete.")

        self._run_in_thread(task, on_done=done)

    def _load_project_for_update(self) -> None:
        root = self._project_root()
        log  = logging.getLogger("pipndeploy")
        self._set_status("Loading project…")

        def task():
            return core_logic.read_pyproject_toml(root)

        def done(data):
            if not data:
                log.error("❌ Could not load pyproject.toml.")
                self._set_status("Load failed.")
                return
            self.upd_name.setText(data.get("name", ""))
            self.upd_version.setText(data.get("version", ""))
            self.upd_description.setText(data.get("description", ""))
            self.upd_author.setText(data.get("author_name", ""))
            self.upd_email.setText(data.get("author_email", ""))
            lic = data.get("license", "")
            self.upd_license.setCurrentText(lic if isinstance(lic, str) else "")
            self.upd_homepage.setText(data.get("homepage_url", ""))
            self.upd_keywords.setText(", ".join(data.get("keywords", [])))
            self.upd_cli_script.setText(data.get("cli_script_value", ""))
            self.upd_dependencies.setText(", ".join(data.get("dependencies", [])))
            log.info("✅ Project loaded for update.")
            self._set_status("Project loaded.")

        self._run_in_thread(task, on_done=done)

    def _run_update(self) -> None:
        name  = self.upd_name.text().strip()
        ver   = self.upd_version.text().strip()
        auth  = self.upd_author.text().strip()
        email = self.upd_email.text().strip()
        log   = logging.getLogger("pipndeploy")

        if not name or not ver or not auth or not email:
            log.error("❌ Name, Version, Author, Email are required.")
            return
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            log.error("❌ Invalid email format.")
            return

        root    = self._project_root()
        desc    = self.upd_description.text().strip()
        lic     = self.upd_license.currentText()
        home    = self.upd_homepage.text().strip()
        kw      = [k.strip() for k in self.upd_keywords.text().split(",") if k.strip()]
        cli     = self.upd_cli_script.text().strip()
        deps    = [d.strip() for d in self.upd_dependencies.text().split(",") if d.strip()]
        clean   = self.upd_clean_first.isChecked()
        test    = self.upd_testpypi.isChecked()
        dry_run = self.upd_dry_run.isChecked()
        self._set_status("Updating…")

        def task():
            if clean:
                log.info("🧹 Cleaning before build…")
                core_logic.clean_project(
                    uninstall=False, purge_pyc=True,
                    interactive=False, project_root=root,
                )
            core_logic.generate_pyproject(
                name=name, version=ver, description=desc,
                author=auth, email=email, dependencies=deps,
                license_text=lic, keywords=kw, homepage=home,
                cli_script_value=cli, project_root=root,
            )
            log.info("✅ pyproject.toml updated.")
            py = core_logic.build_package(project_root=root)
            log.info("✅ Build complete.")
            return core_logic.upload_to_pypi(
                use_testpypi=test, dry_run=dry_run,
                project_root=root, python=py,
            )

        def done(result):
            if result:
                log.info(result)
            log.info("✅ Update complete.")
            self._set_status("Update complete.")

        self._run_in_thread(task, on_done=done)

    def _generate_pypirc(self) -> None:
        import os as _os
        import shutil as _shutil
        log            = logging.getLogger("pipndeploy")
        pypi_token     = self.auth_pypi.text().strip()
        testpypi_token = self.auth_testpypi.text().strip()

        if not pypi_token and not testpypi_token:
            log.error("❌ Enter at least one API token.")
            return

        pypirc = Path.home() / ".pypirc"

        # Warn before overwriting an existing file
        if pypirc.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite ~/.pypirc?",
                f"A .pypirc already exists at:\n{pypirc}\n\n"
                "A backup will be saved as .pypirc.bak before overwriting.\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                log.info("🔎 .pypirc generation cancelled.")
                return
            # Back up the existing file before overwriting
            backup = pypirc.with_name(".pypirc.bak")
            _shutil.copy2(pypirc, backup)
            log.info("🔎 Backed up existing .pypirc → %s", backup)

        # Only list servers that actually have a token configured
        servers: list[str] = []
        if pypi_token:
            servers.append("pypi")
        if testpypi_token:
            servers.append("testpypi")

        config = configparser.ConfigParser()
        # Use newline-indented format so index-servers is one entry per line
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

        try:
            with open(pypirc, "w") as fh:
                config.write(fh)

            # Restrict permissions to owner-only on Unix-like systems
            if _os.name != "nt":
                _os.chmod(pypirc, 0o600)
                log.info("🔎 Set .pypirc permissions to 600 (owner read/write only).")

            log.info("✅ .pypirc generated at %s", pypirc)
            log.info("⚠️  API tokens are stored in plaintext. Keep this file private.")
            self._set_status(".pypirc generated.")
            self.auth_pypi.clear()
            self.auth_testpypi.clear()
        except Exception as exc:
            log.error("❌ Failed to write .pypirc: %s", exc)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor("#1e293b"))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Base,            QColor("#0f172a"))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor("#1e293b"))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor("#334155"))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Text,            QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Button,          QColor("#334155"))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor("#f8fafc"))
    palette.setColor(QPalette.ColorRole.Link,            QColor("#60a5fa"))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor("#3b82f6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    win = PipnDeployGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
