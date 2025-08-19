#!/usr/bin/env python
# teachable.py — versão 2025 (PyCoral + captura robusta)
import argparse, os, sys, time
from collections import deque, Counter

from PIL import Image
from embedding import KNNEmbeddingEngine
from imprinting import DemoImprintingEngine
from camera import make_camera

# ---------- GPIO (Raspberry) ----------
try:
    import RPi.GPIO as _GPIO
except Exception:
    _GPIO = None

class UI_Raspberry:
    def __init__(self, active_low=False):
        if _GPIO is None:
            raise RuntimeError("RPi.GPIO não disponível. Instale RPi.GPIO==0.7.1 e/ou entre no grupo 'gpio'.")
        self._active_low = active_low
        self._buttons = [16, 6, 5, 24, 27]   # [clear, 1, 2, 3, 4] — BCM
        self._leds    = [20, 13, 12, 25, 22] # LEDs 0..4 — BCM
        self._debounce = 0.10
        self._last = [0.0]*len(self._buttons)

        _GPIO.setmode(_GPIO.BCM)
        for b in self._buttons:
            _GPIO.setup(b, _GPIO.IN, pull_up_down=_GPIO.PUD_DOWN)
        for l in self._leds:
            _GPIO.setup(l, _GPIO.OUT)
            _GPIO.output(l, _GPIO.LOW if not self._active_low else _GPIO.HIGH)  # apaga tudo

    def _setLED(self, idx, on):
        if idx is None:  # apaga todos
            for i in range(len(self._leds)):
                self._setLED(i, False)
            return
        level = (_GPIO.LOW if self._active_low else _GPIO.HIGH) if on else (_GPIO.HIGH if self._active_low else _GPIO.LOW)
        _GPIO.output(self._leds[idx], level)

    def setOnlyLED(self, idx):
        for i in range(len(self._leds)):
            self._setLED(i, i == idx if idx is not None else False)

    def getDebouncedButtonState(self):
        now = time.time()
        raw = [(_GPIO.input(b) == _GPIO.HIGH) for b in self._buttons]
        state = []
        for i, pressed in enumerate(raw):
            if pressed and (now - self._last[i]) > self._debounce:
                state.append(True); self._last[i] = now
            else:
                state.append(False)
        return state

    def wiggleLEDs(self, reps=2):
        for _ in range(reps):
            for i in range(len(self._leds)):
                self._setLED(i, True); time.sleep(0.05)
                self._setLED(i, False)

    def cleanup(self):
        try:
            for i in range(len(self._leds)): self._setLED(i, False)
            _GPIO.cleanup()
        except Exception:
            pass

# ---------- UI (teclado) mantida ----------
import sys as _sys, termios, tty, threading, queue, signal, atexit
_old = termios.tcgetattr(_sys.stdin); tty.setcbreak(_sys.stdin.fileno())
def _reset(): termios.tcsetattr(_sys.stdin, termios.TCSADRAIN, _old)
atexit.register(_reset)
def _sig(sig, frame): sys.exit(1)
signal.signal(signal.SIGINT, _sig)
_q = queue.Queue()
def _mon():
    while True:
        ch = _sys.stdin.read(1)
        if ch: _q.put(ch)
t = threading.Thread(target=_mon, daemon=True); t.start()

class UI_Keyboard:
    def __init__(self):
        # Botões: [clear, 1, 2, 3, 4]
        self._buttons = ['q', '1', '2', '3', '4']
        self._debounce = 0.10
        self._last = {b: 0.0 for b in self._buttons}

    def getDebouncedButtonState(self):
        now = time.time()
        pressed = set()
        while not _q.empty():
            pressed.add(_q.get())
        state = []
        for b in self._buttons:
            if b in pressed and (now - self._last[b]) > self._debounce:
                state.append(True); self._last[b] = now
            else:
                state.append(False)
        return state

    def setOnlyLED(self, idx): pass  # sem LEDs físicos nesta variante
    def wiggleLEDs(self, reps=2): pass

# ---------- Núcleo ----------
class TeachableBase:
    def __init__(self, ui):
        self.ui = ui
        self._frame_times = deque(maxlen=40)

    def _visual(self, classification, example_count):
        self._frame_times.append(time.time())
        fps = len(self._frame_times)/max(0.001, (self._frame_times[-1]-self._frame_times[0]))
        classes = ['--', 'One', 'Two', 'Three', 'Four']
        status = f"fps {fps:.1f}; #examples: {example_count}; Class {classes[classification or 0]:>5}"
        print(status)

