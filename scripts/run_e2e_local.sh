#!/usr/bin/env bash
# run_e2e_local.sh — 一条命令打通「用**本仓编排**拉起服务 → 跑 tests/e2e/ → 撤栈」
#
# 背景（为什么需要它）：
#   `tests/e2e/` 打的是**外部活服务**（`KERT_BASE_URL`，默认 127.0.0.1:8106），
#   而 CI 用 `KERT_PROFILE=dev` 起在同一端口。本机 8106 常被其它实例占用，
#   且 `deploy/docker-compose.yml` 起的是 **prod** profile（强制鉴权）——
#   两点叠加使「CI 能过」与「本仓编排能跑」不是同一条路径。本脚本把这条路径固化。
#
# 做四件事（每步印出，便于取证）：
#   1. 用**覆盖文件**把 api 发布端口从 8106 改到 `--port`（默认 8107），
#      **不改** `deploy/docker-compose.yml` 的服务清单/依赖链/加固项/provision 任务；
#   2. 起栈并等就绪：`/livez`、`/readyz` 均须 200；
#   3. 断言**控制面真的供给成功**：`GET /v1/knowledge-maps` 的 `data.count > 0`
#      （=0 说明 provision 未生效，路由按 fail-closed 全拒绝——此时跑 e2e 是在验证空壳）；
#   4. 跑 `pytest tests/e2e/ -rs`（`E2E_REQUIRE_KERT=1`，KERT 缺失即 fail，禁止降级为 skip），
#      退出码原样透出；撤栈用 `down --remove-orphans`，**绝不 `-v`**（不删卷）。
#
# 用法：
#   bash scripts/run_e2e_local.sh                       # 起栈(8107) → 跑 e2e → 撤栈
#   bash scripts/run_e2e_local.sh --port 8108           # 换端口
#   bash scripts/run_e2e_local.sh --keep-up             # 跑完保留栈（人工排查）
#   bash scripts/run_e2e_local.sh --base-url http://127.0.0.1:8106 --no-stack
#                                                       # 打**已存在**的服务，不起栈也不撤栈
#   bash scripts/run_e2e_local.sh -- --collect-only     # `--` 之后的参数原样传给 pytest
#
# 环境变量：
#   KERT_API_KEY    已设置则直接用它（API Key 的**密钥本身（secret）**，非 `key_id:secret`）；
#                   未设置则从 `deploy/.env` 的 `KERT_API_KEYS` **首个 key 的 secret 段**解析。
#   E2E_LEDGER_PATH 覆盖账本落盘路径（默认落到临时目录并打印）。
#   E2E_REBUILD=1   起栈前 `docker compose build`（镜像层陈旧时用；见下方「已知坑」）。
#
# 已知坑（实测踩过，故脚本自带提示）：
#   镜像 `kert-python-core:local` 若由**陈旧缓存层**产出，`/app/src/kert/cli/main.py`
#   会缺 `--init` ⇒ compose 的 `provision` 任务以 exit 2 失败（`No such option: --init`），
#   表现为「起不来但看不出为什么」。脚本在 up 失败时会自动打印 provision 日志并给出
#   `E2E_REBUILD=1` 的建议。
#
# 非声明：本脚本**不是** QA 通过；跨服务用例（需 GITS :8082 / :5173）在本机不可用时
#   按既定口径 skip 并登记在覆盖账本里，不得当作已验证。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/docker-compose.yml"
ENV_FILE="$PROJECT_ROOT/deploy/.env"

# ---------- 默认参数 ----------
PORT=8107                 # 刻意避开 8106：本机常被其它 KERT 实例占用
KEEP_UP=0
NO_STACK=0
BASE_URL=""
PYTEST_ARGS=()
LEDGER_PATH=""

