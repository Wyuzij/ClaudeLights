"""
ClaudeLights — 3D 玻璃质感桌宠信号灯
生命周期完全由 CC hooks 驱动:
- UserPromptSubmit/PreToolUse → 首次触发懒创建灯, 后续更新状态为 working
- Stop → success (灯亮绿色, 会话继续)
- StopFailure → error (灯亮红色)
- SessionEnd → shutdown (灯立即退出)
- 心跳 30s 超时 → 异常退出兜底 (hook 进程被 kill 前来不及写 shutdown)
"""
import json, os, sys, time, math, glob, subprocess, socket, ctypes, argparse, threading
import pygame

# ============================================================
# CLI 模式
# ============================================================
BASE = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(BASE, "sounds")
COMPLETE_SOUND = os.path.join(SOUNDS_DIR, "dragon-studio-new-notification-3-398649.mp3")

def _ensure_sound():
    """确保提示音文件存在"""
    return os.path.exists(COMPLETE_SOUND)

def _play_complete_sound(wait=True):
    """播放任务完成提示音 (pygame.mixer 支持 MP3/WAV). wait=True 会阻塞到播放结束, 用于短生命周期进程."""
    if not _ensure_sound():
        return
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        sound = pygame.mixer.Sound(COMPLETE_SOUND)
        sound.play()
        if wait:
            time.sleep(sound.get_length() + 0.1)
    except Exception:
        pass

def _next_id():
    existing = set()
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        existing.add(os.path.splitext(os.path.basename(f))[0].replace("status-", ""))
    i = 1
    while f"CC-{i}" in existing: i += 1
    return f"CC-{i}"

def _sf(lid): return os.path.join(BASE, f"status-{lid}.json")
def _pidf(lid): return os.path.join(BASE, f".pid-{lid}")
def _mapf(ppid): return os.path.join(BASE, f".map-{ppid}")
def _lock_path(): return os.path.join(BASE, ".lock")

def _acquire_lock(timeout=5.0):
    """文件锁, 防止并发 hook 同时创建信号灯。带死锁检测。"""
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
            # 死锁检测: 锁文件超过 10s → 强行清理
            try:
                with open(lp) as f:
                    info = json.load(f)
                if time.time() - info.get("ts", 0) > 10:
                    try: os.remove(lp)
                    except: pass
                    continue
            except: pass
            if time.time() > deadline:
                return False
            time.sleep(0.1)

def _release_lock():
    try:
        lp = _lock_path()
        if os.path.exists(lp):
            os.remove(lp)
    except: pass

def _sessionf(sid):
    """CC 会话绑定文件: .session-{session_id} → 灯 ID"""
    return os.path.join(BASE, f".session-{sid}")

def _project_marker():
    """项目级标记 (fallback, 同项目共享)"""
    return os.path.join(os.getcwd(), '.claude', '.claude-lights-session')

def _read_heartbeat(lid):
    """读信号灯的最后心跳时间, 文件不存在或损坏返回0"""
    sf = _sf(lid)
    if not os.path.exists(sf): return 0
    try:
        with open(sf, encoding="utf-8") as f:
            return json.load(f).get("heartbeat", 0)
    except: return 0

def _write(lid, status, msg=""):
    with open(_sf(lid), "w", encoding="utf-8") as f:
        json.dump({"status": status, "message": msg, "heartbeat": time.time()}, f, ensure_ascii=False)

def _check_alive(pid):
    """返回 (certain, alive)。用 WaitForSingleObject 精确判断进程死活。"""
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, pid)
        if not h:
            err = k32.GetLastError()
            if err == 5:  # ACCESS_DENIED → 进程存在但无权限
                return False, True
            return True, False
        WAIT_TIMEOUT = 0x00000102
        ret = k32.WaitForSingleObject(h, 0)
        k32.CloseHandle(h)
        alive = ret == WAIT_TIMEOUT
        return True, alive
    except: return False, True

def _is_alive(pid):
    _, alive = _check_alive(pid)
    return alive

