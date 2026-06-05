"""
ClaudeLights Setup Wizard — 一键安装器
用 tkinter (Python 内置) 构建，PyInstaller 打包成独立 exe。
用户双击即开，无需命令行，无需预装任何依赖。
"""
import sys
import os
import json
import re
import subprocess
import shutil
import threading
import tempfile
import time
import tkinter as tk
from tkinter import ttk, messagebox

# ============================================================
# Constants
# ============================================================
INSTALL_DIR = os.path.expanduser("~/.claude-lights")
SETUP_LOCK = os.path.join(tempfile.gettempdir(), "claude-lights-setup.lock")

# When bundled by PyInstaller, sys._MEIPASS is the temp dir containing bundled files.
# When run from source, use the script's own directory.
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Fallback: also check current working directory (for direct invocation)
_SOURCE_DIRS = [SCRIPT_DIR]
_cwd = os.getcwd()
if _cwd not in _SOURCE_DIRS:
    _SOURCE_DIRS.append(_cwd)

# Colors — dark theme
C = {
    "bg":        "#0E0E12",
    "surface":   "#1C1C24",
    "border":    "#3A3A44",
    "text":      "#C8C8D0",
    "text_dim":  "#787880",
    "accent":    "#FFDC00",
    "green":     "#00E030",
    "red":       "#FF3030",
    "white":     "#FFFFFF",
}

# ============================================================
# Embedded file discovery
# ============================================================
# PyInstaller spec bundles core project files at the root level and sounds/ as a subdir.
# We scan SCRIPT_DIR recursively for all .py / .ps1 / .md / sound files.

_FILE_LIST = None  # cached


def get_embedded_files():
    """
    Return {relpath: full_source_path} for all files to install.
    Scans known project files across multiple possible source directories.
    """
    global _FILE_LIST
    if _FILE_LIST is not None:
        return _FILE_LIST

    _FILE_LIST = {}
    project_names = [
        "core.py",
        "light_server.py",
        "main.py",
        "client.py",
        "client.pyw",
        "install.ps1",
        "README.md",
    ]

    # When bundled by PyInstaller, _MEIPASS contains our datas=(file, '.') files.
    # PyInstaller 6.x may extract them directly under _MEIPASS or a sub-tree.
    if getattr(sys, 'frozen', False):
        # Walk _MEIPASS to find all embedded files — more robust than guessing layout.
        meipass = sys._MEIPASS
        for root, dirs, filenames in os.walk(meipass):
            rel_dir = os.path.relpath(root, meipass)
            for fn in filenames:
                if fn in project_names:
                    rel = fn  # flat layout: file is directly in _MEIPASS or its root
                else:
                    rel = os.path.join(rel_dir, fn) if rel_dir != '.' else fn
                fp = os.path.join(root, fn)
                if fn in project_names or fn.endswith(('.mp3', '.wav')):
                    _FILE_LIST[os.path.normpath(rel)] = fp

    # Also check development directories (script dir + cwd)
    for fname in project_names:
        for src_dir in _SOURCE_DIRS:
            fp = os.path.join(src_dir, fname)
            if os.path.isfile(fp) and fname not in _FILE_LIST:
                _FILE_LIST[fname] = fp
                break

    # Sounds directory
    for base in _SOURCE_DIRS:
        sounds_src = os.path.join(base, "sounds")
        if os.path.isdir(sounds_src):
            for fn in os.listdir(sounds_src):
                fp = os.path.join(sounds_src, fn)
                key = os.path.join("sounds", fn)
                if os.path.isfile(fp) and key not in _FILE_LIST:
                    _FILE_LIST[key] = fp
            break  # first match wins

    return _FILE_LIST


