"""GPU availability check for the GPU (DirectML) build.

DirectML runs on any DirectX 12 capable GPU (NVIDIA, AMD, Intel) and needs no CUDA.
The check is done in three steps so the player learns *which* part is missing.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

NO_WINDOW = 0x08000000
# Adapters that exist on machines without a usable GPU.
SOFTWARE_ADAPTERS = ("microsoft basic", "microsoft remote", "remote display", "virtual", "parsec",
                     "citrix", "vmware svga", "virtualbox", "hyper-v", "idd")


@dataclass
class GpuReport:
    usable: bool
    reason: str = ""
    adapters: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)


def list_adapters() -> list[str] | None:
    """Display adapter names from Windows, or None when they cannot be queried."""
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
           "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                             timeout=20, creationflags=NO_WINDOW).stdout.decode("utf-8", "ignore").strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return [data] if isinstance(data, str) else [str(x) for x in data]


def is_hardware(name: str) -> bool:
    low = name.lower()
    return not any(s in low for s in SOFTWARE_ADAPTERS)


def check_gpu() -> GpuReport:
    try:
        import onnxruntime
    except Exception as exc:  # pragma: no cover - broken package
        return GpuReport(False, f"推理库 onnxruntime 无法加载：{exc}")
    providers = list(onnxruntime.get_available_providers())
    if "DmlExecutionProvider" not in providers:
        return GpuReport(False, "本程序包内的推理库不支持 DirectML（可能下载成了 CPU 版的文件）。",
                         providers=providers)

    adapters = list_adapters()
    if adapters is not None:
        hardware = [a for a in adapters if is_hardware(a)]
        if not hardware:
            found = "、".join(adapters) if adapters else "无"
            return GpuReport(False, f"未检测到可用的显卡（系统显示适配器：{found}）。", adapters, providers)
        adapters = hardware

    # Finally make sure a DirectML session really starts on this machine.
    try:
        from .vision.ocr import OcrEngine
        import numpy as np

        engine = OcrEngine(use_gpu=True)
        engine.read(np.full((64, 256, 3), 255, np.uint8))
        if not engine.on_gpu():
            return GpuReport(False, "显卡驱动不支持 DirectX 12 / DirectML，推理已退回 CPU。",
                             adapters or [], providers)
    except Exception as exc:
        return GpuReport(False, f"DirectML 初始化失败：{exc}", adapters or [], providers)
    return GpuReport(True, "", adapters or [], providers)
