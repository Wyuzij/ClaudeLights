"""
ClaudeLights — 3D 玻璃质感桌宠信号灯
统一入口: server 模式 (渲染灯) + CLI 模式 (管理)
"""
import json, os, sys, time, math, glob, subprocess, socket, ctypes, argparse, threading

# ============================================================
# CLI 模式 (lights.py)
# ============================================================
BASE = os.path.dirname(os.path.abspath(__file__))

def _next_id():
    existing = set()
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        existing.add(os.path.splitext(os.path.basename(f))[0].replace("status-", ""))
    i = 1
    while f"CC-{i}" in existing: i += 1
    return f"CC-{i}"

def _sf(lid): return os.path.join(BASE, f"status-{lid}.json")
def _pidf(lid): return os.path.join(BASE, f".pid-{lid}")

def _write(lid, status, msg=""):
    with open(_sf(lid), "w", encoding="utf-8") as f:
        json.dump({"status": status, "message": msg}, f, ensure_ascii=False)

def _is_alive(pid):
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x0400, False, pid)
        if not h:
            err = k32.GetLastError()
            # 87=无效PID(MSYS2内部PID), 5=拒绝访问 — 均无法判断, 乐观假设存活
            return err in (87, 5)
        code = ctypes.c_ulong(); k32.GetExitCodeProcess(h, ctypes.byref(code)); k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except: return True

