# PyInstaller spec, shared by both builds. build.ps1 sets AUTOSTRONGHOLD_BUILD_VARIANT
# (cpu / gpu) and runs it with the matching virtual environment.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

variant = os.environ.get("AUTOSTRONGHOLD_BUILD_VARIANT", "cpu")
name = f"AutoStronghold-{variant.upper()}"
root = Path(SPECPATH).parent

import maa  # noqa: E402  (locate MaaFramework's native files)

maa_dir = Path(maa.__file__).parent
agent_dir = maa_dir.parent / "MaaAgentBinary"

datas = [(str(root / "resources"), "resources")]
datas += collect_data_files("rapidocr_onnxruntime")          # models + config.yaml
datas += [(str(maa_dir / "bin"), "maa/bin")]
if agent_dir.is_dir():
    datas += [(str(agent_dir), "MaaAgentBinary")]
binaries = collect_dynamic_libs("onnxruntime")

common = dict(pathex=[str(root)], binaries=binaries, datas=datas,
              hiddenimports=["autostronghold._build_variant"],
              excludes=["matplotlib", "PyQt5", "PySide6", "IPython", "pytest"], noarchive=False)
gui = Analysis([str(root / "packaging" / "entry_gui.py")], **common)            # the window


def program(analysis, exe_name, console):
    return EXE(PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True, name=exe_name,
               console=console,
               uac_admin=False,  # rights are asked for only when a PC-client run starts (autostronghold/elevate.py)
               upx=False)


coll = COLLECT(program(gui, name, console=False), gui.binaries, gui.datas, name=name, upx=False)
