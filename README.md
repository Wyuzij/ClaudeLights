# ClaudeLights

Claude Code 桌面信号灯 — 3D 玻璃质感悬浮窗，实时显示 AI 任务状态。

![Python](https://img.shields.io/badge/python-3.8+-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

- 真透明置顶悬浮，鼠标穿透不挡操作
- CC hooks 首次触发懒创建，SessionEnd 自动关闭
- 纯 hooks 驱动，无进程树依赖（VSCode + Terminal 均可靠）
- 会话级隔离：`CLAUDE_CODE_SESSION_ID` 绑定，多窗口各自独立信号灯
- 任务完成提示音：pygame.mixer 播放 MP3/WAV，Server 异步不阻塞 UI
- 11 层荧光光晕 + 8 段球体渐变 + 玻璃曲面高光
- 心跳超时兜底 (30s)，异常退出自动清理

---

## 一键安装

要求 Python 3.8+，PowerShell 中执行：

```powershell
# 1. 安装依赖
pip install PySide6 pygame

# 2. 运行安装脚本
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` 自动完成：
- 复制 `main.py` 到 `~/.claude-lights/`
- 创建 `sounds/` 目录（提示音文件需手动放入）
- 配置 PowerShell profile（拦截 `claude` 命令自动启停信号灯）
- 配置 Claude Code hooks（6 个生命周期事件全覆盖）

之后新开 PowerShell 窗口，直接敲 `claude` 就能看到左上角的信号灯。

---

## 手动使用

```powershell
# 启动
python main.py start                    # 自动编号 CC-1
python main.py start --id MyProject     # 自定义 ID

# 查看状态
python main.py list

# 手动更新
python main.py set CC-1 working "Building..."
python main.py set CC-1 success "Done"
python main.py set CC-1 error   "Need input"

# 停止
python main.py stop CC-1
python main.py shutdown                 # 全部停止
```

---

## 状态说明

- **绿灯呼吸** — 就绪 (idle)，默认状态
- **黄灯脉冲** — 运行中 (working)，UserPromptSubmit / PreToolUse 触发
- **绿灯爆闪** — 完成 (success)，Stop 触发，同步播放提示音
- **红灯脉冲** — 异常/需选择 (error)，StopFailure / PermissionRequest 触发

---

## 提示音

任务完成时自动播放提示音。默认音效文件：`sounds/dragon-studio-new-notification-3-398649.mp3`

- 支持 MP3、WAV 格式（pygame.mixer）
- 替换音效：将任意 MP3/WAV 放入 `sounds/` 目录，修改 `main.py` 第 18 行 `COMPLETE_SOUND` 路径
- Server 模式异步播放不阻塞 UI 动画
- Hook/CLI 模式等待播放完成后进程退出，避免截断

---

## 生命周期（纯 CC hooks 驱动）

```
新 CC 会话 → 首次 hook (UserPromptSubmit / PreToolUse)
  → 懒创建信号灯进程 + 写入 CLAUDE_CODE_SESSION_ID 绑定
  → 后续 hook 自动找到所属灯，更新状态

会话进行中:
  PreToolUse / UserPromptSubmit → 黄灯 working
  Stop                         → 绿灯 success + 播放提示音
  StopFailure / PermissionReq  → 红灯 error
  心跳持续刷新（每个 hook 写入 heartbeat）

会话结束:
  SessionEnd hook  → 写入 shutdown → 灯进程立即退出
  异常退出         → 心跳 30s 超时 → 兜底清理
```

---

## 多窗口隔离

每个 CC 会话（VSCode 窗口 / Terminal 标签页）拥有独立信号灯：

- **主机制**：`CLAUDE_CODE_SESSION_ID` 环境变量 → `.session-{sid}` 绑定文件
- **回退**：项目标记 `.claude/.claude-lights-session`（同项目共享）
- **兜底**：心跳扫描 + 存活检查（跳过已被认领的灯）

多灯自动网格排列：每列 8 个，超出自动换列。

---

## 工作原理

```
hooks 驱动 (VSCode + Terminal 通用):

  CC hooks 事件 → main.py hook <status> <message>
    → 查找所属灯 (三级优先级):
      ① CLAUDE_LIGHTS_ID 环境变量 (PS profile 设置)
      ② CLAUDE_CODE_SESSION_ID 会话绑定 (区分不同 CC 会话)
      ③ 项目标记 + 心跳扫描 (兼容回退)
    → 首次触发时懒创建新灯 + 写入会话绑定
    → 写入 status-{id}.json (含 heartbeat 时间戳)

信号灯进程 (PySide6 渲染):

  30ms 动画循环 — 颜色渐变插值 + 正弦脉冲光晕
  350ms 轮询 status-{id}.json:
    → shutdown     → 立即退出 + 清理绑定文件
    → heartbeat > 30s → 兜底退出（会话异常）
    → 状态变更     → 切换灯色 + 重置动画相位
    → success      → pygame.mixer 异步播放提示音
```

---

## 依赖

- Python 3.8+
- [PySide6](https://pypi.org/project/PySide6/) — Qt for Python (窗口渲染)
- [pygame](https://pypi.org/project/pygame/) — SDL2 mixer (提示音播放)

---

## 项目结构

```
ClaudeLights/
  main.py          # 统一入口 (server 渲染 + CLI 管理 + hook 入口)
  install.ps1      # 一键安装脚本 (PowerShell)
  sounds/          # 提示音文件目录
    .gitkeep
  README.md
```

---

## License

MIT
