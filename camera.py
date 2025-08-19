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
        picam = self.Picamera2()
        # stream principal RGB888 no tamanho desejado (sem preview)
        config = picam.create_still_configuration(
            main={"size": self.size, "format": "RGB888"},
            transform=self.Transform(hflip=0, vflip=0),
            buffer_count=2
        )
        picam.configure(config)
        picam.start()
        self.picam = picam

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
    def __init__(self, device: int=0, size: Tuple[int, int]=(640, 480)):
        self.device = device
        self.size = size
        self.cap = None

    def start(self):
        import cv2
        self.cv2 = cv2
        cap = cv2.VideoCapture(self.device)
        cap.set(self.cv2.CAP_PROP_FRAME_WIDTH,  self.size[0])
        cap.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        if not cap.isOpened():
            raise RuntimeError("Não foi possível abrir a câmera via OpenCV.")
        self.cap = cap

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

def make_camera(backend: str, size=(640,480), device: Optional[int]=None) -> CameraBase:
    backend = backend.lower()
    if backend == "picamera2":
        return Picamera2Camera(size=size)
    elif backend == "opencv":
        return OpenCVCamera(device if device is not None else 0, size=size)
    else:
        raise ValueError(f"Backend desconhecido: {backend}. Use 'picamera2' ou 'opencv'.")
