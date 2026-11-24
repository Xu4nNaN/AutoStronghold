"""The part of the ``onnxruntime`` Python API that RapidOCR uses, for the Android app.

ONNX Runtime has no Python wheels for Android, so inference goes through its Java
library (``com.microsoft.onnxruntime:onnxruntime-android``, the same engine) via the Kotlin
class ``OrtBridge``. RapidOCR runs unchanged on top of this module: one float32 input and
one float32 output per model, CPU only.
"""
from __future__ import annotations

import numpy as np
from java import jclass  # Chaquopy

_Bridge = jclass("com.autostronghold.app.OrtBridge")
CPU = "CPUExecutionProvider"


class GraphOptimizationLevel:
    ORT_DISABLE_ALL = 0
    ORT_ENABLE_BASIC = 1
    ORT_ENABLE_EXTENDED = 2
    ORT_ENABLE_ALL = 99


class SessionOptions:
    def __init__(self) -> None:
        self.log_severity_level = 2
        self.enable_cpu_mem_arena = True
        self.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
        self.intra_op_num_threads = 0
        self.inter_op_num_threads = 0


def get_available_providers() -> list[str]:
    return [CPU]


def get_device() -> str:
    return "CPU"


class NodeArg:
    def __init__(self, name: str) -> None:
        self.name = name


class ModelMetadata:
    def __init__(self, custom_metadata_map: dict[str, str]) -> None:
        self.custom_metadata_map = custom_metadata_map


def _floats(java_array) -> np.ndarray:
    try:
        return np.frombuffer(memoryview(java_array), np.float32)
    except TypeError:
        return np.array(list(java_array), np.float32)


class InferenceSession:
    def __init__(self, path, sess_options: SessionOptions | None = None, providers=None) -> None:
        threads = int(getattr(sess_options, "intra_op_num_threads", 0) or 0)
        self._bridge = _Bridge(str(path), threads)

    def get_providers(self) -> list[str]:
        return [CPU]

    def get_inputs(self) -> list[NodeArg]:
        return [NodeArg(str(n)) for n in self._bridge.inputNames()]

    def get_outputs(self) -> list[NodeArg]:
        return [NodeArg(str(n)) for n in self._bridge.outputNames()]

    def get_modelmeta(self) -> ModelMetadata:
        keys = [str(k) for k in self._bridge.metadataKeys()]
        return ModelMetadata({k: str(self._bridge.metadata(k)) for k in keys})

    def run(self, output_names, input_feed: dict) -> list[np.ndarray]:
        (data,) = input_feed.values()
        data = np.ascontiguousarray(data, np.float32)
        out = _floats(self._bridge.run(data.tobytes(), [int(n) for n in data.shape]))
        return [out.reshape([int(n) for n in self._bridge.lastShape()])]
