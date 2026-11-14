"""``aip`` command line: doctor / demo / train / test / export / serve / predict."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import load_config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="AIP - industrial anomaly inspection platform (anomalib based).",
)
ConfigOpt = Annotated[Path, typer.Option("-c", "--config", help="Recipe YAML.")]
SetOpt = Annotated[list[str] | None, typer.Option("--set", help="Override any field: --set data.image_size=[320,320]")]


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    for noisy in ("lightning", "lightning.pytorch", "torch", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def version() -> None:
    """Print the platform version."""
    typer.echo(f"aip {__version__}")


@app.command()
def doctor() -> None:
    """Check GPU / CUDA / onnxruntime / anomalib availability."""
    from .registry import doctor as inspect

    report = inspect()
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    if report.get("cuda_available"):
        typer.secho(f"\nGPU ready: {report['gpu']['name']} ({report['gpu']['capability']}, {report['gpu']['vram_gb']} GB)", fg="green")
    else:
        typer.secho("\nCUDA not available: training will run on CPU (slow).", fg="yellow")


@app.command()
def demo(
    root: Annotated[Path, typer.Option(help="Where to write the demo dataset.")] = Path("datasets/demo"),
    seed: Annotated[int, typer.Option(help="Random seed.")] = 7,
) -> None:
    """Generate a synthetic brushed-metal dataset for smoke tests."""
    from .demo import make_demo_dataset

    make_demo_dataset(root, seed=seed)
    typer.secho(f"Demo dataset ready: {root.resolve()}", fg="green")


@app.command()
def train(config: ConfigOpt, override: SetOpt = None, verbose: Annotated[bool, typer.Option("--verbose")] = False) -> None:
    """Train, evaluate and export the artifact bundle in one shot."""
    _setup_logging(verbose)
    from .train import run_training

    report = run_training(load_config(config, override))
    typer.secho("\n=== run summary ===", bold=True)
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    typer.secho(f"\nBundle: {report['bundle']}", fg="green")


@app.command()
def test(
    config: ConfigOpt,
    bundle: Annotated[Path | None, typer.Option("--bundle", help="Bundle dir (default: recipe bundle_dir).")] = None,
    override: SetOpt = None,
) -> None:
    """Evaluate an existing bundle on the recipe dataset."""
    _setup_logging()
    from .train import run_test

    report = run_test(load_config(config, override), bundle)
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))


@app.command()
def info(bundle: Annotated[Path, typer.Argument(help="Bundle directory.")]) -> None:
    """Print the metadata of a bundle."""
    from .bundle import read_metadata

    typer.echo(json.dumps(read_metadata(bundle), indent=2, ensure_ascii=False))


@app.command()
def predict(
    bundle: Annotated[Path, typer.Option("--bundle", help="Bundle directory.")],
    source: Annotated[Path, typer.Option("--source", help="Image file or directory.")],
    backend: Annotated[str, typer.Option("--backend", help="auto | onnx | torch")] = "auto",
    device: Annotated[str, typer.Option("--device", help="auto | cuda | cpu")] = "auto",
    out: Annotated[Path | None, typer.Option("--out", help="Write JSONL results.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max images to score.")] = 0,
) -> None:
    """Score images offline with a bundle (no server needed)."""
    _setup_logging()
    from .runtime import create_runtime, load_image

    runtime = create_runtime(bundle, backend=backend, device=device)
    paths = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
    if limit:
        paths = paths[:limit]
    if not paths:
        typer.secho("No images found.", fg="red")
        raise typer.Exit(1)

    rows = []
    for path in paths:
        result = runtime.predict(load_image(path)).to_dict()
        result["file"] = str(path)
        rows.append(result)
        flag = "NG" if result["is_defect"] else "OK"
        typer.echo(f"{flag}  {result['score']:.4f}  {result['latency_ms']:7.1f}ms  {path.name}")

    defects = sum(1 for r in rows if r["is_defect"])
    typer.secho(f"\n{len(rows)} images | {defects} NG | backend={rows[0]['backend']}", fg="green")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        typer.echo(f"Written {out}")


@app.command()
def bench(
    bundle: Annotated[Path, typer.Option("--bundle", help="Bundle directory.")],
    backend: Annotated[str, typer.Option("--backend")] = "auto",
    device: Annotated[str, typer.Option("--device")] = "auto",
    source: Annotated[Path | None, typer.Option("--source", help="Image dir; defaults to a random tensor.")] = None,
    iters: Annotated[int, typer.Option("--iters")] = 50,
    batch: Annotated[int, typer.Option("--batch", help="Images per forward pass.")] = 1,
) -> None:
    """Measure latency and throughput for capacity planning."""
    _setup_logging()
    import statistics
    import time

    import numpy as np

    from .runtime import create_runtime, load_image

    runtime = create_runtime(bundle, backend=backend, device=device, max_batch=batch)
    if source and source.exists():
        paths = sorted(p for p in source.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"})
        images = [load_image(p) for p in paths[: max(1, min(len(paths), max(8, batch)))]]
    else:
        images = [np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)]
    if not images:
        typer.secho("No images found.", fg="red")
        raise typer.Exit(1)

    calls = max(1, iters // batch)
    latency_batches: list[float] = []
    started = time.perf_counter()
    for index in range(calls):
        chunk = [images[(index * batch + offset) % len(images)] for offset in range(batch)]
        predictions = runtime.predict_batch(chunk)
        latency_batches.append(predictions[0].latency_ms * batch)  # per-forward wall time
    wall = time.perf_counter() - started

    ordered = sorted(latency_batches)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    typer.secho(
        f"backend={runtime.backend_name}  device={getattr(runtime, 'device', 'n/a')}  batch={batch}  forwards={calls}",
        bold=True,
    )
    typer.echo(f"  per-forward  p50={p50:7.2f} ms   p95={p95:7.2f} ms   min={ordered[0]:7.2f}")
    typer.echo(f"  per-image    p50={p50 / batch:7.2f} ms")
    typer.echo(f"  throughput   {calls * batch / wall:7.1f} img/s")
    try:
        import torch

        if torch.cuda.is_available():
            typer.echo(
                f"  gpu mem      allocated={torch.cuda.memory_allocated() / 1024**2:.0f} MB"
                f"  reserved={torch.cuda.memory_reserved() / 1024**2:.0f} MB"
            )
    except Exception:  # noqa: BLE001 - optional
        pass


@app.command()
def serve(
    bundle: Annotated[Path, typer.Option("--bundle", help="Bundle directory.")] = Path("artifacts/demo"),
    backend: Annotated[str, typer.Option("--backend", help="auto | onnx | torch")] = "auto",
    device: Annotated[str, typer.Option("--device", help="auto | cuda | cpu")] = "auto",
    host: Annotated[str, typer.Option("--host")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code change (dev only).")] = False,
    workers: Annotated[int, typer.Option("--workers", help="Uvicorn workers (1 = share one GPU context).")] = 1,
) -> None:
    """Serve a bundle over HTTP (operator UI at /, API at /predict)."""
    import os

    import uvicorn

    _setup_logging()
    os.environ["AIP_BUNDLE"] = str(bundle.resolve())
    os.environ["AIP_BACKEND"] = backend
    os.environ["AIP_DEVICE"] = device
    typer.secho(f"Starting AIP service on http://{host}:{port}  (bundle={bundle})", fg="green")
    if reload:
        uvicorn.run("aip.serve.app:create_app", factory=True, host=host, port=port, reload=True, log_level="info")
    else:
        uvicorn.run("aip.serve.app:create_app", factory=True, host=host, port=port, workers=workers, log_level="info")


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
