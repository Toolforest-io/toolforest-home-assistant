"""Check that the release can be installed without the development checkout."""

import ast
import json
from zipfile import ZipFile

import pytest

from scripts.package import COMPONENT, build_package


def test_release_contains_installable_integration_and_license(tmp_path):
    output = build_package(tmp_path / "toolforest.zip")
    with ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {"__init__.py", "manifest.json", "config_flow.py", "LICENSE"} <= names
        assert "translations/en.json" in names
        assert {"brand/icon.png", "brand/icon@2x.png"} <= names
        assert not any(
            name.startswith(("tests/", "custom_components/")) for name in names
        )
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["domain"] == "toolforest"
        assert manifest["requirements"] == []
        assert manifest["documentation"].endswith("/toolforest-home-assistant")
        for name in names - {"LICENSE"}:
            assert archive.read(name) == (COMPONENT / name).read_bytes()


def test_release_version_mismatch_cannot_create_archive(tmp_path):
    output = tmp_path / "toolforest.zip"
    with pytest.raises(ValueError, match="manifest version"):
        build_package(output, expected_version="999.0.0")
    assert not output.exists()


def test_release_contains_only_production_endpoints(tmp_path):
    output = build_package(tmp_path / "toolforest.zip")
    with ZipFile(output) as archive:
        constants = {
            assignment.targets[0].id: ast.literal_eval(assignment.value)
            for assignment in ast.parse(archive.read("const.py")).body
            if isinstance(assignment, ast.Assign)
        }
        assert constants["ENVIRONMENTS"] == {
            "prod": ("https://bridge-api.toolforest.io", "wss://bridge.toolforest.io")
        }
        assert constants["VERSION"] == json.loads(archive.read("manifest.json"))["version"]
        for name in archive.namelist():
            if name.endswith((".py", ".json")):
                content = archive.read(name)
                assert b"bridge-api-dev.toolforest.io" not in content
                assert b"bridge-api-test.toolforest.io" not in content
                assert b"bridge-dev.toolforest.io" not in content
                assert b"bridge-test.toolforest.io" not in content
        for name in ("strings.json", "translations/en.json"):
            data = json.loads(archive.read(name))
            assert set(data["config"]["step"]["user"]["data"]) == {"name"}
