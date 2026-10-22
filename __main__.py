"""Orquesta la configuracion, topologia y metadatos del stack Pulumi."""

import pulumi

from components.config_loader import EnvironmentConfig, load_environment_config
from components.environment_stack import DevForgeEnvironment


def build_project_metadata() -> dict[str, str]:
    """Construye metadatos nuevos para el proyecto y el stack activos."""
    return {
        "project": pulumi.get_project(),
        "stack": pulumi.get_stack(),
        "engine": "pulumi-python",
    }


def orchestrate_infrastructure() -> tuple[EnvironmentConfig, DevForgeEnvironment]:
    """Crea el entorno y exporta su contrato, destinos y URLs."""
    env_config = load_environment_config()
    environment = DevForgeEnvironment(
        f"devforge-{env_config.stack_name}-env", env_config=env_config,
    )
    pulumi.export("environment_config", env_config.to_export_dict())
    pulumi.export("network_name", environment.network.name)
    pulumi.export("service_url", environment.service_url)
    pulumi.export("pgadmin_url", environment.pgadmin_url)
    pulumi.export("upstream_hosts", list(environment.upstream_hosts))
    return env_config, environment


pulumi.export("metadata", build_project_metadata())
if pulumi.Config("devforge-cloud").get("environment") is not None:
    orchestrate_infrastructure()
