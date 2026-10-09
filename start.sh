#!/usr/bin/env bash
# 一键启动数字人控制台。macOS / Linux / Windows(Git Bash) 通用。
#
#   bash start.sh              # 启动（缺什么自动装什么）
#   bash start.sh --check      # 只做体检，不启动
#   bash start.sh --stop       # 停掉后台实例
#   bash start.sh --reset      # 删掉虚拟环境重装（依赖装坏了时用）
#
# 设计目标：不懂技术的人也能一次跑通。全程不需要手工敲 pip / venv / 多步脚本。

set -uo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
VENV="$ROOT/.venv"
PORT="${APP_PORT:-8100}"
HOST="${APP_HOST:-127.0.0.1}"
LOG="$ROOT/data/start.log"
PIDFILE="$ROOT/data/start.pid"
MODE="run"

for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --stop)  MODE="stop" ;;
    --reset) MODE="reset" ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

# ---------- 输出helpers ----------
if [ -t 1 ]; then C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_INF=$'\033[36m'; C_DIM=$'\033[2m'; C_END=$'\033[0m'
else C_OK=""; C_WARN=""; C_ERR=""; C_INF=""; C_DIM=""; C_END=""; fi
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s  ✔%s %s\n' "$C_OK" "$C_END" "$*"; }
warn() { printf '%s  !%s %s\n' "$C_WARN" "$C_END" "$*"; }
die()  { printf '%s  ✘%s %s\n' "$C_ERR" "$C_END" "$*" >&2; exit 1; }
step() { printf '\n%s▸ %s%s\n' "$C_INF" "$*" "$C_END"; }
note() { printf '%s    %s%s\n' "$C_DIM" "$*" "$C_END"; }

# ---------- stop ----------
stop_server() {
  if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
      kill "$PID" 2>/dev/null || true
      sleep 1
      kill -9 "$PID" 2>/dev/null || true
      ok "已停止（进程 $PID）"
    fi
    rm -f "$PIDFILE"
  else
    # 没有 pid 文件时兜底：按端口杀
    if command -v lsof >/dev/null 2>&1; then
      PIDS="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
      if [ -n "$PIDS" ]; then kill -9 $PIDS 2>/dev/null || true; ok "已停止占用 $PORT 的进程"; fi
    fi
  fi
}

case "$MODE" in
  stop) stop_server; exit 0 ;;
  reset) stop_server; rm -rf "$VENV"; say "已删除虚拟环境，下次启动会重装"; exit 0 ;;
esac

# ---------- 前置检查 ----------
step "检查运行环境"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    V="$("$c" -c 'import sys;print(1 if sys.version_info>=(3,9) else 0)' 2>/dev/null)"
    [ "$V" = "1" ] && { PY="$c"; break; }
  fi
done
[ -n "$PY" ] || die "没找到 Python 3.9 或更新的版本。请到 https://www.python.org/downloads/ 下载安装后再运行本脚本。"
ok "Python：$($PY -V 2>&1)"

if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg：已安装（用来合成画面和推流）"
elif command -v brew >/dev/null 2>&1; then
  note "没装 ffmpeg，正在用 Homebrew 安装（可能要几分钟）…"
  brew install ffmpeg >/dev/null 2>&1
  command -v ffmpeg >/dev/null 2>&1 && ok "ffmpeg：装好了" || warn "ffmpeg 没装上，合成画面会失败。装法见 README"
else
  warn "没装 ffmpeg，合成画面会失败。Mac: brew install ffmpeg ｜ Windows: winget install ffmpeg ｜ Linux: sudo apt install ffmpeg"
fi

# ---------- 虚拟环境 + 依赖 ----------
step "准备运行环境（第一次会慢一点，之后秒开）"

if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV" 2>/dev/null || die "创建虚拟环境失败。Debian/Ubuntu 上可能要先装 python3-venv：sudo apt install python3-venv"
  ok "已创建运行环境 .venv"
fi
VPY="$VENV/bin/python"
[ -x "$VPY" ] || VPY="$VENV/Scripts/python.exe"   # Windows Git Bash

STAMP="$VENV/.deps-ok"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  # 依次尝试多个源。pip 的重试日志会吓人，所以全部吞掉，
  # 只有**全都失败**才把最后一个源的报错原样打出来。
  SOURCES=""
  [ -n "${PIP_INDEX_URL:-}" ] && SOURCES="$PIP_INDEX_URL"
  SOURCES="$SOURCES https://pypi.tuna.tsinghua.edu.cn/simple
