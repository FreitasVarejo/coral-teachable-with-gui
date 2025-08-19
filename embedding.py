# embedding.py
# Extrai embeddings com PyCoral (substitui BasicEngine legado).
from collections import Counter, defaultdict
import numpy as np
from PIL import Image

from pycoral.utils.edgetpu import make_interpreter
from pycoral.adapters.common import input_size, set_input, output_tensor

class EmbeddingEngine:
    """Extrai embeddings de um modelo headless (Mobilenet 'embedding extractor')."""

    def __init__(self, model_path: str):
        self.interpreter = make_interpreter(model_path)
        self.interpreter.allocate_tensors()
        # valida 1 saída
        outputs = self.interpreter.get_output_details()
        if len(outputs) != 1:
            raise ValueError(f"Modelo deve ter 1 saída (embedding). Tem {len(outputs)}.")
        self._required_size = input_size(self.interpreter)  # (width, height)

    @property
    def required_size(self):
        return self._required_size

    def _dequantize_if_needed(self, v: np.ndarray, details: dict) -> np.ndarray:
        # PyCoral geralmente já retorna tipo correto via output_tensor;
        # ainda assim, garantimos dequantização se vier uint8
        scale, zero = details.get("quantization", (0.0, 0))
        if v.dtype == np.uint8 and scale and scale > 0:
            return scale * (v.astype(np.int32) - int(zero))
        return v.astype(np.float32)

    def DetectWithImage(self, img: Image.Image) -> np.ndarray:
        # redimensiona para (W,H) esperado pelo modelo
        w, h = self._required_size
        resized = img.resize((w, h), Image.NEAREST).convert("RGB")
        set_input(self.interpreter, resized)
        self.interpreter.invoke()
        out = output_tensor(self.interpreter, 0).squeeze()
        out = self._dequantize_if_needed(out, self.interpreter.get_output_details()[0])
        return out.astype(np.float32)

class KNNEmbeddingEngine(EmbeddingEngine):
    """Mantém um store em memória e faz k-NN por cosseno."""
    def __init__(self, model_path: str, kNN: int=3):
        super().__init__(model_path)
        self._kNN = kNN
        self.clear()

    def clear(self):
        self._labels = []
        self._embedding_map = defaultdict(list)
        self._embeddings = None

    def addEmbedding(self, emb: np.ndarray, label: int):
        normal = emb / (np.linalg.norm(emb) + 1e-12)
        self._embedding_map[label].append(normal)

        # reconstrói bloco de embeddings balanceando até kNN por classe
        emb_blocks = []
        self._labels = []
        for lab, embeds in self._embedding_map.items():
            block = np.stack(embeds)
            if block.shape[0] < self._kNN:
                pad = self._kNN - block.shape[0]
                block = np.pad(block, [(0, pad), (0, 0)], mode="reflect")
            emb_blocks.append(block)
            self._labels.extend([lab] * block.shape[0])

        self._embeddings = np.concatenate(emb_blocks, axis=0) if emb_blocks else None

    def kNNEmbedding(self, query_emb: np.ndarray):
        if self._embeddings is None:
            return None
        q = query_emb / (np.linalg.norm(query_emb) + 1e-12)
        dists = self._embeddings @ q  # similaridade cosseno
        k = min(len(dists), self._kNN)
        idx = np.argpartition(dists, -k)[-k:]
        labels = [self._labels[i] for i in idx]
        return Counter(labels).most_common(1)[0][0]

    def exampleCount(self) -> int:
        return sum(len(v) for v in self._embedding_map.values())
