"""
ClaudeLights Management Client — GUI for installing, configuring, and managing signal lights.
Double-click to launch. Minimizes to system tray.
"""
import sys
import os
import time
import json
import glob
import subprocess
import ctypes

# Ensure the project root is on sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from core import (
    set_base, list_lights, get_light_count,
    start_light, stop_light, set_light, restart_light, shutdown_all,
    check_installation, load_config, save_config, DEFAULT_CONFIG,
    BASE as _CORE_BASE, play_complete_sound,
)


# ============================================================
# Constants & Styling
# ============================================================
INSTALL_DIR = os.path.expanduser("~/.claude-lights")
set_base(INSTALL_DIR)  # Client manages lights in ~/.claude-lights/

COLORS = {
    "bg": "#121216",
    "surface": "#1C1C24",
    "surface_light": "#22222A",
    "border": "#555562",
    "text": "#A8A8B8",
    "text_dim": "#6A6A7A",
    "yellow": "#FFDC00",
    "green": "#00FF30",
    "red": "#FF1010",
    "white": "#FFFFFF",
}

STATUS_COLORS = {
    "idle": COLORS["green"],
    "success": COLORS["green"],
    "working": COLORS["yellow"],
    "error": COLORS["red"],
    "shutdown": COLORS["text_dim"],
    "unknown": COLORS["text_dim"],
}

WIN_W, WIN_H = 720, 540


# ============================================================
# Glass-style helper
# ============================================================
def glass_surface_style(radius=12):
    """Return a Qt stylesheet string for a glass-effect card surface."""
    return f"""
        background: #1C1C24;
        border: 1px solid #555562;
        border-radius: {radius}px;
    """


def glass_button_style(base_color=COLORS["surface_light"]):
    return f"""
        QPushButton {{
            background: {base_color};
            border: 1px solid {COLORS["border"]};
            border-radius: 6px;
            color: {COLORS["text"]};
            padding: 6px 14px;
            font-family: "Segoe UI", "Microsoft YaHei UI";
            font-size: 12px;
        }}
        QPushButton:hover {{
            background: #2E2E38;
            border-color: {COLORS["yellow"]};
        }}
        QPushButton:pressed {{
            background: #18181E;
        }}
        QPushButton:disabled {{
            color: {COLORS["text_dim"]};
            background: #16161C;
        }}
    """


# ============================================================
# Custom Frameless Window (utility, not used directly — TitleBarWidget handles drag)
# ============================================================


