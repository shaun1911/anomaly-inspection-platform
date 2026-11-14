"""HTTP inference service for an AIP bundle.

Design goals for a factory floor:

* zero-downtime reload: ``POST /reload`` swaps the runtime without dropping
  the process (new model version arrives -> reload -> rollback is one call);
* one JSON schema regardless of backend;
* a tiny built-in operator page (``GET /``) so a line engineer can verify a
  camera image without any tooling;
* health/readiness split for k8s or a Windows service wrapper.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from ..bundle import read_metadata
from ..runtime import create_runtime, decode_image

logger = logging.getLogger(__name__)
STARTED_AT = time.time()

BUNDLE_ENV = "AIP_BUNDLE"
BACKEND_ENV = "AIP_BACKEND"
DEVICE_ENV = "AIP_DEVICE"


class ServiceState:
    """Holds the active runtime; reloading replaces it atomically."""

    def __init__(self, bundle: str | Path, backend: str = "auto", device: str = "auto") -> None:
        self.bundle = Path(bundle)
        self.backend = backend
        self.device = device
        self.runtime = None
        self.reload()

    def reload(self) -> None:
        self.runtime = create_runtime(
            self.bundle,
            backend=self.backend,
            device=self.device,
            max_batch=int(os.environ.get("AIP_MAX_BATCH", "8")),
        )
        logger.info("Runtime ready: %s (max_batch=%s)", self.runtime.backend_name, self.runtime.max_batch)

    @property
    def metadata(self) -> dict[str, Any]:
        return read_metadata(self.bundle)


def create_app(bundle: str | Path | None = None, backend: str | None = None, device: str | None = None) -> FastAPI:
    """Build the FastAPI app (importable for tests and for ``uvicorn --factory``)."""
    bundle_path = bundle or os.environ.get(BUNDLE_ENV, "artifacts/demo")
    backend_name = backend or os.environ.get(BACKEND_ENV, "auto")
    device_name = device or os.environ.get(DEVICE_ENV, "auto")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = ServiceState(bundle_path, backend=backend_name, device=device_name)
        yield

    app = FastAPI(
        title="AIP - Anomaly Inspection Platform",
        version="0.1.0",
        description="Industrial anomaly detection inference service (anomalib backend).",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ ops
    @app.get("/health")
    def health() -> dict[str, Any]:
        service: ServiceState = app.state.service
        runtime = service.runtime
        return {
            "status": "ok",
            "backend": runtime.backend_name if runtime else None,
            "bundle": str(service.bundle),
            "uptime_s": round(time.time() - STARTED_AT, 1),
        }

    @app.get("/info")
    def info() -> dict[str, Any]:
        service: ServiceState = app.state.service
        meta = service.metadata
        return {
            "project": meta.get("project"),
            "model": meta.get("model"),
            "input": meta.get("input"),
            "postprocess": meta.get("postprocess"),
            "metrics": meta.get("metrics"),
            "created_at": meta.get("created_at"),
            "backend": service.runtime.backend_name if service.runtime else None,
        }

    @app.post("/reload")
    def reload() -> dict[str, str]:
        service: ServiceState = app.state.service
        try:
            service.reload()
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"reload failed: {error}") from error
        return {"status": "reloaded", "backend": service.runtime.backend_name}

    # -------------------------------------------------------------- predict
    @app.post("/predict")
    async def predict(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI idiom
        return_map: bool = Query(default=False, description="Include the anomaly heatmap (base64 PNG)."),
        return_overlay: bool = Query(default=False, description="Include an annotated PNG (base64)."),
    ) -> JSONResponse:
        service: ServiceState = app.state.service
        payload = await file.read()
        try:
            image = decode_image(payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        prediction = service.runtime.predict(image)
        body = prediction.to_dict(with_map=return_map, with_overlay=return_overlay, image=image)
        body["filename"] = file.filename
        return JSONResponse(body)

    @app.post("/predict/batch")
    async def predict_batch(files: list[UploadFile] = File(...)) -> dict[str, Any]:  # noqa: B008
        service: ServiceState = app.state.service
        started = time.perf_counter()
        images, names, results = [], [], []
        for upload in files:
            payload = await upload.read()
            try:
                images.append(decode_image(payload))
                names.append(upload.filename)
            except ValueError as error:
                results.append({"filename": upload.filename, "error": str(error)})
        predictions = service.runtime.predict_batch(images) if images else []
        for name, prediction in zip(names, predictions, strict=True):
            body = prediction.to_dict()
            body["filename"] = name
            results.append(body)
        return {
            "count": len(results),
            "defects": sum(1 for item in results if item.get("is_defect")),
            "batch_size": len(images),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "results": results,
        }

    # ------------------------------------------------------------- operator
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE

    return app


_PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>AIP 缺陷检测</title>
<style>
 body{font-family:system-ui,Segoe UI,Arial;margin:0;background:#0f1115;color:#e6e6e6}
 .wrap{max-width:900px;margin:32px auto;padding:0 16px}
 .card{background:#181b22;border:1px solid #262a35;border-radius:12px;padding:20px;margin-bottom:16px}
 h1{font-size:20px;margin:0 0 16px} .row{display:flex;gap:16px;flex-wrap:wrap}
 .drop{flex:1;min-width:260px;border:2px dashed #39404f;border-radius:10px;padding:28px;text-align:center;color:#98a2b3}
 .drop.on{border-color:#4f8cff;color:#cfe0ff}
 button{background:#2f6fed;border:0;color:#fff;padding:10px 18px;border-radius:8px;cursor:pointer}
 button:disabled{opacity:.5;cursor:default}
 img{max-width:100%;border-radius:8px;margin-top:12px}
 .verdict{font-size:28px;font-weight:700;margin:8px 0}
 .ok{color:#3ddc84} .ng{color:#ff5c5c}
 pre{background:#0b0d12;padding:12px;border-radius:8px;overflow:auto;font-size:12px}
</style></head><body><div class="wrap">
<h1>AIP · 工业异常检测</h1>
<div class="card">
  <div class="row">
    <div class="drop" id="drop">拖拽图片到此，或点击选择<input type="file" id="file" hidden accept="image/*"></div>
    <div style="flex:1;min-width:260px">
      <div class="verdict" id="verdict">等待检测</div>
      <div id="score" style="color:#98a2b3"></div>
      <img id="preview" hidden>
    </div>
  </div>
  <div style="margin-top:12px"><button id="go" disabled>检测</button></div>
  <pre id="out" hidden></pre>
</div></div>
<script>
const drop=document.getElementById('drop'),file=document.getElementById('file'),go=document.getElementById('go'),
 verdict=document.getElementById('verdict'),score=document.getElementById('score'),preview=document.getElementById('preview'),out=document.getElementById('out');
let chosen=null;
drop.onclick=()=>file.click();
drop.ondragover=e=>{e.preventDefault();drop.classList.add('on')};
drop.ondragleave=()=>drop.classList.remove('on');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('on');pick(e.dataTransfer.files[0])};
file.onchange=()=>pick(file.files[0]);
function pick(f){if(!f)return;chosen=f;preview.src=URL.createObjectURL(f);preview.hidden=false;go.disabled=false;verdict.textContent='就绪';verdict.className='verdict';}
go.onclick=async()=>{
 if(!chosen)return; go.disabled=true; verdict.textContent='检测中…'; verdict.className='verdict';
 const fd=new FormData(); fd.append('file',chosen);
 try{
  const r=await fetch('/predict?return_map=true&return_overlay=true',{method:'POST',body:fd});
  const j=await r.json();
  verdict.textContent=j.is_defect?'NG · 检出缺陷':'OK · 无缺陷';
  verdict.className='verdict '+(j.is_defect?'ng':'ok');
  score.textContent=`score=${j.score}  threshold=${j.threshold}  缺陷面积=${(j.defect_ratio*100).toFixed(2)}%  耗时=${j.latency_ms}ms  backend=${j.backend}`;
  out.hidden=false; out.textContent=JSON.stringify({boxes:j.boxes,defect_ratio:j.defect_ratio},null,2);
  if(j.overlay){const i=document.createElement('img');i.src='data:image/png;base64,'+j.overlay;preview.replaceWith(i);i.id='preview';}
 }catch(e){verdict.textContent='请求失败';console.error(e);}
 finally{go.disabled=false;}
};
</script></body></html>"""
