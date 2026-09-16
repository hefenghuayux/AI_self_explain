$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $projectRoot ".env"
$frontendPath = Join-Path $projectRoot "frontend"
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue

if (-not $nodeCommand) {
    throw "缺少 Node.js 运行时。请安装 Node.js 20 或更高版本。"
}

$nvmRoot = Split-Path -Parent (Split-Path -Parent $nodeCommand.Source)
$node20Path = Get-ChildItem -LiteralPath $nvmRoot -Directory -Filter "v20.*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    Select-Object -First 1

if (-not $node20Path) {
    throw "缺少 Node.js 20 运行时。请安装 Node.js 20 或更高版本。"
}

$nodeExecutable = Join-Path $node20Path.FullName "node.exe"
$corepackExecutable = Join-Path $node20Path.FullName "corepack.cmd"
if (-not (Test-Path -LiteralPath $nodeExecutable -PathType Leaf) -or
    -not (Test-Path -LiteralPath $corepackExecutable -PathType Leaf)) {
    throw "Node.js 20 安装不完整，缺少 node.exe 或 corepack.cmd：$($node20Path.FullName)"
}

$env:COREPACK_HOME = Join-Path $env:LOCALAPPDATA "ai-self-explain\corepack"
$env:Path = "$($node20Path.FullName);$env:Path"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "缺少虚拟环境 Python：${pythonPath}。请先创建 .venv 并安装后端依赖。"
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "缺少配置文件：${envFile}。请复制 .env.example 为 .env 并填写配置。"
}

& $pythonPath -m alembic -c backend\alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) {
    throw "数据库迁移失败，退出码：${LASTEXITCODE}"
}

& $pythonPath -m alembic -c backend\alembic.ini current
if ($LASTEXITCODE -ne 0) {
    throw "数据库版本检查失败，退出码：${LASTEXITCODE}"
}

$backend = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", (Join-Path $projectRoot "backend") `
    -WorkingDirectory $projectRoot `
    -NoNewWindow `
    -PassThru

try {
    if ($backend.WaitForExit(1000)) {
        throw "FastAPI 启动失败，退出码：$($backend.ExitCode)"
    }
    Push-Location $frontendPath
    try {
        & $corepackExecutable "pnpm@10.19.0" dev
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
