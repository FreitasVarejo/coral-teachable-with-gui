#!/usr/bin/env bash
# Start rpicam -> v4l2loopback feed as a background process
set -euo pipefail

# Config padrão (pode sobrescrever via env: DEV_NR=12 WIDTH=1280 HEIGHT=720 FPS=30 ./camera_feed_start.sh)
DEV_NR="${DEV_NR:-10}"
WIDTH="${WIDTH:-640}"
HEIGHT="${HEIGHT:-480}"
FPS="${FPS:-30}"

LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/rpicam-loopback"
PID_FILE="$LOG_DIR/pid"
LOG_FILE="$LOG_DIR/log.txt"
RUNNER="$LOG_DIR/runner.sh"

mkdir -p "$LOG_DIR"

# Se já estiver rodando, não sobe de novo
if [[ -f "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" &>/dev/null; then
  echo "⚠️  Já está em execução (PID $(cat "$PID_FILE"))."
  echo "Use ./camera_feed_status.sh para checar ou ./camera_feed_stop.sh para parar."
  exit 0
fi
rm -f "$PID_FILE"

# Checagens rápidas de comandos
for cmd in rpicam-vid ffmpeg v4l2-ctl modprobe; do
  command -v "$cmd" >/dev/null || { echo "Erro: comando '$cmd' não encontrado."; exit 1; }
done

# Carrega módulo v4l2loopback (cria /dev/video$DEV_NR)
if ! lsmod | grep -q '^v4l2loopback'; then
  echo "🔧 Carregando v4l2loopback…"
  sudo modprobe v4l2loopback video_nr="$DEV_NR" card_label="rpicam" exclusive_caps=1 max_buffers=2
else
  # Garante que o device existe com o número desejado
  if [[ ! -e "/dev/video$DEV_NR" ]]; then
    echo "🔧 v4l2loopback já carregado; adicionando device $DEV_NR…"
    sudo modprobe -r v4l2loopback || true
    sudo modprobe v4l2loopback video_nr="$DEV_NR" card_label="rpicam" exclusive_caps=1 max_buffers=2
  fi
fi

# Aguarda device aparecer
for i in {1..25}; do
  [[ -e "/dev/video$DEV_NR" ]] && break
  sleep 0.2
done
[[ -e "/dev/video$DEV_NR" ]] || { echo "❌ /dev/video$DEV_NR não apareceu."; exit 1; }

# Cria runner com trap para derrubar filhos ao sair
cat > "$RUNNER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
trap 'pkill -P $$ || true' EXIT
rpicam-vid -t 0 --codec yuv420 --width "${WIDTH}" --height "${HEIGHT}" --framerate "${FPS}" -o - \
| ffmpeg -hide_banner -loglevel error -re \
    -f rawvideo -pix_fmt yuv420p -s "${WIDTH}x${HEIGHT}" -r "${FPS}" -i - \
    -f v4l2 -vcodec rawvideo -pix_fmt yuv420p -s "${WIDTH}x${HEIGHT}" -r "${FPS}" "/dev/video${DEV_NR}"
EOF
chmod +x "$RUNNER"

# Inicia em background com env e log próprios
echo "🚀 Iniciando feed em segundo plano -> /dev/video$DEV_NR (${WIDTH}x${HEIGHT}@${FPS})"
( cd "$LOG_DIR" && nohup env DEV_NR="$DEV_NR" WIDTH="$WIDTH" HEIGHT="$HEIGHT" FPS="$FPS" "$RUNNER" >>"$LOG_FILE" 2>&1 & echo $! >"$PID_FILE" )

# Valida rápido
sleep 1
if ps -p "$(cat "$PID_FILE")" &>/dev/null; then
  echo "✅ Rodando. PID $(cat "$PID_FILE"). Log: $LOG_FILE"
  exit 0
else
  echo "❌ Falha ao iniciar. Veja logs em $LOG_FILE"
  exit 1
fi