usage() {
    sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

# ---------- 解析参数 ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)      PORT="$2"; shift 2 ;;
        --keep-up)   KEEP_UP=1; shift ;;
        --no-stack)  NO_STACK=1; shift ;;
        --base-url)  BASE_URL="$2"; shift 2 ;;
        --ledger)    LEDGER_PATH="$2"; shift 2 ;;
        -h|--help)   usage ;;
        --)          shift; PYTEST_ARGS=("$@"); break ;;
        *)           echo "[FAIL] 未知参数: $1（-h 查看用法）" >&2; exit 2 ;;
    esac
done

if [[ -z "$BASE_URL" ]]; then
    BASE_URL="http://127.0.0.1:$PORT"
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kert-e2e-local.XXXXXX")"
if [[ -z "$LEDGER_PATH" ]]; then
    LEDGER_PATH="$TMP_DIR/e2e-coverage-ledger.json"
fi

# ---------- Python 解释器：优先仓内 .venv（CI 装的 extras 在这里） ----------
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

# ---------- API Key：取**密钥本身（secret）**，不是 `key_id:secret` ----------
# 见 deploy/README.md §4：服务端对 presented 做摘要比对，`key_id:secret` 会 401。
resolve_api_key() {
    if [[ -n "${KERT_API_KEY:-}" ]]; then
        return 0
    fi
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "[FAIL] 未找到 $ENV_FILE，请先 cp deploy/.env.example deploy/.env 并配置" >&2
        return 1
    fi
    local line first
    line="$(grep -E '^KERT_API_KEYS=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
    if [[ -z "$line" ]]; then
        echo "[FAIL] $ENV_FILE 中未声明 KERT_API_KEYS" >&2
        return 1
    fi
    first="${line%%,*}"          # 多个 key 用逗号分隔 ⇒ 取第一个
    KERT_API_KEY="${first#*:}"   # 去掉 key_id
    KERT_API_KEY="${KERT_API_KEY%%:*}"  # 去掉 scope 段 ⇒ 只留 secret
    if [[ ${#KERT_API_KEY} -lt 16 ]]; then
        echo "[FAIL] 解析出的 API Key 长度异常（<16），请检查 $ENV_FILE 格式" >&2
        return 1
    fi
    export KERT_API_KEY
}

# ---------- 撤栈：只撤本仓 stack，绝不 -v（不删他人的卷） ----------
cleanup() {
    local rc=$?
    if [[ $NO_STACK -eq 0 && $KEEP_UP -eq 0 ]]; then
        echo ""
        echo "[5/5] 撤栈（down --remove-orphans，不加 -v）…"
        docker compose -f "$COMPOSE_FILE" -f "$TMP_DIR/override.yml" \
            --env-file "$ENV_FILE" down --remove-orphans || true
        echo "  残留 kert 容器：$(docker ps -a --filter 'name=^kert-' --format '{{.Names}}' | tr '\n' ' ')"
    elif [[ $KEEP_UP -eq 1 ]]; then
        echo ""
        echo "[5/5] --keep-up：保留栈，未撤（base=$BASE_URL）"
    else
        echo ""
        echo "[5/5] --no-stack：不起栈也不撤栈"
    fi
    rm -rf "$TMP_DIR"
    exit $rc
}
trap cleanup EXIT

echo "=========================================="
echo "KERT e2e 本地打通（本仓编排）"
echo "=========================================="
echo "  项目根     : $PROJECT_ROOT"
echo "  compose    : $COMPOSE_FILE（语义不改，端口用覆盖文件）"
echo "  KERT_BASE_URL : $BASE_URL"
echo "  解释器     : $PYTHON"
echo ""

resolve_api_key

# ---------- 1. 起栈 ----------
if [[ $NO_STACK -eq 0 ]]; then
    echo "[1/5] 起栈（本仓编排 + 端口覆盖 $PORT -> 8106）…"
    # TCP 层判占用（不看 HTTP 状态码）：端口上只要有人监听就拒绝，避免踩他人实例
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
        exec 3<&- 2>/dev/null || true
        echo "[FAIL] 127.0.0.1:$PORT 已被占用，拒绝复用外部实例（换 --port）" >&2
        exit 1
    fi
    cat > "$TMP_DIR/override.yml" <<YAML
services:
  api:
    ports: !override
      - "127.0.0.1:$PORT:8106"
YAML
    if [[ "${E2E_REBUILD:-0}" == "1" ]]; then
        docker compose -f "$COMPOSE_FILE" -f "$TMP_DIR/override.yml" \
            --env-file "$ENV_FILE" build
    fi
    if ! docker compose -f "$COMPOSE_FILE" -f "$TMP_DIR/override.yml" \
            --env-file "$ENV_FILE" up -d; then
        echo "[FAIL] 起栈失败；以下是 provision（控制面供给）日志：" >&2
        docker compose -f "$COMPOSE_FILE" -f "$TMP_DIR/override.yml" \
            --env-file "$ENV_FILE" logs provision >&2 || true
        echo "" >&2
        echo "  ↑ 若见 'No such option: --init'，说明镜像层陈旧（缺 CLI 的 --init）。" >&2
        echo "    重跑：E2E_REBUILD=1 bash scripts/run_e2e_local.sh" >&2
        exit 1
    fi
else
    echo "[1/5] --no-stack：跳过起栈，直接打 $BASE_URL"
fi

# ---------- 2. 等就绪 ----------
echo ""
echo "[2/5] 等就绪（/livez、/readyz 须 200）…"
for i in $(seq 1 60); do
    livez="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$BASE_URL/livez" || true)"
    if [[ "$livez" == "200" ]]; then
        echo "  /livez  = 200（第 ${i} 秒）"
        break
    fi
    if [[ $i -eq 60 ]]; then
        echo "[FAIL] /livez 未在 60 秒内返回 200（最后 HTTP=$livez）" >&2
        exit 1
    fi
    sleep 1
done
readyz_code="$(curl -s -o "$TMP_DIR/readyz.json" -w '%{http_code}' --max-time 10 "$BASE_URL/readyz" || true)"
echo "  /readyz = $readyz_code"
echo "  /readyz body: $(cat "$TMP_DIR/readyz.json" 2>/dev/null || echo '(无)')"
if [[ "$readyz_code" != "200" ]]; then
    echo "[FAIL] /readyz 非 200 ⇒ 未就绪，拒绝继续（勿以 skip 掩盖）" >&2
    exit 1
fi

# ---------- 3. 控制面供给判据 ----------
echo ""
echo "[3/5] 控制面供给判据 GET /v1/knowledge-maps（须 count > 0）…"
km_code="$(curl -s -o "$TMP_DIR/km.json" -w '%{http_code}' --max-time 10 \
    -H "X-API-Key: $KERT_API_KEY" "$BASE_URL/v1/knowledge-maps" || true)"
echo "  HTTP = $km_code"
if [[ "$km_code" != "200" ]]; then
    echo "[FAIL] /v1/knowledge-maps 非 200（401 ⇒ API Key 口径错；值须是 secret 本身）" >&2
    exit 1
fi
"$PYTHON" - "$TMP_DIR/km.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
count = d.get("data", {}).get("count")
print("  data.count =", count)
if not isinstance(count, int) or count <= 0:
    print("[FAIL] 控制面 count = %r（须 > 0）——provision 未生效，路由将 fail-closed 全拒绝" % count,
          file=sys.stderr)
    sys.exit(1)
PY

# ---------- 4. 跑 e2e ----------
echo ""
echo "[4/5] pytest tests/e2e/ -rs（E2E_REQUIRE_KERT=1）…"
set +e
KERT_BASE_URL="$BASE_URL" \
E2E_REQUIRE_KERT=1 \
KERT_API_KEY="$KERT_API_KEY" \
E2E_LEDGER_PATH="$LEDGER_PATH" \
"$PYTHON" -m pytest tests/e2e/ -rs "${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}"
PYTEST_RC=$?
set -e
echo ""
echo "  PYTEST_EXIT_CODE=$PYTEST_RC"
echo "  覆盖账本：$LEDGER_PATH"
exit $PYTEST_RC
