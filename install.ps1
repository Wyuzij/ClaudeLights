<#
  ClaudeLights 一键安装脚本
  用法: powershell -ExecutionPolicy Bypass -File install.ps1 [-ExePath .\claude-lights.exe]
  支持: PowerShell 终端 + VSCode Claude Code Agent (自动懒创建)
#>
param(
    [string]$InstallDir = "$env:USERPROFILE\.claude-lights",
    [string]$ExePath = ""  # 如果提供 exe, 则不需要 Python/PySide6
)

$ErrorActionPreference = "Stop"
Write-Host "`n  ClaudeLights Installer`n" -ForegroundColor Cyan

$useExe = (Test-Path $ExePath)
$BIN = if ($useExe) { $ExePath } else { "python `"$InstallDir\main.py`"" }

# ---- 1. 复制文件 ----
Write-Host "[1/4] 安装文件到 $InstallDir ..."
New-Item -ItemType Directory -Force $InstallDir | Out-Null
$src = if ($ExePath) { Split-Path $ExePath -Parent } else { Split-Path $PSCommandPath -Parent }

if ($useExe) {
    Copy-Item $ExePath "$InstallDir\claude-lights.exe" -Force
    Write-Host "       已安装 claude-lights.exe"
} else {
    @("main.py") | ForEach-Object { Copy-Item "$src\$_" "$InstallDir\$_" -Force }
    Write-Host "       已安装 main.py"
}

# ---- 2. 依赖 ----
if ($useExe) {
    Write-Host "[2/4] (exe 模式, 跳过依赖安装)"
} else {
    Write-Host "[2/4] 安装 PySide6 ..."
    pip install PySide6 -q 2>&1 | Out-Null
    Write-Host "       PySide6 已安装"
}

# ---- 3. 配置 PowerShell Profile ----
Write-Host "[3/4] 配置 PowerShell Profile ..."
$profileDir = Split-Path $PROFILE -Parent
New-Item -ItemType Directory -Force $profileDir | Out-Null

$claudePath = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claudePath) { $claudePath = "claude" }

$func = @"

# ClaudeLights auto-start
function claude {
    `$LIGHTS_DIR = "$InstallDir"
    `$id = `$null
    try {
        `$output = & $BIN start --session-pid `$PID 2>&1
        `$id = (`$output | Select-String -Pattern "CC-\d+").Matches.Value
        if (`$id) {
            `$env:CLAUDE_LIGHTS_ID = `$id
            `$env:CLAUDE_LIGHTS_DIR = `$LIGHTS_DIR
            Write-Host "[ClaudeLights] `$id ready"
        }
        & "$claudePath" @args
    } finally {
        if (`$id) { & $BIN stop `$id 2>`$null }
    }
}
"@

$existing = if (Test-Path $PROFILE) { Get-Content $PROFILE -Raw } else { "" }
if ($existing -match "ClaudeLights auto-start") {
    Write-Host "       Profile 已配置, 更新中..."
    $newContent = $existing -replace "(?s)# ClaudeLights auto-start.*?(?=# ClaudeLights|`\Z)", $func
    Set-Content $PROFILE $newContent -Encoding UTF8
} else {
    Add-Content $PROFILE "`n$func"
}
Write-Host "       Profile 已配置"

# ---- 4. 配置 CC Hooks ----
Write-Host "[4/4] 配置 Claude Code hooks ..."
$settingsPath = "$env:USERPROFILE\.claude\settings.json"
if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    if (-not $settings.hooks) { $settings | Add-Member -NotePropertyName hooks -NotePropertyValue @{} -Force }

    $hookDefs = @{
        PreToolUse = @{ status = "working"; message = "Working..." }
        UserPromptSubmit = @{ status = "working"; message = "Thinking..." }
        Stop = @{ status = "success"; message = "Done" }
        StopFailure = @{ status = "error"; message = "Failed" }
        PermissionRequest = @{ status = "error"; message = "Need Choice" }
        SessionEnd = @{ status = "shutdown"; message = "SessionEnd" }
    }

    foreach ($event in $hookDefs.Keys) {
        $entry = $hookDefs[$event]
        $cmd = "$BIN hook $($entry.status) `"$($entry.message)`""

        if (-not $settings.hooks.$event) {
            $settings.hooks | Add-Member -NotePropertyName $event -NotePropertyValue @() -Force
        }

        $found = $false
        foreach ($group in $settings.hooks.$event) {
            foreach ($h in $group.hooks) {
                if ($h.command -match "lights\.py hook|claude-lights.*hook") {
                    $h.command = $cmd
                    $found = $true
                }
            }
        }
        if (-not $found) {
            if ($settings.hooks.$event.Count -eq 0) {
                $settings.hooks.$event = @(@{ matcher = ""; hooks = @() })
            }
            $settings.hooks.$event[0].hooks += @{
                type = "command"
                command = $cmd
                timeout = 3
                async = $true
                asyncRewake = $false
            }
        }
    }

    $settings | ConvertTo-Json -Depth 6 | Set-Content $settingsPath -Encoding UTF8
    Write-Host "       CC hooks 已配置"
} else {
    Write-Host "       (未找到 CC settings, 跳过 hooks)"
}

Write-Host "`n  安装完成! 新开 PowerShell 窗口, 输入 claude 启动`n" -ForegroundColor Green
Write-Host "  手动控制: $BIN {set|list|stop} ...`n"
