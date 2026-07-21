import path from "node:path"
import { fileURLToPath, URL } from "node:url"

import vue from "@vitejs/plugin-vue"
import { defineConfig, loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  const projectRoot = fileURLToPath(new URL("..", import.meta.url))
  const env = loadEnv(mode, projectRoot, "")
  const backendProxyTarget = env.BACKEND_PROXY_TARGET

  if (!backendProxyTarget) {
    throw new Error("缺少 BACKEND_PROXY_TARGET，请在项目根目录 .env 中配置后端代理地址")
  }

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        "@": path.resolve(fileURLToPath(new URL(".", import.meta.url)), "src"),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: backendProxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