# ============================================================
# Install Logic
# ============================================================
class Installer:
    def __init__(self, log_callback, progress_callback):
        self.log = log_callback
        self.progress = progress_callback
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        steps = [
            ("提取文件", self._extract_files),
            ("安装 Python 依赖", self._install_deps),
            ("配置 PowerShell Profile", self._configure_profile),
            ("配置 Claude Code Hooks", self._configure_hooks),
            ("验证安装", self._verify),
        ]
        total = len(steps)
        errors = []

        for i, (name, func) in enumerate(steps):
            if self._cancelled:
                self.log("⏹ 安装已取消")
                return False, ["用户取消"]
            self.progress(i + 1, total, name)
            self.log(f"\n▸ {name}...")
            try:
                func()
            except Exception as e:
                self.log(f"  ✗ 失败: {e}")
                errors.append(f"{name}: {e}")

        self.progress(total, total, "完成" if not errors else "部分完成")
        return len(errors) == 0, errors

    def _extract_files(self):
        files = get_embedded_files()
        if not files:
            searched = ", ".join(_SOURCE_DIRS)
            self.log(f"  ⚠ 未找到任何项目文件（搜索路径: {searched}）")
            self.log(f"  ▸ 当前工作目录: {os.getcwd()}")
            self.log(f"  ▸ SCRIPT_DIR: {SCRIPT_DIR}")
            self.log(f"  ▸ 将尝试从当前目录复制...")
            # Last-resort: try CWD for everything
            cwd = os.getcwd()
            for fn in ["core.py", "light_server.py", "main.py"]:
                fp = os.path.join(cwd, fn)
                if os.path.isfile(fp):
                    files[fn] = fp

        if not files:
            self.log(f"  ✗ 无法找到源文件，安装无法继续")
            raise RuntimeError("未找到项目文件")

        os.makedirs(INSTALL_DIR, exist_ok=True)

        count = 0
        for fname, src_path in files.items():
            if self._cancelled:
                return
            dst = os.path.join(INSTALL_DIR, fname)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src_path, "rb") as src_f:
                with open(dst, "wb") as dst_f:
                    dst_f.write(src_f.read())
            count += 1

        self.log(f"  ✓ 已提取 {count} 个文件到 {INSTALL_DIR}")

    def _install_deps(self):
        deps = ["PySide6", "pygame"]
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        for dep in deps:
            if self._cancelled:
                return
            self.log(f"  ▸ pip install {dep} (PySide6 ~100MB, 下载需要几分钟)...")

            # Use Popen + real-time output forwarding so the user can see progress.
            # Without this, a blank log for 3-5 minutes looks like it's frozen.
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", dep, "--no-input",
                 "--progress-bar", "on"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creationflags,
            )

            # Read lines with timeout — show key lines to user
            last_log = time.time()
            try:
                for line in iter(proc.stdout.readline, ""):
                    if self._cancelled:
                        proc.terminate()
                        proc.wait()
                        return
                    line = line.strip()
                    if line:
                        # Forward every few lines or important ones
                        if any(kw in line for kw in ("Downloading", "Installing", "Successfully",
                                                      "Requirement", "ERROR", "error", "kB", "MB")):
                            self.log(f"    {line}")
                            last_log = time.time()
                        # If no interesting lines for 15s, show something
                        elif time.time() - last_log > 15:
                            self.log(f"    [下载中...]")
                            last_log = time.time()
            except Exception:
                pass

            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f"pip install {dep} 失败 (exit code {rc})")
            self.log(f"  ✓ {dep} 已安装")

    def _configure_profile(self):
        bin_cmd = f'python "{INSTALL_DIR}\\main.py"'
        func = f"""
# ClaudeLights auto-start — cmd /c 绕开 function 覆盖, 避免递归
function claude {{
    $LIGHTS_DIR = "{INSTALL_DIR}"
    $id = $null
    try {{
        $output = & {bin_cmd} start 2>&1
        $id = ($output | Select-String -Pattern "CC-\\d+").Matches.Value
        if ($id) {{
            $env:CLAUDE_LIGHTS_ID = $id
            $env:CLAUDE_LIGHTS_DIR = $LIGHTS_DIR
            Write-Host "[ClaudeLights] $id ready"
        }}
        cmd /c "claude $args"
    }} finally {{
        if ($id) {{ & {bin_cmd} stop $id 2>$null }}
    }}
}}
"""

        for pp in [
            os.path.expandvars(r"%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"),
            os.path.expandvars(r"%USERPROFILE%\Documents\PowerShell\Microsoft.PowerShell_profile.ps1"),
        ]:
            if self._cancelled:
                return
            os.makedirs(os.path.dirname(pp), exist_ok=True)
            existing = ""
            if os.path.exists(pp):
                with open(pp, encoding="utf-8") as f:
                    existing = f.read()

            if "ClaudeLights auto-start" in existing:
                new_func = func.strip()
                new_content = re.sub(
                    r'(?s)# ClaudeLights auto-start.*?(?=\n# ClaudeLights|\n# [A-Z]|\Z|\Z)',
                    lambda _: new_func,
                    existing,
                )
            else:
                new_content = existing.rstrip() + "\n" + func

            with open(pp, "w", encoding="utf-8") as f:
                f.write(new_content)

        self.log("  ✓ PowerShell Profile 已配置")

    def _configure_hooks(self):
        settings_path = os.path.expanduser("~/.claude/settings.json")
        bin_cmd = f'python "{INSTALL_DIR}\\main.py"'

        hook_defs = {
            "PreToolUse":        ("working",  "Working..."),
            "UserPromptSubmit":  ("working",  "Thinking..."),
            "Stop":              ("success",  "Done"),
            "StopFailure":       ("error",    "Failed"),
            "PermissionRequest": ("error",    "Need Choice"),
            "SessionEnd":        ("shutdown", "SessionEnd"),
        }

        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, encoding="utf-8") as f:
                    settings = json.load(f) or {}
            except Exception:
                settings = {}

        if "hooks" not in settings:
            settings["hooks"] = {}

        for event, (status, message) in hook_defs.items():
            if self._cancelled:
                return
            cmd = f'{bin_cmd} hook {status} "{message}"'

            if event not in settings["hooks"]:
                settings["hooks"][event] = []

            found = False
            for group in settings["hooks"].get(event, []):
                for h in group.get("hooks", []):
                    if "claude-lights" in h.get("command", "").lower():
                        h["command"] = cmd
                        found = True

            if not found:
                if len(settings["hooks"].get(event, [])) == 0:
                    settings["hooks"][event] = [{"matcher": "", "hooks": []}]
                settings["hooks"][event][0]["hooks"].append({
                    "type": "command",
                    "command": cmd,
                    "timeout": 3,
                    "async": True,
                    "asyncRewake": False,
                })

        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

        self.log("  ✓ Claude Code Hooks 已配置")

    def _verify(self):
        # Test import core from install dir
        sys.path.insert(0, INSTALL_DIR)
        try:
            import importlib
            importlib.import_module("core")
            self.log("  ✓ 核心模块验证通过")
        except Exception as e:
            self.log(f"  ⚠ 模块验证: {e}")

        # Check files
        for fn in ["core.py", "light_server.py", "main.py"]:
            fp = os.path.join(INSTALL_DIR, fn)
            if os.path.exists(fp):
                self.log(f"  ✓ {fn}")
            else:
                self.log(f"  ✗ {fn} 缺失")

        self.log("\n  安装完成! 🎉")


