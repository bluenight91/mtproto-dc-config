# MTProto DC Config (Dokploy + GHCR)

每日生成并提供 Surge 可用的 `mtproto-dc-config.json`。容器监听 **8080**，交给 Dokploy / Traefik 反代。

构建时从 [surge-networks/MTProtoDCConfigGenerator](https://github.com/surge-networks/MTProtoDCConfigGenerator) 编译官方 generator。

## 自动构建（类似 DockerHub-AutoBuild）

GitHub Actions 每天检查上游 `main` 的 commit SHA（上游目前没有 Release）：

- SHA 变化 → 构建多架构镜像并推到 GHCR
- SHA 不变 → 跳过构建（几乎不消耗 Actions 分钟）
- 本仓库 Dockerfile / 脚本变更，或手动 `workflow_dispatch` → 强制构建

镜像：

```text
ghcr.io/<你的用户名>/mtproto-dc-config:latest
ghcr.io/<你的用户名>/mtproto-dc-config:sha-<短SHA>
```

首次把仓库推到 GitHub 后：

1. 打开 Actions，跑一次 **Build and push GHCR image**
2. 在 GitHub Packages 里把该 package 设为 **Public**（或给 Dokploy 配 pull token）
3. 把 `docker-compose.yml` 里的 `OWNER` 改成你的用户名

## Dokploy

1. 用 Docker Compose / Docker image 部署
2. 镜像填 `ghcr.io/<你的用户名>/mtproto-dc-config:latest`
3. 端口 **8080**，绑域名
4. 可选环境变量：`CRON_SCHEDULE`、`TZ`、`PORT`、`DROP_SECRET_ENDPOINTS`（默认 `1`）

说明：

- **镜像更新**：仅在上游 generator 代码更新时重建（Actions）
- **JSON 日更**：在运行中的容器内 cron 完成，不依赖重新拉镜像
- **去重**：生成后会把 IPv6 规范成压缩形式，并对同一 `(dc, ip, port)` 合并为一条（`flags` 按位或，例如普通 + STATIC → 保留 STATIC）
- **过滤 SECRET**：默认去掉带 `secret` / Fake-TLS（`0xee` + Google SNI 等）的入口。这类 IP 常不在 Telegram 分流名单里，容易命中兜底规则并疯狂重试。若确实需要，设 `DROP_SECRET_ENDPOINTS=0`。

访问（根路径与下面路径等价，都直接返回 JSON）：

```text
https://你的域名/
https://你的域名/mtproto-dc-config.json
```

Surge：

```ini
[MTProto]
dc-config-url = https://你的域名/mtproto-dc-config.json
```

## 本地

```sh
# 改 compose 里的 image OWNER，或临时改回 build: .
docker compose up -d
curl -sS http://127.0.0.1:8080/mtproto-dc-config.json | head
```
