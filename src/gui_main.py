# gui_main.py — Tkinter GUI for pipndeploy (wired to core_logic.py)

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from pathlib import Path
import sys
import os
import re
from functools import partial
import json
import configparser

from PiPnDeploy import core_logic

WINDOW_TITLE = "PiPnDeploy GUI"
PAD = 10
HELP_FILE = Path(__file__).parent / "Features.md"
PROFILE_FILE = "profile.json"
LICENSE_OPTIONS = [
    "MIT",
    "Apache-2.0",
    "GPL-3.0",
    "LGPL-3.0",
    "BSD-3-Clause",
    "BSD-2-Clause",
    "Mozilla Public License 2.0",
    "Eclipse Public License 20",
    "The Unlicense",
    "ISC",
    "Creative Commons Zero v1.0 Universal",
    "Freeware"
]

class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(self.tooltip_window, text=self.text, background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                          font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class StdoutRedirector(object):
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.tags = {
            "✅": "success",
            "❌": "error",
            "⚠️": "warning",
            "🔎": "info",
        }

    def write(self, string):
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        for mark, tag in self.tags.items():
            if mark in string:
                start = self.text_widget.search(mark, "1.0", tk.END)
                if start:
                    end = self.text_widget.index(f"{start} lineend")
                    self.text_widget.tag_add(tag, start, end)

    def flush(self):
        pass

class PipnDeployGUI:
    def __init__(self, root):
        self.root = root
        root.title(WINDOW_TITLE)
        self.full_pipeline_step = 0
        self.full_pipeline_frames = {}
        self.project_path = tk.StringVar(value=os.getcwd())
        self.original_cwd = os.getcwd()

        self.setup_ui()
        self.setup_output_redirect()
        self.load_profile()
        self.update_status(f"Project directory: {self.project_path.get()}")


    def setup_ui(self):
        # Create a container frame for tabs and console
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Project directory selector at the top
        path_frame = ttk.LabelFrame(main_frame, text="Project Directory")
        path_frame.pack(fill=tk.X, padx=PAD, pady=PAD)
        path_entry = ttk.Entry(path_frame, textvariable=self.project_path)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(PAD, 5))
        path_button = ttk.Button(path_frame, text="Select Folder", command=self.select_project_directory)
        path_button.pack(side=tk.RIGHT, padx=(0, PAD))

        # Tab control below the path selector
        self.tab_control = ttk.Notebook(main_frame)
        self.tab_profile = ttk.Frame(self.tab_control)
        self.tab_init = ttk.Frame(self.tab_control)
        self.tab_build = ttk.Frame(self.tab_control)
        self.tab_deploy = ttk.Frame(self.tab_control)
        self.tab_clean = ttk.Frame(self.tab_control)
        self.tab_full = ttk.Frame(self.tab_control)
        self.tab_update = ttk.Frame(self.tab_control)
        self.tab_auth_gen = ttk.Frame(self.tab_control) # New tab for auth generation
        self.tab_help = ttk.Frame(self.tab_control) 

        self.tab_control.add(self.tab_profile, text='👤 Profile')
        self.tab_control.add(self.tab_init, text='🛠 Init')
        self.tab_control.add(self.tab_build, text='📦 Build')
        self.tab_control.add(self.tab_deploy, text='🚀 Deploy')
        self.tab_control.add(self.tab_clean, text='🧹 Clean')
        self.tab_control.add(self.tab_full, text='🌀 Full')
        self.tab_control.add(self.tab_update, text='🔄 Update')
        self.tab_control.add(self.tab_auth_gen, text='🔑 Auth Gen') # Add the new tab
        self.tab_control.add(self.tab_help, text='📘 Help')

        self.tab_control.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Output console at the bottom
        console_frame = ttk.LabelFrame(main_frame, text="Output Console")
        console_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=PAD, pady=PAD)
        self.output_text = scrolledtext.ScrolledText(console_frame, wrap=tk.WORD, height=10)
        self.output_text.pack(expand=1, fill='both', padx=PAD, pady=PAD)

        # Configure color tags
        self.output_text.tag_configure("success", foreground="green")
        self.output_text.tag_configure("error", foreground="red")
        self.output_text.tag_configure("warning", foreground="orange")
        self.output_text.tag_configure("info", foreground="blue")
        
        # Status Bar
        self.status_bar = ttk.Label(main_frame, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.build_profile_tab()
        self.build_init_tab()
        self.build_build_tab()
        self.build_deploy_tab()
        self.build_clean_tab()
        self.build_full_tab()
        self.build_update_tab()
        self.build_auth_gen_tab() # Call to build the new auth generation tab
        self.build_help_tab()

    def select_project_directory(self):
        new_path = filedialog.askdirectory()
        if new_path:
            self.project_path.set(new_path)
            self.update_status(f"Project directory set to: {new_path}")
            print(f"🔎 Project directory set to: {new_path}")


    def setup_output_redirect(self):
        sys.stdout = StdoutRedirector(self.output_text)
        sys.stderr = StdoutRedirector(self.output_text)

    def update_status(self, message):
        self.status_bar.config(text=message)

    def load_help_content(self):
        # Ensure help_display_text is initialized before inserting content
        if hasattr(self, 'help_display_text'):
            if HELP_FILE.exists():
                with open(HELP_FILE, encoding='utf-8') as f:
                    self.help_display_text.insert(tk.END, f.read())
            else:
                self.help_display_text.insert(tk.END, "❌ Help file (Features.md) not found.")
        else:
            print("⚠️ Help display widget not initialized yet. Skipping help content load.")


    def load_profile(self):
        if Path(PROFILE_FILE).exists():
            try:
                with open(PROFILE_FILE, 'r') as f:
                    profile_data = json.load(f)
                    # Update init and full tab entries
                    self.author_entry.insert(0, profile_data.get('author', ''))
                    self.email_entry.insert(0, profile_data.get('email', ''))
                    self.full_author_entry.insert(0, profile_data.get('author', ''))
                    self.full_email_entry.insert(0, profile_data.get('email', ''))
                    # Update profile tab entries
                    self.profile_author_entry.insert(0, profile_data.get('author', ''))
                    self.profile_email_entry.insert(0, profile_data.get('email', ''))
                    self.update_status("Profile loaded successfully.")
                    print("🔎 Profile loaded from profile.json")
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"⚠️ Could not load profile: {e}")
                self.update_status("Profile not found or corrupted.")
        else:
            self.update_status("No profile found. Use the Profile tab to save your details.")
            print("🔎 No profile found.")

    def save_profile(self):
        author = self.profile_author_entry.get()
        email = self.profile_email_entry.get()
        
        if not author or not email:
            print("❌ Both Author and Email are required to save a profile.")
            return

        profile_data = {
            'author': author,
            'email': email
        }
        
        try:
            with open(PROFILE_FILE, 'w') as f:
                json.dump(profile_data, f, indent=4)
            print("✅ Profile saved successfully.")
            self.update_status("Profile saved.")
            # Update init and full tab entries
            self.author_entry.delete(0, tk.END)
            self.author_entry.insert(0, author)
            self.email_entry.delete(0, tk.END)
            self.email_entry.insert(0, email)
            self.full_author_entry.delete(0, tk.END)
            self.full_author_entry.insert(0, author)
            self.full_email_entry.delete(0, tk.END)
            self.full_email_entry.insert(0, email)

        except Exception as e:
            print(f"❌ Failed to save profile: {e}")
            self.update_status("Failed to save profile.")

    def build_profile_tab(self):
        frame = self.tab_profile
        input_frame = ttk.Frame(frame)
        input_frame.pack(pady=PAD)
        
        ttk.Label(input_frame, text="Default Author:").grid(row=0, column=0, sticky='e', padx=PAD, pady=5)
        self.profile_author_entry = ttk.Entry(input_frame)
        self.profile_author_entry.grid(row=0, column=1, padx=PAD, pady=5)
        
        ttk.Label(input_frame, text="Default Email:").grid(row=1, column=0, sticky='e', padx=PAD, pady=5)
        self.profile_email_entry = ttk.Entry(input_frame)
        self.profile_email_entry.grid(row=1, column=1, padx=PAD, pady=5)
        
        save_btn = ttk.Button(frame, text="Save Profile", command=self.save_profile)
        save_btn.pack(pady=PAD)

    def build_init_tab(self):
        frame = self.tab_init
        
        input_frame = ttk.Frame(frame)
        input_frame.pack(pady=PAD)

        ttk.Label(input_frame, text="Package Name:").grid(row=0, column=0, sticky='e', padx=PAD, pady=5)
        self.name_entry = ttk.Entry(input_frame)
        self.name_entry.grid(row=0, column=1, padx=PAD, pady=5)
        check_name_btn = ttk.Button(input_frame, text="Check Name", command=self.check_name_command)
        check_name_btn.grid(row=0, column=2, padx=PAD)
        Tooltip(check_name_btn, "Check if the package name is available on PyPI and TestPyPI.")
        
        ttk.Label(input_frame, text="Author:").grid(row=1, column=0, sticky='e', padx=PAD, pady=5)
        self.author_entry = ttk.Entry(input_frame)
        self.author_entry.grid(row=1, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')
        
        ttk.Label(input_frame, text="Email:").grid(row=2, column=0, sticky='e', padx=PAD, pady=5)
        self.email_entry = ttk.Entry(input_frame)
        self.email_entry.grid(row=2, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Description:").grid(row=3, column=0, sticky='e', padx=PAD, pady=5)
        self.description_entry = ttk.Entry(input_frame)
        self.description_entry.grid(row=3, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')
        
        ttk.Label(input_frame, text="License:").grid(row=4, column=0, sticky='e', padx=PAD, pady=5)
        self.license_combobox = ttk.Combobox(input_frame, values=LICENSE_OPTIONS, state="readonly")
        self.license_combobox.set("MIT")
        self.license_combobox.grid(row=4, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Homepage URL:").grid(row=5, column=0, sticky='e', padx=PAD, pady=5)
        self.homepage_entry = ttk.Entry(input_frame)
        self.homepage_entry.grid(row=5, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')
        self.homepage_entry.insert(0, "https://github.com/yourusername/your-package")

        ttk.Label(input_frame, text="Keywords (comma-separated):").grid(row=6, column=0, sticky='e', padx=PAD, pady=5)
        self.keywords_entry = ttk.Entry(input_frame)
        self.keywords_entry.grid(row=6, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="CLI Script:").grid(row=7, column=0, sticky='e', padx=PAD, pady=5)
        self.cli_script_entry = ttk.Entry(input_frame)
        self.cli_script_entry.grid(row=7, column=1, padx=PAD, pady=5, sticky='we')
        cli_browse_btn = ttk.Button(input_frame, text="Browse...", command=self.select_cli_script_file)
        cli_browse_btn.grid(row=7, column=2, padx=PAD)
        Tooltip(cli_browse_btn, "Select the Python file that contains the main entry point for your CLI.")

        self.auto_deps_var = tk.BooleanVar(value=True)
        auto_deps_cb = ttk.Checkbutton(input_frame, text="Auto Detect Dependencies", variable=self.auto_deps_var)
        auto_deps_cb.grid(row=8, columnspan=3, pady=PAD)
        Tooltip(auto_deps_cb, "Automatically detect dependencies and add them to pyproject.toml.")

        init_btn = ttk.Button(frame, text="Run Init", command=self.run_init_command)
        init_btn.pack(pady=PAD)

    def select_cli_script_file(self):
        file_path = filedialog.askopenfilename(
            initialdir=self.project_path.get(),
            title="Select CLI Script File",
            filetypes=(("Python files", "*.py"), ("All files", "*.*"))
        )
        if file_path:
            # Extract the file name (e.g., "main.py") and remove the extension
            file_name = Path(file_path).name
            module_name = file_name.removesuffix('.py')
            
            # Use the package name from the entry field
            package_name = self.name_entry.get()
            
            if not package_name:
                messagebox.showerror("Error", "Please enter a Package Name first.")
                return

            # Construct the cli_script string
            cli_script = f'{package_name}.{module_name}:main'
            
            # Update the entry field
            self.cli_script_entry.delete(0, tk.END)
            self.cli_script_entry.insert(0, cli_script)
            print(f"🔎 CLI Script set to: {cli_script}")
    
    def build_build_tab(self):
        frame = self.tab_build
        build_btn = ttk.Button(frame, text="Build Package", command=self.run_build_command)
        build_btn.pack(pady=PAD)

    def build_deploy_tab(self):
        frame = self.tab_deploy
        self.deploy_test_var = tk.BooleanVar()
        self.deploy_dry_run_var = tk.BooleanVar()

        test_cb = ttk.Checkbutton(frame, text="Upload to TestPyPI", variable=self.deploy_test_var)
        test_cb.pack(anchor="w", padx=PAD)
        Tooltip(test_cb, "Upload the package to the TestPyPI repository.")

        dry_run_cb = ttk.Checkbutton(frame, text="Dry Run (no upload)", variable=self.deploy_dry_run_var)
        dry_run_cb.pack(anchor="w", padx=PAD)
        Tooltip(dry_run_cb, "Simulate the upload without actually publishing the package.")

        deploy_btn = ttk.Button(frame, text="Run Deploy", command=self.run_deploy_command)
        deploy_btn.pack(pady=PAD)

        # Add Auth Check button to Deploy tab
        auth_check_btn = ttk.Button(frame, text="Run Auth Check", command=self.run_auth_check_command)
        auth_check_btn.pack(pady=PAD)
        Tooltip(auth_check_btn, "Check your .pypirc file for correct PyPI/TestPyPI authentication token configuration.")

    def build_clean_tab(self):
        frame = self.tab_clean
        self.clean_uninstall = tk.BooleanVar(value=True)
        self.clean_purge = tk.BooleanVar(value=True)
        self.clean_interactive = tk.BooleanVar(value=False)

        ttk.Checkbutton(frame, text="Uninstall package", variable=self.clean_uninstall).pack(anchor="w", padx=PAD)
        ttk.Checkbutton(frame, text="Purge .pyc & cache", variable=self.clean_purge).pack(anchor="w", padx=PAD)
        ttk.Checkbutton(frame, text="Interactive prompts", variable=self.clean_interactive).pack(anchor="w", padx=PAD)

        ttk.Button(frame, text="Clean Project", command=self.run_clean_command).pack(pady=PAD)

    def build_full_tab(self):
        frame = self.tab_full
        
        self.full_pipeline_frames['init'] = ttk.Frame(frame)
        init_frame = self.full_pipeline_frames['init']
        
        ttk.Label(init_frame, text="Package Name:").grid(row=0, column=0, sticky='e', padx=PAD, pady=5)
        self.full_name_entry = ttk.Entry(init_frame)
        self.full_name_entry.grid(row=0, column=1, padx=PAD, pady=5)
        
        ttk.Label(init_frame, text="Author:").grid(row=1, column=0, sticky='e', padx=PAD, pady=5)
        self.full_author_entry = ttk.Entry(init_frame)
        self.full_author_entry.grid(row=1, column=1, padx=PAD, pady=5)
        
        ttk.Label(init_frame, text="Email:").grid(row=2, column=0, sticky='e', padx=PAD, pady=5)
        self.full_email_entry = ttk.Entry(init_frame)
        self.full_email_entry.grid(row=2, column=1, padx=PAD, pady=5)

        ttk.Label(init_frame, text="Description:").grid(row=3, column=0, sticky='e', padx=PAD, pady=5)
        self.full_description_entry = ttk.Entry(init_frame)
        self.full_description_entry.grid(row=3, column=1, padx=PAD, pady=5)

        ttk.Label(init_frame, text="License:").grid(row=4, column=0, sticky='e', padx=PAD, pady=5)
        self.full_license_combobox = ttk.Combobox(init_frame, values=LICENSE_OPTIONS, state="readonly")
        self.full_license_combobox.set("MIT")
        self.full_license_combobox.grid(row=4, column=1, padx=PAD, pady=5)

        ttk.Label(init_frame, text="Homepage URL:").grid(row=5, column=0, sticky='e', padx=PAD, pady=5)
        self.full_homepage_entry = ttk.Entry(init_frame)
        self.full_homepage_entry.grid(row=5, column=1, padx=PAD, pady=5)
        self.full_homepage_entry.insert(0, "https://github.com/yourusername/your-package")

        ttk.Label(init_frame, text="Keywords (comma-separated):").grid(row=6, column=0, sticky='e', padx=PAD, pady=5)
        self.full_keywords_entry = ttk.Entry(init_frame)
        self.full_keywords_entry.grid(row=6, column=1, padx=PAD, pady=5)

        ttk.Label(init_frame, text="CLI Script:").grid(row=7, column=0, sticky='e', padx=PAD, pady=5)
        self.full_cli_script_entry = ttk.Entry(init_frame)
        self.full_cli_script_entry.grid(row=7, column=1, padx=PAD, pady=5, sticky='we')
        full_cli_browse_btn = ttk.Button(init_frame, text="Browse...", command=self.select_full_cli_script_file)
        full_cli_browse_btn.grid(row=7, column=2, padx=PAD)
        Tooltip(full_cli_browse_btn, "Select the Python file that contains the main entry point for your CLI.")

        self.full_auto_deps_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(init_frame, text="Auto Detect Dependencies", variable=self.full_auto_deps_var).grid(row=8, columnspan=2, pady=PAD)
        
        self.full_next_button = ttk.Button(init_frame, text="Next: Build", command=self.run_full_pipeline)
        self.full_next_button.grid(row=9, columnspan=2, pady=PAD)
        self.full_pipeline_frames['init'].pack()

        self.full_pipeline_frames['build'] = ttk.Frame(frame)
        ttk.Label(self.full_pipeline_frames['build'], text="Building the package... Please wait.").pack(pady=PAD)
        ttk.Button(self.full_pipeline_frames['build'], text="Back", command=partial(self.show_full_pipeline_frame, 'init')).pack(pady=PAD)

        self.full_pipeline_frames['deploy'] = ttk.Frame(frame)
        self.full_test_var = tk.BooleanVar()
        self.full_dry_run_var = tk.BooleanVar()
        ttk.Label(self.full_pipeline_frames['deploy'], text="Build successful. Ready to deploy.").pack(pady=PAD)
        ttk.Checkbutton(self.full_pipeline_frames['deploy'], text="Upload to TestPyPI", variable=self.full_test_var).pack(anchor="w", padx=PAD)
        ttk.Checkbutton(self.full_pipeline_frames['deploy'], text="Dry Run (no upload)", variable=self.full_dry_run_var).pack(anchor="w", padx=PAD)
        ttk.Button(self.full_pipeline_frames['deploy'], text="Back", command=partial(self.show_full_pipeline_frame, 'init')).pack(pady=5)
        self.full_deploy_button = ttk.Button(self.full_pipeline_frames['deploy'], text="Run Deploy", command=self.run_full_deploy_command)
        self.full_deploy_button.pack(pady=PAD)

    def build_update_tab(self):
        frame = self.tab_update
        input_frame = ttk.Frame(frame)
        input_frame.pack(pady=PAD)

        ttk.Label(input_frame, text="Package Name:").grid(row=0, column=0, sticky='e', padx=PAD, pady=5)
        self.update_name_entry = ttk.Entry(input_frame, state='readonly')
        self.update_name_entry.grid(row=0, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Version:").grid(row=1, column=0, sticky='e', padx=PAD, pady=5)
        self.update_version_entry = ttk.Entry(input_frame)
        self.update_version_entry.grid(row=1, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')
        
        ttk.Label(input_frame, text="Description:").grid(row=2, column=0, sticky='e', padx=PAD, pady=5)
        self.update_description_entry = ttk.Entry(input_frame)
        self.update_description_entry.grid(row=2, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Author:").grid(row=3, column=0, sticky='e', padx=PAD, pady=5)
        self.update_author_entry = ttk.Entry(input_frame)
        self.update_author_entry.grid(row=3, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')
        
        ttk.Label(input_frame, text="Email:").grid(row=4, column=0, sticky='e', padx=PAD, pady=5)
        self.update_email_entry = ttk.Entry(input_frame)
        self.update_email_entry.grid(row=4, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="License:").grid(row=5, column=0, sticky='e', padx=PAD, pady=5)
        self.update_license_combobox = ttk.Combobox(input_frame, values=LICENSE_OPTIONS, state="readonly")
        self.update_license_combobox.grid(row=5, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Homepage URL:").grid(row=6, column=0, sticky='e', padx=PAD, pady=5)
        self.update_homepage_entry = ttk.Entry(input_frame)
        self.update_homepage_entry.grid(row=6, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Keywords (comma-separated):").grid(row=7, column=0, sticky='e', padx=PAD, pady=5)
        self.update_keywords_entry = ttk.Entry(input_frame)
        self.update_keywords_entry.grid(row=7, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="CLI Script:").grid(row=8, column=0, sticky='e', padx=PAD, pady=5)
        self.update_cli_script_entry = ttk.Entry(input_frame)
        self.update_cli_script_entry.grid(row=8, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        ttk.Label(input_frame, text="Dependencies (comma-separated):").grid(row=9, column=0, sticky='e', padx=PAD, pady=5)
        self.update_dependencies_entry = ttk.Entry(input_frame)
        self.update_dependencies_entry.grid(row=9, column=1, padx=PAD, pady=5, columnspan=2, sticky='we')

        load_project_btn = ttk.Button(frame, text="Load Project", command=self.load_project_for_update)
        load_project_btn.pack(pady=PAD)

        self.update_clean_before_build_var = tk.BooleanVar(value=False) # New checkbox variable
        clean_cb = ttk.Checkbutton(frame, text="Clean before Build", variable=self.update_clean_before_build_var)
        clean_cb.pack(anchor="w", padx=PAD)
        Tooltip(clean_cb, "Run a clean operation (remove build artifacts, caches) before building and deploying.")

        self.update_test_var = tk.BooleanVar()
        self.update_dry_run_var = tk.BooleanVar()

        test_cb = ttk.Checkbutton(frame, text="Upload to TestPyPI", variable=self.update_test_var)
        test_cb.pack(anchor="w", padx=PAD)
        Tooltip(test_cb, "Upload the package to the TestPyPI repository.")

        dry_run_cb = ttk.Checkbutton(frame, text="Dry Run (no upload)", variable=self.update_dry_run_var)
        dry_run_cb.pack(anchor="w", padx=PAD)
        Tooltip(dry_run_cb, "Simulate the upload without actually publishing the package.")

        update_deploy_btn = ttk.Button(frame, text="Build & Deploy Update", command=self.run_update_build_and_deploy)
        update_deploy_btn.pack(pady=PAD)


    def build_auth_gen_tab(self):
        frame = self.tab_auth_gen
        
        input_frame = ttk.Frame(frame)
        input_frame.pack(pady=PAD)
        
        ttk.Label(input_frame, text="PyPI API Token:").pack(pady=(10,0))
        self.pypi_token_entry = ttk.Entry(input_frame, width=50, show="*")
        self.pypi_token_entry.pack(pady=(0,10))
        
        ttk.Label(input_frame, text="TestPyPI API Token:").pack(pady=(10,0))
        self.testpypi_token_entry = ttk.Entry(input_frame, width=50, show="*")
        self.testpypi_token_entry.pack(pady=(0,10))
        
        generate_button = ttk.Button(frame, text="Generate .pypirc", command=self.run_pypirc_generator)
        generate_button.pack(pady=20)
        
        tk.Label(frame, text="Note: Tokens will be saved in ~/.pypirc\nAt least one token is required.", 
                 font=("Arial", 8), justify="center").pack(pady=10)

    def run_pypirc_generator(self):
        pypi_token = self.pypi_token_entry.get().strip()
        testpypi_token = self.testpypi_token_entry.get().strip()
        
        if not pypi_token and not testpypi_token:
            print("❌ Please enter at least one API token.")
            self.update_status("Generation failed.")
            return

        config = configparser.ConfigParser()
        config['distutils'] = {'index-servers': 'pypi testpypi'}
        
        if pypi_token:
            config['pypi'] = {
                'repository': 'https://upload.pypi.org/legacy/',
                'username': '__token__',
                'password': pypi_token
            }
        
        if testpypi_token:
            config['testpypi'] = {
                'repository': 'https://test.pypi.org/legacy/',
                'username': '__token__',
                'password': testpypi_token
            }
            
        try:
            home_dir = Path.home()
            pypirc_path = home_dir / ".pypirc"
            
            with open(pypirc_path, "w") as f:
                config.write(f)
            
            print(f"✅ .pypirc file generated successfully at {pypirc_path}")
            self.update_status(".pypirc file generated.")

            self.pypi_token_entry.delete(0, tk.END)
            self.testpypi_token_entry.delete(0, tk.END)
            
        except Exception as e:
            print(f"❌ Failed to generate .pypirc file: {str(e)}")
            self.update_status("Generation failed.")

    def build_help_tab(self):
        frame = self.tab_help
        # Create a dedicated scrolled text widget for the help content
        self.help_display_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=20)
        self.help_display_text.pack(expand=1, fill='both', padx=PAD, pady=PAD)
        # Load content into the dedicated help text widget
        self.load_help_content()

    def select_full_cli_script_file(self):
        file_path = filedialog.askopenfilename(
            initialdir=self.project_path.get(),
            title="Select CLI Script File",
            filetypes=(("Python files", "*.py"), ("All files", "*.*"))
        )
        if file_path:
            file_name = Path(file_path).name
            module_name = file_name.removesuffix('.py')
            package_name = self.full_name_entry.get()
            
            if not package_name:
                messagebox.showerror("Error", "Please enter a Package Name first.")
                return

            cli_script = f'{package_name}.{module_name}:main'
            
            self.full_cli_script_entry.delete(0, tk.END)
            self.full_cli_script_entry.insert(0, cli_script)
            print(f"🔎 CLI Script set to: {cli_script}")

    def show_full_pipeline_frame(self, frame_name):
        for frame in self.full_pipeline_frames.values():
            frame.pack_forget()
        self.full_pipeline_frames[frame_name].pack()

    def run_with_cwd(self, func, *args, **kwargs):
        """Temporarily changes the current working directory before calling a function."""
        current_path = os.getcwd()
        try:
            os.chdir(self.project_path.get())
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            print(f"❌ An error occurred: {e}")
        finally:
            os.chdir(current_path)
        return None

    def run_init_command(self):
        self.run_with_cwd(self.run_init)

    def run_build_command(self):
        self.run_with_cwd(self.run_build)

    def run_deploy_command(self):
        output = self.run_with_cwd(self.run_deploy)
        if output:
            print(output)

    def run_clean_command(self):
        self.run_with_cwd(self.run_clean)

    def run_full_deploy_command(self):
        output = self.run_with_cwd(self.run_full_deploy)
        if output:
            print(output)
            
    def run_auth_check_command(self):
        self.update_status("Running authentication check...")
        success, messages = self.run_with_cwd(core_logic.auth_check)
        for msg in messages:
            print(msg)
        if success:
            self.update_status("Authentication check passed.")
        else:
            self.update_status("Authentication check failed. See console for details.")


    def check_name_command(self):
        name = self.name_entry.get()
        self.update_status("Checking package name...")
        if not name:
            print("⚠️ Please enter a package name to check.")
            self.update_status("Ready")
            return
        
        self.run_with_cwd(self.run_check_name_command, name)

    def run_check_name_command(self, name):
        print(f"🔎 Checking availability for '{name}'...")
        taken_pypi, taken_test = core_logic.check_name_availability(name)
        
        if taken_pypi is True:
            print(f"❌ '{name}' is taken on PyPI.")
        elif taken_pypi is False:
            print(f"✅ '{name}' is available on PyPI.")
        else:
            print(f"⚠️ Could not determine availability on PyPI.")

        if taken_test is True:
            print(f"❌ '{name}' is taken on TestPyPI.")
        elif taken_test is False:
            print(f"✅ '{name}' is available on TestPyPI.")
        else:
            print(f"⚠️ Could not determine availability on TestPyPI.")
        self.update_status("Ready")

    def run_init(self):
        name = self.name_entry.get()
        author = self.author_entry.get()
        email = self.email_entry.get()
        description = self.description_entry.get()
        license_text = self.license_combobox.get()
        homepage = self.homepage_entry.get()
        keywords = [k.strip() for k in self.keywords_entry.get().split(',') if k.strip()]
        cli_script_value = self.cli_script_entry.get()

        if not name or not author or not email:
            print("❌ All fields (Name, Author, Email) are required.")
            self.update_status("Init failed: Missing fields.")
            return

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            print("❌ Invalid email format.")
            self.update_status("Init failed: Invalid email.")
            return
        
        if not cli_script_value:
            cli_script_value = f"{name}.main:main"
            print(f"🔎 CLI Script field was empty, using default: {cli_script_value}")

        self.update_status("Initializing project...")
        try:
            dependencies = core_logic.detect_dependencies() if self.auto_deps_var.get() else []
            classifiers = [
                "Programming Language :: Python :: 3",
                "License :: OSI Approved :: MIT License",
                "Operating System :: OS Independent"
            ]
            core_logic.init_project_command(
                name=name,
                version="0.1.0",
                description=description,
                author=author,
                email=email,
                dependencies=dependencies,
                license_text=license_text,
                keywords=keywords,
                classifiers=classifiers,
                homepage=homepage,
                cli_script_value=cli_script_value
            )
            print("✅ Init Complete: pyproject.toml and README.md created.")
            self.update_status("Init complete.")
        except ValueError as e:
            print(f"❌ Error: {e}")
            self.update_status("Init failed.")

    def run_build(self):
        self.update_status("Building package...")
        try:
            core_logic.build_package_command() 
            print("✅ Build Complete.")
            self.update_status("Build complete.")
        except Exception as e:
            print(f"❌ Build failed: {e}")
            self.update_status("Build failed.")

    def run_deploy(self):
        self.update_status("Deploying package...")
        try:
            output = core_logic.deploy_package_command(
                testpypi=self.deploy_test_var.get(),
                dry_run=self.deploy_dry_run_var.get()
            )
            if output:
                print(output)
            else:
                self.update_status("Deploy complete.")
                print("✅ Deploy complete.")
        except Exception as e:
            print(f"❌ Deploy failed: {e}")
            self.update_status("Deploy failed.")

    def run_clean(self):
        self.update_status("Cleaning project...")
        try:
            core_logic.clean_project_command(
                uninstall=self.clean_uninstall.get(),
                purge_pyc=self.clean_purge.get(),
                interactive=self.clean_interactive.get()
            )
            print("✅ Clean complete.")
            self.update_status("Clean complete.")
        except Exception as e:
            print(f"❌ Clean failed: {e}")
            self.update_status("Clean failed.")
    
    def run_full_pipeline(self):
        if self.full_pipeline_step == 0:
            name = self.full_name_entry.get()
            author = self.full_author_entry.get()
            email = self.full_email_entry.get()
            description = self.full_description_entry.get()
            license_text = self.full_license_combobox.get()
            homepage = self.full_homepage_entry.get()
            keywords = [k.strip() for k in self.full_keywords_entry.get().split(',') if k.strip()]
            cli_script_value = self.full_cli_script_entry.get()

            if not name or not author or not email:
                print("❌ All fields (Name, Author, Email) are required for the full pipeline.")
                self.update_status("Full pipeline failed: Missing fields.")
                return

            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                print("❌ Invalid email format.")
                self.update_status("Full pipeline failed: Invalid email.")
                return

            if not cli_script_value:
                cli_script_value = f"{name}.main:main"
                print(f"🔎 CLI Script field was empty, using default: {cli_script_value}")
            
            self.update_status("Initializing project...")
            self.run_with_cwd(self.run_full_init_step, name, author, email, description, license_text, homepage, keywords, cli_script_value)

        elif self.full_pipeline_step == 1:
            self.update_status("Building package...")
            self.run_with_cwd(self.run_full_build_step)
        
    def run_full_init_step(self, name, author, email, description, license_text, homepage, keywords, cli_script_value):
        try:
            dependencies = core_logic.detect_dependencies() if self.full_auto_deps_var.get() else []
            classifiers = [
                "Programming Language :: Python :: 3",
                "License :: OSI Approved :: MIT License",
                "Operating System :: OS Independent"
            ]
            core_logic.init_project_command(
                name=name,
                version="0.1.0",
                description=description,
                author=author,
                email=email,
                dependencies=dependencies,
                license_text=license_text,
                keywords=keywords,
                classifiers=classifiers,
                homepage=homepage,
                cli_script_value=cli_script_value
            )
            print("✅ Init Complete: pyproject.toml and README.md created.")
            self.full_pipeline_step = 1
            self.show_full_pipeline_frame('build')
            self.root.after(100, self.run_full_pipeline)
        except ValueError as e:
            print(f"❌ Error during init: {e}")
            self.update_status("Full pipeline failed.")
        except Exception as e:
            print(f"❌ An unexpected error occurred during init: {e}")
            self.update_status("Full pipeline failed.")

    def run_full_build_step(self):
        try:
            core_logic.build_package_command() 
            print("✅ Build Complete.")
            self.full_pipeline_step = 2
            self.show_full_pipeline_frame('deploy')
            self.update_status("Build successful.")
        except Exception as e:
            print(f"❌ Build failed: {e}")
            self.full_pipeline_step = 0
            self.show_full_pipeline_frame('init')
            self.update_status("Full pipeline failed.")

    def run_full_deploy(self):
        self.update_status("Deploying package...")
        try:
            output = core_logic.deploy_package_command(
                testpypi=self.full_test_var.get(),
                dry_run=self.full_dry_run_var.get()
            )
            if output:
                print(output)
            else:
                print("✅ Full pipeline complete.")
            self.full_pipeline_step = 0
            self.show_full_pipeline_frame('init')
            self.update_status("Full pipeline complete.")
        except Exception as e:
            print(f"❌ Deploy failed: {e}")
            self.full_pipeline_step = 0
            self.show_full_pipeline_frame('init')
            self.update_status("Full pipeline failed.")

    def load_project_for_update(self):
        self.update_status("Loading project for update...")
        # Clear all fields first
        self.update_name_entry.config(state='normal')
        self.update_name_entry.delete(0, tk.END)
        self.update_name_entry.config(state='readonly')
        self.update_version_entry.delete(0, tk.END)
        self.update_description_entry.delete(0, tk.END)
        self.update_author_entry.delete(0, tk.END)
        self.update_email_entry.delete(0, tk.END)
        self.update_license_combobox.set('')
        self.update_homepage_entry.delete(0, tk.END)
        self.update_keywords_entry.delete(0, tk.END)
        self.update_cli_script_entry.delete(0, tk.END)
        self.update_dependencies_entry.delete(0, tk.END)


        try:
            project_data = self.run_with_cwd(core_logic.read_pyproject_toml)
            if project_data:
                self.update_name_entry.config(state='normal')
                self.update_name_entry.insert(0, project_data.get('name', ''))
                self.update_name_entry.config(state='readonly')

                self.update_version_entry.insert(0, project_data.get('version', ''))
                self.update_description_entry.insert(0, project_data.get('description', ''))
                self.update_author_entry.insert(0, project_data.get('author_name', ''))
                self.update_email_entry.insert(0, project_data.get('author_email', ''))
                self.update_license_combobox.set(project_data.get('license', {}).get('text', ''))
                self.update_homepage_entry.insert(0, project_data.get('homepage_url', ''))
                self.update_keywords_entry.insert(0, ", ".join(project_data.get('keywords', [])))
                self.update_cli_script_entry.insert(0, project_data.get('cli_script_value', ''))
                self.update_dependencies_entry.insert(0, ", ".join(project_data.get('dependencies', [])))


                print("✅ Project details loaded for update.")
                self.update_status("Project loaded for update.")
            else:
                print("❌ Failed to load project details. Is pyproject.toml present and valid?")
                self.update_status("Project load failed.")
        except Exception as e:
            print(f"❌ Error loading project for update: {e}")
            self.update_status("Project load failed.")

    def run_update_build_and_deploy(self):
        self.update_status("Building and deploying update...")
        name = self.update_name_entry.get()
        version = self.update_version_entry.get()
        description = self.update_description_entry.get()
        author = self.update_author_entry.get()
        email = self.update_email_entry.get()
        license_text = self.update_license_combobox.get()
        homepage = self.update_homepage_entry.get()
        keywords = [k.strip() for k in self.update_keywords_entry.get().split(',') if k.strip()]
        dependencies = [d.strip() for d in self.update_dependencies_entry.get().split(',') if d.strip()]
        cli_script_value = self.update_cli_script_entry.get()

        if not name or not version or not author or not email:
            print("❌ All fields (Name, Version, Author, Email) are required for update.")
            self.update_status("Update failed: Missing fields.")
            return

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            print("❌ Invalid email format.")
            self.update_status("Update failed: Invalid email.")
            return

        try:
            # Step 1: Optional Clean
            if self.update_clean_before_build_var.get():
                print("🧹 Cleaning project before build...")
                self.run_with_cwd(
                    core_logic.clean_project_command,
                    uninstall=False, # Don't uninstall the package itself during update clean
                    purge_pyc=True,
                    interactive=False
                )
                print("✅ Clean complete.")

            # Step 2: Generate/Update pyproject.toml
            classifiers = [
                "Programming Language :: Python :: 3",
                "License :: OSI Approved :: MIT License",
                "Operating System :: OS Independent"
            ]
            self.run_with_cwd(
                core_logic.generate_pyproject,
                name=name,
                version=version,
                description=description,
                author=author,
                email=email,
                dependencies=dependencies,
                license_text=license_text,
                keywords=keywords,
                classifiers=classifiers,
                homepage=homepage,
                cli_script_value=cli_script_value
            )
            print("✅ pyproject.toml updated successfully.")
            
            # Step 3: Build Package (explicitly called after clean and pyproject.toml update)
            self.run_with_cwd(core_logic.build_package_command)
            print("✅ Package built successfully.")

            # Step 4: Deploy (Upload only, as build is already done)
            output = self.run_with_cwd(
                core_logic.upload_to_pypi, 
                use_testpypi=self.update_test_var.get(),
                dry_run=self.update_dry_run_var.get()
            )
            if output:
                print(output)
            else:
                print("✅ Update build and deploy complete.")
            self.update_status("Update complete.")

        except Exception as e:
            print(f"❌ Update build and deploy failed: {e}")
            self.update_status("Update failed.")


if __name__ == '__main__':
    root = tk.Tk()
    app = PipnDeployGUI(root)
    root.mainloop()