class TeachableKNN(TeachableBase):
    def __init__(self, model_path, ui, k=3):
        super().__init__(ui)
        self.buffer = deque(maxlen=4)
        self.engine = KNNEmbeddingEngine(model_path, k)

    def step(self, img: Image.Image) -> bool:
        emb = self.engine.DetectWithImage(img)
        self.buffer.append(self.engine.kNNEmbedding(emb))
        classification = Counter(self.buffer).most_common(1)[0][0]

        buttons = self.ui.getDebouncedButtonState()
        for i, b in enumerate(buttons):
            if not b: continue
            if i == 0: self.engine.clear()
            else: self.engine.addEmbedding(emb, i)
        if sum(1 for x in buttons[1:] if x) == 4 and not buttons[0]:
            return True
        self.ui.setOnlyLED(classification)
        self._visual(classification, self.engine.exampleCount())
        return False

class TeachableImprinting(TeachableBase):
    def __init__(self, model_path, ui, output_path, keep_classes, mode="imprinting"):
        super().__init__(ui)
        self.mode = mode
        self.engine = DemoImprintingEngine(model_path, output_path, keep_classes, batch_size=4)

    def step(self, img: Image.Image) -> bool:
        if self.mode == "imprinting":
            classification = self.engine.classify(img)
        else:
            classification = self.engine.classify_backprop(img)

        buttons = self.ui.getDebouncedButtonState()
        for i, b in enumerate(buttons):
            if not b: continue
            if i == 0:
                # salva e limpa
                self.engine.clear()
            else:
                self.engine.addImage(img, i)

        if self.mode == "backprop" and self.engine.exampleCount() and (self.engine.exampleCount() % 8 == 0):
            self.engine.train_backprop()

        if sum(1 for x in buttons[1:] if x) == 4 and not buttons[0]:
            return True

        self.ui.setOnlyLED(classification)
        self._visual(classification, self.engine.exampleCount())
        return False

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', default='models/mobilenet_v1_1.0_224_quant_embedding_extractor_edgetpu.tflite')
    p.add_argument('--backend', default='picamera2', choices=['picamera2', 'opencv'])
    p.add_argument('--device', type=int, default=0, help='Índice do device (OpenCV).')
    p.add_argument('--res', default='640x480')
    p.add_argument('--keyboard', action='store_true', help='Usa UI de teclado.')
    p.add_argument('--method', default='knn', choices=['knn', 'imprinting', 'backprop'])
    p.add_argument('--outputmodel', default='output_imprinting.tflite')
    p.add_argument('--keepclasses', action='store_true')
    p.add_argument('--testui', action='store_true', help='Testa botões/LEDs no GPIO (sem câmera).')
    p.add_argument('--led-active-low', action='store_true', help='LEDs ativo-baixo (inverte a lógica).')
    args = p.parse_args()

    w, h = map(int, args.res.lower().split('x'))
    cam = make_camera(args.backend, size=(w, h), device=args.device if args.backend=='opencv' else None)
    ui = UI_Keyboard() if args.keyboard else (UI_Raspberry(active_low=args.led_active_low) if _GPIO else UI_Keyboard())
    if (not args.keyboard) and (_GPIO is None):
        print("Aviso: RPi.GPIO indisponível — caindo para teclado. Instale RPi.GPIO==0.7.1 e entre no grupo 'gpio'.", file=sys.stderr)
    if args.testui:
        ui.wiggleLEDs(2)
        print("Testando UI GPIO — pressione botões (Ctrl-C para sair).")
        try:
            while True:
                st = ui.getDebouncedButtonState()
                for i, b in enumerate(st):
                    if b:
                        ui.setOnlyLED(i)
                        print(f"Botão {i} OK")
                time.sleep(0.02)
        except KeyboardInterrupt:
            pass
        finally:
            if hasattr(ui, "cleanup"): ui.cleanup()
        return 0
    if args.method == 'knn':
        teachable = TeachableKNN(args.model, ui)
    elif args.method == 'imprinting':
        teachable = TeachableImprinting(args.model, ui, args.outputmodel, args.keepclasses, mode="imprinting")
    else:
        teachable = TeachableImprinting(args.model, ui, args.outputmodel, args.keepclasses, mode="backprop")

    print("Start capture…")
    cam.start()
    try:
        for frame in cam.frames():
            if teachable.step(frame):
                break
    finally:
        cam.stop()
        ui.wiggleLEDs(2)
    if hasattr(ui, "cleanup"): ui.cleanup()
if __name__ == '__main__':
    sys.exit(main())
