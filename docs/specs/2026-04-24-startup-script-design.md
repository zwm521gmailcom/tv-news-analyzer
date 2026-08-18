# TV News Analyzer 启动脚本设计

**Goal:** 提供一个轻量 Bash 管理脚本，一键启动、停止、查询和重启新闻采集服务与 Web 看板。

**Architecture:** 在仓库根目录新增 `tvnews.sh`，由它统一管理两个独立进程：`python3 -u run.py` 和 `python3 -u web/server.py`。脚本按仓库根目录定位运行环境，把日志和 PID 文件放在 `logs/` 下，避免引入额外的进程守护层。

**Tech Stack:** Bash, Python 3, existing `run.py`, existing Flask web server.

---

## Scope

- 管理两个已有入口：
  - 新闻采集：`run.py`
  - Web 服务：`web/server.py`
- 支持命令：
  - `start`
  - `stop`
  - `status`
  - `restart`
- 允许直接执行 `./tvnews.sh` 默认进入 `start`
- 不修改采集、存储或 Web 的业务逻辑

## Process Rules

- 启动前自动创建 `logs/`
- 新闻与 Web 使用独立日志文件
- 新闻与 Web 使用独立 PID 文件
- `start` 需要幂等，已运行时不重复拉起
- `stop` 需要先优雅退出，超时后再强制退出
- `status` 需要显示每个进程是否运行

## Files

- Create: `tvnews.sh`
- Modify: `README.md`
- Modify: `.gitignore`

## Verification

- `bash -n tvnews.sh`
- `./tvnews.sh status`
- `./tvnews.sh start`
- `./tvnews.sh stop`

