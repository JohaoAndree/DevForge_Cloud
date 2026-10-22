"""Verifica balanceo, jerarquia y aislamiento de la topologia Docker."""

import asyncio
from typing import Any, Iterator

import pulumi
import pulumi.runtime
import pytest

from components.config_loader import EnvironmentConfig
from components.environment_stack import DevForgeEnvironment
from components.load_balancer_conf import (
    build_upstream_hosts,
    render_nginx_load_balancer_conf,
)


class _EnvironmentMocks(pulumi.runtime.Mocks):
    """Captura el grafo de recursos sin acceder al daemon Docker."""

    def __init__(self) -> None:
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(
        self, args: pulumi.runtime.MockResourceArgs,
    ) -> tuple[str, dict[str, Any]]:
        """Conserva las propiedades de cada recurso registrado."""
        self.resources.append(args)
        return f"{args.name}_id", args.inputs

    def call(
        self, args: pulumi.runtime.MockCallArgs,
    ) -> tuple[dict[str, Any], None]:
        """Resuelve consultas sin contactar proveedores externos."""
        return {}, None


@pytest.fixture
def environment_mocks() -> Iterator[_EnvironmentMocks]:
    """Aisla el motor simulado y su ciclo de eventos por prueba."""
    event_loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(event_loop)
        mocks = _EnvironmentMocks()
        pulumi.runtime.set_mocks(mocks, project="devforge-cloud", stack="dev")
        yield mocks
    finally:
        event_loop.close()
        asyncio.set_event_loop(None)


def _environment_config(stack_name: str) -> EnvironmentConfig:
    return EnvironmentConfig(
        stack_name=stack_name,
        environment=stack_name,
        replicas=1 if stack_name == "dev" else 3,
        lb_port=8080 if stack_name == "dev" else 80,
        enable_pgadmin=stack_name == "dev",
        pgadmin_port=5050,
        db_name="devforgedb",
        db_user="devforge_user",
        network_name=f"devforge-{stack_name}-net",
    )


def test_render_nginx_load_balancer_conf_lists_all_replicas_in_order() -> None:
    """Garantiza tres destinos ordenados y cabeceras del proxy en Nginx."""
    hosts = build_upstream_hosts("prod", 3)
    assert hosts == (
        "devforge-prod-app-1:80", "devforge-prod-app-2:80", "devforge-prod-app-3:80",
    )
    configuration = render_nginx_load_balancer_conf(hosts)
    upstream = configuration.split("upstream devforge_backend {", 1)[1].split("}", 1)[0]
    assert upstream.strip().splitlines() == [
        "server devforge-prod-app-1:80;",
        "        server devforge-prod-app-2:80;",
        "        server devforge-prod-app-3:80;",
    ]
    assert "events {\n    worker_connections 1024;\n}" in configuration
    assert "listen 80;" in configuration
    assert "location / {" in configuration
    assert "proxy_pass http://devforge_backend;" in configuration
    assert "proxy_set_header Host $host;" in configuration
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in configuration
    assert "\r" not in configuration
    assert configuration == render_nginx_load_balancer_conf(list(hosts))


@pytest.mark.parametrize("stack_name,replicas", [("dev", 0), ("prod", -1), ("", 1), ("  ", 1)])
def test_build_upstream_hosts_rejects_invalid_inputs(
    stack_name: str, replicas: int,
) -> None:
    """Rechaza nombres vacios y cantidades no positivas de replicas."""
    with pytest.raises(ValueError):
        build_upstream_hosts(stack_name, replicas)


@pytest.mark.parametrize("hosts", [(), []])
def test_render_nginx_load_balancer_conf_rejects_empty_hosts(
    hosts: tuple[str, ...] | list[str],
) -> None:
    """Rechaza una tabla de balanceo sin destinos."""
    with pytest.raises(ValueError, match="upstream_hosts"):
        render_nginx_load_balancer_conf(hosts)


