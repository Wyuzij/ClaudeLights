"""
ClaudeLights Core — shared IPC, process management, and hook operations.
No PySide6 dependency. Uses pygame only for sound playback.
"""
import json
import os
import sys
import time
import glob
import subprocess
import ctypes
import argparse
from collections import namedtuple

# ============================================================
# Configurable base directory
# ============================================================
BASE = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(BASE, "sounds")
COMPLETE_SOUND = os.path.join(SOUNDS_DIR, "dragon-studio-new-notification-3-398649.mp3")


def set_base(path):
    """Redirect all file paths to a different base directory (used by client)."""
    global BASE, SOUNDS_DIR, COMPLETE_SOUND
    BASE = path
    SOUNDS_DIR = os.path.join(BASE, "sounds")
    COMPLETE_SOUND = os.path.join(SOUNDS_DIR, "dragon-studio-new-notification-3-398649.mp3")


# ============================================================
# File path helpers
# ============================================================
def _sf(lid):
    return os.path.join(BASE, f"status-{lid}.json")

def _pidf(lid):
    return os.path.join(BASE, f".pid-{lid}")

def _mapf(ppid):
    return os.path.join(BASE, f".map-{ppid}")

def _lock_path():
    return os.path.join(BASE, ".lock")

def _sessionf(sid):
    return os.path.join(BASE, f".session-{sid}")

def _project_marker():
    return os.path.join(os.getcwd(), '.claude', '.claude-lights-session')

def _config_path():
    return os.path.join(BASE, "client-config.json")


# ============================================================
# Lock mechanism
# ============================================================
def _acquire_lock(timeout=5.0):
    """File lock to prevent concurrent hook race conditions. With deadlock detection."""
    lp = _lock_path()
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            with open(lp, "w") as f:
                json.dump({"pid": os.getpid(), "ts": time.time()}, f)
            return True
        except FileExistsError:
            try:
                with open(lp) as f:
                    info = json.load(f)
                if time.time() - info.get("ts", 0) > 10:
                    try:
                        os.remove(lp)
                    except Exception:
                        pass
                    continue
            except Exception:
                pass
            if time.time() > deadline:
                return False
            time.sleep(0.1)


def _release_lock():
    try:
        lp = _lock_path()
        if os.path.exists(lp):
            os.remove(lp)
    except Exception:
        pass


# ============================================================
# Heartbeat & status file I/O
# ============================================================
def _read_heartbeat(lid):
    sf = _sf(lid)
    if not os.path.exists(sf):
        return 0
    try:
        with open(sf, encoding="utf-8") as f:
            return json.load(f).get("heartbeat", 0)
    except Exception:
        return 0


def _write(lid, status, msg=""):
    os.makedirs(BASE, exist_ok=True)
    with open(_sf(lid), "w", encoding="utf-8") as f:
        json.dump({"status": status, "message": msg, "heartbeat": time.time()}, f, ensure_ascii=False)


# ============================================================
# Process liveness check
# ============================================================
def _check_alive(pid):
    """Returns (certain, alive). Uses WaitForSingleObject for precise check."""
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, pid)
        if not h:
            err = k32.GetLastError()
            if err == 5:  # ACCESS_DENIED — process exists but no permission
                return False, True
            return True, False
        WAIT_TIMEOUT = 0x00000102
        ret = k32.WaitForSingleObject(h, 0)
        k32.CloseHandle(h)
        alive = ret == WAIT_TIMEOUT
        return True, alive
    except Exception:
        return False, True


def _is_alive(pid):
    _, alive = _check_alive(pid)
    return alive


# ============================================================
# Light ID management
# ============================================================
def _next_id():
    existing = set()
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        existing.add(os.path.splitext(os.path.basename(f))[0].replace("status-", ""))
    i = 1
    while f"CC-{i}" in existing:
        i += 1
    return f"CC-{i}"


