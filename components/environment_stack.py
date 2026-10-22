"""Encapsula la topologia Docker de un entorno DevForge."""

import pulumi
import pulumi_docker

from components.config_loader import EnvironmentConfig
from components.load_balancer_conf import (
    build_upstream_hosts,
    render_nginx_load_balancer_conf,
)
from components.network_factory import create_isolated_network


POSTGRES_IMAGE = "postgres:16-alpine"
PGADMIN_IMAGE = "dpage/pgadmin4:latest"
BACKEND_IMAGE = "traefik/whoami:v1.10"
NGINX_IMAGE = "nginx:1.27-alpine"


class DevForgeEnvironment(pulumi.ComponentResource):
    """Agrupa red, persistencia, aplicaciones y balanceador de un stack."""

    def __init__(
        self,
        name: str,
        env_config: EnvironmentConfig,
        db_password: pulumi.Input[str] | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ) -> None:
        """Declara los recursos hijos y registra los outputs del entorno."""
        super().__init__("devforge:cloud:DevForgeEnvironment", name, None, opts)
        child_opts = pulumi.ResourceOptions(parent=self)
        resolved_password = pulumi.Output.secret(
            f"devforge-{env_config.stack_name}-local-secret"
            if db_password is None else db_password
        )
        self.network = create_isolated_network(env_config, opts=child_opts)
        self.db_volume = pulumi_docker.Volume(
            resource_name=f"devforge-{env_config.stack_name}-db-vol",
            name=f"devforge-{env_config.stack_name}-pgdata",
            opts=child_opts,
        )
        self.db_container = pulumi_docker.Container(
            resource_name=f"devforge-{env_config.stack_name}-db",
            name=f"devforge-{env_config.stack_name}-db",
            image=POSTGRES_IMAGE,
            restart="unless-stopped",
            networks_advanced=[
                pulumi_docker.ContainerNetworksAdvancedArgs(name=self.network.name)
            ],
            volumes=[pulumi_docker.ContainerVolumeArgs(
                volume_name=self.db_volume.name,
                container_path="/var/lib/postgresql/data",
            )],
            envs=[
                f"POSTGRES_DB={env_config.db_name}",
                f"POSTGRES_USER={env_config.db_user}",
                resolved_password.apply(lambda password: f"POSTGRES_PASSWORD={password}"),
            ],
            ports=[],
            opts=child_opts,
        )
        self.pgadmin_container: pulumi_docker.Container | None = None
        if env_config.enable_pgadmin:
            self.pgadmin_container = pulumi_docker.Container(
                resource_name=f"devforge-{env_config.stack_name}-pgadmin",
                name=f"devforge-{env_config.stack_name}-pgadmin",
                image=PGADMIN_IMAGE,
                restart="unless-stopped",
                networks_advanced=[
                    pulumi_docker.ContainerNetworksAdvancedArgs(name=self.network.name)
                ],
                ports=[pulumi_docker.ContainerPortArgs(
                    internal=80, external=env_config.pgadmin_port,
                )],
                envs=[
                    "PGADMIN_DEFAULT_EMAIL=admin@example.com",
                    resolved_password.apply(
                        lambda password: f"PGADMIN_DEFAULT_PASSWORD={password}"
                    ),
                ],
                opts=child_opts,
            )
        self.app_containers: tuple[pulumi_docker.Container, ...] = tuple(
            pulumi_docker.Container(
                resource_name=f"devforge-{env_config.stack_name}-app-{index}",
                name=f"devforge-{env_config.stack_name}-app-{index}",
                image=BACKEND_IMAGE,
                restart="unless-stopped",
                networks_advanced=[
                    pulumi_docker.ContainerNetworksAdvancedArgs(name=self.network.name)
                ],
                envs=[
                    f"WHOAMI_NAME=devforge-{env_config.stack_name}-app-{index}",
                    f"DB_HOST=devforge-{env_config.stack_name}-db",
                ],
                ports=[],
                opts=child_opts,
            )
            for index in range(1, env_config.replicas + 1)
        )
        self.upstream_hosts = build_upstream_hosts(
            env_config.stack_name, env_config.replicas,
        )
        self.nginx_conf = render_nginx_load_balancer_conf(self.upstream_hosts)
        self.load_balancer = pulumi_docker.Container(
            resource_name=f"devforge-{env_config.stack_name}-lb",
            name=f"devforge-{env_config.stack_name}-lb",
            image=NGINX_IMAGE,
            restart="unless-stopped",
            networks_advanced=[
                pulumi_docker.ContainerNetworksAdvancedArgs(name=self.network.name)
            ],
            ports=[pulumi_docker.ContainerPortArgs(
                internal=80, external=env_config.lb_port,
            )],
            uploads=[pulumi_docker.ContainerUploadArgs(
                file="/etc/nginx/nginx.conf", content=self.nginx_conf,
            )],
            opts=pulumi.ResourceOptions(
                parent=self, depends_on=list(self.app_containers),
            ),
        )
        self.service_url = f"http://localhost:{env_config.lb_port}"
        self.pgadmin_url = (
            f"http://localhost:{env_config.pgadmin_port}"
            if env_config.enable_pgadmin else None
        )
        self.register_outputs({
            "network_name": self.network.name,
            "service_url": self.service_url,
            "pgadmin_url": self.pgadmin_url,
            "replicas": env_config.replicas,
        })
