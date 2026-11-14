# aip — Industrial Anomaly Inspection Platform

Thin operational layer on top of [anomalib](https://github.com/open-edge-platform/anomalib):

```
recipe.yaml ──► aip train ──► runs/<project>/…            (logs, ckpt, metrics)
                              artifacts/<project>/        (deployable bundle)
                                 ├─ metadata.json
                                 ├─ model.onnx   (pre + model + post, portable)
                                 ├─ model.ckpt   (torch / retrain)
                                 └─ config.yaml  (the recipe that produced it)
                     │
                     └──► aip serve ──► HTTP /  /predict  /predict/batch  /reload
```

## Commands

| command | purpose |
|---|---|
| `aip doctor` | GPU / CUDA / onnxruntime / anomalib probe |
| `aip demo` | generate a synthetic brushed-metal dataset |
| `aip train -c configs/demo_patchcore.yaml` | fit → test → export bundle |
| `aip test -c … [--bundle …]` | re-evaluate a bundle (regression gate) |
| `aip predict --bundle … --source imgs/` | offline scoring, no server |
| `aip serve --bundle … --port 8000` | HTTP service + operator UI |
| `aip info <bundle>` | dump bundle metadata |

Every field of the recipe can be overridden from the CLI:

```bash
aip train -c configs/demo_patchcore.yaml --set data.image_size=[320,320] --set model.args.coreset_sampling_ratio=0.05
```

## Design notes

* **No fork of anomalib.** Data modules, models, `Engine`, post-processing and
  export all come from upstream; this package only wires them and adds the
  artifact contract.
* **The bundle is the product.** Serving never needs the dataset, the recipe
  path, or the training environment — only `metadata.json` + `model.onnx`.
* **Two backends, one schema.** `onnx` (portable, CPU or CUDA EP) and `torch`
  (highest fidelity / fastest on Blackwell). `auto` prefers ONNX when present.
* **Thresholds travel with the model.** `metadata.json` carries the learned
  F1-adaptive threshold, the min/max normalisation range and the sensitivity
  values, so labels are reproducible outside anomalib.
