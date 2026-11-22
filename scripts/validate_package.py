"""Validate the release archive against its source and write a SHA-256 checksum."""
from __future__ import annotations

import argparse
import configparser
import hashlib
from pathlib import Path, PurePosixPath
import stat
from zipfile import ZipFile

from build_plugin import PLUGIN, EXCLUDED_NAMES, EXCLUDED_PARTS


def validate_package(path: Path) -> str:
    expected = {
        "ta_tasks/" + file.relative_to(PLUGIN).as_posix(): file
        for file in PLUGIN.rglob("*")
        if file.is_file() and file.name not in EXCLUDED_NAMES
        and file.suffix not in {".pyc", ".pyo"}
        and not any(part in EXCLUDED_PARTS for part in file.relative_to(PLUGIN).parts)
    }
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("Archive file list differs from the release source")
        if archive.testzip() is not None:
            raise ValueError("Archive has a failed CRC check")
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if parts[0] != "ta_tasks" or ".." in parts or "\\" in info.filename:
                raise ValueError(f"Unsafe archive path: {info.filename}")
            if any(part.startswith(".") or part == "__MACOSX" for part in parts):
                raise ValueError(f"Hidden or macOS metadata file: {info.filename}")
            if PurePosixPath(info.filename).suffix not in {".py", ".md", ".txt", ".svg"} and parts[-1] != "LICENSE":
                raise ValueError(f"Unexpected package file type: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"Symbolic link: {info.filename}")
            if expected[info.filename].is_symlink():
                raise ValueError(f"Source symbolic link: {info.filename}")
            if archive.read(info.filename) != expected[info.filename].read_bytes():
                raise ValueError(f"Source mismatch: {info.filename}")
        for name in ("__init__.py", "metadata.txt", "LICENSE", "HELP.md", "SECURITY.md", "RELEASE_CHECKLIST.md"):
            if f"ta_tasks/{name}" not in names:
                raise ValueError(f"Missing required file: {name}")
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read_string(archive.read("ta_tasks/metadata.txt").decode("utf-8"))
        if metadata["general"]["experimental"] != "True":
            raise ValueError("Beta must remain experimental")
        version = metadata["general"]["version"]
        if path.name != f"ta_tasks-{version}.zip":
            raise ValueError("Archive filename and metadata version differ")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    checksum = validate_package(args.archive)
    args.archive.with_suffix(".zip.sha256").write_text(
        f"{checksum}  {args.archive.name}\n", encoding="utf-8"
    )
    print(f"Validated {args.archive.name}; SHA-256 {checksum}")


if __name__ == "__main__":
    main()
