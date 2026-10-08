#!/bin/sh

set -eu
umask 077

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
shared_dir=$(CDPATH= cd -- "$project_root/../../shared" && pwd)

if [ ! -f .env.production ]; then
    echo "缺少共享服务器配置文件 .env.production" >&2
    exit 1
fi

case "${IMAGE_TAG:-}" in
    *[!0-9a-f]* | "")
        echo "IMAGE_TAG 必须是完整的小写 Git 提交哈希" >&2
        exit 1
        ;;
esac
if [ "${#IMAGE_TAG}" -ne 40 ] || [ "$(basename "$project_root")" != "$IMAGE_TAG" ]; then
    echo "发布目录必须是 releases/<40 位 IMAGE_TAG>" >&2
    exit 1
fi
export IMAGE_TAG

exec 9>"$shared_dir/.deploy.lock"
if ! flock -n 9; then
    echo "已有部署正在执行，停止本次发布" >&2
    exit 1
fi

compose() {
    docker compose -p ai-self-explain --env-file .env.production -f docker-compose.prod.yml "$@"
}

check_schema() {
    compose run --rm --no-deps --pull never backend python -c '
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from app.core.config import Settings

settings = Settings()
if not settings.database_url.startswith("mysql+pymysql://"):
    raise SystemExit("生产部署要求使用已确认的 MySQL 数据库")
expected = set(ScriptDirectory.from_config(Config("/app/backend/alembic.ini")).get_heads())
engine = create_engine(settings.database_url)
try:
    with engine.connect() as connection:
        actual = set(MigrationContext.configure(connection).get_current_heads())
finally:
    engine.dispose()
if actual != expected:
    raise SystemExit(f"数据库版本不匹配：当前 {sorted(actual)}，需要 {sorted(expected)}；请备份并单独授权迁移")
print("数据库版本校验通过：" + ", ".join(sorted(actual)))
'
}

last_successful_tag_file="$shared_dir/.deploy-last-successful-tag"
last_successful_tag=""
if [ -f "$last_successful_tag_file" ]; then
    last_successful_tag=$(cat "$last_successful_tag_file")
    case "$last_successful_tag" in
        *[!0-9a-f]* | "")
            echo "上一版发布记录不是有效的提交哈希" >&2
            exit 1
            ;;
    esac
    if [ "${#last_successful_tag}" -ne 40 ] || [ ! -f "$project_root/../$last_successful_tag/docker-compose.prod.yml" ]; then
        echo "上一版发布目录缺失或版本记录无效" >&2
        exit 1
    fi
fi

compose config --quiet
compose pull backend frontend caddy
check_schema

rollback() {
    trap - EXIT HUP INT TERM
    echo "部署失败：$IMAGE_TAG，开始处理失败版本" >&2
    compose ps >&2 || true
    if [ -n "$last_successful_tag" ]; then
        cd "$project_root/../$last_successful_tag"
        IMAGE_TAG="$last_successful_tag"
        export IMAGE_TAG
        if check_schema && compose up -d --no-build --pull never --wait --wait-timeout 120; then
            echo "已恢复上一版容器：$last_successful_tag" >&2
        else
            echo "上一版与当前数据库不兼容或恢复失败，需要人工处理；没有回退数据库" >&2
        fi
    else
        if compose stop; then
            echo "没有上一版，已停止失败的首次发布容器" >&2
        else
            echo "停止失败版本失败，需要人工处理" >&2
        fi
    fi
    exit 1
}

trap rollback EXIT
trap 'exit 1' HUP INT TERM
compose up -d --no-build --pull never --wait --wait-timeout 120
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
    http://127.0.0.1:18081/api/health >/dev/null
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
    https://ai-self-explain.xyz/api/health >/dev/null
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
    https://ai-self-explain.xyz/ >/dev/null
printf '%s\n' "$IMAGE_TAG" > "$last_successful_tag_file.tmp"
mv "$last_successful_tag_file.tmp" "$last_successful_tag_file"
trap - EXIT HUP INT TERM
echo "部署成功：$IMAGE_TAG"