def _find_my_light():
    """
    查找当前 CC 会话的信号灯 ID。
    优先级: CLAUDE_LIGHTS_ID → CLAUDE_CODE_SESSION_ID → 项目标记 → 心跳扫描
    带重试机制, 防止并发 hook 同时创建灯 (竞态)。
    """
    # 1. 手动指定 (PS profile 设置的 CLAUDE_LIGHTS_ID)
    lid = os.environ.get("CLAUDE_LIGHTS_ID", "")
    if lid and os.path.exists(_pidf(lid)):
        try:
            with open(_pidf(lid)) as f:
                if _is_alive(int(f.read().strip())):
                    return lid
        except: pass

    # 2. CC 会话 ID 绑定 (每个 CC 窗口独立)
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid:
        ssf = _sessionf(sid)
        # 轮询等待: 另一个并发 hook 可能正在创建 → 等它写完 .pid
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if os.path.exists(ssf):
                try:
                    with open(ssf) as f: lid = f.read().strip()
                    pidf = _pidf(lid)
                    if os.path.exists(pidf):
                        with open(pidf) as f:
                            pid = int(f.read().strip())
                        if _is_alive(pid):
                            return lid
                        # 灯已死 → 清理绑定 (加锁防止惊群)
                        if _acquire_lock(2.0):
                            try:
                                if os.path.exists(ssf):
                                    os.remove(ssf)
                                # 删除死灯的 pidf, 让 _next_id 重新分配
                                dead_pidf = _pidf(lid)
                                if os.path.exists(dead_pidf):
                                    try: os.remove(dead_pidf)
                                    except: pass
                                dead_sf = _sf(lid)
                                if os.path.exists(dead_sf):
                                    try: os.remove(dead_sf)
                                    except: pass
                            finally:
                                _release_lock()
                        break
                    # .session 存在但 .pid 还不存在 → 另一个 hook 正在创建, 等待
                except:
                    # 文件损坏/不可读 → 等待后清理
                    if time.time() > deadline - 0.5:
                        try: os.remove(ssf)
                        except: pass
            time.sleep(0.15)
        # SID 存在但无绑定 → 新 CC 会话, 不蹭别人的灯
        return ""

    # 3. 项目标记 (仅 CLI 直接调用时回退, SID 为空才会到这)
    pm = _project_marker()
    if os.path.exists(pm):
        try:
            with open(pm) as f: lid = f.read().strip()
            if os.path.exists(_pidf(lid)):
                with open(_pidf(lid)) as f:
                    if _is_alive(int(f.read().strip())):
                        return lid
        except: pass
        try: os.remove(pm)
        except: pass

    # 有 .claude/ 但无标记 → 新项目, 不蹭别人的灯
    if os.path.isdir(os.path.join(os.getcwd(), '.claude')):
        return ""

    # 4. 心跳扫描 (兜底: 非 CC 项目目录)
    for mp in glob.glob(os.path.join(BASE, ".map-*")):
        try:
            map_ppid = int(os.path.basename(mp).replace(".map-", ""))
        except: continue
        if not _is_alive(map_ppid):
            try: os.remove(mp)
            except: pass

    best_lid, best_hb = "", 0
    now = time.time()
    for pidf in glob.glob(os.path.join(BASE, ".pid-*")):
        try:
            with open(pidf) as f: server_pid = int(f.read().strip())
        except: continue
        if _is_alive(server_pid):
            lid = os.path.basename(pidf).replace(".pid-", "")
            hb = _read_heartbeat(lid)
            if hb > 0 and now - hb < 30 and hb > best_hb:
                best_lid, best_hb = lid, hb
    return best_lid