# ============================================================
# Session / light lookup
# ============================================================
def _find_my_light():
    """
    Find the light ID for the current CC session.
    Priority: CLAUDE_LIGHTS_ID → CLAUDE_CODE_SESSION_ID → project marker → heartbeat scan
    """
    # 1. Manual override (set by PS profile)
    lid = os.environ.get("CLAUDE_LIGHTS_ID", "")
    if lid and os.path.exists(_pidf(lid)):
        try:
            with open(_pidf(lid)) as f:
                if _is_alive(int(f.read().strip())):
                    return lid
        except Exception:
            pass

    # 2. CC session ID binding
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid:
        ssf = _sessionf(sid)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if os.path.exists(ssf):
                try:
                    with open(ssf) as f:
                        lid = f.read().strip()
                    pidf = _pidf(lid)
                    if os.path.exists(pidf):
                        with open(pidf) as f:
                            pid = int(f.read().strip())
                        if _is_alive(pid):
                            return lid
                        if _acquire_lock(2.0):
                            try:
                                if os.path.exists(ssf):
                                    os.remove(ssf)
                                for p in [_pidf(lid), _sf(lid)]:
                                    if os.path.exists(p):
                                        try:
                                            os.remove(p)
                                        except Exception:
                                            pass
                            finally:
                                _release_lock()
                        break
                except Exception:
                    if time.time() > deadline - 0.5:
                        try:
                            os.remove(ssf)
                        except Exception:
                            pass
            time.sleep(0.15)
        return ""

    # 3. Project marker (fallback when SID is empty)
    pm = _project_marker()
    if os.path.exists(pm):
        try:
            with open(pm) as f:
                lid = f.read().strip()
            if os.path.exists(_pidf(lid)):
                with open(_pidf(lid)) as f:
                    if _is_alive(int(f.read().strip())):
                        return lid
        except Exception:
            pass
        try:
            os.remove(pm)
        except Exception:
            pass

    if os.path.isdir(os.path.join(os.getcwd(), '.claude')):
        return ""

    # 4. Heartbeat scan (fallback)
    for mp in glob.glob(os.path.join(BASE, ".map-*")):
        try:
            map_ppid = int(os.path.basename(mp).replace(".map-", ""))
        except Exception:
            continue
        if not _is_alive(map_ppid):
            try:
                os.remove(mp)
            except Exception:
                pass

    best_lid, best_hb = "", 0
    now = time.time()
    for pidf in glob.glob(os.path.join(BASE, ".pid-*")):
        try:
            with open(pidf) as f:
                server_pid = int(f.read().strip())
        except Exception:
            continue
        if _is_alive(server_pid):
            lid = os.path.basename(pidf).replace(".pid-", "")
            hb = _read_heartbeat(lid)
            if hb > 0 and hb > best_hb:
                best_lid, best_hb = lid, hb
    return best_lid


# ============================================================
# Sound
# ============================================================
def _ensure_sound():
    return os.path.exists(COMPLETE_SOUND)


def play_complete_sound(wait=True):
    """Play task completion sound via pygame.mixer."""
    if not _ensure_sound():
        return
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        sound = pygame.mixer.Sound(COMPLETE_SOUND)
        sound.play()
        if wait:
            time.sleep(sound.get_length() + 0.1)
    except Exception:
        pass


# ============================================================
# LightInfo — structured data for client consumption
# ============================================================
LightInfo = namedtuple('LightInfo', ['id', 'status', 'message', 'pid', 'alive', 'heartbeat'])


