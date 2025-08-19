#!/usr/bin/env bash
# Stop rpicam -> v4l2loopback feed; optional --unload to remove module
set -euo pipefail

DEV_NR="${DEV_NR:-10}"
LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/rpicam-loopback"
PID_FILE="$LOG_DIR/pid"
UNLOAD="${1:-}"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if ps -p "$PID" &>/dev/null; then
    echo "🛑 Encerrando feed (PID $PID)…"
    kill "$PID" || true
    # Aguarda até cair
    for _ in {1..30}; do
      ps -p "$PID" &>/dev/null || break
      sleep 0.2
    done
    ps -p "$PID" &>/dev/null && { echo "⚠️  Forçando encerramento…"; kill -9 "$PID" || true; }
  else
    echo "ℹ️  PID no arquivo, mas processo não está vivo."
  fi
  rm -f "$PID_FILE"
else
  echo "ℹ️  Nenhum pidfile encontrado; tentando parar por assinatura de comando…"
  pkill -f 'rpicam-vid -t 0 --codec yuv420' || true
  pkill -f "ffmpeg .* /dev/video${DEV_NR}" || true
fi

echo "✅ Pipeline parado."

if [[ "$UNLOAD" == "--unload" ]]; then
  echo "🔧 Removendo módulo v4l2loopback…"
  if lsmod | grep -q '^v4l2loopback'; then
    sudo modprobe -r v4l2loopback || { echo "⚠️  Não foi possível remover (em uso?)."; exit 0; }
    echo "✅ v4l2loopback removido."
  else
    echo "ℹ️  v4l2loopback já não estava carregado."
  fi
fi