def _lazy_start(lid_hint, status, msg):
    """
    懒创建信号灯: 新 CC 会话首次 hook 触发时自动创建。
    用 CLAUDE_CODE_SESSION_ID 绑定 → 每个 CC 窗口独立信号灯。
    加文件锁防止并发 hook 同时创建。
    **先写 .session 绑定, 再创建灯** — 让并发 hook 第一时间发现已有绑定。
    """
    if not _acquire_lock(5.0):
        return ""  # 获取锁超时, 不可能

    try:
        # 二次检查: 锁获得后, 另一个 hook 可能已创建
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        ssf = _sessionf(sid) if sid else ""
        if ssf and os.path.exists(ssf):
            try:
                with open(ssf) as f: return f.read().strip()
            except: pass

        lid = lid_hint or _next_id()
        # ① 先写 CC 会话 ID 绑定 — 让并发 hook 第一时间发现此灯
        if sid:
            with open(ssf, "w") as f: f.write(lid)
        # ② 项目级标记
        try:
            pm = _project_marker()
            os.makedirs(os.path.dirname(pm), exist_ok=True)
            with open(pm, "w") as f: f.write(lid)
        except: pass
        # ③ 写初始状态
        _write(lid, status, msg)
        # ④ 启动灯进程
        cmdline = [sys.executable, __file__, "server", "--id", lid]
        proc = subprocess.Popen(cmdline, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
        # ⑤ 写 PID (在进程启动后)
        with open(_pidf(lid), "w") as f: f.write(str(proc.pid))
        return lid
    finally:
        _release_lock()

def cmd_start():
    ap = argparse.ArgumentParser(); ap.add_argument("--id", default=None)
    ns, _ = ap.parse_known_args(sys.argv[2:])
    lid = ns.id or _next_id()
    _write(lid, "idle", "Ready")
    cmdline = [sys.executable, __file__, "server", "--id", lid]
    proc = subprocess.Popen(cmdline, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
    with open(_pidf(lid), "w") as f: f.write(str(proc.pid))
    print(f"  {lid} 已启动 (PID={proc.pid})")

def cmd_stop():
    ap = argparse.ArgumentParser(); ap.add_argument("id"); ns, _ = ap.parse_known_args(sys.argv[2:])
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
    # 清理指向本灯的会话绑定
    for sf in glob.glob(os.path.join(BASE, ".session-*")):
        try:
            with open(sf) as f:
                if f.read().strip() == ns.id:
                    os.remove(sf)
        except: pass
    # 清理项目标记
    pm = os.path.join(os.getcwd(), '.claude', '.claude-lights-session')
    try:
        if os.path.exists(pm):
            with open(pm) as f:
                if f.read().strip() == ns.id:
                    os.remove(pm)
    except: pass
    # 清理旧版 .map-* 残留
    for mf in glob.glob(os.path.join(BASE, ".map-*")):
        try:
            with open(mf) as f:
                if f.read().strip() == ns.id:
                    os.remove(mf)
        except: pass
    print(f"  {ns.id} 已停止")

def cmd_set():
    ap = argparse.ArgumentParser(); ap.add_argument("id"); ap.add_argument("status"); ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    _write(ns.id, ns.status, ns.message)
    print(f"  {ns.id} -> {ns.status} {ns.message}")
    if ns.status == "success":
        _play_complete_sound()

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

def cmd_hook():
    """
    CC hook 入口。所有 hook 事件 (PreToolUse, Stop, SessionEnd 等) 都走这里。
    生命周期:
    - 首次 hook → 懒创建灯 + 写状态
    - 后续 hook → 找已有灯 + 写状态
    - SessionEnd 传 shutdown → 灯进程读到后立即退出
    """
    ap = argparse.ArgumentParser(); ap.add_argument("status"); ap.add_argument("message", nargs="?", default="")
    ns, _ = ap.parse_known_args(sys.argv[2:])
    lid = _find_my_light()
    if not lid:
        lid = _lazy_start(None, ns.status, ns.message)
        if lid:
            return  # _lazy_start 已写入初始状态
    if lid: _write(lid, ns.status, ns.message)
    else: cmd_broadcast()
    # 任务完成时播放提示音
    if ns.status == "success":
        _play_complete_sound()

def cmd_shutdown():
    for f in glob.glob(os.path.join(BASE, "status-*.json")):
        name = os.path.basename(f).replace("status-", "").replace(".json", "")
        _write(name, "shutdown")
    print("  已发送全部停止信号")


# ============================================================
# Server 模式 (PySide6 渲染)
# ============================================================
def server_main():
    from PySide6.QtCore import Qt, QTimer, QPointF
    from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPainterPath,
                                 QRadialGradient, QLinearGradient)
    from PySide6.QtWidgets import QApplication, QWidget

    WW, WH = 54, 152
    POLL_MS = 350
    WINDOW_OPACITY = 0.92
    HEARTBEAT_TIMEOUT = 30  # 30s 无心跳 → 会话异常退出, 兜底关闭
    SOCKET = QColor(0x10, 0x10, 0x16)
    OFF = [QColor(0x08,0x08,0x0A), QColor(0x08,0x08,0x0A), QColor(0x08,0x08,0x0A)]
    ON  = [QColor(0xFF,0x10,0x10), QColor(0xFF,0xDC,0x00), QColor(0x00,0xFF,0x30)]
    LIGHT_Y = [47, 83, 119]
    LIGHT_R = 13.5
    PULSE = {"idle":(0.010,0.08,0.30), "working":(0.055,0.34,0.44),
             "success":(0.08,0.50,0.56), "error":(0.10,0.48,0.48)}

    ap = argparse.ArgumentParser()
    ap.add_argument("server", nargs="?"); ap.add_argument("--id", required=True)
    ns = ap.parse_args()
    lid = ns.id

    sf = _sf(lid)
    if not os.path.exists(sf):
        _write(lid, "idle", "Ready")

    class SignalWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.lid = lid; self.sf = sf
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
            if sys.platform == "win32":
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_LAYERED = 0x00080000
                user32 = ctypes.windll.user32
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT | WS_EX_LAYERED)

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
            # 清理指向本灯的 .session-* 绑定
            for sf in glob.glob(os.path.join(BASE, ".session-*")):
                try:
                    with open(sf) as f:
                        if f.read().strip() == self.lid:
                            os.remove(sf)
                except: pass
            # 清理项目标记
            pm = os.path.join(os.getcwd(), '.claude', '.claude-lights-session')
            try:
                if os.path.exists(pm):
                    with open(pm) as f:
                        if f.read().strip() == self.lid:
                            os.remove(pm)
            except: pass
            # 清理旧版 .map-* 残留
            for mf in glob.glob(os.path.join(BASE, ".map-*")):
                try:
                    with open(mf) as f:
                        if f.read().strip() == self.lid:
                            os.remove(mf)
                except: pass

        def _read(self):
            """
            纯状态文件驱动 — 不依赖进程树。
            SessionEnd hook 写 shutdown → 立即退出。
            心跳超时 → 异常退出兜底 (hook 进程被 kill 前来不及写 shutdown)。
            """
            try:
                with open(self.sf,"r",encoding="utf-8") as f: d = json.load(f)
            except: return
            s = d.get("status","idle")
            if s == "shutdown":
                self._cleanup(); QApplication.quit(); return
            hb = d.get("heartbeat", 0)
            if hb and time.time() - hb > HEARTBEAT_TIMEOUT:
                self._cleanup(); QApplication.quit(); return
            if s != self.status:
                self.status = s
                self.age = 0.0
                p = PULSE.get(s, PULSE["idle"])
                self._tspd, self._tamp, self._tbase = p
                # 转换到 success 时播放提示音 (server 长生命周期, 异步播放不阻塞 UI)
                if s == "success":
                    _play_complete_sound(wait=False)

        def paintEvent(self, e):
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            glow = self._glow(); cx = WW/2; rr = 15.0

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
                for gr, ab in [(LIGHT_R+24,0.006),(LIGHT_R+21,0.010),(LIGHT_R+18,0.016),
                               (LIGHT_R+15.5,0.024),(LIGHT_R+13,0.035),(LIGHT_R+10.5,0.050),
                               (LIGHT_R+8,0.070),(LIGHT_R+6,0.095),(LIGHT_R+4.2,0.125),
                               (LIGHT_R+2.8,0.160),(LIGHT_R+1.5,0.200)]:
                    a = int(ab * glow * 255)
                    p.setBrush(QColor(cur.red(), cur.green(), cur.blue(), a))
                    p.drawEllipse(QPointF(cx, cy), gr, gr)

                bulb = QRadialGradient(QPointF(cx-3.5, cy-4.5), LIGHT_R*1.25)
                bulb.setColorAt(0.00, QColor(min(255,cur.red()+140), min(255,cur.green()+140), min(255,cur.blue()+140)))
                bulb.setColorAt(0.08, QColor(min(255,cur.red()+80), min(255,cur.green()+80), min(255,cur.blue()+80)))
                bulb.setColorAt(0.18, QColor(min(255,cur.red()+30), min(255,cur.green()+30), min(255,cur.blue()+30)))
                bulb.setColorAt(0.35, cur)
                bulb.setColorAt(0.55, QColor(max(0,cur.red()-30), max(0,cur.green()-30), max(0,cur.blue()-30)))
                bulb.setColorAt(0.75, QColor(max(0,cur.red()-55), max(0,cur.green()-55), max(0,cur.blue()-55)))
                bulb.setColorAt(0.92, QColor(max(0,cur.red()-80), max(0,cur.green()-80), max(0,cur.blue()-80)))
                bulb.setColorAt(1.00, QColor(0,0,0,0))
                p.setBrush(bulb); p.drawEllipse(QPointF(cx, cy), LIGHT_R, LIGHT_R)

                p.setBrush(QColor(255,255,255,75))
                p.drawEllipse(QPointF(cx-4.5, cy-6), 3.5, 2.0)
                p.setBrush(QColor(255,255,255,40))
                p.drawEllipse(QPointF(cx-3.5, cy-5), 2.2, 1.2)
                if glow > 0.12:
                    p.setBrush(QColor(255,255,255, int(glow*32)))
                    p.drawEllipse(QPointF(cx+2.5, cy+6), 4.5, 2.0)

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
