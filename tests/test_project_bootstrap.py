"""Verifica el manifiesto y los metadatos iniciales de Pulumi."""

import asyncio
from pathlib import Path
import runpy
from typing import Any
from unittest.mock import patch

import pulumi
import pulumi.runtime
import yaml


class _ProjectMocks(pulumi.runtime.Mocks):
    """Simula el motor Pulumi sin acceder a proveedores externos."""

    def new_resource(
        self, args: pulumi.runtime.MockResourceArgs
    ) -> tuple[str, dict[str, Any]]:
        """Devuelve una identidad estable y las propiedades recibidas."""
        return f"{args.name}_id", args.inputs

    def call(
        self, args: pulumi.runtime.MockCallArgs
    ) -> tuple[dict[str, Any], None]:
        """Devuelve una respuesta vacia para consultas del proveedor."""
        return {}, None


def test_pulumi_manifest_declares_python_virtualenv() -> None:
    """Garantiza que el manifiesto declara Python con el entorno venv."""
    manifest_path = Path(__file__).resolve().parents[1] / "Pulumi.yaml"
    assert manifest_path.is_file()

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "devforge-cloud"
    assert manifest["runtime"]["name"] == "python"
    assert manifest["runtime"]["options"]["virtualenv"] == "venv"


def test_build_project_metadata_returns_expected_contract() -> None:
    """Garantiza metadatos independientes y su exportacion al stack."""
    @pulumi.runtime.test
    def _verify_metadata() -> None:
        entrypoint_path = Path(__file__).resolve().parents[1] / "__main__.py"
        expected_metadata = {
            "project": "devforge-cloud",
            "stack": "test",
            "engine": "pulumi-python",
        }

        with patch("pulumi.export", wraps=pulumi.export) as export_metadata:
            program = runpy.run_path(str(entrypoint_path))

        build_project_metadata = program["build_project_metadata"]
        metadata = build_project_metadata()

        assert isinstance(metadata, dict)
        assert metadata == expected_metadata
        export_metadata.assert_called_once_with("metadata", expected_metadata)

        metadata["stack"] = "changed"
        assert build_project_metadata() == expected_metadata
        assert export_metadata.call_args.args[1] == expected_metadata

    event_loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(event_loop)
        pulumi.runtime.set_mocks(
            _ProjectMocks(), project="devforge-cloud", stack="test"
        )
        _verify_metadata()
    finally:
        event_loop.close()
        asyncio.set_event_loop(None)
