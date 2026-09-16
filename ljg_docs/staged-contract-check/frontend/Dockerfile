FROM node:20-bookworm-slim AS build

WORKDIR /workspace/frontend

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend ./

ENV BACKEND_PROXY_TARGET=http://backend:8000
RUN pnpm build

FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/frontend/dist /usr/share/nginx/html

EXPOSE 80