# ============================================================
# Title Bar Widget
# ============================================================
class TitleBarWidget:
    """Custom dark title bar with drag support. Returns a QWidget."""
    def __init__(self, parent, title="ClaudeLights"):
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
        from PySide6.QtCore import Qt

        self._window = parent
        self.widget = QWidget()
        self.widget.setFixedHeight(36)
        self.widget.setStyleSheet("""
            QWidget#titleBar {
                background: #0E0E12;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
        """)
        self.widget.setObjectName("titleBar")

        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(14, 0, 6, 0)
        layout.setSpacing(0)

        # Icon + Title
        self.icon_label = QLabel("●")
        self.icon_label.setStyleSheet(f"color: {COLORS['green']}; font-size: 14px; background: transparent;")
        self.icon_label.setFixedWidth(22)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"""
            color: {COLORS['text']};
            font-family: "SF Pro Display", "Segoe UI", "Microsoft YaHei UI";
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 0.5px;
            background: transparent;
        """)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addStretch()

        # Minimize button
        self.min_btn = QPushButton("─")
        self.min_btn.setFixedSize(28, 28)
        self.min_btn.setStyleSheet(f"""
            QPushButton {{
                color: {COLORS['text']};
                background: transparent;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #2A2A32; }}
        """)
        self.min_btn.clicked.connect(parent.showMinimized)
        layout.addWidget(self.min_btn)

        # Close button
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {COLORS['text']};
                background: transparent;
                border: none;
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{ background: #CC3333; color: white; }}
        """)
        self.close_btn.clicked.connect(parent.close)
        layout.addWidget(self.close_btn)

        # Enable dragging from entire title bar area
        self._dragging = False
        self._drag_pos = None
        self.widget.mousePressEvent = self._on_press
        self.widget.mouseMoveEvent = self._on_move
        self.widget.mouseReleaseEvent = self._on_release

    def _on_press(self, event):
        from PySide6.QtCore import Qt
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint()

    def _on_move(self, event):
        if self._dragging and self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self._window.move(self._window.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()

    def _on_release(self, event):
        self._dragging = False
        self._drag_pos = None


# ============================================================
# Pages
# ============================================================
class WelcomePage:
    """First-run welcome and one-click install page."""
    def __init__(self, parent, on_install_complete):
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
            QFrame, QProgressDialog,
        )
        from PySide6.QtCore import Qt

        self.parent = parent
        self.on_install_complete = on_install_complete
        self.widget = QWidget()

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(18)

        # Centered content
        layout.addStretch()

        # Icon placeholder
        icon_label = QLabel("● ● ●")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"""
            font-size: 48px;
            letter-spacing: 12px;
            color: {COLORS['green']};
            background: transparent;
        """)
        layout.addWidget(icon_label)

        # Title
        title = QLabel("Welcome to ClaudeLights")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            color: {COLORS['text']};
            font-family: "SF Pro Display", "Segoe UI", "Microsoft YaHei UI";
            font-size: 22px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Desktop signal light for Claude Code — real-time AI status at a glance")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 13px; background: transparent;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # Feature list
        features_frame = QFrame()
        features_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
        """)
        features_layout = QVBoxLayout(features_frame)
        features_layout.setContentsMargins(20, 14, 20, 14)
        features_layout.setSpacing(8)

        for feature in [
            ("●", "Installs the signal light server"),
            ("●", "Configures PowerShell auto-start with claude"),
            ("●", "Sets up Claude Code lifecycle hooks"),
            ("●", "Includes task-complete sound alerts"),
            ("●", "Session isolation — one light per CC window"),
        ]:
            fl = QLabel(f"{feature[0]}  {feature[1]}")
            fl.setStyleSheet(f"""
                color: {COLORS['text_dim']};
                font-size: 12px;
                background: transparent;
            """)
            features_layout.addWidget(fl)

        layout.addWidget(features_frame)

        layout.addSpacing(10)

        # Install status
        install_info = check_installation()
        if install_info["installed"]:
            self.status_label = QLabel("✓ ClaudeLights is already installed")
            self.status_label.setStyleSheet(f"color: {COLORS['green']}; font-size: 12px; font-weight: bold;")
            self.status_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.status_label)

            go_btn = QPushButton("Go to Dashboard →")
            go_btn.setStyleSheet(glass_button_style() + f"""
                QPushButton {{ background: {COLORS['surface']}; padding: 12px 32px; font-size: 15px; font-weight: bold; }}
                QPushButton:hover {{ background: #2E2E38; color: {COLORS['green']}; }}
            """)
            go_btn.clicked.connect(self._go_dashboard)
            layout.addWidget(go_btn, alignment=Qt.AlignCenter)
        else:
            # Installation status details
            for detail in install_info["details"]:
                dl = QLabel(detail)
                color = COLORS["green"] if detail.startswith("✓") else COLORS["red"]
                dl.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")
                dl.setAlignment(Qt.AlignCenter)
                layout.addWidget(dl)

            layout.addSpacing(6)

            # One-click install button
            self.install_btn = QPushButton("⚡ 一键安装  One-Click Install")
            self.install_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #FFDC00, stop:0.3 #FFC800, stop:1 #E6A800);
                    color: #1A1A1A;
                    border: none;
                    border-radius: 10px;
                    padding: 14px 36px;
                    font-size: 16px;
                    font-weight: bold;
                    font-family: "SF Pro Display", "Segoe UI", "Microsoft YaHei UI";
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #FFE830, stop:0.3 #FFD420, stop:1 #F0B800);
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #E6A800, stop:0.3 #CC9600, stop:1 #B88600);
                }}
            """)
            self.install_btn.clicked.connect(self._do_install)
            layout.addWidget(self.install_btn, alignment=Qt.AlignCenter)

            # Advanced settings link
            adv_btn = QPushButton("Advanced Settings...")
            adv_btn.setStyleSheet(f"""
                QPushButton {{
                    color: {COLORS['text_dim']};
                    background: transparent;
                    border: none;
                    font-size: 11px;
                    text-decoration: underline;
                }}
                QPushButton:hover {{ color: {COLORS['text']}; }}
            """)
            adv_btn.clicked.connect(lambda: parent.nav.setCurrentIndex(2))
            layout.addWidget(adv_btn, alignment=Qt.AlignCenter)

        layout.addStretch()

    def _do_install(self):
        self.parent._run_install()

    def _go_dashboard(self):
        self.parent.nav.setCurrentIndex(1)


class DashboardPage:
    """Main dashboard showing all running lights."""
    def __init__(self, parent):
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
            QScrollArea, QFrame,
        )
        from PySide6.QtCore import Qt

        self.parent = parent
        self.widget = QWidget()
        self._light_cards = {}  # lid -> QFrame

        main_layout = QVBoxLayout(self.widget)
        main_layout.setContentsMargins(20, 10, 20, 14)
        main_layout.setSpacing(10)

        # Stats row
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(16, 10, 16, 10)
        stats_layout.setSpacing(20)

        self.stat_labels = {}
        for key, label in [("alive", "Lights Running"), ("working", "Working"), ("idle", "Idle"), ("error", "Errors")]:
            box = QVBoxLayout()
            num = QLabel("—")
            num.setStyleSheet(f"color: {COLORS['text']}; font-size: 22px; font-weight: bold; background: transparent;")
            num.setAlignment(Qt.AlignCenter)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;")
            lbl.setAlignment(Qt.AlignCenter)
            box.addWidget(num)
            box.addWidget(lbl)
            stats_layout.addLayout(box)
            self.stat_labels[key] = num

        main_layout.addWidget(stats_frame)

        # Section label
        section_row = QHBoxLayout()
        section_label = QLabel("Active Lights")
        section_label.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: 14px;
            font-weight: bold;
            background: transparent;
        """)
        section_row.addWidget(section_label)
        section_row.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet(glass_button_style())
        self.refresh_btn.clicked.connect(self._refresh)
        section_row.addWidget(self.refresh_btn)

        main_layout.addLayout(section_row)

        # Scrollable light cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {COLORS['bg']};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border']};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self.cards_container = QWidget()
        self.cards_container.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

        # Empty state
        self.empty_label = QLabel("No lights running yet.\nOpen a PowerShell window and type 'claude' to start.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            color: {COLORS['text_dim']};
            font-size: 13px;
            padding: 40px;
            background: transparent;
        """)
        self.empty_label.setWordWrap(True)
        self.cards_layout.insertWidget(0, self.empty_label)

        # Bottom action row
        action_row = QHBoxLayout()

        self.start_btn = QPushButton("+ Start New Light")
        self.start_btn.setStyleSheet(glass_button_style() + f"""
            QPushButton {{ color: {COLORS['green']}; font-weight: bold; padding: 8px 18px; }}
            QPushButton:hover {{ border-color: {COLORS['green']}; }}
        """)
        self.start_btn.clicked.connect(self._start_light)
        action_row.addWidget(self.start_btn)

        action_row.addStretch()

        self.stop_all_btn = QPushButton("Shutdown All")
        self.stop_all_btn.setStyleSheet(glass_button_style() + f"""
            QPushButton {{ color: {COLORS['red']}; padding: 8px 18px; }}
            QPushButton:hover {{ border-color: {COLORS['red']}; background: #2A1818; }}
        """)
        self.stop_all_btn.clicked.connect(self._shutdown_all)
        action_row.addWidget(self.stop_all_btn)

        main_layout.addLayout(action_row)

        # Status bar
        from PySide6.QtWidgets import QStatusBar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                color: {COLORS['text_dim']};
                font-size: 11px;
                background: transparent;
                border: none;
            }}
        """)
        self.status_bar.showMessage("Ready")
        main_layout.addWidget(self.status_bar)

        # Timers
        from PySide6.QtCore import QTimer
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._refresh)
        self._poll_timer.start(2000)

        self._uptime_timer = QTimer()
        self._uptime_timer.timeout.connect(self._update_uptimes)
        self._uptime_timer.start(1000)

        self._start_times = {}  # lid -> timestamp

    def _refresh(self):
        """Refresh the dashboard from disk."""
        lights = list_lights()
        alive_ids = set()

        for info in lights:
            alive_ids.add(info.id)
            if info.id not in self._start_times:
                self._start_times[info.id] = time.time()

            if info.id in self._light_cards:
                self._update_card(info)
            else:
                self._add_card(info)

        # Remove dead cards
        for lid in list(self._light_cards.keys()):
            if lid not in alive_ids:
                self._remove_card(lid)
                if lid in self._start_times:
                    del self._start_times[lid]

        # Show/hide empty state
        self.empty_label.setVisible(len(self._light_cards) == 0)

        # Update stats
        counts = get_light_count()
        self.stat_labels["alive"].setText(str(counts["alive"]))
        self.stat_labels["working"].setText(str(counts["working"]))
        self.stat_labels["idle"].setText(str(counts["idle"]))
        self.stat_labels["error"].setText(str(counts["error"]))

        # Color the error count
        if counts["error"] > 0:
            self.stat_labels["error"].setStyleSheet(f"color: {COLORS['red']}; font-size: 22px; font-weight: bold; background: transparent;")
        else:
            self.stat_labels["error"].setStyleSheet(f"color: {COLORS['text']}; font-size: 22px; font-weight: bold; background: transparent;")

        self.status_bar.showMessage(f"Last refresh: just now  ·  {counts['alive']} lights running")

    def _add_card(self, info):
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QMenu
        from PySide6.QtCore import Qt

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
            QFrame:hover {{
                background: {COLORS['surface_light']};
            }}
        """)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(10)

        # Status dot
        dot_color = STATUS_COLORS.get(info.status, COLORS["text_dim"])
        dot = QLabel("●")
        dot.setFixedWidth(16)
        dot.setStyleSheet(f"color: {dot_color}; font-size: 12px; background: transparent;")
        card_layout.addWidget(dot)

        # Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        id_label = QLabel(info.id)
        id_label.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: 13px;
            font-weight: bold;
            font-family: "Consolas", "Cascadia Code", monospace;
            background: transparent;
        """)
        info_layout.addWidget(id_label)

        detail_label = QLabel(f"{info.status.upper()}  ·  {info.message or '—'}  ·  PID {info.pid}")
        detail_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;")
        info_layout.addWidget(detail_label)

        card_layout.addLayout(info_layout, stretch=1)

        # Uptime
        uptime_label = QLabel("")
        uptime_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;")
        card_layout.addWidget(uptime_label)

        # Actions
        status_combo = QPushButton("Set Status ▾")
        status_combo.setStyleSheet(glass_button_style())
        status_menu = QMenu(status_combo)
        status_menu.setStyleSheet(f"""
            QMenu {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text']};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {COLORS['surface_light']};
            }}
        """)
        for s, label in [("idle", "Idle (Green)"), ("working", "Working (Yellow)"), ("success", "Success (Green Flash)"), ("error", "Error (Red)")]:
            action = status_menu.addAction(label)
            action.triggered.connect(lambda checked, lid=info.id, st=s: self._set_status(lid, st))
        status_combo.setMenu(status_menu)
        card_layout.addWidget(status_combo)

        restart_btn = QPushButton("Restart")
        restart_btn.setStyleSheet(glass_button_style())
        restart_btn.clicked.connect(lambda: self._restart_light(info.id))
        card_layout.addWidget(restart_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.setStyleSheet(glass_button_style() + f"""
            QPushButton {{ color: {COLORS['red']}; }}
            QPushButton:hover {{ border-color: {COLORS['red']}; background: #2A1818; }}
        """)
        stop_btn.clicked.connect(lambda: self._stop_light(info.id))
        card_layout.addWidget(stop_btn)

        # Store references
        card._info = {
            "dot": dot,
            "id_label": id_label,
            "detail_label": detail_label,
            "uptime_label": uptime_label,
            "status": info.status,
        }

        # Insert before the stretch
        n_items = self.cards_layout.count()
        self.cards_layout.insertWidget(n_items - 1, card)
        self._light_cards[info.id] = card

    def _update_card(self, info):
        card = self._light_cards.get(info.id)
        if not card:
            return
        ci = card._info
        dot_color = STATUS_COLORS.get(info.status, COLORS["text_dim"])
        ci["dot"].setStyleSheet(f"color: {dot_color}; font-size: 12px; background: transparent;")
        ci["detail_label"].setText(f"{info.status.upper()}  ·  {info.message or '—'}  ·  PID {info.pid}")
        ci["status"] = info.status

    def _remove_card(self, lid):
        card = self._light_cards.pop(lid, None)
        if card:
            self.cards_layout.removeWidget(card)
            card.deleteLater()

    def _update_uptimes(self):
        from PySide6.QtCore import Qt
        now = time.time()
        for lid, card in self._light_cards.items():
            start_t = self._start_times.get(lid, now)
            elapsed = int(now - start_t)
            mins, secs = divmod(elapsed, 60)
            if mins > 0:
                card._info["uptime_label"].setText(f"⏱ {mins}m{secs:02d}s")
            else:
                card._info["uptime_label"].setText(f"⏱ {secs}s")

    def _set_status(self, lid, status):
        set_light(lid, status, f"Manual: {status}")
        self._refresh()

    def _restart_light(self, lid):
        try:
            restart_light(lid)
            self._start_times[lid] = time.time()
        except Exception as e:
            self.status_bar.showMessage(f"Failed to restart {lid}: {e}")
        self._refresh()

    def _stop_light(self, lid):
        stop_light(lid)
        self._light_cards.pop(lid, None)
        if lid in self._start_times:
            del self._start_times[lid]
        self._refresh()

    def _start_light(self):
        lid = start_light()
        self._start_times[lid] = time.time()
        self._refresh()

    def _shutdown_all(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self.parent, "Confirm Shutdown",
            "Stop all running signal lights?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            shutdown_all()
            self._light_cards.clear()
            self._start_times.clear()
            self._refresh()


class SettingsPage:
    """Settings and configuration page."""
    def __init__(self, parent):
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
            QCheckBox, QSlider, QFrame, QFileDialog,
        )
        from PySide6.QtCore import Qt

        self.parent = parent
        self.widget = QWidget()
        self.config = load_config()

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(20, 10, 20, 14)
        layout.setSpacing(12)

        # === Sound Section ===
        layout.addWidget(self._section_label("Sound"))

        sound_frame = QFrame()
        sound_frame.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px;")
        sound_layout = QVBoxLayout(sound_frame)
        sound_layout.setContentsMargins(16, 12, 16, 12)
        sound_layout.setSpacing(8)

        # Sound file
        sf_row = QHBoxLayout()
        sf_row.addWidget(QLabel("Sound file:"))
        self.sound_path_label = QLabel(self.config.get("sound_file", "") or "(default)")
        self.sound_path_label.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent; padding: 2px 6px; border: 1px solid {COLORS['border']}; border-radius: 4px;")
        sf_row.addWidget(self.sound_path_label, stretch=1)
        browse_btn = QPushButton("Browse...")
        browse_btn.setStyleSheet(glass_button_style())
        browse_btn.clicked.connect(self._browse_sound)
        sf_row.addWidget(browse_btn)
        preview_btn = QPushButton("▶ Preview")
        preview_btn.setStyleSheet(glass_button_style())
        preview_btn.clicked.connect(self._preview_sound)
        sf_row.addWidget(preview_btn)
        sound_layout.addLayout(sf_row)

        # Volume
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config.get("sound_volume", 70))
        self.volume_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {COLORS['bg']};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['yellow']};
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
        """)
        vol_row.addWidget(self.volume_slider, stretch=1)
        self.volume_label = QLabel(f"{self.config.get('sound_volume', 70)}%")
        self.volume_label.setFixedWidth(36)
        self.volume_label.setStyleSheet(f"color: {COLORS['text']}; background: transparent;")
        self.volume_slider.valueChanged.connect(lambda v: self.volume_label.setText(f"{v}%"))
        vol_row.addWidget(self.volume_label)
        sound_layout.addLayout(vol_row)

        # Sound enabled
        self.sound_check = QCheckBox("Play sound on task complete")
        self.sound_check.setChecked(self.config.get("sound_enabled", True))
        sound_layout.addWidget(self.sound_check)

        layout.addWidget(sound_frame)

        # === Hooks Section ===
        layout.addWidget(self._section_label("Claude Code Hooks"))

        hooks_frame = QFrame()
        hooks_frame.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px;")
        hooks_layout = QVBoxLayout(hooks_frame)
        hooks_layout.setContentsMargins(16, 12, 16, 12)
        hooks_layout.setSpacing(6)

        hooks_config = self.config.get("hooks", DEFAULT_CONFIG["hooks"])
        self.hook_checkboxes = {}
        for event, entry in hooks_config.items():
            row = QHBoxLayout()
            cb = QCheckBox(f"{event} → {entry['status']} \"{entry['message']}\"")
            cb.setChecked(entry.get("enabled", True))
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {COLORS['text']};
                    font-size: 11px;
                    font-family: "Consolas", "Cascadia Code", monospace;
                    background: transparent;
                }}
                QCheckBox::indicator {{
                    width: 14px; height: 14px;
                    border: 1px solid {COLORS['border']};
                    border-radius: 3px;
                    background: {COLORS['bg']};
                }}
                QCheckBox::indicator:checked {{
                    background: {COLORS['green']};
                    border-color: {COLORS['green']};
                }}
            """)
            self.hook_checkboxes[event] = cb
            row.addWidget(cb)
            row.addStretch()
            hooks_layout.addLayout(row)

        layout.addWidget(hooks_frame)

        # === Profile Section ===
        layout.addWidget(self._section_label("PowerShell Profile"))

        profile_frame = QFrame()
        profile_frame.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px;")
        profile_layout = QVBoxLayout(profile_frame)
        profile_layout.setContentsMargins(16, 12, 16, 12)
        profile_layout.setSpacing(8)

        self.auto_start_check = QCheckBox("Auto-start lights with `claude` command")
        self.auto_start_check.setChecked(self.config.get("auto_start_lights", True))
        profile_layout.addWidget(self.auto_start_check)

        self.auto_stop_check = QCheckBox("Auto-stop lights when claude exits")
        self.auto_stop_check.setChecked(self.config.get("auto_stop_lights", True))
        profile_layout.addWidget(self.auto_stop_check)

        profile_action_row = QHBoxLayout()
        reinstall_btn = QPushButton("Reinstall Profile Function")
        reinstall_btn.setStyleSheet(glass_button_style())
        reinstall_btn.clicked.connect(self._reinstall_profile)
        profile_action_row.addWidget(reinstall_btn)
        profile_action_row.addStretch()
        profile_layout.addLayout(profile_action_row)

        layout.addWidget(profile_frame)

        # === General Section ===
        layout.addWidget(self._section_label("General"))

        general_frame = QFrame()
        general_frame.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px;")
        general_layout = QVBoxLayout(general_frame)
        general_layout.setContentsMargins(16, 12, 16, 12)
        general_layout.setSpacing(8)

        self.tray_check = QCheckBox("Start minimized to system tray")
        self.tray_check.setChecked(self.config.get("minimize_to_tray", True))
        general_layout.addWidget(self.tray_check)

        self.autostart_check = QCheckBox("Start with Windows (auto-run on boot)")
        self.autostart_check.setChecked(self.config.get("start_with_windows", False))
        general_layout.addWidget(self.autostart_check)

        self.notify_check = QCheckBox("Show notification on status change")
        self.notify_check.setChecked(self.config.get("show_notifications", True))
        general_layout.addWidget(self.notify_check)

        layout.addWidget(general_frame)

        # Uninstall link
        layout.addSpacing(6)
        uninstall_btn = QPushButton("Uninstall ClaudeLights...")
        uninstall_btn.setStyleSheet(f"""
            QPushButton {{
                color: {COLORS['red']};
                background: transparent;
                border: 1px solid {COLORS['red']};
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: #2A1818;
            }}
        """)
        uninstall_btn.clicked.connect(lambda: self.parent.nav.setCurrentIndex(3))
        layout.addWidget(uninstall_btn, alignment=Qt.AlignCenter)

        # Save button
        layout.addStretch()
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet(glass_button_style() + f"""
            QPushButton {{ background: {COLORS['yellow']}; color: #1A1A1A; font-weight: bold; padding: 10px 28px; font-size: 13px; }}
            QPushButton:hover {{ background: #FFE830; }}
        """)
        save_btn.clicked.connect(self._save_settings)
        save_row.addWidget(save_btn)
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setStyleSheet(glass_button_style())
        reset_btn.clicked.connect(self._reset_defaults)
        save_row.addWidget(reset_btn)
        save_row.addStretch()
        layout.addLayout(save_row)

    def _section_label(self, text):
        from PySide6.QtWidgets import QLabel
        label = QLabel(text)
        label.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: 13px;
            font-weight: bold;
            background: transparent;
            padding-top: 4px;
        """)
        return label

    def _browse_sound(self):
        from PySide6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(
            self.parent, "Select Sound File",
            os.path.expanduser("~"),
            "Audio Files (*.mp3 *.wav);;All Files (*.*)",
        )
        if f:
            self.sound_path_label.setText(f)
            self.config["sound_file"] = f

    def _preview_sound(self):
        sf = self.sound_path_label.text()
        if sf and sf != "(default)" and os.path.exists(sf):
            import core as c
            old_sound = c.COMPLETE_SOUND
            c.COMPLETE_SOUND = sf
            try:
                c.play_complete_sound(wait=False)
            except Exception:
                pass
            c.COMPLETE_SOUND = old_sound
        else:
            play_complete_sound(wait=False)

    def _reinstall_profile(self):
        self.parent._install_profile()
        self.parent.status_bar.showMessage("PowerShell profile reinstalled")

    def _save_settings(self):
        self.config["sound_volume"] = self.volume_slider.value()
        self.config["sound_enabled"] = self.sound_check.isChecked()
        for event, cb in self.hook_checkboxes.items():
            if event in self.config.get("hooks", {}):
                self.config["hooks"][event]["enabled"] = cb.isChecked()
        self.config["auto_start_lights"] = self.auto_start_check.isChecked()
        self.config["auto_stop_lights"] = self.auto_stop_check.isChecked()
        self.config["minimize_to_tray"] = self.tray_check.isChecked()
        self.config["start_with_windows"] = self.autostart_check.isChecked()
        self.config["show_notifications"] = self.notify_check.isChecked()
        save_config(self.config)
        self.parent._apply_hooks_config()
        self.parent._apply_autostart()
        self.parent.status_bar.showMessage("Settings saved")

    def _reset_defaults(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self.parent, "Reset Settings",
            "Reset all settings to defaults?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.config = DEFAULT_CONFIG.copy()
            self.volume_slider.setValue(70)
            self.volume_label.setText("70%")
            self.sound_check.setChecked(True)
            self.sound_path_label.setText("(default)")
            self.auto_start_check.setChecked(True)
            self.auto_stop_check.setChecked(True)
            self.tray_check.setChecked(True)
            self.autostart_check.setChecked(False)
            self.notify_check.setChecked(True)
            for cb in self.hook_checkboxes.values():
                cb.setChecked(True)
            save_config(self.config)


class UninstallPage:
    """Uninstall confirmation and cleanup."""
    def __init__(self, parent):
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QLineEdit
        from PySide6.QtCore import Qt

        self.parent = parent
        self.widget = QWidget()

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        layout.addStretch()

        # Warning icon
        warn_label = QLabel("⚠")
        warn_label.setAlignment(Qt.AlignCenter)
        warn_label.setStyleSheet(f"color: {COLORS['red']}; font-size: 56px; background: transparent;")
        layout.addWidget(warn_label)

        # Title
        title = QLabel("Uninstall ClaudeLights")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: 20px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(title)

        # What will be removed
        remove_frame = QFrame()
        remove_frame.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px;")
        remove_layout = QVBoxLayout(remove_frame)
        remove_layout.setContentsMargins(20, 14, 20, 14)
        remove_layout.setSpacing(6)

        items = [
            "All light server files from ~/.claude-lights/",
            "PowerShell profile function (claude wrapper)",
            "Claude Code hook configurations",
            "Session bindings and PID files",
        ]
        for item in items:
            il = QLabel(f"☑  {item}")
            il.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent;")
            remove_layout.addWidget(il)

        layout.addWidget(remove_frame)

        # Warning
        warn = QLabel("⚠ Any running lights will be stopped. This action cannot be undone.")
        warn.setAlignment(Qt.AlignCenter)
        warn.setStyleSheet(f"color: {COLORS['red']}; font-size: 12px; background: transparent;")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        # Type to confirm
        confirm_label = QLabel('Type "DELETE" to confirm:')
        confirm_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px; background: transparent;")
        layout.addWidget(confirm_label)

        self.confirm_input = QLineEdit()
        self.confirm_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text']};
                padding: 8px 12px;
                font-size: 14px;
                font-family: "Consolas", "Cascadia Code", monospace;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['red']};
            }}
        """)
        layout.addWidget(self.confirm_input)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(glass_button_style() + "padding: 10px 24px;")
        cancel_btn.clicked.connect(lambda: self.parent.nav.setCurrentIndex(1))
        btn_row.addWidget(cancel_btn)

        self.uninstall_btn = QPushButton("Uninstall ClaudeLights")
        self.uninstall_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['red']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #DD2222; }}
            QPushButton:disabled {{
                background: #442222;
                color: #886666;
            }}
        """)
        self.uninstall_btn.setEnabled(False)
        self.uninstall_btn.clicked.connect(self._do_uninstall)
        self.confirm_input.textChanged.connect(lambda t: self.uninstall_btn.setEnabled(t == "DELETE"))
        btn_row.addWidget(self.uninstall_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

    def _do_uninstall(self):
        from PySide6.QtWidgets import QMessageBox

        # 1. Stop all lights
        shutdown_all()
        time.sleep(1.0)

        # 2. Remove hooks from CC settings
        try:
            import core
            settings_path = core.get_cc_settings_path()
            if os.path.exists(settings_path):
                with open(settings_path, encoding="utf-8") as f:
                    settings = json.load(f)
                hooks = settings.get("hooks", {})
                for event in list(hooks.keys()):
                    new_groups = []
                    for group in hooks[event]:
                        new_hooks = [h for h in group.get("hooks", [])
                                     if "claude-lights" not in h.get("command", "").lower()]
                        if new_hooks:
                            group["hooks"] = new_hooks
                            new_groups.append(group)
                    if new_groups:
                        hooks[event] = new_groups
                    else:
                        del hooks[event]
                settings["hooks"] = hooks
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self.parent, "Warning", f"Could not clean up CC hooks: {e}")

        # 3. Remove PowerShell profile function
        try:
            import core
            for pp in core.get_ps_profile_paths():
                if os.path.exists(pp):
                    with open(pp, encoding="utf-8") as f:
                        content = f.read()
                    if "ClaudeLights auto-start" in content:
                        import re
                        new_content = re.sub(
                            r'\n?# ClaudeLights auto-start.*?(?=\n# ClaudeLights|\n# |\Z)',
                            '',
                            content,
                            flags=re.DOTALL,
                        )
                        # Also remove the standalone marker if regex didn't catch it
                        new_content = re.sub(
                            r'\n?# ClaudeLights auto-start.*',
                            '',
                            new_content,
                        )
                        with open(pp, "w", encoding="utf-8") as f:
                            f.write(new_content)
        except Exception as e:
            QMessageBox.warning(self.parent, "Warning", f"Could not clean up PowerShell profile: {e}")

        # 4. Remove files
        import shutil
        try:
            if os.path.exists(INSTALL_DIR):
                shutil.rmtree(INSTALL_DIR)
        except Exception:
            # Fallback: remove file by file
            for f in glob.glob(os.path.join(INSTALL_DIR, "*")):
                try:
                    os.remove(f)
                except Exception:
                    pass
            try:
                os.rmdir(INSTALL_DIR)
            except Exception:
                pass

        # 5. Remove Windows auto-start
        try:
            startup_lnk = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ClaudeLights.lnk")
            if os.path.exists(startup_lnk):
                os.remove(startup_lnk)
        except Exception:
            pass

        QMessageBox.information(
            self.parent, "Uninstalled",
            "ClaudeLights has been removed.\n\n"
            "You can reinstall at any time by running the client again."
        )

        # Reset to Welcome page
        self.parent._post_install_check()


# ============================================================
# Main Window
# ============================================================
class MainWindow:
    def __init__(self):
        from PySide6.QtWidgets import (
            QApplication, QMainWindow, QVBoxLayout, QWidget,
            QStackedWidget, QSystemTrayIcon, QMenu, QMessageBox, QStatusBar,
        )
        from PySide6.QtGui import QIcon, QAction
        from PySide6.QtCore import Qt

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.window = QMainWindow()
        self.window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.window.setAttribute(Qt.WA_TranslucentBackground, True)
        self.window.setStyleSheet(f"""
            QMainWindow {{
                background: {COLORS['bg']}E8;
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
            QLabel {{ color: {COLORS['text']}; font-family: "SF Pro Display", "Segoe UI", "Microsoft YaHei UI"; font-size: 12px; }}
        """)
        self.window.resize(WIN_W, WIN_H)
        self.window.setMinimumSize(580, 400)

        # Center on screen
        screen = self.app.primaryScreen().geometry()
        self.window.move(
            (screen.width() - WIN_W) // 2,
            (screen.height() - WIN_H) // 2,
        )

        # Central widget
        central = QWidget()
        central.setStyleSheet("background: transparent;")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        self.title_bar = TitleBarWidget(self.window)
        main_layout.addWidget(self.title_bar.widget)

        # Navigation stack
        self.nav = QStackedWidget()
        self.nav.setStyleSheet("background: transparent;")

        # Create pages
        self.welcome_page = WelcomePage(self, self._post_install_check)
        self.dashboard_page = DashboardPage(self)
        self.settings_page = SettingsPage(self)
        self.uninstall_page = UninstallPage(self)

        self.nav.addWidget(self.welcome_page.widget)   # index 0
        self.nav.addWidget(self.dashboard_page.widget)  # index 1
        self.nav.addWidget(self.settings_page.widget)   # index 2
        self.nav.addWidget(self.uninstall_page.widget)   # index 3

        main_layout.addWidget(self.nav, stretch=1)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                color: {COLORS['text_dim']};
                font-size: 11px;
                background: #0E0E12;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
                border-top: 1px solid {COLORS['border']};
                padding: 2px 12px;
            }}
        """)
        self.status_bar.showMessage("Ready")
        main_layout.addWidget(self.status_bar)

        self.window.setCentralWidget(central)

        # System tray
        self._setup_tray()

        # Show correct page
        self._post_install_check()

        # Apply autostart setting
        self._apply_autostart()

        self.window.show()

    def _setup_tray(self):
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu
        from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction

        # Create a simple icon programmatically
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(COLORS["green"]))
        painter.setPen(QColor(0, 0, 0, 0))
        painter.drawEllipse(4, 4, 24, 24)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawEllipse(8, 6, 8, 5)
        painter.end()

        icon = QIcon(pixmap)
        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip("ClaudeLights")

        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                color: {COLORS['text']};
                padding: 4px;
                font-family: "Segoe UI", "Microsoft YaHei UI";
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {COLORS['surface_light']};
            }}
        """)

        open_action = menu.addAction("Open Dashboard")
        open_action.triggered.connect(self._show_window)

        menu.addSeparator()

        self.tray_lights_menu = menu.addMenu("Lights")
        self.tray_lights_menu.setTitle("Lights")

        start_action = menu.addAction("Start New Light")
        start_action.triggered.connect(lambda: start_light())

        stop_all_action = menu.addAction("Shutdown All")
        stop_all_action.triggered.connect(lambda: shutdown_all())

        menu.addSeparator()

        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(lambda: self._show_window(2))

        menu.addSeparator()

        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self._quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)

        # Build initial light submenu
        self._update_tray_lights()
        tray_timer = self.app
        from PySide6.QtCore import QTimer
        self._tray_timer = QTimer()
        self._tray_timer.timeout.connect(self._update_tray_lights)
        self._tray_timer.start(3000)

        self.tray.show()

    def _update_tray_lights(self):
        lights = list_lights()
        alive = [l for l in lights if l.alive]
        self.tray_lights_menu.clear()
        if alive:
            for info in alive:
                dot = "●" if info.status != "error" else "○"
                action = self.tray_lights_menu.addAction(f"{dot} {info.id} — {info.status}")
        else:
            no_lights = self.tray_lights_menu.addAction("(no lights)")
            no_lights.setEnabled(False)

        # Update tray icon color
        from PySide6.QtGui import QPixmap, QPainter, QColor
        if any(l.status == "error" for l in alive):
            color = COLORS["red"]
        elif any(l.status == "working" for l in alive):
            color = COLORS["yellow"]
        elif alive:
            color = COLORS["green"]
        else:
            color = COLORS["text_dim"]

        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(QColor(0, 0, 0, 0))
        painter.drawEllipse(4, 4, 24, 24)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawEllipse(8, 6, 8, 5)
        painter.end()
        self.tray.setIcon(QIcon(pixmap))

    def _tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _show_window(self, page_idx=None):
        if page_idx is not None:
            self.nav.setCurrentIndex(page_idx)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _quit(self):
        config = load_config()
        if config.get("confirm_exit", True):
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self.window, "Exit ClaudeLights",
                "Close the management client?\n(Running lights will continue.)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.tray.hide()
        self.app.quit()

    # ================================================================
    # Installation logic (Python-native, mirrors install.ps1)
    # ================================================================
    def _run_install(self):
        from PySide6.QtWidgets import QProgressDialog, QMessageBox, QApplication
        from PySide6.QtCore import Qt, QTimer

        progress = QProgressDialog("Installing ClaudeLights...", None, 0, 6, self.window)
        progress.setWindowTitle("Installing")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setStyleSheet(f"""
            QProgressDialog {{
                background: {COLORS['surface']};
                color: {COLORS['text']};
                font-family: "Segoe UI", "Microsoft YaHei UI";
                font-size: 12px;
            }}
            QProgressBar {{
                background: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                text-align: center;
                height: 18px;
            }}
            QProgressBar::chunk {{
                background: {COLORS['yellow']};
                border-radius: 3px;
            }}
        """)
        progress.show()
        QApplication.processEvents()

        def update_step(step, msg):
            progress.setLabelText(f"[{step}/6] {msg}")
            progress.setValue(step)
            QApplication.processEvents()

        errors = []

        # Step 1: Create install directory
        update_step(1, "Creating install directory...")
        try:
            os.makedirs(INSTALL_DIR, exist_ok=True)
        except Exception as e:
            errors.append(f"Create directory: {e}")

        # Step 2: Copy files
        update_step(2, "Copying core files...")
        try:
            src_dir = _SCRIPT_DIR
            for fname in ["core.py", "light_server.py", "main.py"]:
                src = os.path.join(src_dir, fname)
                if os.path.exists(src):
                    with open(src, encoding="utf-8") as f:
                        content = f.read()
                    with open(os.path.join(INSTALL_DIR, fname), "w", encoding="utf-8") as f:
                        f.write(content)
            # Copy sounds
            sounds_src = os.path.join(src_dir, "sounds")
            sounds_dst = os.path.join(INSTALL_DIR, "sounds")
            os.makedirs(sounds_dst, exist_ok=True)
            if os.path.isdir(sounds_src):
                for fname in os.listdir(sounds_src):
                    src = os.path.join(sounds_src, fname)
                    dst = os.path.join(sounds_dst, fname)
                    if os.path.isfile(src):
                        with open(src, "rb") as sf:
                            with open(dst, "wb") as df:
                                df.write(sf.read())
        except Exception as e:
            errors.append(f"Copy files: {e}")

        # Step 3: Install Python dependencies
        update_step(3, "Installing Python dependencies (PySide6, pygame)...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "PySide6", "pygame", "-q"],
                capture_output=True, timeout=120,
            )
        except Exception as e:
            errors.append(f"pip install: {e}")

        # Step 4: Configure PowerShell profile
        update_step(4, "Configuring PowerShell profile...")
        errors.extend(self._install_profile())

        # Step 5: Configure CC hooks
        update_step(5, "Configuring Claude Code hooks...")
        errors.extend(self._install_hooks())

        # Step 6: Verify
        update_step(6, "Verifying installation...")
        try:
            # Test that we can import the installed modules
            sys.path.insert(0, INSTALL_DIR)
            import importlib
            try:
                importlib.import_module("core")
            except Exception:
                errors.append("Module import test failed")
        except Exception as e:
            errors.append(f"Verification: {e}")

        progress.close()

        if errors:
            QMessageBox.warning(
                self.window, "Installation Issues",
                "Some issues occurred during installation:\n\n" + "\n".join(errors) +
                "\n\nClaudeLights may still work. Check Settings for manual configuration."
            )
        else:
            QMessageBox.information(
                self.window, "Installation Complete",
                "ClaudeLights is now installed!\n\n"
                "• Open a new PowerShell window\n"
                "• Type 'claude' to start Claude Code\n"
                "• The signal light will appear automatically\n\n"
                "You can manage lights from this dashboard."
            )

        self._post_install_check()

    def _install_profile(self):
        """Install the claude wrapper function into PowerShell profile. Returns list of errors."""
        errors = []
        install_dir = INSTALL_DIR
        bin_cmd = f'python "{install_dir}\\main.py"'

        func = f"""