def list_lights():
    """
    Scan all lights and return structured LightInfo tuples.
    Cleans up dead light files automatically.
    """
    results = []
    seen_ids = set()

    for sf_path in glob.glob(os.path.join(BASE, "status-*.json")):
        name = os.path.basename(sf_path).replace("status-", "").replace(".json", "")
        seen_ids.add(name)
        pid = 0
        alive = False
        pidf_path = _pidf(name)
        if os.path.exists(pidf_path):
            try:
                with open(pidf_path) as f:
                    pid = int(f.read().strip())
                alive = _is_alive(pid)
            except Exception:
                pass

        status = "unknown"
        message = ""
        heartbeat = 0
        try:
            with open(sf_path, encoding="utf-8") as f:
                d = json.load(f)
                status = d.get("status", "unknown")
                message = d.get("message", "")
                heartbeat = d.get("heartbeat", 0)
        except Exception:
            pass

        # Clean up dead lights
        if not alive:
            for p in [sf_path, pidf_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

        results.append(LightInfo(name, status, message, pid, alive, heartbeat))

    # Also check for .pid files without corresponding status files
    for pidf_path in glob.glob(os.path.join(BASE, ".pid-*")):
        name = os.path.basename(pidf_path).replace(".pid-", "")
        if name in seen_ids:
            continue
        pid = 0
        alive = False
        try:
            with open(pidf_path) as f:
                pid = int(f.read().strip())
            alive = _is_alive(pid)
        except Exception:
            pass
        if not alive and os.path.exists(pidf_path):
            try:
                os.remove(pidf_path)
            except Exception:
                pass
        elif alive:
            results.append(LightInfo(name, "unknown", "", pid, True, 0))

    results.sort(key=lambda x: x.id)
    return results


def get_light_count():
    """Return (total, alive, working, error, idle) counts."""
    lights = list_lights()
    alive_lights = [l for l in lights if l.alive]
    return {
        "total": len(lights),
        "alive": len(alive_lights),
        "working": sum(1 for l in alive_lights if l.status == "working"),
        "error": sum(1 for l in alive_lights if l.status == "error"),
        "idle": sum(1 for l in alive_lights if l.status in ("idle", "success")),
    }


# ============================================================
# Light lifecycle operations (programmatic API)
# ============================================================
def start_light(lid=None):
    """
    Start a new light server process. Returns the light ID.
    This spawns a Python subprocess running main.py server --id <lid>.
    """
    lid = lid or _next_id()
    _write(lid, "idle", "Ready")
    main_py = os.path.join(BASE, "main.py")
    if not os.path.exists(main_py):
        # Fall back to __file__'s directory or use sys.executable directly on core
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    cmdline = [sys.executable, main_py, "server", "--id", lid]
    proc = subprocess.Popen(
        cmdline,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    with open(_pidf(lid), "w") as f:
        f.write(str(proc.pid))
    return lid


def stop_light(lid):
    """Stop a specific light and clean up its files."""
    _write(lid, "shutdown")
    waited = 0.0
    while waited < 4.0:
        time.sleep(0.3)
        waited += 0.3
        sf = _sf(lid)
        if not os.path.exists(sf):
            break
        if os.path.exists(_pidf(lid)):
            try:
                with open(_pidf(lid)) as f:
                    pid = int(f.read().strip())
                if not _is_alive(pid):
                    break
            except Exception:
                break
    for p in [_sf(lid), _pidf(lid)]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    # Clean up session bindings pointing to this light
    for sf in glob.glob(os.path.join(BASE, ".session-*")):
        try:
            with open(sf) as f:
                if f.read().strip() == lid:
                    os.remove(sf)
        except Exception:
            pass
    # Clean up project marker
    pm = os.path.join(os.getcwd(), '.claude', '.claude-lights-session')
    try:
        if os.path.exists(pm):
            with open(pm) as f:
                if f.read().strip() == lid:
                    os.remove(pm)
    except Exception:
        pass
    # Clean up legacy .map-* files
    for mf in glob.glob(os.path.join(BASE, ".map-*")):
        try:
            with open(mf) as f:
                if f.read().strip() == lid:
                    os.remove(mf)
        except Exception:
            pass


def set_light(lid, status, message=""):
    """Update a light's status."""
    _write(lid, status, message)
    if status == "success":
        play_complete_sound()


def broadcast(status, message=""):
    """Update all lights simultaneously."""
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        with open(f, "w", encoding="utf-8") as fh:
            json.dump({"status": status, "message": message, "heartbeat": time.time()}, fh, ensure_ascii=False)


def shutdown_all():
    """Send shutdown to all lights."""
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        name = os.path.basename(f).replace("status-", "").replace(".json", "")
        _write(name, "shutdown")


def restart_light(lid):
    """Restart a light: stop it, then start a new one with the same ID."""
    stop_light(lid)
    time.sleep(0.5)
    _write(lid, "idle", "Ready")
    main_py = os.path.join(BASE, "main.py")
    if not os.path.exists(main_py):
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    cmdline = [sys.executable, main_py, "server", "--id", lid]
    proc = subprocess.Popen(
        cmdline,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    with open(_pidf(lid), "w") as f:
        f.write(str(proc.pid))
    return lid


def _lazy_start(lid_hint, status, msg):
    """
    Lazy-create a light on first hook trigger.
    Uses file lock to prevent concurrent creation.
    """
    if not _acquire_lock(5.0):
        return ""

    try:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        ssf = _sessionf(sid) if sid else ""
        if ssf and os.path.exists(ssf):
            try:
                with open(ssf) as f:
                    existing = f.read().strip()
                pidf = _pidf(existing)
                if os.path.exists(pidf):
                    with open(pidf) as f:
                        if _is_alive(int(f.read().strip())):
                            return existing
                for p in [ssf, pidf, _sf(existing)]:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            except Exception:
                try:
                    os.remove(ssf)
                except Exception:
                    pass

        lid = lid_hint or _next_id()
        if sid:
            with open(ssf, "w") as f:
                f.write(lid)
        try:
            pm = _project_marker()
            os.makedirs(os.path.dirname(pm), exist_ok=True)
            with open(pm, "w") as f:
                f.write(lid)
        except Exception:
            pass
        _write(lid, status, msg)
        main_py = os.path.join(BASE, "main.py")
        if not os.path.exists(main_py):
            main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        cmdline = [sys.executable, main_py, "server", "--id", lid]
        proc = subprocess.Popen(
            cmdline,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        with open(_pidf(lid), "w") as f:
            f.write(str(proc.pid))
        return lid
    finally:
        _release_lock()


# ============================================================
# Hook entry point (called by CC hooks)
# ============================================================
def hook_entry(status, message=""):
    """
    CC hook entry point. All hook events go through here.
    - First hook → lazy-create light + write status
    - Subsequent hooks → find existing light + write status
    - SessionEnd with shutdown → light process exits
    """
    lid = _find_my_light()
    if not lid:
        lid = _lazy_start(None, status, message)
        if lid:
            return lid
    if lid:
        _write(lid, status, message)
    else:
        broadcast(status, message)
    if status == "success":
        play_complete_sound()
    return lid


# ============================================================
# Installation helpers
# ============================================================
def check_installation():
    """
    Check installation status. Returns dict with installation state.
    """
    result = {
        "installed": False,
        "files_ok": False,
        "profile_ok": False,
        "hooks_ok": False,
        "details": [],
    }

    # Check files
    main_py = os.path.join(BASE, "main.py")
    result["files_ok"] = os.path.exists(main_py)
    if result["files_ok"]:
        result["details"].append("✓ Core files installed")
    else:
        result["details"].append("✗ Core files not found")

    # Check PowerShell profile
    profile_path = os.path.expandvars(r"$env:USERPROFILE\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1")
    # Also check new PowerShell 7 profile location
    ps7_profile = os.path.expandvars(r"$env:USERPROFILE\Documents\PowerShell\Microsoft.PowerShell_profile.ps1")
    profile_found = False
    for pp in [profile_path, ps7_profile]:
        if os.path.exists(pp):
            try:
                with open(pp, encoding="utf-8") as f:
                    if "ClaudeLights auto-start" in f.read():
                        profile_found = True
                        break
            except Exception:
                pass
    result["profile_ok"] = profile_found
    if profile_found:
        result["details"].append("✓ PowerShell profile configured")
    else:
        result["details"].append("✗ PowerShell profile not configured")

    # Check CC hooks
    settings_path = os.path.expanduser("~/.claude/settings.json")
    hooks_found = False
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
            hooks = settings.get("hooks", {})
            for event in ["PreToolUse", "Stop", "SessionEnd"]:
                if event in hooks:
                    for group in hooks[event]:
                        for h in group.get("hooks", []):
                            if "claude-lights" in h.get("command", "").lower():
                                hooks_found = True
                                break
        except Exception:
            pass
    result["hooks_ok"] = hooks_found
    if hooks_found:
        result["details"].append("✓ CC hooks configured")
    else:
        result["details"].append("✗ CC hooks not configured")

    result["installed"] = result["files_ok"] and result["profile_ok"] and result["hooks_ok"]
    return result


def get_cc_settings_path():
    return os.path.expanduser("~/.claude/settings.json")


def get_ps_profile_paths():
    """Return list of possible PowerShell profile paths."""
    return [
        os.path.expandvars(r"$env:USERPROFILE\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"),
        os.path.expandvars(r"$env:USERPROFILE\Documents\PowerShell\Microsoft.PowerShell_profile.ps1"),
    ]


# ============================================================
# Config persistence
# ============================================================
DEFAULT_CONFIG = {
    "sound_file": "",
    "sound_volume": 70,
    "sound_enabled": True,
    "hooks": {
        "PreToolUse": {"status": "working", "message": "Working..."},
        "UserPromptSubmit": {"status": "working", "message": "Thinking..."},
        "Stop": {"status": "success", "message": "Done"},
        "StopFailure": {"status": "error", "message": "Failed"},
        "PermissionRequest": {"status": "error", "message": "Need Choice"},
        "SessionEnd": {"status": "shutdown", "message": "SessionEnd"},
    },
    "minimize_to_tray": True,
    "start_with_windows": False,
    "auto_start_lights": True,
    "auto_stop_lights": True,
    "show_notifications": True,
    "refresh_interval": 2,
}


def load_config():
    """Load client configuration from disk."""
    cp = _config_path()
    if os.path.exists(cp):
        try:
            with open(cp, encoding="utf-8") as f:
                saved = json.load(f)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(saved)
                return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save client configuration to disk."""
    os.makedirs(BASE, exist_ok=True)
    cp = _config_path()
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ============================================================
# CLI command functions (print-based, used by main.py)
# ============================================================
def cmd_start():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default=None)
    ns, _ = ap.parse_known_args(sys.argv[2:])
    lid = start_light(ns.id)
    pidf_path = _pidf(lid)
    pid = 0
    if os.path.exists(pidf_path):
        try:
            with open(pidf_path) as f:
                pid = int(f.read().strip())
        except Exception:
            pass
    print(f"  {lid} 已启动 (PID={pid})")


def cmd_stop():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    stop_light(ns.id)
    print(f"  {ns.id} 已停止")


def cmd_set():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("status")
    ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    set_light(ns.id, ns.status, ns.message)
    print(f"  {ns.id} -> {ns.status} {ns.message}")


def cmd_list():
    lights = list_lights()
    alive_lights = [l for l in lights if l.alive]
    dead_lights = [l for l in lights if not l.alive]
    for info in alive_lights:
        print(f"  {info.id:8s} | {info.status:8s} | {info.message}")
    for info in dead_lights:
        # Dead lights are auto-cleaned in list_lights()
        pass
    if not alive_lights:
        print("  (无运行中的信号灯)")


def cmd_broadcast():
    ap = argparse.ArgumentParser()
    ap.add_argument("status")
    ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    broadcast(ns.status, ns.message)


def cmd_hook():
    ap = argparse.ArgumentParser()
    ap.add_argument("status")
    ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    hook_entry(ns.status, ns.message)


def cmd_shutdown():
    shutdown_all()
    print("  已发送全部停止信号")
