"""AIP - Industrial anomaly inspection platform on top of anomalib.

Pipeline: dataset -> anomalib model -> train -> evaluate -> export bundle -> serve.

The platform never forks anomalib internals: it wires the official components
(DataModule / AnomalibModule / Engine) and adds the operational layer that a
factory deployment needs (config recipes, GPU tuning, self-contained artifact
bundle, HTTP inference service).
"""

__version__ = "0.1.0"
