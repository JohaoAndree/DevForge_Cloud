"""Verifica configuracion y aislamiento del grafo multi-entorno."""

import asyncio
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import runpy
from typing import Any, Iterator
from unittest.mock import patch

import pulumi
import pulumi.runtime
import pytest
import yaml

from components.config_loader import load_environment_config
from components.network_factory import create_isolated_network


def _stack_values(stack_name: str) -> dict[str, Any]:
    stack_path = Path(__file__).resolve().parents[1] / f"Pulumi.{stack_name}.yaml"
    return yaml.safe_load(stack_path.read_text(encoding="utf-8"))["config"]


def _config_environment(values: dict[str, Any]) -> dict[str, str]:
    return {"PULUMI_CONFIG": json.dumps({
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in values.items()
    })}


class _NetworkMocks(pulumi.runtime.Mocks):
    """Captura recursos sin contactar al daemon Docker."""

    def __init__(self) -> None:
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(
        self, args: pulumi.runtime.MockResourceArgs
    ) -> tuple[str, dict[str, Any]]:
        """Conserva identidad y propiedades del recurso registrado."""
        self.resources.append(args)
        return f"{args.name}_id", args.inputs

    def call(
        self, args: pulumi.runtime.MockCallArgs
    ) -> tuple[dict[str, Any], None]:
        """Devuelve una consulta vacia sin acceder al proveedor."""
        return {}, None


@pytest.fixture
def network_mocks() -> Iterator[_NetworkMocks]:
    """Aisla el motor simulado y su ciclo de eventos por prueba."""
    event_loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(event_loop)
        mocks = _NetworkMocks()
        pulumi.runtime.set_mocks(mocks, project="devforge-cloud", stack="dev")
        yield mocks
    finally:
        event_loop.close()
        asyncio.set_event_loop(None)


def test_stack_yaml_files_define_non_colliding_topologies() -> None:
    """Garantiza parametros exactos y entradas distintas entre stacks."""
    for stack_name, replicas, lb_port, enable_pgadmin in (
        ("dev", 1, 8080, True), ("prod", 3, 80, False)
    ):
        assert _stack_values(stack_name) == {
            "devforge-cloud:environment": stack_name,
            "devforge-cloud:replicas": replicas,
            "devforge-cloud:lb_port": lb_port,
            "devforge-cloud:enable_pgadmin": enable_pgadmin,
            "devforge-cloud:pgadmin_port": 5050,
            "devforge-cloud:db_name": "devforgedb",
            "devforge-cloud:db_user": "devforge_user",
        }
    assert _stack_values("dev")["devforge-cloud:lb_port"] != _stack_values("prod")[
        "devforge-cloud:lb_port"
    ]


@pytest.mark.parametrize("stack_name", ["dev", "prod"])
def test_load_environment_config_preserves_immutable_contract(stack_name: str) -> None:
    """Garantiza carga tipada, inmutabilidad y exportaciones independientes."""
    values = _stack_values(stack_name)
    with patch.dict("os.environ", _config_environment(values)):
        env_config = load_environment_config(pulumi.Config("devforge-cloud"), stack_name)
    expected = {key.split(":", 1)[1]: value for key, value in values.items()}
    expected.update(stack_name=stack_name, network_name=f"devforge-{stack_name}-net")
    assert env_config.to_export_dict() == expected
    assert type(env_config.replicas) is int
    assert type(env_config.enable_pgadmin) is bool
    with pytest.raises(FrozenInstanceError):
        env_config.replicas = 9
    exported = env_config.to_export_dict()
    exported["replicas"] = 9
    assert env_config.to_export_dict() == expected


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("enable_pgadmin", True, "enable_pgadmin"),
        ("replicas", 0, "replicas"),
        ("replicas", -1, "replicas"),
        ("lb_port", 0, "lb_port"),
        ("lb_port", 65536, "lb_port"),
        ("pgadmin_port", 0, "pgadmin_port"),
        ("pgadmin_port", 65536, "pgadmin_port"),
        ("lb_port", 5050, "distintos"),
    ],
)
def test_load_environment_config_rejects_pgadmin_in_prod(
    key: str, value: int | bool, message: str
) -> None:
    """Rechaza PgAdmin en prod, replicas invalidas y puertos invalidos o iguales."""
    values = _stack_values("prod")
    values[f"devforge-cloud:{key}"] = value
    with patch.dict("os.environ", _config_environment(values)):
        with pytest.raises(ValueError, match=message):
            load_environment_config(pulumi.Config("devforge-cloud"), "prod")


@pytest.mark.parametrize("stack_name", ["dev", "prod"])
def test_create_isolated_network_uses_stack_prefix(
    network_mocks: _NetworkMocks, stack_name: str
) -> None:
    """Garantiza nombres logicos y fisicos por stack con driver bridge."""
    @pulumi.runtime.test
    def _verify_network() -> pulumi.Output[None]:
        with patch.dict("os.environ", _config_environment(_stack_values(stack_name))):
            env_config = load_environment_config(stack_name=stack_name)
        network = create_isolated_network(env_config)

        def _assert_network(network_name: str) -> None:
            assert network_name == f"devforge-{stack_name}-net"
            resources = [
                resource for resource in network_mocks.resources
                if resource.typ == "docker:index/network:Network"
            ]
            assert len(resources) == 1
            assert resources[0].name == f"devforge-{stack_name}-network"
            assert resources[0].inputs["name"] == network_name
            assert resources[0].inputs["driver"] == "bridge"

        return network.name.apply(_assert_network)

    _verify_network()


def test_entrypoint_exports_environment_and_network(network_mocks: _NetworkMocks) -> None:
    """Garantiza orquestacion automatica y outputs con configuracion activa."""
    @pulumi.runtime.test
    def _verify_exports() -> pulumi.Output[None]:
        entrypoint_path = Path(__file__).resolve().parents[1] / "__main__.py"
        with patch.dict("os.environ", _config_environment(_stack_values("dev"))):
            expected = load_environment_config().to_export_dict()
            with patch("pulumi.export", wraps=pulumi.export) as export_outputs:
                runpy.run_path(str(entrypoint_path))

        assert [call.args[0] for call in export_outputs.call_args_list] == [
            "metadata", "environment_config", "network_name",
            "service_url", "pgadmin_url", "upstream_hosts",
        ]
        assert export_outputs.call_args_list[1].args[1] == expected
        assert export_outputs.call_args_list[3].args[1] == "http://localhost:8080"
        assert export_outputs.call_args_list[4].args[1] == "http://localhost:5050"
        assert export_outputs.call_args_list[5].args[1] == ["devforge-dev-app-1:80"]

        def _assert_exports(network_name: str) -> None:
            assert network_name == "devforge-dev-net"
            networks = [
                resource for resource in network_mocks.resources
                if resource.typ == "docker:index/network:Network"
            ]
            assert len(networks) == 1
            assert networks[0].inputs["name"] == network_name
            assert networks[0].inputs["driver"] == "bridge"

        return export_outputs.call_args_list[2].args[1].apply(_assert_exports)

    _verify_exports()