def cmd_start():
    ap = argparse.ArgumentParser(); ap.add_argument("--id", default=None); ap.add_argument("--session-pid", type=int, default=0)
    ns, _ = ap.parse_known_args(sys.argv[2:])
    lid = ns.id or _next_id(); sp = ns.session_pid or 0
    _write(lid, "idle", "Ready")
    # 映射: 会话PID → 灯ID (供 hook 进程树查找)
    if sp:
        with open(os.path.join(BASE, f".map-{sp}"), "w") as f: f.write(lid)
    cmdline = [sys.executable, __file__, "server", "--id", lid]
    if sp: cmdline += ["--session-pid", str(sp)]
    proc = subprocess.Popen(cmdline, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
    with open(_pidf(lid), "w") as f: f.write(str(proc.pid))
    print(f"  {lid} 已启动 (PID={proc.pid})")

def cmd_stop():
    ap = argparse.ArgumentParser(); ap.add_argument("id"); ns, _ = ap.parse_known_args()
    _write(ns.id, "shutdown")
    waited = 0.0
    while waited < 4.0:
        time.sleep(0.3); waited += 0.3
        sf = _sf(ns.id)
        if not os.path.exists(sf): break
        if os.path.exists(_pidf(ns.id)):
            try:
                with open(_pidf(ns.id)) as f: pid = int(f.read().strip())
                if not _is_alive(pid): break
            except: break
    for p in [_sf(ns.id), _pidf(ns.id)]:
        if os.path.exists(p):
            try: os.remove(p)
            except: pass
    # 清理映射文件
    for mf in glob.glob(os.path.join(BASE, ".map-*")):
        try:
            with open(mf) as f: mid = f.read().strip()
            if mid == ns.id: os.remove(mf)
        except: pass
    print(f"  {ns.id} 已停止")

def cmd_set():
    ap = argparse.ArgumentParser(); ap.add_argument("id"); ap.add_argument("status"); ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    _write(ns.id, ns.status, ns.message)
    print(f"  {ns.id} -> {ns.status} {ns.message}")

def cmd_list():
    files = glob.glob(os.path.join(BASE, "status-*.json"))
    alive, dead = [], []
    for f in sorted(files):
        name = os.path.basename(f).replace("status-", "").replace(".json", "")
        pidf = _pidf(name); pid = 0
        if os.path.exists(pidf):
            try:
                with open(pidf) as fh: pid = int(fh.read().strip())
            except: pass
        (alive if pid and _is_alive(pid) else dead).append((name, f))
    for name, f in alive:
        try:
            with open(f, "r", encoding="utf-8") as fh: d = json.load(fh)
            print(f"  {name:8s} | {d.get('status','?'):8s} | {d.get('message','')}")
        except: print(f"  {name:8s} | (读取失败)")
    for name, f in dead:
        for p in [f, _pidf(name)]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
    if not alive: print("  (无运行中的信号灯)")

def cmd_broadcast():
    ap = argparse.ArgumentParser(); ap.add_argument("status"); ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        with open(f, "w", encoding="utf-8") as fh:
            json.dump({"status": ns.status, "message": ns.message}, fh, ensure_ascii=False)

def _snapshot():
    """获取进程快照列表 [(pid, ppid, name)]"""
    try:
        TH32CS_SNAPPROCESS = 0x02
        class PE(ctypes.Structure):
            _fields_ = [("sz",ctypes.c_ulong),("u",ctypes.c_ulong),("pid",ctypes.c_ulong),
                        ("d1",ctypes.c_void_p),("d2",ctypes.c_ulong),("t",ctypes.c_ulong),
                        ("ppid",ctypes.c_ulong),("p",ctypes.c_long),("f",ctypes.c_ulong),
                        ("e",ctypes.c_char*260)]
        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1: return []
        result = []
        e = PE(); e.sz = ctypes.sizeof(PE)
        if k32.Process32First(snap, ctypes.byref(e)):
            while True:
                name = e.e.decode("utf-8", errors="ignore") if e.e else ""
                result.append((e.pid, e.ppid, name))
                if not k32.Process32Next(snap, ctypes.byref(e)): break
        k32.CloseHandle(snap)
        return result
    except: return []


def _find_cc_anchor():
    """
    沿进程树向上找 CC 进程做会话锚点。
    返回 (anchor_pid, anchor_name)。anchor_pid 在同一 CC 会话的多次 hook 调用间稳定。
    """
    snap = {p: (pp, n) for p, pp, n in _snapshot()}
    pid = os.getpid()
    # 先找 claude.exe/node.exe — 这是最可靠的锚点
    for _ in range(12):
        info = snap.get(pid)
        if not info: break
        ppid, name = info[0], (info[1] or "")
        if not ppid: break
        nl = name.lower()
        if "claude" in nl or ("node" in nl and "claude" not in nl):
            return ppid, name
        pid = ppid
    # 回退: 用当前进程的顶级非系统父进程
    pid = os.getpid()
    for _ in range(8):
        info = snap.get(pid)
        if not info: break
        ppid, name = info[0], info[1] or ""
        if not ppid: break
        nl = name.lower()
        # 跳过系统进程, 找到第一个"有意义"的父进程
        if nl and nl not in ("cmd.exe", "bash.exe", "pwsh.exe", "powershell.exe", "conhost.exe",
                             "svchost.exe", "winlogon.exe", "csrss.exe", "smss.exe", ""):
            if "cmd" not in nl:  # cmd.exe 太通用, 继续向上
                return ppid, name
        pid = ppid
    return os.getppid(), ""


def _find_my_light():
    """查找当前 CC 会话的信号灯 ID"""
    # 1. env var
    lid = os.environ.get("CLAUDE_LIGHTS_ID", "")
    if lid: return lid
    # 2. 进程树锚点查找
    anchor, _ = _find_cc_anchor()
    if anchor:
        mf = os.path.join(BASE, f".map-{anchor}")
        if os.path.exists(mf):
            try:
                with open(mf) as f: return f.read().strip()
            except: pass
        # 也检查父进程 PID (兼容旧版 .map 文件)
        pid = os.getpid()
        for _ in range(10):
            snap = {p: (pp, n) for p, pp, n in _snapshot()}
            info = snap.get(pid)
            if not info: break
            pid = info[0]
            if not pid: break
            mf = os.path.join(BASE, f".map-{pid}")
            if os.path.exists(mf):
                try:
                    with open(mf) as f: return f.read().strip()
                except: pass
    return ""


def _lazy_start(lid_hint, status, msg):
    """
    懒创建信号灯: 新 CC 会话首次 hook 触发时自动创建。
    用 CC 进程 PID 做锚点，同一会话多次 hook 调用绑定同一灯。
    """
    anchor, _ = _find_cc_anchor()
    mf = os.path.join(BASE, f".map-{anchor}") if anchor else ""
    # 检查是否已有映射 (竞态保护)
    if mf and os.path.exists(mf):
        try:
            with open(mf) as f: return f.read().strip()
        except: pass
    # 创建新灯
    lid = lid_hint or _next_id()
    _write(lid, status, msg)
    if anchor:
        with open(mf, "w") as f: f.write(lid)
    cmdline = [sys.executable, __file__, "server", "--id", lid]
    if anchor: cmdline += ["--session-pid", str(anchor)]
    proc = subprocess.Popen(cmdline, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
    with open(_pidf(lid), "w") as f: f.write(str(proc.pid))
    return lid


def cmd_hook():
    ap = argparse.ArgumentParser(); ap.add_argument("status"); ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    # 1. env var (PS profile 设置)
    lid = os.environ.get("CLAUDE_LIGHTS_ID", "")
    # 2. 进程树查找 (持久化映射)
    if not lid: lid = _find_my_light()
    # 3. 懒创建: 新 CC 会话首次触发时自动创建灯
    if not lid:
        lid = _lazy_start(None, ns.status, ns.message)
        if lid:
            return  # 已写入初始状态, 不需要再写
    if lid: _write(lid, ns.status, ns.message)
    else: cmd_broadcast()

def cmd_shutdown():
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        name = os.path.basename(f).replace("status-", "").replace(".json", "")
        _write(name, "shutdown")
    print("  已发送全部停止信号")


# ============================================================
# Server 模式 (light_server.py - PySide6 渲染)
# ============================================================
def server_main():
    from PySide6.QtCore import Qt, QTimer, QPointF
    from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPainterPath,
                                 QRadialGradient, QLinearGradient)
    from PySide6.QtWidgets import QApplication, QWidget

    WW, WH = 54, 152
    POLL_MS = 350
    WINDOW_OPACITY = 0.78
    SOCKET = QColor(0x10, 0x10, 0x16)
    OFF = [QColor(0x30,0x15,0x18), QColor(0x24,0x20,0x12), QColor(0x10,0x1E,0x15)]
    ON  = [QColor(0xFF,0x28,0x28), QColor(0xFF,0xCA,0x00), QColor(0x20,0xFF,0x46)]
    LIGHT_Y = [47, 83, 119]
    LIGHT_R = 13.5
    PULSE = {"idle":(0.010,0.06,0.18), "working":(0.045,0.26,0.36),
             "success":(0.06,0.42,0.48), "error":(0.08,0.40,0.40)}

    ap = argparse.ArgumentParser()
    ap.add_argument("server", nargs="?"); ap.add_argument("--id", required=True)
    ap.add_argument("--session-pid", type=int, default=0)
    ns = ap.parse_args()
    lid = ns.id; sp = ns.session_pid

    sf = _sf(lid)
    if not os.path.exists(sf):
        _write(lid, "idle", "Ready")

    class SignalWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.lid = lid; self.sf = sf; self._ppid = sp
            self.status = "idle"; self.age = 0.0; self.phase = 0.0
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

            try: n = int(lid.split("-")[-1])
            except: n = 1
            col, row = (n-1)//8, (n-1)%8
            self.move(16 + col*70, 16 + row*168)

            self._t0 = time.time()
            self._anim = QTimer(self); self._anim.timeout.connect(self._tick); self._anim.start(30)
            self._poll = QTimer(self); self._poll.timeout.connect(self._read); self._poll.start(POLL_MS)

        def _tick(self):
            now = time.time(); dt = min(now - self._t0, 0.1); self._t0 = now
            self.age += dt
            self.spd += (self._tspd - self.spd)*0.08
            self.amp += (self._tamp - self.amp)*0.08
            self.base += (self._tbase - self.base)*0.08
            self._targets()
            for i in range(3):
                c, t = self.cur[i], self.tgt[i]
                self.cur[i] = QColor(int(c.red()+(t.red()-c.red())*0.10),
                                     int(c.green()+(t.green()-c.green())*0.10),
                                     int(c.blue()+(t.blue()-c.blue())*0.10))
            self.update()

        def _targets(self):
            self.tgt = [QColor(c) for c in OFF]
            s, a = self.status, self.age
            if s in ("idle","success"):
                if s=="success" and a<0.1:   self.tgt[2]=QColor(255,255,255)
                elif s=="success" and a<0.7: self.tgt[2]=self._mx((255,255,255),ON[2],(a-0.1)/0.6)
                else: self.tgt[2]=QColor(ON[2])
            elif s=="working": self.tgt[1]=QColor(ON[1])
            elif s=="error":
                if a<0.08:  self.tgt[0]=QColor(255,255,255)
                elif a<0.5: self.tgt[0]=self._mx((255,255,255),ON[0],(a-0.08)/0.42)
                else: self.tgt[0]=QColor(ON[0])

        def _mx(self,a,b,t): return QColor(int(a[0]+(b.red()-a[0])*t),int(a[1]+(b.green()-a[1])*t),int(a[2]+(b.blue()-a[2])*t))

        def _glow(self):
            self.phase += self.spd
            return max(0.0, min(1.0, self.base+math.sin(self.phase)*self.amp))

        def _cleanup(self):
            for p in [self.sf, _pidf(self.lid)]:
                if os.path.exists(p):
                    try: os.remove(p)
                    except: pass
            # 清理映射文件
            for mf in glob.glob(os.path.join(BASE, ".map-*")):
                try:
                    with open(mf) as f:
                        if f.read().strip() == self.lid:
                            os.remove(mf)
                except: pass

        def _read(self):
            if self._ppid and not _is_alive(self._ppid):
                self._cleanup(); QApplication.quit(); return
            try:
                with open(self.sf,"r",encoding="utf-8") as f: d = json.load(f)
            except: return
            s = d.get("status","idle")
            if s=="shutdown": self._cleanup(); QApplication.quit(); return
            if s != self.status:
                self.status = s
                self.age = 0.0
                p = PULSE.get(s,PULSE["idle"])
                self._tspd,self._tamp,self._tbase = p

        def paintEvent(self, e):
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            glow = self._glow(); cx = WW/2; rr = 15.0

            # 投影
            shadow = QPainterPath()
            shadow.addRoundedRect(2, 16, WW-4, WH-18, rr, rr)
            p.fillPath(shadow, QColor(0,0,0,35))

            body = QPainterPath()
            body.addRoundedRect(0.5, 14.5, WW-1, WH-16, rr, rr)
            p.fillPath(body, QColor(0x1C,0x1C,0x24))

            cyl = QLinearGradient(0, 0, WW, 0)
            cyl.setColorAt(0.0, QColor(0x18,0x18,0x1E))
            cyl.setColorAt(0.15, QColor(0x22,0x22,0x2A))
            cyl.setColorAt(0.35, QColor(0x2A,0x2A,0x32))
            cyl.setColorAt(0.50, QColor(0x2E,0x2E,0x36))
            cyl.setColorAt(0.65, QColor(0x2A,0x2A,0x32))
            cyl.setColorAt(0.85, QColor(0x22,0x22,0x2A))
            cyl.setColorAt(1.0, QColor(0x18,0x18,0x1E))
            p.fillPath(body, cyl)

            p.setPen(QPen(QColor(0x55,0x55,0x62), 0.7)); p.drawPath(body)

            inner_rim = QPainterPath()
            inner_rim.addRoundedRect(1.2, 15.2, WW-2.4, WH-17.4, rr-0.8, rr-0.8)
            p.setPen(QPen(QColor(0xFF,0xFF,0xFF,12), 0.5)); p.drawPath(inner_rim)
            p.setPen(QPen(QColor(0,0,0,30), 0.8)); p.drawPath(body)

            highlight = QPainterPath()
            highlight.addRoundedRect(2.5, 15.5, WW-17, WH-54, rr-2, rr-2)
            clip = QPainterPath()
            clip.addRoundedRect(0.5, 14.5, WW-1, WH-16, rr, rr)
            highlight = highlight.intersected(clip)
            hl_grad = QLinearGradient(0, 14, 0, 14 + (WH-16)*0.38)
            hl_grad.setColorAt(0.0, QColor(255,255,255,30))
            hl_grad.setColorAt(0.3, QColor(255,255,255,14))
            hl_grad.setColorAt(1.0, QColor(255,255,255,0))
            p.fillPath(highlight, hl_grad)

            for i in range(2):
                sy = (LIGHT_Y[i] + LIGHT_Y[i+1]) / 2
                sep = QLinearGradient(0, sy, WW, sy)
                sep.setColorAt(0.0, QColor(0,0,0,0))
                sep.setColorAt(0.2, QColor(0,0,0,20))
                sep.setColorAt(0.5, QColor(0,0,0,12))
                sep.setColorAt(0.8, QColor(0,0,0,20))
                sep.setColorAt(1.0, QColor(0,0,0,0))
                p.fillRect(5, int(sy), WW-10, 1, sep)

            for i, cy in enumerate(LIGHT_Y):
                sr = LIGHT_R + 3.5
                p.setPen(Qt.NoPen); p.setBrush(SOCKET)
                p.drawEllipse(QPointF(cx, cy), sr, sr)
                sg = QRadialGradient(QPointF(cx, cy), sr)
                sg.setColorAt(0.0, QColor(0x14,0x14,0x1A))
                sg.setColorAt(1.0, QColor(0x08,0x08,0x0C))
                p.setBrush(sg); p.drawEllipse(QPointF(cx, cy), sr-0.5, sr-0.5)

                cur = self.cur[i]
                for gr, ab in [(LIGHT_R+15,0.012),(LIGHT_R+12,0.022),(LIGHT_R+9,0.036),(LIGHT_R+6,0.055),(LIGHT_R+3.5,0.080),(LIGHT_R+1.2,0.115)]:
                    a = int(ab * glow * 255)
                    p.setBrush(QColor(cur.red(), cur.green(), cur.blue(), a))
                    p.drawEllipse(QPointF(cx, cy), gr, gr)

                bulb = QRadialGradient(QPointF(cx-3.5, cy-4.5), LIGHT_R*1.25)
                bulb.setColorAt(0.00, QColor(min(255,cur.red()+70), min(255,cur.green()+70), min(255,cur.blue()+70)))
                bulb.setColorAt(0.10, QColor(min(255,cur.red()+45), min(255,cur.green()+45), min(255,cur.blue()+45)))
                bulb.setColorAt(0.25, QColor(min(255,cur.red()+18), min(255,cur.green()+18), min(255,cur.blue()+18)))
                bulb.setColorAt(0.50, cur)
                bulb.setColorAt(0.70, QColor(max(0,cur.red()-35), max(0,cur.green()-35), max(0,cur.blue()-35)))
                bulb.setColorAt(0.88, QColor(max(0,cur.red()-55), max(0,cur.green()-55), max(0,cur.blue()-55)))
                bulb.setColorAt(1.00, QColor(max(0,cur.red()-75), max(0,cur.green()-75), max(0,cur.blue()-75)))
                p.setBrush(bulb); p.drawEllipse(QPointF(cx, cy), LIGHT_R, LIGHT_R)

                p.setBrush(QColor(255,255,255,38))
                p.drawEllipse(QPointF(cx-4.5, cy-6), 3.5, 2.0)
                p.setBrush(QColor(255,255,255,18))
                p.drawEllipse(QPointF(cx-3.5, cy-5), 2.2, 1.2)
                if glow > 0.15:
                    p.setBrush(QColor(255,255,255, int(glow*14)))
                    p.drawEllipse(QPointF(cx+2.5, cy+6), 4.2, 1.8)

            p.setPen(QColor(0xA8,0xA8,0xB8))
            f0 = QFont("SF Pro Display, Segoe UI, Microsoft YaHei UI", 9)
            f0.setBold(True); f0.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
            p.setFont(f0); p.drawText(0, 0, WW, 15, Qt.AlignHCenter, self.lid)
            p.end()

    app = QApplication(sys.argv)
    w = SignalWidget(); w.show()
    sys.exit(app.exec())


# ============================================================
# 入口分发
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        server_main()
    elif len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "start": cmd_start()
        elif cmd == "stop": cmd_stop()
        elif cmd == "set": cmd_set()
        elif cmd == "list": cmd_list()
        elif cmd == "broadcast": cmd_broadcast()
        elif cmd == "hook": cmd_hook()
        elif cmd == "shutdown": cmd_shutdown()
        else: print(f"未知命令: {cmd}\n用法: {sys.argv[0]} {{start|stop|set|list|broadcast|hook|shutdown}}")
    else:
        print("ClaudeLights\n用法: main.py {start|stop|set|list|broadcast|hook|shutdown}")
