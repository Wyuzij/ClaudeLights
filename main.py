"""
ClaudeLights — 3D 玻璃质感桌宠信号灯
生命周期完全由 CC hooks 驱动:
- UserPromptSubmit/PreToolUse → 首次触发懒创建灯, 后续更新状态为 working
- Stop → success (灯亮绿色, 会话继续)
- StopFailure → error (灯亮红色)
- SessionEnd → shutdown (灯立即退出)
- 心跳 30s 超时 → 异常退出兜底 (hook 进程被 kill 前来不及写 shutdown)

This is the main entry point — kept as a thin shim for backward compatibility.
"""
import sys
import os

# Ensure core.py and light_server.py are importable from the same directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from core import (
    cmd_start, cmd_stop, cmd_set, cmd_list,
    cmd_broadcast, cmd_hook, cmd_shutdown,
)
from light_server import server_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        server_main()
    elif len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "start":
            cmd_start()
        elif cmd == "stop":
            cmd_stop()
        elif cmd == "set":
            cmd_set()
        elif cmd == "list":
            cmd_list()
        elif cmd == "broadcast":
            cmd_broadcast()
        elif cmd == "hook":
            cmd_hook()
        elif cmd == "shutdown":
            cmd_shutdown()
        else:
            print(f"未知命令: {cmd}\n用法: {sys.argv[0]} {{start|stop|set|list|broadcast|hook|shutdown|server}}")
    else:
        print("ClaudeLights\n用法: main.py {start|stop|set|list|broadcast|hook|shutdown|server}")
