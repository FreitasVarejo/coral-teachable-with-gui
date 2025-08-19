#!/usr/bin/env bash
# Report health of the rpicam -> v4l2loopback pipeline
set -euo pipefail

DEV_NR="${DEV_NR:-10}"
LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/rpicam-loopback"
PID_FILE="$LOG_DIR/pid"

ok=true

echo "=== rpicam-loopback status ==="

# Módulo
if lsmod | grep -q '^v4l2loopback'; then
  echo "✅ Módulo v4l2loopback carregado"
else
  echo "❌ v4l2loopback NÃO carregado"
  ok=false
fi

# Device
if [[ -e "/dev/video$DEV_NR" ]]; then
  echo "✅ Device /dev/video$DEV_NR existe"
else
  echo "❌ /dev/video$DEV_NR não existe"
  ok=false
fi

# Processo
if [[ -f "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" &>/dev/null; then
  echo "✅ Runner ativo (PID $(cat "$PID_FILE"))"
else
  # Tenta detectar pelos comandos
  if pgrep -f 'rpicam-vid -t 0 --codec yuv420' >/dev/null && pgrep -f "ffmpeg .* /dev/video${DEV_NR}" >/dev/null; then
    echo "✅ Pipeline ativo (detectado por assinatura de processos)"
  else
    echo "❌ Pipeline NÃO está rodando"
    ok=false
  fi
fi

# Formato / consulta V4L2
if command -v v4l2-ctl >/dev/null && [[ -e "/dev/video$DEV_NR" ]]; then
  if v4l2-ctl -D -d "/dev/video$DEV_NR" >/dev/null 2>&1; then
    echo "✅ v4l2-ctl responde"
    v4l2-ctl --get-fmt-video -d "/dev/video$DEV_NR" || true
  else
    echo "⚠️  v4l2-ctl não conseguiu consultar /dev/video$DEV_NR"
    ok=false
  fi
fi

$ok && exit 0 || exit 1

