# ClaudeLights

Claude Code 桌面信号灯。3D 玻璃质感悬浮窗，AI 状态一目了然。

[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## 效果速览

屏幕左上角出现一个半透明悬浮窗，三盏灯实时反映 Claude Code 的状态：

| 灯光 | 触发条件 |
|---|---|
| 🟢 **绿色呼吸** | 就绪，等待输入 |
| 🟡 **黄色脉冲** | AI 思考/工作中（`UserPromptSubmit` / `PreToolUse`） |
| 🟢 **绿色爆闪** + 🔊 | 任务完成（`Stop`），同步播放提示音 |
| 🔴 **红色脉冲** | 异常或需要用户选择（`StopFailure` / `PermissionRequest`） |

灯窗口**鼠标完全穿透** — 点击只会落在它下方的窗口上，不影响任何操作。

---

## 安装（下载 → 双击 → 完成）

**前提：** 电脑装有 Python 3.8+（[python.org](https://python.org) 下载）

1. **下载** [`ClaudeLights-Setup.exe`](https://github.com/Wyuzij/ClaudeLights/releases/latest/download/ClaudeLights-Setup.exe)

2. **双击打开** → 暗色主题安装向导启动

3. **点击"⚡ 一键安装"** → 全自动完成五项配置（见下文）

4. **新开 PowerShell，输入 `claude`** → 信号灯自动出现

> 不需要手动 `pip install` 任何东西 — setup.exe 自动安装 PySide6 + pygame。

---

## 安装后多了什么

安装程序只改三个地方：

| 位置 | 做了什么 |
|---|---|
| `~/.claude-lights/` | 复制 core.py、light_server.py、main.py、client.py、声音文件 |
| `~/.claude/settings.json` | 写入 6 个 hook 命令（Claude Code 生命周期钩子） |
| PowerShell profile | 注入 `claude` 包装函数（拦截命令，自动启停信号灯） |

**卸载同理**：客户端里输入 `DELETE` 确认，三个地方原样清理。

---

## 它是怎么工作的

布局很简单：**两层拦截 + 一层文件通信**。

### ① PowerShell profile → 拦下 `claude` 命令

每次你敲 `claude`，先启动信号灯进程，再启动真正的 Claude Code，退出时自动关灯：

```powershell
function claude {
    # 1. 启动信号灯
    $id = (python ~/.claude-lights/main.py start | sls "CC-\d+").Matches.Value
    $env:CLAUDE_LIGHTS_ID = $id

    # 2. 启动真正的 claude
    cmd /c "claude $args"

    # 3. 退出后关灯
    python ~/.claude-lights/main.py stop $id
}
```

### ② Claude Code hooks → 监听 6 个生命周期事件

`~/.claude/settings.json` 里注入的 hook 命令。每当 CC 内部状态变化，自动执行一行 Python：

```
UserPromptSubmit  →  python main.py hook working   "Thinking..."
PreToolUse        →  python main.py hook working   "Working..."
Stop              →  python main.py hook success   "Done"
StopFailure       →  python main.py hook error     "Failed"
PermissionRequest →  python main.py hook error     "Need Choice"
SessionEnd        →  python main.py hook shutdown  "SessionEnd"
```

所有 hook 都是 `"async": true` — 发完即返回，不阻塞 Claude。

### ③ 信号灯进程（PySide6）→ 文件轮询

Hook 写 JSON → 信号灯 350ms 读一次 → 看到变化就切动画：

```
status-CC-1.json 写入 "working"   →  信号灯读到 → 黄灯脉冲
status-CC-1.json 写入 "success"   →  信号灯读到 → 绿灯爆闪 + 播 MP3
status-CC-1.json 写入 "shutdown"  →  信号灯读到 → 清理退出
```

**全程用文件系统通信**，没有管道、没有网络、不读进程树。这就是为什么无论 Claude Code 跑在独立终端、VSCode 集成终端、还是 VSCode Agent 面板，信号灯都正常工作。

### 支持 VSCode Claude 插件

在 VSCode 中通过 Claude Code 插件使用时，信号灯同样正常运作。CC 自动设置 `CLAUDE_CODE_SESSION_ID` 环境变量，hook 据此查找或懒创建对应信号灯，每个 VSCode 窗口的 CC 会话各自独立。

---

## 多窗口

一个 VSCode 窗口跑 Claude，一个 Terminal 也跑 Claude → 两个独立的信号灯，自动排成纵向一列。每列 8 个，超出换列。

---

## GUI 管理客户端

双击 `~/.claude-lights/client.pyw` 或从安装向导启动。系统托盘常驻，双击托盘图标打开仪表盘：

- **仪表盘**：实时状态、启停控制、统计
- **系统托盘**：灯泡颜色 = 当前状态（绿/黄/红/灰）
- **设置**：换提示音、开关单个 hook、开机自启
- **卸载**：输入 DELETE 全清

---

## 手动命令

```powershell
python main.py start          # 启动
python main.py list           # 查看所有灯
python main.py set CC-1 idle  # 改状态
python main.py stop CC-1      # 停止一个
python main.py shutdown       # 全部停止
```

---

## 构建

```powershell
pip install pyinstaller
pyinstaller setup.spec          # → dist/ClaudeLights-Setup.exe （约 8MB）
```

---

## License

MIT
