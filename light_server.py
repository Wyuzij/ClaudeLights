"""
ClaudeLights Light Server — PySide6 3D glass-effect signal light widget.
Extracted from main.py for modularity.
"""
import json
import os
import sys
import time
import math
import glob
import ctypes
import argparse

from core import (
    BASE, SOUNDS_DIR, COMPLETE_SOUND,
    _sf, _pidf, _write, play_complete_sound as _core_play_sound,
)


# Re-import the full play function (uses pygame)
def _play_complete_sound(wait=True):
    """Play task completion sound via pygame.mixer."""
    if not os.path.exists(COMPLETE_SOUND):
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


def server_main():
    from PySide6.QtCore import Qt, QTimer, QPointF
    from PySide6.QtGui import (
        QPainter, QColor, QPen, QFont, QPainterPath,
        QRadialGradient, QLinearGradient,
    )
    from PySide6.QtWidgets import QApplication, QWidget

    WW, WH = 54, 152
    POLL_MS = 350
    WINDOW_OPACITY = 0.92
    HEARTBEAT_TIMEOUT = 300  # 5min — 长思考时无 hook 事件，兜底清理
    SOCKET = QColor(0x10, 0x10, 0x16)
    OFF = [QColor(0x08, 0x08, 0x0A), QColor(0x08, 0x08, 0x0A), QColor(0x08, 0x08, 0x0A)]
    ON = [QColor(0xFF, 0x10, 0x10), QColor(0xFF, 0xDC, 0x00), QColor(0x00, 0xFF, 0x30)]
    LIGHT_Y = [47, 83, 119]
    LIGHT_R = 13.5
    PULSE = {
        "idle": (0.010, 0.08, 0.30),
        "working": (0.055, 0.34, 0.44),
        "success": (0.08, 0.50, 0.56),
        "error": (0.10, 0.48, 0.48),
    }

    ap = argparse.ArgumentParser()
    ap.add_argument("server", nargs="?")
    ap.add_argument("--id", required=True)
    ns = ap.parse_args()
    lid = ns.id

    sf = _sf(lid)
    if not os.path.exists(sf):
        _write(lid, "idle", "Ready")

    class SignalWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.lid = lid
            self.sf = sf
            self.status = "idle"
            self.age = 0.0
            self.phase = 0.0
            self.cur = [OFF[i] for i in range(3)]
            self.tgt = [OFF[i] for i in range(3)]
            p = PULSE["idle"]
            self.spd, self.amp, self.base = p
            self._tspd, self._tamp, self._tbase = p

            self.setWindowTitle(f"CL-{lid}")
            self.setFixedSize(WW, WH)
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setStyleSheet("background: transparent;")
            self.setWindowOpacity(WINDOW_OPACITY)
            if sys.platform == "win32":
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_LAYERED = 0x00080000
                user32 = ctypes.windll.user32
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT | WS_EX_LAYERED)

            try:
                n = int(lid.split("-")[-1])
            except Exception:
                n = 1
            col, row = (n - 1) // 8, (n - 1) % 8
            self.move(16 + col * 70, 16 + row * 168)

            self._t0 = time.time()
            self._anim = QTimer(self)
            self._anim.timeout.connect(self._tick)
            self._anim.start(30)
            self._poll = QTimer(self)
            self._poll.timeout.connect(self._read)
            self._poll.start(POLL_MS)

        def _tick(self):
            now = time.time()
            dt = min(now - self._t0, 0.1)
            self._t0 = now
            self.age += dt
            self.spd += (self._tspd - self.spd) * 0.08
            self.amp += (self._tamp - self.amp) * 0.08
            self.base += (self._tbase - self.base) * 0.08
            self._targets()
            for i in range(3):
                c, t = self.cur[i], self.tgt[i]
                self.cur[i] = QColor(
                    int(c.red() + (t.red() - c.red()) * 0.10),
                    int(c.green() + (t.green() - c.green()) * 0.10),
                    int(c.blue() + (t.blue() - c.blue()) * 0.10),
                )
            self.update()

        def _targets(self):
            self.tgt = [QColor(c) for c in OFF]
            s, a = self.status, self.age
            if s in ("idle", "success"):
                if s == "success" and a < 0.1:
                    self.tgt[2] = QColor(255, 255, 255)
                elif s == "success" and a < 0.7:
                    self.tgt[2] = self._mx((255, 255, 255), ON[2], (a - 0.1) / 0.6)
                else:
                    self.tgt[2] = QColor(ON[2])
            elif s == "working":
                self.tgt[1] = QColor(ON[1])
            elif s == "error":
                if a < 0.08:
                    self.tgt[0] = QColor(255, 255, 255)
                elif a < 0.5:
                    self.tgt[0] = self._mx((255, 255, 255), ON[0], (a - 0.08) / 0.42)
                else:
                    self.tgt[0] = QColor(ON[0])

        def _mx(self, a, b, t):
            return QColor(
                int(a[0] + (b.red() - a[0]) * t),
                int(a[1] + (b.green() - a[1]) * t),
                int(a[2] + (b.blue() - a[2]) * t),
            )

        def _glow(self):
            self.phase += self.spd
            return max(0.0, min(1.0, self.base + math.sin(self.phase) * self.amp))

        def _cleanup(self):
            for p in [self.sf, _pidf(self.lid)]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            for sf_path in glob.glob(os.path.join(BASE, ".session-*")):
                try:
                    with open(sf_path) as f:
                        if f.read().strip() == self.lid:
                            os.remove(sf_path)
                except Exception:
                    pass
            pm = os.path.join(os.getcwd(), '.claude', '.claude-lights-session')
            try:
                if os.path.exists(pm):
                    with open(pm) as f:
                        if f.read().strip() == self.lid:
                            os.remove(pm)
            except Exception:
                pass
            for mf in glob.glob(os.path.join(BASE, ".map-*")):
                try:
                    with open(mf) as f:
                        if f.read().strip() == self.lid:
                            os.remove(mf)
                except Exception:
                    pass

        def _read(self):
            try:
                with open(self.sf, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                return
            s = d.get("status", "idle")
            if s == "shutdown":
                self._cleanup()
                QApplication.quit()
                return
            # 仅关灯信号 (shutdown) 退出。不依赖心跳超时 —
            # 对话期间可能长时间无 hook 事件（长思考），信号灯应持续显示。
            if s != self.status:
                self.status = s
                self.age = 0.0
                p = PULSE.get(s, PULSE["idle"])
                self._tspd, self._tamp, self._tbase = p
                if s == "success":
                    _play_complete_sound(wait=False)

        def paintEvent(self, e):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            glow = self._glow()
            cx = WW / 2
            rr = 15.0

            shadow = QPainterPath()
            shadow.addRoundedRect(2, 16, WW - 4, WH - 18, rr, rr)
            p.fillPath(shadow, QColor(0, 0, 0, 35))

            body = QPainterPath()
            body.addRoundedRect(0.5, 14.5, WW - 1, WH - 16, rr, rr)
            p.fillPath(body, QColor(0x1C, 0x1C, 0x24))

            cyl = QLinearGradient(0, 0, WW, 0)
            cyl.setColorAt(0.0, QColor(0x18, 0x18, 0x1E))
            cyl.setColorAt(0.15, QColor(0x22, 0x22, 0x2A))
            cyl.setColorAt(0.35, QColor(0x2A, 0x2A, 0x32))
            cyl.setColorAt(0.50, QColor(0x2E, 0x2E, 0x36))
            cyl.setColorAt(0.65, QColor(0x2A, 0x2A, 0x32))
            cyl.setColorAt(0.85, QColor(0x22, 0x22, 0x2A))
            cyl.setColorAt(1.0, QColor(0x18, 0x18, 0x1E))
            p.fillPath(body, cyl)

            p.setPen(QPen(QColor(0x55, 0x55, 0x62), 0.7))
            p.drawPath(body)

            inner_rim = QPainterPath()
            inner_rim.addRoundedRect(1.2, 15.2, WW - 2.4, WH - 17.4, rr - 0.8, rr - 0.8)
            p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF, 12), 0.5))
            p.drawPath(inner_rim)
            p.setPen(QPen(QColor(0, 0, 0, 30), 0.8))
            p.drawPath(body)

            highlight = QPainterPath()
            highlight.addRoundedRect(2.5, 15.5, WW - 17, WH - 54, rr - 2, rr - 2)
            clip = QPainterPath()
            clip.addRoundedRect(0.5, 14.5, WW - 1, WH - 16, rr, rr)
            highlight = highlight.intersected(clip)
            hl_grad = QLinearGradient(0, 14, 0, 14 + (WH - 16) * 0.38)
            hl_grad.setColorAt(0.0, QColor(255, 255, 255, 30))
            hl_grad.setColorAt(0.3, QColor(255, 255, 255, 14))
            hl_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillPath(highlight, hl_grad)

            for i in range(2):
                sy = (LIGHT_Y[i] + LIGHT_Y[i + 1]) / 2
                sep = QLinearGradient(0, sy, WW, sy)
                sep.setColorAt(0.0, QColor(0, 0, 0, 0))
                sep.setColorAt(0.2, QColor(0, 0, 0, 20))
                sep.setColorAt(0.5, QColor(0, 0, 0, 12))
                sep.setColorAt(0.8, QColor(0, 0, 0, 20))
                sep.setColorAt(1.0, QColor(0, 0, 0, 0))
                p.fillRect(5, int(sy), WW - 10, 1, sep)

            for i, cy in enumerate(LIGHT_Y):
                sr = LIGHT_R + 3.5
                p.setPen(Qt.NoPen)
                p.setBrush(SOCKET)
                p.drawEllipse(QPointF(cx, cy), sr, sr)
                sg = QRadialGradient(QPointF(cx, cy), sr)
                sg.setColorAt(0.0, QColor(0x14, 0x14, 0x1A))
                sg.setColorAt(1.0, QColor(0x08, 0x08, 0x0C))
                p.setBrush(sg)
                p.drawEllipse(QPointF(cx, cy), sr - 0.5, sr - 0.5)

                cur = self.cur[i]
                for gr, ab in [
                    (LIGHT_R + 24, 0.006), (LIGHT_R + 21, 0.010), (LIGHT_R + 18, 0.016),
                    (LIGHT_R + 15.5, 0.024), (LIGHT_R + 13, 0.035), (LIGHT_R + 10.5, 0.050),
                    (LIGHT_R + 8, 0.070), (LIGHT_R + 6, 0.095), (LIGHT_R + 4.2, 0.125),
                    (LIGHT_R + 2.8, 0.160), (LIGHT_R + 1.5, 0.200),
                ]:
                    a = int(ab * glow * 255)
                    p.setBrush(QColor(cur.red(), cur.green(), cur.blue(), a))
                    p.drawEllipse(QPointF(cx, cy), gr, gr)

                bulb = QRadialGradient(QPointF(cx - 3.5, cy - 4.5), LIGHT_R * 1.25)
                bulb.setColorAt(0.00, QColor(min(255, cur.red() + 140), min(255, cur.green() + 140), min(255, cur.blue() + 140)))
                bulb.setColorAt(0.08, QColor(min(255, cur.red() + 80), min(255, cur.green() + 80), min(255, cur.blue() + 80)))
                bulb.setColorAt(0.18, QColor(min(255, cur.red() + 30), min(255, cur.green() + 30), min(255, cur.blue() + 30)))
                bulb.setColorAt(0.35, cur)
                bulb.setColorAt(0.55, QColor(max(0, cur.red() - 30), max(0, cur.green() - 30), max(0, cur.blue() - 30)))
                bulb.setColorAt(0.75, QColor(max(0, cur.red() - 55), max(0, cur.green() - 55), max(0, cur.blue() - 55)))
                bulb.setColorAt(0.92, QColor(max(0, cur.red() - 80), max(0, cur.green() - 80), max(0, cur.blue() - 80)))
                bulb.setColorAt(1.00, QColor(0, 0, 0, 0))
                p.setBrush(bulb)
                p.drawEllipse(QPointF(cx, cy), LIGHT_R, LIGHT_R)

                p.setBrush(QColor(255, 255, 255, 75))
                p.drawEllipse(QPointF(cx - 4.5, cy - 6), 3.5, 2.0)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawEllipse(QPointF(cx - 3.5, cy - 5), 2.2, 1.2)
                if glow > 0.12:
                    p.setBrush(QColor(255, 255, 255, int(glow * 32)))
                    p.drawEllipse(QPointF(cx + 2.5, cy + 6), 4.5, 2.0)

            p.setPen(QColor(0xA8, 0xA8, 0xB8))
            f0 = QFont("SF Pro Display, Segoe UI, Microsoft YaHei UI", 9)
            f0.setBold(True)
            f0.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
            p.setFont(f0)
            p.drawText(0, 0, WW, 15, Qt.AlignHCenter, self.lid)
            p.end()

    app = QApplication(sys.argv)
    w = SignalWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    server_main()
