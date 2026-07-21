$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $projectRoot ".env"

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
    & pnpm --dir (Join-Path $projectRoot "frontend") dev
}
finally {
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
}
