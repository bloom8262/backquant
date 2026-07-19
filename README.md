# BackQuant 量化回测平台

[English](README_EN.md) | 简体中文

> 重要提示：示例网站已上线，请轻操：https://my.clawbot.help/    
> 默认用户名/密码：`admin` / `pass123456`

<u>**完全本地化部署，策略和数据本地运行，不依赖第三方平台，既保障隐私安全，又具备高度可定制性。**</u>

本仓库包含后端（Flask + RQAlpha）与前端（Vue 3）两部分，并提供 Research 工作台（Jupyter Lab）集成能力。
支持 **RQAlpha 股票日线回测** 与 **VnPy 期货 CTA 策略可视化回测**，期货数据从 rqalpha bundle 一键导入 MariaDB。
**推荐使用 Docker 安装部署**，一次性包含 Flask、Jupyter、Nginx 与前端构建产物

## 一、Docker 安装与部署

### 安装 Docker

```bash
sudo curl -fsSL https://get.docker.com | sh
```

### 安装前注意事项

1. **RQAlpha 行情数据时间范围为 200501 至 202602**，压缩包约 1G，下载解压耗时较长。
2. **Docker 构建完成后需等待行情下载完成才能登录**。
3. **系统运行请至少准备 5G 硬盘空间**。

### 安装与启动（Docker Compose）

Docker Compose 默认使用 named volume 持久化所有数据，下载逻辑在容器 entrypoint 内完成：
首次启动会下载行情数据到 `/data/rqalpha/bundle`，之后复用同一 volume，不会重复下载。

```bash
cp .env.example .env
docker compose up --build -d
```

### RQAlpha 与日线数据

- Docker 镜像已内置 RQAlpha（`rqalpha==6.1.2`）。
- 镜像已预装 VnPy 4.3.0（含 vnpy_ctastrategy、vnpy_mysql 等），支持期货 CTA 策略回测。
- 镜像已预装常用量化库：`numpy`、`pandas`、`statsmodels`、`scikit-learn`
- 内置一个默认策略 `demo`，可直接在策略列表中运行。
- 日线数据按月更新：容器启动时自动写入 crontab（`/etc/cron.d/rqalpha-bundle`，默认每月 1 日 03:00 运行更新任务）。
- 如需调整更新时间，设置环境变量 `RQALPHA_BUNDLE_CRON`（例如 `0 4 1 * *`）。
- 如需关闭自动更新，设置 `RQALPHA_BUNDLE_CRON=off`。
- 如需跳过首次下载，设置 `RQALPHA_BUNDLE_BOOTSTRAP=0`（仅建议已手动准备好 bundle 时使用）。

### 访问

- 前端：`http://localhost:8088`
- 首次登录账号/密码：`admin` / `pass123456`（可在 `.env` 中修改）

说明：后端 API 与 Jupyter 已通过同域路径反向代理（`/api`、`/jupyter`），一般无需单独访问端口。

### 系统截图

![Screenshot 0](images/screen0.png?v=2)
![Screenshot 1](images/screen1.png?v=2)
![Screenshot 3](images/screen3.png?v=2)

## 二、配置说明

后端主要配置在 `backtest/.env.wsgi`：

- `SECRET_KEY` JWT 签名密钥，必须修改
- `LOCAL_AUTH_MOBILE` / `LOCAL_AUTH_PASSWORD` 默认管理员用户名/密码（首次初始化写入数据库）
- `LOCAL_AUTH_PASSWORD_HASH` 可选，bcrypt hash 优先级高于明文密码
- `RESEARCH_NOTEBOOK_*` Jupyter 相关配置
- 说明：Jupyter token 可不设置（空值表示不启用 token 鉴权，仅建议用于内网/本机）。

前端支持两种方式配置 API 基址：

- 构建时环境变量 `VUE_APP_API_BASE`
- 运行时 `frontend/public/config.js`（无需重新构建）

## 三、其他的

### Docker Volume 数据持久化

所有重要数据均存储在 Docker named volume 中，**重建镜像、升级、重启容器均不会丢失数据**：

| Volume 名称 | 挂载路径 | 存储内容 |
|------------|---------|---------|
| `mariadb_data` | MariaDB `/var/lib/mysql` | 数据库（用户、市场任务、回测元数据等） |
| `backtest_data` | 容器 `/data/backtest` | 回测结果、策略文件、日志 |
| `rqalpha_bundle` | 容器 `/data/rqalpha/bundle` | RQAlpha 行情数据包 |
| `notebooks` | 容器 `/data/notebooks` | Jupyter Notebook 文件 |

**常用操作对数据的影响：**

```bash
docker compose build          # ✅ 安全：只重建镜像，volume 不受影响
docker compose up -d          # ✅ 安全：容器重建时 volume 自动重新挂载
docker compose down           # ✅ 安全：停止并删除容器，volume 保留
docker compose down -v        # ⚠️ 危险：会同时删除所有 volume，数据永久丢失
```

### Jupyter 示例

- 示例 Notebook：`docs/notebooks/example.ipynb`
- 详细说明：`docs/jupyter.md`

### 美股日线数据

- 下载、增量更新及 MariaDB 导入：`docs/us-equity-data.md`

### Nginx 反代说明

生产环境可参考 `docs/nginx.md`。

### API 文档

后端 API 说明见 `backtest/README.md`。

### License

Apache-2.0. See `LICENSE`.
