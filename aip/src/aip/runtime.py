"""Inference runtimes that consume an AIP bundle.

Two backends, same contract:

* ``onnx``  - onnxruntime (CPU or CUDA EP). Portable, no torch on the target.
* ``torch`` - anomalib + torch. Highest fidelity, best on Blackwell when the
              work is batched or the backbone is large.

Both return :class:`Prediction`, so the HTTP layer never branches on backend.
Both support batched inference: at batch_size=1 the GPU is usually *slower*
than a many-core CPU (kernel launch overhead), the crossover comes with
batching or bigger backbones.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from .bundle import read_metadata

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- result
@dataclass
class Prediction:
    """Backend-agnostic inference result."""

    score: float
    label: bool
    threshold: float | None
    defect_ratio: float
    boxes: list[list[int]] = field(default_factory=list)
    localized: bool = True
    anomaly_map: np.ndarray | None = None
    mask: np.ndarray | None = None
    latency_ms: float = 0.0
    backend: str = ""

    def to_dict(
        self,
        *,
        with_map: bool = False,
        with_overlay: bool = False,
        image: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """JSON-serialisable payload (numpy arrays optionally inlined as PNG)."""
        payload: dict[str, Any] = {
            "score": round(float(self.score), 6),
            "label": "defect" if self.label else "ok",
            "is_defect": bool(self.label),
            # None when there is no defect to localise
            "localized": (bool(self.localized) if self.label else None),
            "threshold": None if self.threshold is None else round(float(self.threshold), 6),
            "defect_ratio": round(float(self.defect_ratio), 6),
            "boxes": self.boxes,
            "latency_ms": round(float(self.latency_ms), 2),
            "backend": self.backend,
        }
        if with_map and self.anomaly_map is not None:
            payload["anomaly_map"] = _encode_png(self.anomaly_map, as_mask=False)
        if with_overlay and self.mask is not None and image is not None:
            payload["overlay"] = _overlay_png(image, self.mask, self.anomaly_map)
        return payload


# ------------------------------------------------------------------ helpers
def _encode_png(array: np.ndarray, *, as_mask: bool) -> dict[str, Any]:
    import cv2

    if as_mask:
        payload = (array > 0).astype(np.uint8) * 255
    else:
        payload = cv2.applyColorMap(_to_uint8(array), cv2.COLORMAP_JET)
    ok, buffer = cv2.imencode(".png", payload)
    if not ok:  # pragma: no cover
        return {}
    return {"png_base64": base64.b64encode(buffer.tobytes()).decode("ascii"), "shape": list(array.shape)}


def _to_uint8(array: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(array)), float(np.max(array))
    if hi - lo < 1e-9:
        return np.zeros_like(array, dtype=np.uint8)
    return (((array - lo) / (hi - lo)) * 255).astype(np.uint8)


def _overlay_png(image: np.ndarray, mask: np.ndarray, heatmap: np.ndarray | None) -> str:
    """Blend a heatmap + defect contours on the original image (operator view)."""
    import cv2

    canvas = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.ndim == 3 else image.copy()
    if heatmap is not None:
        resized = cv2.resize(_to_uint8(heatmap), (canvas.shape[1], canvas.shape[0]))
        color = cv2.applyColorMap(resized, cv2.COLORMAP_JET)
        canvas = cv2.addWeighted(canvas, 0.65, color, 0.35, 0)
    m = cv2.resize((mask > 0).astype(np.uint8) * 255, (canvas.shape[1], canvas.shape[0]), interpolation=cv2.INTER_NEAREST)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(canvas, contours, -1, (0, 0, 255), 2)
    ok, buffer = cv2.imencode(".png", canvas)
    return base64.b64encode(buffer.tobytes()).decode("ascii") if ok else ""


def _boxes_from_mask(mask: np.ndarray) -> list[list[int]]:
    import cv2

    contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [list(map(int, cv2.boundingRect(c))) for c in contours if cv2.contourArea(c) > 4]


def _hotspot_box(anomaly_map: np.ndarray, fraction: float = 0.12) -> list[int] | None:
    """Box around the anomaly-map maximum, sized relative to the image."""
    if anomaly_map.size == 0:
        return None
    import cv2

    height, width = anomaly_map.shape[:2]
    _, _, _, (cx, cy) = cv2.minMaxLoc(anomaly_map.astype(np.float32))
    half = max(8, int(min(height, width) * fraction / 2))
    x = int(max(0, min(width - 1, cx - half)))
    y = int(max(0, min(height - 1, cy - half)))
    return [x, y, int(min(2 * half, width - x)), int(min(2 * half, height - y))]


def _resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    import cv2

    if mask.shape[:2] == size:
        return mask.astype(np.uint8)
    return cv2.resize(mask.astype(np.uint8), (size[1], size[0]), interpolation=cv2.INTER_NEAREST)


def _resize_float(array: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    import cv2

    if array.shape[:2] == size:
        return array.astype(np.float32)
    return cv2.resize(array.astype(np.float32), (size[1], size[0]), interpolation=cv2.INTER_LINEAR)


# ------------------------------------------------------------ image helpers
def load_image(path: str | Path) -> np.ndarray:
    """Read an image as RGB uint8 (H, W, 3)."""
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        msg = f"Cannot decode image: {path}"
        raise ValueError(msg)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def decode_image(data: bytes) -> np.ndarray:
    """Decode uploaded bytes to RGB uint8."""
    import cv2

    buffer = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        msg = "Uploaded payload is not a decodable image."
        raise ValueError(msg)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def preprocess(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Resize + scale to [0,1] + HWC->CHW float32 (matches anomalib's dataloader)."""
    import cv2

    resized = cv2.resize(image, (int(size[1]), int(size[0])), interpolation=cv2.INTER_LINEAR)
    tensor = resized.astype(np.float32) / 255.0
    return np.transpose(tensor, (2, 0, 1))


