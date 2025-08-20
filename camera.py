# camera.py
# Captura de frames de forma simples e robusta (Picamera2 ou OpenCV).
from typing import Iterator, Optional, Tuple
from PIL import Image

class CameraBase:
    def start(self): ...
    def stop(self): ...
    def frames(self) -> Iterator[Image.Image]:
        raise NotImplementedError

class Picamera2Camera(CameraBase):
    def __init__(self, size: Tuple[int, int]=(640, 480)):
        from picamera2 import Picamera2
        from libcamera import Transform  # fornecido pelo pacote picamera2
        self.Picamera2 = Picamera2
        self.Transform = Transform
        self.size = size
        self.picam = None

    def start(self):
        import cv2, time, os
        self.cv2 = cv2

        # Só aceitamos V4L2: inteiro (índice) ou caminho /dev/videoN
        is_v4l2_path = isinstance(self.device, str) and self.device.startswith("/dev/video")
        is_index = isinstance(self.device, int)

        if not (is_index or is_v4l2_path):
            raise ValueError(
                "Fonte de câmera inválida para OpenCV. Use um índice V4L2 (ex.: 30) "
                "ou um caminho /dev/videoN (ex.: /dev/video30). "
                "Pipelines GStreamer não são suportadas aqui."
            )

        # Tenta abrir explicitamente com CAP_V4L2 e depois sem flag
        candidates = []
        if is_index:
            candidates += [(self.device, cv2.CAP_V4L2), (self.device, 0)]
        else:
            # caminho /dev/videoN deve existir
            if not os.path.exists(self.device):
                raise FileNotFoundError(f"Dispositivo não encontrado: {self.device}")
            candidates += [(self.device, cv2.CAP_V4L2), (self.device, 0)]

        self.cap = None
        for dev, api in candidates:
            cap = cv2.VideoCapture(dev, api)
            if cap and cap.isOpened():
                self.cap = cap
                break
            time.sleep(0.05)

        if not self.cap or not self.cap.isOpened():
            hint = []
            if is_v4l2_path and not os.access(self.device, os.R_OK):
                hint.append("permissão: adicione seu usuário ao grupo 'video' (usermod -aG video $USER)")
            hint.append("verifique se o feeder (libcamerasrc -> v4l2sink) está rodando")
            hint.append("confira: v4l2-ctl --all -d /dev/video30 (deve ter Video Capture/Output)")
            raise RuntimeError(
                f"Não foi possível abrir a câmera ({self.device}). Dicas: " + "; ".join(hint)
            )

        # Ajusta tamanho desejado (best-effort)
        self.cap.set(self.cv2.CAP_PROP_FRAME_WIDTH,  self.size[0])
        self.cap.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])

    def stop(self):
        if self.picam:
            self.picam.stop()
            self.picam.close()
            self.picam = None

    def frames(self) -> Iterator[Image.Image]:
        from PIL import Image
        while True:
            arr = self.picam.capture_array("main")  # HxWx3 em RGB
            yield Image.fromarray(arr, mode="RGB")

class OpenCVCamera(CameraBase):
    def __init__(self, device=0, size: Tuple[int, int]=(640, 480)):
        self.device = device  # pode ser int (v4l2) ou str (pipeline GStreamer)
        self.size = size
        self.cap = None

    def start(self):
        import cv2, time
        self.cv2 = cv2

        def try_open(dev, api=None):
            cap = cv2.VideoCapture(dev) if api is None else cv2.VideoCapture(dev, api)
            return cap if (cap and cap.isOpened()) else None

        # Se vier string "/dev/videoN", tratar como V4L2
        is_v4l2_path = isinstance(self.device, str) and self.device.startswith("/dev/video")

        candidates = []
        if isinstance(self.device, int):
            candidates += [(self.device, cv2.CAP_V4L2), (self.device, None)]
        elif is_v4l2_path:
            candidates += [(self.device, cv2.CAP_V4L2), (self.device, None)]
        else:
            # string que é pipeline GStreamer
            candidates += [(self.device, cv2.CAP_GSTREAMER), (self.device, None)]

        self.cap = None
        for dev, api in candidates:
            self.cap = try_open(dev, api)
            if self.cap:
                break
            time.sleep(0.05)

        if not self.cap or not self.cap.isOpened():
            raise RuntimeError(f"Não foi possível abrir a câmera ({self.device}).")

        # se for v4l2, ajusta tamanho desejado
        if isinstance(self.device, int) or is_v4l2_path:
            self.cap.set(self.cv2.CAP_PROP_FRAME_WIDTH,  self.size[0])
            self.cap.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])

    def stop(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def frames(self) -> Iterator[Image.Image]:
        from PIL import Image
        while True:
            ok, frame = self.cap.read()
            if not ok:
                continue
            rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
            yield Image.fromarray(rgb, mode="RGB")


def make_camera(backend: str, size=(640,480), device=None) -> CameraBase:
    backend = backend.lower()
    if backend == "picamera2":
        return Picamera2Camera(size=size)
    elif backend == "opencv":
        return OpenCVCamera(device if device is not None else 0, size=size)
    else:
        raise ValueError(f"Backend desconhecido: {backend}. Use 'picamera2' ou 'opencv'.")
