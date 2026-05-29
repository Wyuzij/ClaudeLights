# ClaudeLights

Claude Code 桌面信号灯 — 3D 玻璃质感悬浮窗，实时显示 AI 任务状态。

![Python](https://img.shields.io/badge/python-3.8+-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

- 真透明置顶悬浮，鼠标穿透不挡操作
- 每 CC 窗口/Agent 自动创建独立信号灯，关闭自动消除
- **支持 PowerShell 终端 + VSCode Claude Code Agent**
- 3D 球体灯珠 + 6 层光晕 + 玻璃曲面高光
- CC hooks 首次触发时懒创建，无需手动启动

---

## 一键安装

要求 Python 3.8+，PowerShell 中执行：

```powershell
# 1. 安装依赖
pip install PySide6

# 2. 运行安装脚本
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` 会自动完成：
- 复制文件到 `~/.claude-lights/`
- 配置 PowerShell profile（拦截 `claude` 命令自动创建信号灯）
- 配置 Claude Code hooks（PreToolUse / UserPromptSubmit / Stop / PermissionRequest）

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

| 灯色 | 含义 | 触发条件 |
|------|------|----------|
| 绿灯呼吸 | 就绪 | 默认状态 |
| 黄灯脉冲 | 运行中 | UserPromptSubmit / PreToolUse |
| 绿灯爆闪 | 完成 | Stop |
| 红灯脉冲 | 异常/需选择 | StopFailure / PermissionRequest |

---

## 工作原理

```
新 PS 窗口 → 敲 claude
  → PS profile 拦截, python main.py start
  → 创建信号灯进程(独立悬浮窗), 写入映射文件
  → 启动真正的 Claude Code
  → CC hooks 通过进程树查找所属灯, 更新状态
  → 退出时 main.py stop 关灯
  → 直接关终端 → 信号灯检测父进程消亡, 自清理
```

---

## 项目结构

```
ClaudeLights/
  main.py          # 统一入口 (server 渲染 + CLI 管理)
  install.ps1       # 一键安装脚本
  README.md
```

---

## 依赖

- Python 3.8+
- [PySide6](https://pypi.org/project/PySide6/) — Qt for Python

## License

MIT
