$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $projectRoot ".env"
$frontendPath = Join-Path $projectRoot "frontend"
$vitePath = Join-Path $frontendPath "node_modules\.bin\vite.cmd"
$firewallRuleName = "AI Self Explain LAN (Vite 5173)"

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return
    }

    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $processName = if ($null -eq $process) { "未知进程" } else { $process.ProcessName }
    throw "端口 ${Port} 已被 ${processName}（PID $($listener.OwningProcess)）占用。请先停止该进程后重试。"
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "缺少虚拟环境 Python：${pythonPath}。请先创建 .venv 并安装后端依赖。"
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "缺少配置文件：${envFile}。请复制 .env.example 为 .env 并填写配置。"
}

if (-not (Test-Path -LiteralPath $vitePath -PathType Leaf)) {
    throw "缺少前端依赖：${vitePath}。请先在 frontend 目录执行 pnpm install。"
}

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($currentUser)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath `
        -Verb RunAs
    exit
}

$defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" |
    Sort-Object RouteMetric |
    Select-Object -First 1
if ($null -eq $defaultRoute) {
    throw "未找到默认 IPv4 路由，无法确定局域网访问地址。"
}

$connectionProfile = Get-NetConnectionProfile -InterfaceIndex $defaultRoute.InterfaceIndex
if ($connectionProfile.NetworkCategory -ne "Private") {
    throw "当前网络不是专用网络。请先在 Windows 设置中将当前网络设为专用，再运行此脚本。"
}

$lanAddress = Get-NetIPAddress -InterfaceIndex $defaultRoute.InterfaceIndex -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress
if ([string]::IsNullOrWhiteSpace($lanAddress)) {
    throw "未找到当前网络的 IPv4 地址，无法生成局域网访问地址。"
}

Assert-PortAvailable -Port 8000
Assert-PortAvailable -Port 5173

$firewallRule = Get-NetFirewallRule -DisplayName $firewallRuleName -ErrorAction SilentlyContinue
if ($null -eq $firewallRule) {
    New-NetFirewallRule `
        -DisplayName $firewallRuleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 5173 `
        -Profile Private | Out-Null
}
else {
    Set-NetFirewallRule `
        -DisplayName $firewallRuleName `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Private | Out-Null
}

& $pythonPath -m alembic -c backend\alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) {
    throw "数据库迁移失败，退出码：${LASTEXITCODE}"
}

$backend = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", (Join-Path $projectRoot "backend"), "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $projectRoot `
    -NoNewWindow `
    -PassThru

try {
    $backendReady = $false
    for ($attempt = 1; $attempt -le 40; $attempt += 1) {
        if ($backend.HasExited) {
            throw "FastAPI 启动失败，退出码：$($backend.ExitCode)"
        }
        if (Test-NetConnection -ComputerName "127.0.0.1" -Port 8000 -InformationLevel Quiet) {
            $backendReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $backendReady) {
        throw "FastAPI 在 10 秒内未开始监听 127.0.0.1:8000。"
    }

    Write-Host "局域网访问地址：http://${lanAddress}:5173"
    Write-Host "请让其他设备连接同一专用局域网后访问该地址。按 Ctrl+C 可停止服务。"
    Push-Location $frontendPath
    try {
        & $vitePath --host "0.0.0.0" --strictPort
    }
    finally {
        Pop-Location
    }
}
finally {
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
}
