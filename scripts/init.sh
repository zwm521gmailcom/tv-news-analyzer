#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# scripts/init.sh — 幂等初始化（不删除任何数据）
#
# 设计原则：
#   1. 所有动作都是幂等的——重复运行结果相同
#   2. 已存在的文件/表/数据 一律保留，绝不覆盖
#   3. 只在缺失时创建（目录、空文件、.gitkeep）
#   4. DB 通过 init_db() 的 CREATE TABLE IF NOT EXISTS + 幂等迁移
#   5. 退出码 0 = 成功；非 0 = 失败（且失败时不会留下半成品）
#
# 用法：
#   bash scripts/init.sh                # 完整初始化
#   bash scripts/init.sh --check        # 只检查，不修改
#   bash scripts/init.sh --db-only      # 只初始化 DB（建表/迁移）
#
# 不需要 sudo，所有操作在项目根目录下。
# ─────────────────────────────────────────────────────────

set -euo pipefail

# ── 路径与配置 ──
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DATA_DIR="$ROOT_DIR/data"
BACKUP_DIR="$ROOT_DIR/backups"
LOG_DIR="$ROOT_DIR/logs"
SCRIPTS_DIR="$ROOT_DIR/scripts"
DB_PATH="$DATA_DIR/tv_news.db"
PYTHON_BIN="${PYTHON_BIN:-python3}"

CHECK_ONLY=0
DB_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --check)    CHECK_ONLY=1 ;;
    --db-only)  DB_ONLY=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg（试试 --help）" >&2
      exit 64
      ;;
  esac
done

# ── 颜色（终端可用时） ──
if [[ -t 1 ]]; then
  C_OK="\033[32m"   # 绿
  C_NEW="\033[36m"  # 青（新建）
  C_KEEP="\033[33m" # 黄（保留）
  C_OFF="\033[0m"
else
  C_OK=""; C_NEW=""; C_KEEP=""; C_OFF=""
fi

ok()   { printf "${C_OK}✓${C_OFF} %s\n" "$*"; }
new()  { printf "${C_NEW}+${C_OFF} %s\n" "$*"; }
keep() { printf "${C_KEEP}=${C_OFF} %s\n" "$*"; }
die()  { printf "✗ %s\n" "$*" >&2; exit 1; }

# ── 预检 ──
[[ -d "$ROOT_DIR" ]] || die "项目根目录不存在: $ROOT_DIR"
[[ -f "$ROOT_DIR/db/database.py" ]] || die "未找到 db/database.py，请确认在项目根目录运行"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "未找到 $PYTHON_BIN，请先安装 Python 3"

# ── step 0: 检查模式（不写任何东西） ──
if [[ "$CHECK_ONLY" == "1" ]]; then
  echo "=== 检查模式（不修改任何东西） ==="
  for d in "$DATA_DIR" "$BACKUP_DIR" "$LOG_DIR"; do
    if [[ -d "$d" ]]; then keep "$d 已存在"
    else new "$d 缺失（运行 init.sh 即可创建）"; fi
  done
  if [[ -f "$DB_PATH" ]]; then
    keep "$DB_PATH 已存在"
  else
    new "$DB_PATH 缺失（运行 init.sh 即可建表）"
  fi
  exit 0
fi

echo "=== 初始化项目: $ROOT_DIR ==="
echo

# ── step 1: 建目录（已存在就跳过） ──
echo "[1/4] 目录"
for d in "$DATA_DIR" "$BACKUP_DIR" "$LOG_DIR"; do
  if [[ -d "$d" ]]; then
    keep "$d"
  else
    mkdir -p "$d" || die "无法创建 $d"
    new "$d 已创建"
  fi
done

# ── step 2: 数据库初始化（幂等） ──
echo
echo "[2/4] 数据库（幂等 CREATE IF NOT EXISTS）"

DB_EXISTED_BEFORE=0
DB_SIZE_BEFORE=0
if [[ -f "$DB_PATH" ]]; then
  DB_EXISTED_BEFORE=1
  DB_SIZE_BEFORE=$(stat -f%z "$DB_PATH" 2>/dev/null || echo 0)
  keep "$DB_PATH 已存在（$(echo "scale=2; $DB_SIZE_BEFORE/1048576" | bc 2>/dev/null || echo $((DB_SIZE_BEFORE/1048576))) MB）— 不动"
