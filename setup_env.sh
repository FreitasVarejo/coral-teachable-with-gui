#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="coral-3.9"
PY_VERSION="3.9.18"

echo "==> [1/7] Atualizando índices APT…"
sudo apt update

echo "==> [2/7] Instalando pacotes de sistema base…"
BASE_PKGS=(
  build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev
  wget curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libffi-dev
  liblzma-dev python3-openssl git
  gstreamer1.0-tools python3-gi
  libatlas-base-dev
  # Câmera do Pi (opcional; se quiser rodar com Python do sistema e backend picamera2)
  python3-libcamera python3-picamera2
  v4l2loopback-dkms v4l2loopback-utils
  gstreamer1.0-libcamera gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
  gstreamer1.0-plugins-ugly gstreamer1.0-tools
)
sudo apt install -y "${BASE_PKGS[@]}"

echo "==> [3/7] Garantindo repositório Coral e libedgetpu1-std…"
if ! apt-cache policy libedgetpu1-std | grep -q Candidate; then
  sudo mkdir -p /usr/share/keyrings
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | sudo gpg --dearmor -o /usr/share/keyrings/coral-edgetpu.gpg
  echo "deb [signed-by=/usr/share/keyrings/coral-edgetpu.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main" \
    | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list >/dev/null
  sudo apt update
fi
sudo apt install -y libedgetpu1-std || {
  echo "[WARN] Não foi possível instalar libedgetpu1-std. Verifique conectividade e rode 'sudo apt update' novamente."
}

# Recarrega udev (regras da TPU)
sudo udevadm control --reload-rules || true
sudo udevadm trigger || true

echo "==> [4/7] Checando/instalando pyenv…"
if ! command -v pyenv >/dev/null 2>&1; then
  curl -fsSL https://pyenv.run | bash
fi

# Garante pyenv no PATH deste shell
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"

echo "==> [5/7] Python $PY_VERSION no pyenv e venv $ENV_NAME…"
# instala python se faltar
pyenv install -s "$PY_VERSION"

# checa se o venv existe SEM pipeline com '!'
if pyenv virtualenvs --bare | awk -v v="$ENV_NAME" '$0==v{found=1} END{exit !found}'; then
  echo "Virtualenv $ENV_NAME já existe; pulando criação."
else
  pyenv virtualenv "$PY_VERSION" "$ENV_NAME"
fi

cd "$PROJECT_DIR"
# grava .python-version; a auto-ativação do pyenv-virtualenv pode mudar seu prompt,
# mas não deve interromper o script
pyenv local "$ENV_NAME"

echo "==> [6/7] Instalando dependências (pip) no venv…"
pip install --upgrade pip wheel setuptools

PIP_MAIN_INDEX="https://pypi.org/simple"
PIP_CORAL_INDEX="https://google-coral.github.io/py-repo/"

if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
  pip install -i "$PIP_MAIN_INDEX" --extra-index-url "$PIP_CORAL_INDEX" -r requirements.txt
else
  pip install -i "$PIP_MAIN_INDEX" numpy==1.26.4 Pillow==10.4.0 opencv-python-headless==4.10.0.84 RPi.GPIO==0.7.1
  pip install -i "$PIP_MAIN_INDEX" --extra-index-url "$PIP_CORAL_INDEX" pycoral==2.0.0
fi


# Fallback: se ainda assim o pycoral não estiver importável, instala o wheel direto do GitHub
python - <<'PY'
import sys
try:
    import pycoral  # noqa
    print("[CHECK] pycoral importado ok.")
except Exception as e:
    print("[WARN] pycoral não importou a partir dos índices. Tentando instalar o wheel direto…", e)
    import os, subprocess
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    arch = os.uname().machine
    if arch == "aarch64":
        wheel_arch = "linux_aarch64"
    else:
        wheel_arch = arch
    url = f"https://github.com/google-coral/pycoral/releases/download/v2.0.0/pycoral-2.0.0-{tag}-{tag}-{wheel_arch}.whl"
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-i", "https://pypi.org/simple", url])
    import pycoral  # tenta de novo
    print("[CHECK] pycoral instalado via wheel direto.")
PY

echo "==> [7/7] Auto-check do Edge TPU no venv…"
python - <<'PY'
try:
    from pycoral.utils.edgetpu import get_runtime_version, list_edge_tpus
    print("[CHECK] PyCoral Runtime:", get_runtime_version())
    tpus = list_edge_tpus()
    print("[CHECK] Edge TPUs detectados:", tpus)
    if not tpus:
        print("[WARN] Nenhum Edge TPU detectado. Conecte a USB TPU ou verifique cabos/energia.")
except Exception as e:
    print("[ERROR] Falha usando pycoral no venv:", e)
PY

echo "==> [8/9] Criando script feeder de câmera virtual…"
mkdir -p scripts
cat > scripts/start_feeder.sh <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
# Cria loopback /dev/video30 se não existir
sudo modprobe -r v4l2loopback || true
sudo modprobe v4l2loopback devices=1 video_nr=30 card_label="rpicam" exclusive_caps=0 max_buffers=64

# Injeta frames da câmera real no /dev/video30
gst-launch-1.0 libcamerasrc ! \
  video/x-raw,width=1280,height=720,framerate=30/1,format=NV12 ! \
  videoconvert ! video/x-raw,format=BGRx ! \
  v4l2sink device=/dev/video30 sync=false io-mode=mmap
EOS
chmod +x scripts/start_feeder.sh

echo
echo "------------------------------------------------------------"
echo "✅ Ambiente pronto!"
echo "Pasta: $PROJECT_DIR"
echo "Venv:  $ENV_NAME"
echo
echo "Para rodar:"
echo "  1) Em um terminal: ./scripts/start_feeder.sh"
echo "  2) Em outro terminal (com venv ativo):"
echo "     python teachable.py --backend opencv --device 30 --keyboard --model models/mobilenet_v1_1.0_224_quant_embedding_extractor_edgetpu.tflite"
echo
echo "Se preferir usar Picamera2 (sem feeder):"
echo "     python3 teachable.py --backend picamera2 --model models/mobilenet_v1_1.0_224_quant_embedding_extractor_edgetpu.tflite"
echo "------------------------------------------------------------"
