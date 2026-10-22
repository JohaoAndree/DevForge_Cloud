"""Exporta los metadatos base del proyecto Pulumi."""

import pulumi


def build_project_metadata() -> dict[str, str]:
    """Construye metadatos nuevos para el proyecto y el stack activos."""
    return {
        "project": pulumi.get_project(),
        "stack": pulumi.get_stack(),
        "engine": "pulumi-python",
    }


pulumi.export("metadata", build_project_metadata())