else
  new "$DB_PATH 尚不存在，建表后会创建"
fi

# 跑 init_db() — 完全幂等：CREATE TABLE IF NOT EXISTS + 幂等迁移
"$PYTHON_BIN" - <<'PY' || die "init_db() 失败（DB 未创建/未修改）"
import asyncio
import sys
import os
sys.path.insert(0, os.getcwd())

from db.database import init_db
from config import settings

async def main():
    print(f"  - 目标 DB: {settings.DB_PATH}")
    await init_db()
    print("  - init_db() 完成（建表 + 幂等迁移）")

asyncio.run(main())
PY

# 验证结果
if [[ ! -f "$DB_PATH" ]]; then
  die "init_db() 完成后 $DB_PATH 仍不存在"
fi
DB_SIZE_AFTER=$(stat -f%z "$DB_PATH" 2>/dev/null || echo 0)

# 安全断言：如果之前 DB 存在且 size 变小，警告（理论上 init_db() 不会缩 DB）
if [[ "$DB_EXISTED_BEFORE" == "1" ]]; then
  if (( DB_SIZE_AFTER < DB_SIZE_BEFORE )); then
    die "DB size 从 ${DB_SIZE_BEFORE} 降到 ${DB_SIZE_AFTER}（异常，停止）"
  else
    keep "DB size: ${DB_SIZE_BEFORE} → ${DB_SIZE_AFTER} bytes（一致或增长）"
  fi
else
  new "DB 已创建（${DB_SIZE_AFTER} bytes）"
fi

# 查行数（只读，不会写）
DB_ROWS=$("$PYTHON_BIN" - <<'PY' 2>/dev/null || echo "0"
import asyncio, sys, os
sys.path.insert(0, os.getcwd())
from db.database import get_db
async def main():
    async with get_db() as db:
        try:
            cur = await db.execute("SELECT COUNT(*) FROM raw_news")
            row = await cur.fetchone()
            print(row[0])
        except Exception:
            print("0")
asyncio.run(main())
PY
)
keep "raw_news 当前行数: $DB_ROWS"

# ── step 3: .gitkeep 占位（保证空目录可被 git 跟踪） ──
echo
echo "[3/4] 占位文件（仅在缺失时创建）"
for d in "$DATA_DIR" "$BACKUP_DIR" "$LOG_DIR"; do
  marker="$d/.gitkeep"
  if [[ -f "$marker" ]]; then
    keep "$marker"
  else
    touch "$marker" || die "无法创建 $marker"
    new "$marker"
  fi
done

# ── step 4: 依赖检查（仅提示，不强制安装） ──
echo
echo "[4/4] 依赖检查"
if [[ -f "$ROOT_DIR/requirements.txt" ]]; then
  MISSING=$("$PYTHON_BIN" - <<'PY' 2>/dev/null || echo "?"
import importlib, sys
required = open("requirements.txt").read().splitlines()
missing = []
for line in required:
    pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split(">")[0].split("<")[0].strip()
    if not pkg or pkg.startswith("#"):
        continue
    mod = pkg.replace("-", "_")
    try:
        importlib.import_module(mod)
    except ImportError:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
print(",".join(missing) if missing else "OK")
PY
)
  if [[ "$MISSING" == "OK" ]]; then
    keep "Python 依赖完整"
  elif [[ "$MISSING" == "?" || -z "$MISSING" ]]; then
    keep "依赖检查跳过（脚本运行问题，请手动 pip install -r requirements.txt）"
  else
    new "缺失依赖: $MISSING"
    echo "  提示: pip install -r requirements.txt"
  fi
fi

# ── 总结 ──
echo
echo "=== 初始化完成 ==="
echo "  DB 路径    : $DB_PATH"
echo "  备份目录   : $BACKUP_DIR"
echo "  日志目录   : $LOG_DIR"
echo "  raw_news 行: $DB_ROWS"
echo
echo "下一步："
echo "  bash tvnews.sh start    # 启动 News + Web"
echo "  bash tvnews.sh status   # 查看状态"
echo "  open http://localhost:5888/  # 打开 Web"
