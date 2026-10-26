# 前端：node 构建 → nginx 静态托管（生产构建）
#
# ⚠️ 构建上下文是**仓库根**（见 docker-compose.yml 的 `build.context: .`）：
#    `vite.config.ts` 在构建期也会读 `../scripts/demo_ports.py`（dev 端口的单一来源），
#    用 `web/` 单独作上下文时那个文件不存在 ⇒ 构建失败。
FROM node:22-alpine AS build

WORKDIR /app

# 先只拷清单：依赖没变时这层能命中缓存（可复现：npm ci 严格按 lock 安装）
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web ./
# 供 vite.config.ts 读取端口（只用于 dev server；生产构建不依赖它的取值）
COPY scripts/demo_ports.py /scripts/demo_ports.py

RUN npm run build

FROM nginx:1.27-alpine

COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