https://mirrors.aliyun.com/pypi/simple/
https://pypi.org/simple"

  INSTALLED=0
  LASTLOG=""
  n=0
  for SRC in $SOURCES; do
    n=$((n + 1))
    note "正在从 $SRC 安装依赖（第 $n 次尝试，第一次会慢一点）…"
    if "$VPY" -m pip install -q --disable-pip-version-check --no-input \
         --timeout 30 --retries 2 -i "$SRC" -r requirements.txt >"$ROOT/.pipinstall.log" 2>&1; then
      INSTALLED=1
      break
    fi
    LASTLOG="$SRC"
  done

  if [ "$INSTALLED" != "1" ]; then
    say ""
    warn "依赖没能装好。最后一次的报错如下："
    tail -n 12 "$ROOT/.pipinstall.log" 2>/dev/null | sed 's/^/    /'
    say ""
    say "  ${C_DIM}多半是网络问题。可以试试：${C_END}"
    say "  ${C_DIM}· 换个网络（手机热点常常能通）${C_END}"
    say "  ${C_DIM}· 或手动换源执行：${C_END}"
    say "      ${C_INF}$VPY -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt${C_END}"
    rm -f "$ROOT/.pipinstall.log"
    exit 1
  fi
  rm -f "$ROOT/.pipinstall.log"
  touch "$STAMP"
  ok "依赖装好了"
else
  ok "依赖已就绪"
fi

# ---------- 配置文件 ----------
[ -f .env ] || { cp -n .env.example .env 2>/dev/null || true; ok "已生成 .env（没填 Key 也能先跑）"; }

# ---------- 素材 ----------
if [ ! -f data/avatars/demo/actions/idle.mp4 ]; then
  step "准备演示素材"
  "$VPY" scripts/make_placeholder_actions.py >/dev/null 2>&1 \
    && ok "已生成演示动作视频（换自己的照片请看 README）" \
    || warn "演示素材生成失败，开播时可能提示缺 idle 视频"
fi

# ---------- 体检 ----------
step "体检"
# 只把「需要你处理的问题」讲出来，技术细节（Python 路径、包名）不打扰用户
CHECKLOG="$(mktemp)"
"$VPY" scripts/00_check_env.py >"$CHECKLOG" 2>&1 || true
PROBLEMS="$(sed -n 's/^  \[!!\].*/&/p' "$CHECKLOG" | sed 's/^  \[!!\]/  ·/')"
if [ -n "$PROBLEMS" ]; then
  warn "有几项还没就绪，不影响先试用："
  printf '%s\n' "$PROBLEMS" | head -6 | sed 's/^/    /'
else
  ok "环境都齐了"
fi
rm -f "$CHECKLOG"
[ "$MODE" = "check" ] && { say ""; ok "体检结束。去掉 --check 就能启动。"; exit 0; }

# ---------- 启动 ----------
stop_server
mkdir -p "$(dirname "$LOG")"
say ""
say "  ${C_INF}数字人控制台正在启动…${C_END}"
say "  ${C_DIM}首次启动要几秒，之后会快很多${C_END}"
say ""

( cd "$ROOT" && APP_HOST="$HOST" APP_PORT="$PORT" exec "$VPY" scripts/07_run_api.py --host "$HOST" --port "$PORT" ) > "$LOG" 2>&1 &
SRV=$!
echo "$SRV" > "$PIDFILE"

# 等服务起来
READY=0
for _ in $(seq 1 40); do
  sleep 1
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null "http://$HOST:$PORT/" 2>/dev/null && { READY=1; break; }
  elif "$VPY" -c "import socket,sys;s=socket.socket();s.settimeout(1);sys.exit(0 if s.connect_ex(('$HOST',$PORT))==0 else 1)" 2>/dev/null; then
    READY=1; break
  fi
  kill -0 "$SRV" 2>/dev/null || break
done

if [ "$READY" != "1" ]; then
  say ""
  say "启动没成功。最后几行日志："
  tail -n 15 "$LOG" 2>/dev/null | sed 's/^/    /'
  say ""
  say "  可以试试： ${C_INF}bash start.sh --reset${C_END}  （依赖装坏了就重来一遍）"
  exit 1
fi

URL="http://$HOST:$PORT"
say "  ${C_OK}${C_END}  ${C_OK}搞定了${C_END}"
say ""
say "  ${C_INF}浏览器打开这个地址：${C_END}"
say "      ${C_OK}${C_BOLD:-}$URL${C_END}"
say ""
say "  ${C_DIM}关掉这个窗口就会停止服务；后台运行请用 Ctrl+C 或 bash start.sh --stop${C_END}"
say ""
say "  ${C_DIM}第一次用？${C_END}"
say "  ${C_DIM}1. 直接点「开始直播」，选「仅预览」${C_END}"
say "  ${C_DIM}2. 在下面聊天框发一句话，看数字人回${C_END}"
say "  ${C_DIM}3. 宣讲带货（分屏+知识库）：房间选 promo${C_END}"
say ""

# 自动开浏览器（macOS / Linux 有 GUI 时）
if command -v open >/dev/null 2>&1 && [ -z "${CI:-}" ]; then open "$URL" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ] && [ -z "${CI:-}" ]; then xdg-open "$URL" >/dev/null 2>&1 &
fi

wait "$SRV"