# ============================================================
# Setup Wizard UI (tkinter)
# ============================================================
class SetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ClaudeLights 安装向导")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Window size & center
        W, H = 520, 480
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        except Exception:
            self.geometry(f"{W}x{H}")

        # Try to set dark title bar on Windows
        try:
            import ctypes
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(ctypes.c_int(1)), 4)
        except Exception:
            pass

        # Styles
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=C["white"], background=C["bg"])
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground=C["text_dim"], background=C["bg"])
        style.configure("Body.TLabel", font=("Segoe UI", 10), foreground=C["text"], background=C["bg"])
        style.configure("Green.TLabel", font=("Segoe UI", 10, "bold"), foreground=C["green"], background=C["bg"])
        style.configure("Steps.TLabel", font=("Cascadia Code", 9), foreground=C["text_dim"], background=C["surface"])

        # Main container
        self.main = tk.Frame(self, bg=C["bg"], padx=36, pady=28)
        self.main.pack(fill="both", expand=True)

        self._show_welcome()

    def _clear(self):
        for w in self.main.winfo_children():
            w.destroy()

    def _on_close(self):
        if hasattr(self, "_installing") and self._installing:
            if messagebox.askyesno("取消安装", "安装正在进行中，确定要退出吗？"):
                if hasattr(self, "_installer"):
                    self._installer.cancel()
                self.destroy()
        else:
            self.destroy()

    # ================================================================
    # Page 1: Welcome
    # ================================================================
    def _show_welcome(self):
        self._clear()

        tk.Label(self.main, text="● ● ●", font=("Segoe UI", 32), fg=C["green"], bg=C["bg"]).pack(pady=(0, 8))

        tk.Label(self.main, text="ClaudeLights", font=("Segoe UI", 22, "bold"),
                 fg=C["white"], bg=C["bg"]).pack()

        tk.Label(self.main, text="Claude Code 桌面信号灯",
                 font=("Segoe UI", 11), fg=C["text_dim"], bg=C["bg"]).pack(pady=(2, 16))

        # Feature list frame
        features = tk.Frame(self.main, bg=C["surface"], padx=20, pady=14,
                            highlightbackground=C["border"], highlightthickness=1)
        features.pack(fill="x", padx=10, pady=(0, 14))
        for t in [
            "●  实时显示 Claude Code AI 任务状态",
            "●  3D 玻璃质感悬浮窗，鼠标穿透不挡操作",
            "●  多窗口会话隔离，自动启停",
            "●  任务完成提示音",
        ]:
            tk.Label(features, text=t, font=("Segoe UI", 9), fg=C["text_dim"],
                     bg=C["surface"], anchor="w", justify="left").pack(fill="x")

        # Detected status
        installed = os.path.exists(os.path.join(INSTALL_DIR, "core.py"))
        if installed:
            tk.Label(self.main, text="✓  检测到已有安装，将更新到最新版本",
                     font=("Segoe UI", 10, "bold"), fg=C["green"], bg=C["bg"]).pack(pady=(0, 6))
        else:
            tk.Label(self.main, text="即将安装到: " + INSTALL_DIR,
                     font=("Segoe UI", 9), fg=C["text_dim"], bg=C["bg"]).pack(pady=(0, 6))

        # Install button
        btn_frame = tk.Frame(self.main, bg=C["bg"])
        btn_frame.pack(pady=10)
        self._big_button(btn_frame, "⚡  一 键 安 装", C["accent"], "#1A1A1A", self._start_install)

        tk.Label(self.main, text="需要 Python 3.8+   •   自动安装 PySide6 + pygame",
                 font=("Segoe UI", 8), fg=C["text_dim"], bg=C["bg"]).pack(pady=(8, 0))

    def _big_button(self, parent, text, bg, fg, command):
        btn = tk.Button(parent, text=text, font=("Segoe UI", 13, "bold"),
                        fg=fg, bg=bg, activebackground="#FFE840", activeforeground="#1A1A1A",
                        relief="flat", padx=28, pady=10, cursor="hand2",
                        borderwidth=0, highlightthickness=0, command=command)
        btn.pack()
        btn.bind("<Enter>", lambda e: btn.configure(bg="#FFE840"))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    # ================================================================
    # Page 2: Installing (progress + log)
    # ================================================================
    def _start_install(self):
        # Prevent re-entry — double-click or rapid clicks
        if getattr(self, '_installing', False):
            return
        self._clear()
        self._installing = True

        tk.Label(self.main, text="正在安装...", font=("Segoe UI", 16, "bold"),
                 fg=C["white"], bg=C["bg"]).pack(pady=(0, 14))

        # Progress bar
        bar_frame = tk.Frame(self.main, bg=C["surface"], padx=2, pady=2,
                             highlightbackground=C["border"], highlightthickness=1)
        bar_frame.pack(fill="x", padx=20, pady=(0, 6))
        self._bar_canvas = tk.Canvas(bar_frame, height=18, bg=C["surface"],
                                      highlightthickness=0, bd=0)
        self._bar_canvas.pack(fill="x")
        self._bar_rect = self._bar_canvas.create_rectangle(0, 0, 0, 18, fill=C["accent"], outline="")

        # Step label
        self._step_label = tk.Label(self.main, text="准备中...", font=("Segoe UI", 9),
                                    fg=C["text_dim"], bg=C["bg"])
        self._step_label.pack(pady=(0, 10))

        # Log area
        log_frame = tk.Frame(self.main, bg=C["surface"], padx=10, pady=8,
                             highlightbackground=C["border"], highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=4, pady=(0, 10))

        self._log_text = tk.Text(log_frame, font=("Cascadia Code", 8),
                                  fg=C["text"], bg=C["surface"],
                                  relief="flat", borderwidth=0,
                                  wrap="word", height=8)
        self._log_text.pack(fill="both", expand=True)
        self._log_text.configure(state="disabled")

        # Buttons
        btn_frame = tk.Frame(self.main, bg=C["bg"])
        btn_frame.pack(pady=(6, 0))
        self._cancel_btn = tk.Button(btn_frame, text="取消", font=("Segoe UI", 9),
                                      fg=C["text_dim"], bg=C["surface"],
                                      relief="flat", padx=16, pady=4, cursor="hand2",
                                      command=lambda: self._installer.cancel() if hasattr(self, "_installer") else None)
        self._cancel_btn.pack(side="left", padx=(0, 10))

        self._close_btn = tk.Button(btn_frame, text="关闭", font=("Segoe UI", 9),
                                     fg=C["text_dim"], bg=C["surface"],
                                     relief="flat", padx=16, pady=4, cursor="hand2",
                                     command=self.destroy, state="disabled")
        self._close_btn.pack(side="left")

        self._launch_btn = tk.Button(btn_frame, text="启动管理客户端 →", font=("Segoe UI", 9, "bold"),
                                      fg="#1A1A1A", bg=C["accent"],
                                      relief="flat", padx=16, pady=4, cursor="hand2",
                                      command=self._launch_client, state="disabled")
        self._launch_btn.pack(side="right")

        self.update()
        self._run_install_thread()

    def _append_log(self, msg):
        self._log_text.configure(state="normal")
        self._log_text.insert("end", msg + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _update_progress(self, step, total, name):
        ratio = step / total
        bw = self._bar_canvas.winfo_width()
        self._bar_canvas.coords(self._bar_rect, 0, 0, int(bw * ratio), 18)
        self._step_label.configure(text=f"[{step}/{total}] {name}")
        self.update_idletasks()

    def _run_install_thread(self):
        self._installer = Installer(
            log_callback=lambda msg: self.after(0, self._append_log, msg),
            progress_callback=lambda s, t, n: self.after(0, self._update_progress, s, t, n),
        )

        def run():
            success, errors = self._installer.run()
            self.after(0, self._install_done, success, errors)

        threading.Thread(target=run, daemon=True).start()

    def _install_done(self, success, errors):
        self._installing = False
        self._cancel_btn.configure(state="disabled")

        if success:
            self._step_label.configure(text="✅ 安装完成！", fg=C["green"])
            self._close_btn.configure(state="normal")
            self._launch_btn.configure(state="normal", text="🚀 启动管理客户端 →")
            self._append_log("\n🎉 安装成功！点击下方按钮启动管理客户端。")
            self._append_log("新开 PowerShell 窗口，输入 claude 即可体验信号灯。")
            # Flash the launch button
            self._flash_launch()
        else:
            self._step_label.configure(text="⚠ 安装遇到问题", fg=C["red"])
            self._close_btn.configure(state="normal")
            self._append_log(f"\n⚠ 遇到 {len(errors)} 个错误:")
            for e in errors:
                self._append_log(f"  - {e}")
            self._append_log("\n请检查网络连接和 Python 环境后重试。")

    def _flash_launch(self):
        def toggle():
            if not hasattr(self, "_launch_btn") or not self._launch_btn.winfo_exists():
                return
            current = self._launch_btn.cget("bg")
            self._launch_btn.configure(bg=C["white"] if current == C["accent"] else C["accent"])
            self.after(400, toggle)
        self.after(200, toggle)

    def _launch_client(self):
        """Launch the management client after successful install."""
        # Verify PySide6 is actually importable before attempting launch
        try:
            subprocess.run(
                [sys.executable, "-c", "import PySide6"],
                capture_output=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception:
            self._append_log("\n✗ PySide6 未正确安装, 无法启动管理客户端")
            self._append_log("  请手动运行: pip install PySide6 pygame")
            self._append_log("  然后运行: python ~/.claude-lights/client.pyw")
            return

        client_py = os.path.join(INSTALL_DIR, "client.pyw")
        if not os.path.exists(client_py):
            client_py = os.path.join(INSTALL_DIR, "client.py")
        if os.path.exists(client_py):
            try:
                subprocess.Popen(
                    [sys.executable, client_py],
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                self._append_log("\n✓ 管理客户端已启动（查看系统托盘）")
            except Exception as e:
                self._append_log(f"\n✗ 启动客户端失败: {e}")
                self._append_log(f"  请手动运行: python {client_py}")
        else:
            self._append_log("\n✗ 未找到客户端文件，请检查安装目录")

        self.after(1000, self.destroy)


# ============================================================
# Entry Point
# ============================================================
def main():
    # Check Python version
    if sys.version_info < (3, 8):
        messagebox.showerror("错误", "需要 Python 3.8 或更高版本。\n当前版本: " + sys.version)
        sys.exit(1)

    # Single-instance lock — prevent multiple setup wizards from opening
    try:
        lock_fd = os.open(SETUP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(lock_fd)
    except FileExistsError:
        messagebox.showinfo("ClaudeLights", "安装向导已在运行中。\n请查看已打开的安装窗口。")
        sys.exit(0)

    try:
        app = SetupApp()
        app.mainloop()
    finally:
        try:
            os.remove(SETUP_LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
