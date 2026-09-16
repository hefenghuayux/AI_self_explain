#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

if [ ! -f .env.production ]; then
    echo "缺少服务器配置文件 .env.production" >&2
    exit 1
fi

case "${IMAGE_TAG:-}" in
    *[!0-9a-f]* | "")
        echo "IMAGE_TAG 必须是小写 Git 提交哈希" >&2
        exit 1
        ;;
esac

compose() {
    docker compose --env-file .env.production -f docker-compose.prod.yml "$@"
}

last_successful_tag_file=.deploy-last-successful-tag
last_successful_tag=""
if [ -f "$last_successful_tag_file" ]; then
    last_successful_tag=$(cat "$last_successful_tag_file")
fi

compose pull backend frontend
compose run --rm backend python -m alembic -c /app/backend/alembic.ini upgrade head
compose up -d --remove-orphans

backend_container=$(compose ps -q backend)
attempt=1
while [ "$attempt" -le 30 ]; do
    health_status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}starting{{end}}' "$backend_container")
    if [ "$health_status" = "healthy" ]; then
        printf '%s\n' "$IMAGE_TAG" > "$last_successful_tag_file"
        echo "部署成功：$IMAGE_TAG"
        exit 0
    fi
    if [ "$health_status" = "unhealthy" ]; then
        break
    fi
    sleep 2
    attempt=$((attempt + 1))
done

if [ -n "$last_successful_tag" ]; then
    echo "新版本健康检查失败，恢复上一版：$last_successful_tag" >&2
    IMAGE_TAG="$last_successful_tag" compose up -d --no-deps backend frontend
fi

echo "部署失败：后端健康检查未通过" >&2
exit 1
