"""ClaudeLights Client — double-click launcher (no console window)."""
import sys
import os

# Ensure the script directory is on sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from client import main
    main()
except Exception as e:
    import traceback
    # If we crash, write to a temp log and show a message box
    log_path = os.path.expanduser("~/.claude-lights/client-error.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        f.write(traceback.format_exc())
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "ClaudeLights Error",
                             f"Failed to start client:\n\n{e}\n\nDetails written to: {log_path}")
    except Exception:
        pass
