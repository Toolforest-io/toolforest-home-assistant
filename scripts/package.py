"""Build the integration-only release archive consumed by HACS and manual installs."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "toolforest"


def build_package(output: Path, expected_version: str | None = None) -> Path:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    if expected_version is not None and manifest["version"] != expected_version:
        raise ValueError("Release tag must match the integration manifest version")
    files = {
        path.relative_to(COMPONENT).as_posix(): path
        for path in COMPONENT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json"}
    }
    files["LICENSE"] = ROOT / "LICENSE"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, source in sorted(files.items()):
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Require this exact manifest version")
    args = parser.parse_args()
    print(build_package(ROOT / "dist" / "toolforest.zip", args.version))