# ------------------------------------------------------------------ runtimes
class BaseRuntime:
    """Common contract for serving backends."""

    backend_name = "base"

    def __init__(
        self,
        bundle: str | Path,
        *,
        image_sensitivity: float | None = None,
        pixel_sensitivity: float | None = None,
        max_batch: int = 8,
    ):
        self.bundle = Path(bundle)
        if self.bundle.is_file():
            self.bundle = self.bundle.parent
        self.metadata = read_metadata(self.bundle)
        self.input_size = tuple(self.metadata["input"]["size"])
        post = self.metadata.get("postprocess", {})
        self.image_sensitivity = float(
            image_sensitivity if image_sensitivity is not None else post.get("image_sensitivity", 0.5)
        )
        self.pixel_sensitivity = float(
            pixel_sensitivity if pixel_sensitivity is not None else post.get("pixel_sensitivity", 0.5)
        )
        self.max_batch = max(1, int(max_batch))
        self._lock = Lock()
        self.warmup()

    # -- backend hooks ----------------------------------------------------
    def _infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        raise NotImplementedError

    def warmup(self) -> None:
        """One dummy inference so the first request is not seconds slower."""
        try:
            self._infer(np.zeros((1, 3, *self.input_size), dtype=np.float32))
        except Exception as error:  # noqa: BLE001 - warmup must never block start
            logger.warning("Warmup failed (%s): %s", self.backend_name, error)

    # -- public API --------------------------------------------------------
    def predict(self, image: np.ndarray) -> Prediction:
        """Run one image end-to-end."""
        return self.predict_batch([image])[0]

    def predict_batch(self, images: list[np.ndarray]) -> list[Prediction]:
        """Run N images in chunks of ``max_batch`` (GPU loves this)."""
        if not images:
            return []
        results: list[Prediction] = []
        for start in range(0, len(images), self.max_batch):
            chunk = images[start : start + self.max_batch]
            tensor = np.stack([preprocess(image, self.input_size) for image in chunk])
            started = time.perf_counter()
            with self._lock:
                outputs = self._infer(tensor)
            elapsed_ms = (time.perf_counter() - started) * 1000
            per_image_ms = elapsed_ms / len(chunk)
            for offset, image in enumerate(chunk):
                results.append(self._build_prediction(outputs, offset, len(chunk), image, per_image_ms))
        return results

    # -- shared post-processing -------------------------------------------
    def _build_prediction(
        self,
        outputs: dict[str, np.ndarray],
        index: int,
        batch_len: int,
        image: np.ndarray,
        latency_ms: float,
    ) -> Prediction:
        score = float(np.ravel(_slice(outputs.get("pred_score"), index, batch_len, default=[np.nan]))[0])
        label_output = _slice(outputs.get("pred_label"), index, batch_len)
        threshold = self._normalized_threshold()
        if label_output is not None:
            label = bool(np.ravel(label_output)[0])
        else:  # thresholding disabled inside the bundle
            label = bool(score > (threshold if threshold is not None else 0.5))

        anomaly_map = _slice(outputs.get("anomaly_map"), index, batch_len)
        anomaly_map = np.squeeze(anomaly_map) if anomaly_map is not None else None

        pred_mask = _slice(outputs.get("pred_mask"), index, batch_len)
        if pred_mask is not None:
            mask = np.squeeze(pred_mask).astype(np.uint8)
        elif anomaly_map is not None:
            mask = (anomaly_map > (threshold if threshold is not None else 0.5)).astype(np.uint8)
        else:
            mask = None

        # back to native resolution for the operator view
        if mask is not None:
            mask = _resize_mask(mask, image.shape[:2])
        if anomaly_map is not None:
            anomaly_map = _resize_float(anomaly_map, image.shape[:2])

        ratio = float(mask.mean()) if mask is not None else 0.0
        boxes = _boxes_from_mask(mask) if mask is not None else []
        localized = bool(boxes)

        # Image-level NG but nothing above the pixel threshold is a real case:
        # thin defects move the image score without surviving the stricter
        # pixel threshold. Operators still need somewhere to look, so point at
        # the hottest region and flag the hint as coarse.
        if label and not localized and anomaly_map is not None:
            hint = _hotspot_box(anomaly_map)
            if hint is not None:
                boxes = [hint]
                localized = False

        return Prediction(
            score=score,
            label=label,
            threshold=threshold,
            defect_ratio=ratio,
            boxes=boxes,
            localized=localized,
            anomaly_map=anomaly_map,
            mask=mask,
            latency_ms=latency_ms,
            backend=self.backend_name,
        )

    def _normalized_threshold(self) -> float | None:
        """Threshold in the score space the graph emits.

        anomalib normalises scores to [0, 1] around the learned threshold, so the
        decision boundary becomes ``1 - sensitivity``. Without normalisation the
        raw threshold is used.
        """
        post = self.metadata.get("postprocess", {})
        if post.get("enable_normalization", True):
            return 1.0 - self.image_sensitivity
        threshold = post.get("image_threshold")
        if threshold is None:
            lo, hi = post.get("image_min"), post.get("image_max")
            threshold = (lo + hi) / 2 if lo is not None and hi is not None else None
        return None if threshold is None else float(threshold)


