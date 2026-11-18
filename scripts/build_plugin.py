"""Build the clean QGIS plugin archive using only the Python standard library."""
from __future__ import annotations

import configparser
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "ta_tasks"
DIST = ROOT / "dist"
EXCLUDED_PARTS = {"__pycache__", "tests"}
EXCLUDED_NAMES = {".DS_Store"}


def main() -> None:
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(PLUGIN / "metadata.txt", encoding="utf-8")
    version = metadata["general"]["version"]
    DIST.mkdir(exist_ok=True)
    target = DIST / f"ta_tasks-{version}.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PLUGIN.rglob("*")):
            relative = path.relative_to(PLUGIN)
            if (path.is_dir() or path.name in EXCLUDED_NAMES or
                    path.suffix in {".pyc", ".pyo"} or
                    any(part in EXCLUDED_PARTS for part in relative.parts)):
                continue
            archive.write(path, Path("ta_tasks") / relative)
    print(target)


if __name__ == "__main__":
    main()
