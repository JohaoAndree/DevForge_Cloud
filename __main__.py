"""Orquesta la configuracion, red y metadatos del stack Pulumi."""

import pulumi
import pulumi_docker

from components.config_loader import EnvironmentConfig, load_environment_config
from components.network_factory import create_isolated_network


def build_project_metadata() -> dict[str, str]:
    """Construye metadatos nuevos para el proyecto y el stack activos."""
    return {
        "project": pulumi.get_project(),
        "stack": pulumi.get_stack(),
        "engine": "pulumi-python",
    }


def orchestrate_infrastructure() -> tuple[EnvironmentConfig, pulumi_docker.Network]:
    """Crea la red del entorno y exporta su contrato y nombre."""
    env_config = load_environment_config()
    network = create_isolated_network(env_config)
    pulumi.export("environment_config", env_config.to_export_dict())
    pulumi.export("network_name", network.name)
    return env_config, network


pulumi.export("metadata", build_project_metadata())
if pulumi.Config("devforge-cloud").get("environment") is not None:
    orchestrate_infrastructure()
