"""Copy the license files of every bundled third-party package into <dist>/licenses.

Usage: python packaging/collect_licenses.py <output folder> [--site <folder>]
Run with the same interpreter that built the package so the versions match. The Android
build passes ``--site`` with Chaquopy's install folder of the app's packages (searched with
its sub-folders, one per ABI) and also gets the texts of the parts that do not come from
pip (Chaquopy, the Python runtime, ONNX Runtime for Android).
"""
from __future__ import annotations

import shutil
import sys
from importlib import metadata
from pathlib import Path

# Distributions that end up inside the executable (directly or as dependencies).
BUNDLED = ["maafw", "MaaAgentBinary", "rapidocr-onnxruntime", "onnxruntime", "onnxruntime-directml",
           "opencv-python", "opencv-python-headless", "numpy", "pyclipper", "shapely", "PyYAML", "six", "Pillow", "tqdm",
           "flatbuffers", "protobuf", "sympy", "mpmath", "packaging", "coloredlogs", "humanfriendly",
           "pyinstaller", "colorama", "StrEnum"]
TEXTS = Path(__file__).resolve().parent / "license_texts"
NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "THIRDPARTYNOTICES", "THIRD_PARTY_NOTICES", "AUTHORS")


def license_files(dist: metadata.Distribution) -> list[Path]:
    out = []
    files = dist.files
    if files is None and getattr(dist, "_path", None):
        # Chaquopy installs without RECORD: look through the .dist-info folder itself.
        info = Path(dist._path)
        files = [p.relative_to(info.parent) for p in info.rglob("*") if p.is_file()]
    for f in files or []:
        stem = Path(str(f)).name.upper().replace("-", "").replace(".TXT", "").replace(".MD", "").replace(".RST", "")
        if any(stem.startswith(n.replace("_", "")) or stem.startswith(n) for n in NAMES):
            p = Path(dist.locate_file(f))
            if p.is_file():
                out.append(p)
    return out


def find(name: str, site: Path | None) -> metadata.Distribution | None:
    if site is None:
        try:
            return metadata.distribution(name)
        except metadata.PackageNotFoundError:
            return None
    folders = [str(site)] + [str(d) for d in site.iterdir() if d.is_dir()]
    key = name.lower().replace("_", "-")
    for dist in metadata.distributions(path=folders):
        if (dist.metadata["Name"] or "").lower().replace("_", "-") == key:
            return dist
    return None


def main(target: str, site: Path | None = None) -> None:
    root = Path(target) / "licenses"
    root.mkdir(parents=True, exist_ok=True)
    summary = []
    for name in BUNDLED:
        dist = find(name, site)
        if dist is None:
            continue
        files = license_files(dist)
        folder = root / f"{dist.metadata['Name']}-{dist.version}"
        folder.mkdir(exist_ok=True)
        for f in files:
            shutil.copy2(f, folder / f.name)
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        if not files and "apache" in lic.lower():
            # Some wheels (e.g. rapidocr-onnxruntime) declare Apache-2.0 without shipping the text.
            shutil.copy2(TEXTS / "Apache-2.0.txt", folder / "LICENSE-Apache-2.0.txt")
            files = [folder / "LICENSE-Apache-2.0.txt"]
        summary.append(f"{dist.metadata['Name']} {dist.version}: {lic.splitlines()[0] if lic else 'see files'}"
                       f" ({len(files)} file(s))")
    # Code ported from Stronghold-Protocol (autostronghold/game/rules.py) is GPL-3.0-or-later.
    ported = root / "Stronghold-Protocol"
    ported.mkdir(exist_ok=True)
    shutil.copy2(TEXTS / "GPL-3.0.txt", ported / "LICENSE-GPL-3.0.txt")
    summary.append("Stronghold-Protocol (ported rules, autostronghold/game/rules.py): GPL-3.0-or-later (1 file(s))")
    if site is not None:
        if len(summary) < 4:
            raise SystemExit(f"No package licenses found under {site}; has Chaquopy changed its install folder?")
        android = root / "Android"
        shutil.copytree(TEXTS / "android", android, dirs_exist_ok=True)
        summary.append("Chaquopy runtime: MIT; Python: PSF License; ONNX Runtime for Android: MIT "
                       f"({len(list(android.iterdir()))} file(s))")
    (root / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    args = sys.argv[1:]
    site_dir = Path(args[args.index("--site") + 1]) if "--site" in args else None
    main(args[0], site_dir)
