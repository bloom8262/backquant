# BackQuant Agent Notes

## Docker Compose Change Scope

当改动涉及 Jupyter 默认配置，或 `backtest` 镜像内的 Python 依赖时，按最小范围处理：

- 只重建 `backend` 和 `jupyter`
- 只重启 `backend` 和 `jupyter`
- 不要顺带重建或重启 `frontend`、`mariadb` 等无关服务

推荐命令：

```bash
docker compose build backend jupyter
docker compose up -d --no-deps backend jupyter
```

## Git Config Defaults

- 提交代码时，Git 用户名必须为 `bloom8262`，邮箱为 `bloom8262@users.noreply.github.com`（切勿使用 `root`）。

## Docker Container Management

- 不要在未经用户明确确认的情况下，自动或擅自重新启动 Docker 容器，防止中断用户正在运行的任务。
