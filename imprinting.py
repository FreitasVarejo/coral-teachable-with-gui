# imprinting.py
# Imprinting Engine moderno (PyCoral) + opção de backprop com SoftmaxRegression.

from collections import defaultdict
import numpy as np
from PIL import Image

from pycoral.utils.edgetpu import make_interpreter
from pycoral.adapters.common import input_size, set_input, output_tensor

# Imprinting (low-shot) — substitui o legado deprecado
from pycoral.learn.imprinting.engine import ImprintingEngine  # moderno
# Backprop (softmax da última camada)
from pycoral.learn.backprop.softmax_regression import SoftmaxRegression

class DemoImprintingEngine:
    """Wrapper para demonstrar imprinting/treino on-device."""

    def __init__(self, model_path: str, output_path: str, keep_classes: bool, batch_size: int=1):
        self._model_path = model_path
        self._keep_classes = keep_classes
        self._output_path = output_path
        self._batch_size = batch_size

        # interpretador para descobrir (W,H) e extrair features quando precisar
        self._interpreter = make_interpreter(self._model_path)
        self._interpreter.allocate_tensors()
        w, h = input_size(self._interpreter)
        self._required_size = (w, h)

        self._imprinting_engine = ImprintingEngine(self._model_path, keep_classes=self._keep_classes)
        self.clear()

    def getRequiredInputShape(self):
        return self._required_size  # (W,H)

    def clear(self):
        if getattr(self, "_example_count", 0) > 0:
            self._imprinting_engine.SaveModel(self._output_path)
        self._example_count = 0
        self._label_map_button2real = {}
        self._label_map_real2button = {}
        self._max_real_label = 0
        self._image_map = defaultdict(list)

    def _resize_to_input(self, img: Image.Image) -> Image.Image:
        w, h = self._required_size
        return img.resize((w, h), Image.NEAREST).convert("RGB")

    def _embedding(self, img: Image.Image) -> np.ndarray:
        resized = self._resize_to_input(img)
        set_input(self._interpreter, resized)
        self._interpreter.invoke()
        out = output_tensor(self._interpreter, 0).squeeze()
        # dequantização simples (se necessário)
        scale, zero = self._interpreter.get_output_details()[0].get("quantization", (0.0, 0))
        if out.dtype == np.uint8 and scale and scale > 0:
            out = scale * (out.astype(np.int32) - int(zero))
        return out.astype(np.float32)

    # -------------------
    # Modo Imprinting
    # -------------------
    def train_batch_imprinting(self):
        for real_label, imgs in self._image_map.items():
            if not imgs:
                continue
            # para imprinting, a engine aceita arrays de imagens já redimensionadas (planas)
            batch = np.asarray(imgs, dtype=np.uint8)  # engine espera uint8 flat
            self._imprinting_engine.Train(batch, real_label)
        self._image_map = defaultdict(list)

    def addImage(self, img: Image.Image, label_button: int):
        if label_button not in self._label_map_button2real:
            self._label_map_button2real[label_button] = self._max_real_label
            self._label_map_real2button[self._max_real_label] = label_button
            self._max_real_label += 1
        label_real = self._label_map_button2real[label_button]
        self._example_count += 1
        resized = self._resize_to_input(img)
        self._image_map[label_real].append(np.asarray(resized).flatten())

        if sum(len(v) for v in self._image_map.values()) >= self._batch_size:
            self.train_batch_imprinting()

    def classify(self, img: Image.Image):
        if self.exampleCount() == 0:
            return None
        resized = self._resize_to_input(img)
        scores = self._imprinting_engine.ClassifyWithResizedImage(resized, top_k=1)
        return self._label_map_real2button[scores[0][0]]

    # -------------------
    # Opção Backprop (última camada)
    # -------------------
    def train_backprop(self):
        # agrega embeddings e treina softmax
        X, y = [], []
        for real_label, imgs in self._image_map.items():
            for flat in imgs:
                img = Image.fromarray(np.asarray(flat, dtype=np.uint8).reshape(self._required_size[1], self._required_size[0], 3))
                X.append(self._embedding(img))
                y.append(real_label)
        if not X:
            return
        X = np.stack(X)
        y = np.asarray(y, dtype=np.int32)
        feat_dim = X.shape[1]
        num_classes = self._max_real_label
        self._softmax = SoftmaxRegression(feature_dim=feat_dim, num_classes=num_classes)
        self._softmax.train_with_sgd(X, y, lr=0.05, num_iters=200, reg=1e-4)

    def classify_backprop(self, img: Image.Image):
        if not hasattr(self, "_softmax"):
            return None
        emb = self._embedding(img)
        pred = np.argmax(self._softmax.predict(np.expand_dims(emb, 0)), axis=1)[0]
        return self._label_map_real2button.get(int(pred))

    def exampleCount(self) -> int:
        return self._example_count