def _slice(array: np.ndarray | None, index: int, batch_len: int, default: Any = None) -> Any:
    """Take row ``index`` when the output is batched, otherwise return as-is."""
    if array is None:
        return default
    if batch_len == 1:
        return array[0:1] if array.ndim and array.shape[0] == 1 else array
    if array.shape and array.shape[0] == batch_len:
        return array[index : index + 1]
    return array


class OnnxRuntime(BaseRuntime):
    """onnxruntime backend (CPU by default, CUDA EP when available)."""

    backend_name = "onnx"

    def __init__(self, bundle, *, device: str = "auto", **kwargs):
        self.device = device
        super().__init__(bundle, **kwargs)

    def _create_session(self):
        import onnxruntime as ort

        model_path = self.bundle / self.metadata["artifacts"].get("onnx", "model.onnx")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        available = ort.get_available_providers()
        providers: list[Any] = []
        if self.device in ("auto", "cuda") and "CUDAExecutionProvider" in available:
            providers.append(("CUDAExecutionProvider", {"device_id": 0}))
        providers.append("CPUExecutionProvider")
        session = ort.InferenceSession(str(model_path), sess_options=options, providers=providers)
        logger.info("onnxruntime providers: %s", session.get_providers())
        self.input_name = session.get_inputs()[0].name
        self.output_names = {output.name: idx for idx, output in enumerate(session.get_outputs())}
        return session

    def _infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        if not hasattr(self, "session"):
            self.session = self._create_session()
        raw = self.session.run(None, {self.input_name: tensor})
        named = {name: raw[idx] for name, idx in self.output_names.items()}
        aliases = {
            "pred_score": ("pred_score", "pred_scores"),
            "pred_label": ("pred_label",),
            "pred_mask": ("pred_mask",),
            "anomaly_map": ("anomaly_map", "anomaly_maps"),
        }
        return {
            key: next((named[name] for name in names if name in named), None)
            for key, names in aliases.items()
            if any(name in named for name in names)
        }

    def warmup(self) -> None:
        self.session = self._create_session()
        super().warmup()


