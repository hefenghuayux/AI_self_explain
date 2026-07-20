$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "缺少配置文件：$envFile。请复制 .env.example 为 .env 并填写配置。"
}

$backend = Start-Process `
    -FilePath "python" `
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