# ClaudeLights auto-start — cmd /c 绕开 function 覆盖, 避免递归
function claude {{
    $LIGHTS_DIR = "{install_dir}"
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

        import core as c
        for pp in c.get_ps_profile_paths():
            try:
                os.makedirs(os.path.dirname(pp), exist_ok=True)
                existing = ""
                if os.path.exists(pp):
                    with open(pp, encoding="utf-8") as f:
                        existing = f.read()

                if "ClaudeLights auto-start" in existing:
                    import re
                    new_content = re.sub(
                        r'# ClaudeLights auto-start.*?(?=\n# ClaudeLights|\n# [A-Z]|\Z)',
                        func.strip(),
                        existing,
                        flags=re.DOTALL,
                    )
                else:
                    new_content = existing.rstrip() + "\n" + func

                with open(pp, "w", encoding="utf-8") as f:
                    f.write(new_content)
            except Exception as e:
                errors.append(f"PowerShell profile ({pp}): {e}")

        return errors

    def _install_hooks(self):
        """Configure Claude Code hooks. Returns list of errors."""
        errors = []
        settings_path = os.path.expanduser("~/.claude/settings.json")
        install_dir = INSTALL_DIR
        bin_cmd = f'python "{install_dir}\\main.py"'

        hook_defs = {
            "PreToolUse": {"status": "working", "message": "Working..."},
            "UserPromptSubmit": {"status": "working", "message": "Thinking..."},
            "Stop": {"status": "success", "message": "Done"},
            "StopFailure": {"status": "error", "message": "Failed"},
            "PermissionRequest": {"status": "error", "message": "Need Choice"},
            "SessionEnd": {"status": "shutdown", "message": "SessionEnd"},
        }

        try:
            settings = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, encoding="utf-8") as f:
                        settings = json.load(f) or {}
                except Exception:
                    settings = {}

            if "hooks" not in settings:
                settings["hooks"] = {}

            for event, entry in hook_defs.items():
                cmd = f'{bin_cmd} hook {entry["status"]} "{entry["message"]}"'

                if event not in settings["hooks"]:
                    settings["hooks"][event] = []

                found = False
                for group in settings["hooks"][event]:
                    for h in group.get("hooks", []):
                        if "claude-lights" in h.get("command", "").lower():
                            h["command"] = cmd
                            found = True

                if not found:
                    if len(settings["hooks"][event]) == 0:
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
        except Exception as e:
            errors.append(f"CC hooks: {e}")

        return errors

    def _apply_hooks_config(self):
        """Apply hooks configuration from saved config to settings.json.
        Disabled hooks are removed; enabled hooks are added/updated."""
        config = load_config()
        hooks_config = config.get("hooks", {})
        settings_path = os.path.expanduser("~/.claude/settings.json")
        install_dir = INSTALL_DIR
        bin_cmd = f'python "{install_dir}\\main.py"'

        try:
            settings = {}
            if os.path.exists(settings_path):
                with open(settings_path, encoding="utf-8") as f:
                    settings = json.load(f) or {}

            if "hooks" not in settings:
                settings["hooks"] = {}

            for event, entry in hooks_config.items():
                enabled = entry.get("enabled", True)

                # Remove existing claude-lights hooks for this event
                if event in settings["hooks"]:
                    for group in settings["hooks"][event]:
                        group["hooks"] = [
                            h for h in group.get("hooks", [])
                            if "claude-lights" not in h.get("command", "").lower()
                        ]
                    # Remove empty groups
                    settings["hooks"][event] = [
                        g for g in settings["hooks"][event]
                        if len(g.get("hooks", [])) > 0
                    ]

                # Add hook if enabled
                if enabled:
                    cmd = f'{bin_cmd} hook {entry["status"]} "{entry["message"]}"'
                    if event not in settings["hooks"] or len(settings["hooks"][event]) == 0:
                        settings["hooks"][event] = [{"matcher": "", "hooks": []}]
                    settings["hooks"][event][0]["hooks"].append({
                        "type": "command",
                        "command": cmd,
                        "timeout": 3,
                        "async": True,
                        "asyncRewake": False,
                    })

                # Remove empty event entries
                if event in settings["hooks"] and len(settings["hooks"][event]) == 0:
                    del settings["hooks"][event]

            # Clean up empty top-level hooks
            if not settings["hooks"]:
                del settings["hooks"]

            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _apply_autostart(self):
        """Create or remove Windows startup shortcut."""
        config = load_config()
        startup_dir = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
        shortcut_path = os.path.join(startup_dir, "ClaudeLights.lnk")

        if config.get("start_with_windows", False):
            try:
                os.makedirs(startup_dir, exist_ok=True)
                # Use PowerShell to create the shortcut (WSH doesn't exist on all systems)
                client_py = os.path.join(_SCRIPT_DIR, "client.pyw")
                if not os.path.exists(client_py):
                    client_py = os.path.join(_SCRIPT_DIR, "client.py")
                ps_cmd = (
                    f'$WshShell = New-Object -ComObject WScript.Shell; '
                    f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}"); '
                    f'$Shortcut.TargetPath = "{sys.executable}"; '
                    f'$Shortcut.Arguments = "{client_py}"; '
                    f'$Shortcut.WorkingDirectory = "{_SCRIPT_DIR}"; '
                    f'$Shortcut.Save()'
                )
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass
        else:
            if os.path.exists(shortcut_path):
                try:
                    os.remove(shortcut_path)
                except Exception:
                    pass

    def _post_install_check(self):
        """Check if installed and show the appropriate page."""
        info = check_installation()
        if info["installed"]:
            self.nav.setCurrentIndex(1)  # Dashboard
            self.dashboard_page._refresh()
        else:
            self.nav.setCurrentIndex(0)  # Welcome


# ============================================================
# Entry point
# ============================================================
def main():
    # Single instance check
    import core as c
    if not c._acquire_lock(timeout=0.5):
        # Another instance is already running — bring it forward
        from PySide6.QtWidgets import QMessageBox, QApplication
        temp_app = QApplication(sys.argv)
        QMessageBox.information(None, "ClaudeLights", "ClaudeLights client is already running.\nCheck your system tray.")
        return
    c._release_lock()

    # Use a persistent lock file for single instance
    instance_lock = os.path.join(INSTALL_DIR, ".client-lock")
    try:
        fd = os.open(instance_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        from PySide6.QtWidgets import QMessageBox, QApplication
        temp_app = QApplication(sys.argv)
        QMessageBox.information(None, "ClaudeLights", "ClaudeLights client is already running.\nCheck your system tray.")
        return

    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = MainWindow()
        sys.exit(app.exec())
    finally:
        if os.path.exists(instance_lock):
            try:
                os.remove(instance_lock)
            except Exception:
                pass


if __name__ == "__main__":
    main()
