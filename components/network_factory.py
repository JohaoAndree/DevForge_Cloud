"""Define la red Docker aislada de cada stack."""

import pulumi
import pulumi_docker

from components.config_loader import EnvironmentConfig


def create_isolated_network(
    env_config: EnvironmentConfig, opts: pulumi.ResourceOptions | None = None
) -> pulumi_docker.Network:
    """Crea una red bridge con identidad propia del stack."""
    return pulumi_docker.Network(
        resource_name=f"devforge-{env_config.stack_name}-network",
        name=env_config.network_name,
        driver="bridge",
        opts=opts,
    )
