"""DPOLens: engine, HTTP API, worker and CLI."""

import os

# ONNX Runtime reports to Microsoft by default on Linux and macOS, and reads this
# once when it loads, so it is set before any module here can import it.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

__version__ = "0.0.0"