class TorchRuntime(BaseRuntime):
    """anomalib + torch backend, closest to the training-time numerics."""

    backend_name = "torch"

    def __init__(self, bundle, *, device: str = "auto", compile: bool = False, **kwargs):
        self.device = device
        self.compile = compile
        super().__init__(bundle, **kwargs)

    def _load(self):
        import torch

        import anomalib.models as models

        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        model_name = self.metadata["model"]["name"]
        ckpt = self.bundle / self.metadata["artifacts"].get("ckpt", "model.ckpt")
        model_cls = getattr(models, model_name)
        # The checkpoint carries every weight, so skip the pretrained download:
        # factory PCs are often offline and this saves 45-260 MB of fetch.
        overrides: dict[str, Any] = {}
        try:
            import inspect

            if "pre_trained" in inspect.signature(model_cls.__init__).parameters:
                overrides["pre_trained"] = False
        except (TypeError, ValueError):  # pragma: no cover - exotic signatures
            pass
        try:
            # lightning restores the constructor arguments from hyper_parameters
            model = model_cls.load_from_checkpoint(str(ckpt), map_location=self.device, **overrides)
        except Exception as error:  # noqa: BLE001 - fall back to metadata + state dict
            logger.warning("load_from_checkpoint failed (%s); rebuilding from metadata", error)
            from anomalib.models import get_model

            model = get_model(model_name, **self.metadata["model"].get("args", {}))
            state = torch.load(str(ckpt), map_location=self.device, weights_only=False)["state_dict"]
            model.load_state_dict(state)
        model = model.eval().to(self.device)
        if self.compile and hasattr(torch, "compile"):
            model = torch.compile(model)
        return model

    def _infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        import torch

        if not hasattr(self, "model"):
            self.model = self._load()
        with torch.inference_mode():
            batch = torch.from_numpy(tensor).to(self.device)
            output = self.model(batch)
        return {
            key: (value.detach().float().cpu().numpy() if value is not None else None)
            for key, value in output._asdict().items()
            if value is not None
        }


def create_runtime(bundle: str | Path, backend: str = "auto", **kwargs) -> BaseRuntime:
    """Instantiate the requested backend, falling back gracefully."""
    bundle = Path(bundle)
    # validates the bundle up-front: a missing metadata.json is a user error,
    # not a backend-selection problem
    has_onnx = bool(read_metadata(bundle).get("artifacts", {}).get("onnx"))

    if backend in ("auto", "onnx") and has_onnx:
        try:
            return OnnxRuntime(bundle, **kwargs)
        except Exception as error:  # noqa: BLE001
            if backend == "onnx":
                raise
            logger.warning("ONNX backend unavailable (%s); falling back to torch.", error)
    if backend in ("auto", "torch"):
        return TorchRuntime(bundle, **kwargs)
    msg = f"No usable backend for bundle at {bundle} (requested {backend})"
    raise RuntimeError(msg)
