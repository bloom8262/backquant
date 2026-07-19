# 美股日线下载与导入

脚本在 `backend` 容器内运行，行情来自 Yahoo Finance，CSV 保存在持久化的
`backtest_data` volume 中。数据库使用 `(symbol, date)` 主键，重复执行会更新已有
记录，不会清空 QQQ 等其他标的数据。

## 增加 VIX 和 VOO

镜像更新后，一条命令完成下载和导入：

```bash
docker compose exec backend \
  python /app/import_us_equity_to_mariadb.py --download VIX VOO
```

`VIX` 会自动使用 Yahoo Finance 的 `^VIX` 下载，数据库中保存为 `VIX`。
VOO 已存在时只会补充新日期并修正最近几天的数据。

查看数据库中已有标的和日期范围：

```bash
docker compose exec backend \
  python /app/import_us_equity_to_mariadb.py --inventory
```

## 增加其他标的

普通股票或 ETF 直接写代码：

```bash
docker compose exec backend \
  python /app/import_us_equity_to_mariadb.py --download AAPL SPY GLD
```

Yahoo 代码和希望保存的数据库代码不同时，使用 `数据库代码=Yahoo代码`：

```bash
docker compose exec backend \
  python /app/import_us_equity_to_mariadb.py --download 'SPX=^GSPC' 'DJI=^DJI'
```

也可以在 `.env` 中维护默认列表：

```dotenv
US_EQUITY_SYMBOLS=QQQ,TQQQ,VOO,VIX,SPY
```

此后不写标的即可更新默认列表：

```bash
docker compose exec backend \
  python /app/import_us_equity_to_mariadb.py --download
```

## 分开执行

只下载 CSV：

```bash
docker compose exec backend python /app/scripts/us_download.py VIX VOO
```

导入已经下载的 CSV：

```bash
docker compose exec backend python /app/import_us_equity_to_mariadb.py VIX VOO
```

默认采用前复权日线价格。下载时会覆盖最近 7 天，以吸收数据源可能发生的修正；
导入使用 upsert，因此命令可以安全重复执行。

## 首次应用代码变更

这次变更增加了 Python 依赖和容器环境变量，需要按项目约定仅重建并更新
`backend` 与 `jupyter`。执行前应确认当前没有重要任务在运行：

```bash
docker compose build backend jupyter
docker compose up -d --no-deps backend jupyter
```