def _verify_environment(mocks: _EnvironmentMocks, stack_name: str) -> None:
    @pulumi.runtime.test
    def _verify_graph() -> pulumi.Output[None]:
        config = _environment_config(stack_name)
        env = DevForgeEnvironment(f"devforge-{stack_name}-env", config)
        assert isinstance(env, pulumi.ComponentResource)
        assert isinstance(env.app_containers, tuple)
        assert len(env.app_containers) == config.replicas
        assert env.service_url == f"http://localhost:{config.lb_port}"
        if config.enable_pgadmin:
            assert env.pgadmin_container is not None
            assert env.pgadmin_url == "http://localhost:5050"
        else:
            assert env.pgadmin_container is None
            assert env.pgadmin_url is None
        children = [env.network, env.db_volume, env.db_container, *env.app_containers, env.load_balancer]
        if env.pgadmin_container is not None:
            children.append(env.pgadmin_container)

        def _assert_graph(resolved: list[Any]) -> None:
            assert all(
                "devforge:cloud:DevForgeEnvironment$" in urn
                for urn in resolved[:len(children)]
            )
            assert resolved[-1] is True
            resources = {resource.name: resource for resource in mocks.resources}
            prefix = f"devforge-{stack_name}"
            assert len(resources) == len(children) + 1
            assert resources[f"{prefix}-network"].inputs["driver"] == "bridge"
            assert resources[f"{prefix}-db-vol"].inputs["name"] == f"{prefix}-pgdata"
            database = resources[f"{prefix}-db"].inputs
            assert database.get("ports", []) == []
            assert database["image"] == "postgres:16-alpine"
            assert database["volumes"] == [{
                "volumeName": f"{prefix}-pgdata",
                "containerPath": "/var/lib/postgresql/data",
            }]
            containers = [resource for resource in resources.values() if resource.typ == "docker:index/container:Container"]
            for container in containers:
                assert container.inputs["restart"] == "unless-stopped"
                assert container.inputs["networksAdvanced"] == [{"name": config.network_name}]
                assert not container.inputs.get("mounts")
                assert not container.inputs.get("host")
            for index in range(1, config.replicas + 1):
                backend = resources[f"{prefix}-app-{index}"].inputs
                assert backend["image"] == "traefik/whoami:v1.10"
                assert backend.get("ports", []) == []
                assert backend["envs"] == [f"WHOAMI_NAME={prefix}-app-{index}", f"DB_HOST={prefix}-db"]
            load_balancer = resources[f"{prefix}-lb"].inputs
            assert load_balancer["image"] == "nginx:1.27-alpine"
            assert load_balancer["ports"] == [{"internal": 80, "external": config.lb_port}]
            assert load_balancer["uploads"] == [{
                "file": "/etc/nginx/nginx.conf", "content": env.nginx_conf,
            }]
            assert env.upstream_hosts == build_upstream_hosts(stack_name, config.replicas)
            assert env.nginx_conf == render_nginx_load_balancer_conf(env.upstream_hosts)
            if config.enable_pgadmin:
                pgadmin = resources[f"{prefix}-pgadmin"].inputs
                assert pgadmin["image"] == "dpage/pgadmin4:latest"
                assert pgadmin["ports"] == [{"internal": 80, "external": 5050}]
            else:
                assert f"{prefix}-pgadmin" not in resources

        return pulumi.Output.all(
            *[child.urn for child in children],
            pulumi.Output.is_secret(env.db_container.envs),
        ).apply(_assert_graph)

    _verify_graph()


def test_dev_environment_provisions_pgadmin_and_single_replica(
    environment_mocks: _EnvironmentMocks,
) -> None:
    """Garantiza PgAdmin, una replica y persistencia privada en dev."""
    _verify_environment(environment_mocks, "dev")


def test_prod_environment_omits_pgadmin_and_provisions_three_replicas(
    environment_mocks: _EnvironmentMocks,
) -> None:
    """Garantiza tres replicas, persistencia privada y ausencia de PgAdmin en prod."""
    _verify_environment(environment_mocks, "prod")
