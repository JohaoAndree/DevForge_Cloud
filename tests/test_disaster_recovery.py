"""Verifica la configuracion, el grafo y los planes del sello de recuperacion."""

from dataclasses import replace
from unittest.mock import patch

import pulumi
import pulumi.runtime
import pytest

from components.config_loader import EnvironmentConfig, load_environment_config
from components.disaster_recovery import build_backup_restore_plan, build_failover_transition
from components.environment_stack import DevForgeEnvironment
from tests.test_environment_stack import _EnvironmentMocks, environment_mocks
from tests.test_stack_isolation import _config_environment, _stack_values


def _load_dr_config(**overrides: str | int | bool) -> EnvironmentConfig:
    stack_config = _stack_values("dr")
    stack_config.update({f"devforge-cloud:{key}": value for key, value in overrides.items()})
    with patch.dict("os.environ", _config_environment(stack_config)):
        return load_environment_config(pulumi.Config("devforge-cloud"), stack_name="dr")


def test_dr_yaml_defines_pilot_light_topology_without_port_collisions() -> None:
    """Garantiza una configuracion de espera con identidad y puerto propios."""
    configs = [_stack_values(stack_name) for stack_name in ("dev", "prod", "dr")]
    dr = configs[-1]
    assert dr == {
        "devforge-cloud:environment": "dr",
        "devforge-cloud:dr_mode": "pilot-light",
        "devforge-cloud:replicas": 0,
        "devforge-cloud:lb_port": 8090,
        "devforge-cloud:enable_pgadmin": False,
        "devforge-cloud:pgadmin_port": 5050,
        "devforge-cloud:db_name": "devforgedb",
        "devforge-cloud:db_user": "devforge_user",
        "devforge-cloud:primary_stack": "prod",
        "devforge-cloud:rpo_minutes": 15,
        "devforge-cloud:rto_seconds": 10,
    }
    assert dr["devforge-cloud:enable_pgadmin"] is False
    assert [config["devforge-cloud:environment"] for config in configs] == ["dev", "prod", "dr"]
    assert [config["devforge-cloud:lb_port"] for config in configs] == [8080, 80, 8090]


def test_load_environment_config_enforces_pilot_light_and_failover_rules() -> None:
    """Garantiza replicas coherentes con el modo y PgAdmin desactivado en dr."""
    pilot_light = _load_dr_config()
    assert (pilot_light.dr_mode, pilot_light.replicas) == ("pilot-light", 0)

    failover = _load_dr_config(dr_mode="failover", replicas=3, rpo_minutes=30, rto_seconds=20)
    assert (failover.dr_mode, failover.replicas) == ("failover", 3)
    assert (failover.rpo_minutes, failover.rto_seconds) == (30, 20)

    for overrides, field in (
        ({"replicas": 2}, "replicas"),
        ({"dr_mode": "failover"}, "replicas"),
        ({"dr_mode": "active"}, "replicas"),
        ({"enable_pgadmin": True}, "enable_pgadmin"),
        ({"dr_mode": "invalid"}, "dr_mode"),
        ({"rpo_minutes": 0}, "rpo_minutes"),
        ({"rto_seconds": 0}, "rto_seconds"),
    ):
        with pytest.raises(ValueError, match=field):
            _load_dr_config(**overrides)


def test_pilot_light_stamp_provisions_warm_db_zero_apps_and_standby_gateway(
    environment_mocks: _EnvironmentMocks,
) -> None:
    """Garantiza persistencia privada y un gateway 503 en ausencia de replicas."""
    @pulumi.runtime.test
    def _verify_graph() -> pulumi.Output[None]:
        env = DevForgeEnvironment("devforge-dr-env", _load_dr_config())
        assert env.dr_mode == "pilot-light"
        assert env.db_container is not None
        assert env.app_containers == ()
        assert env.upstream_hosts == ()
        assert 'return 503 "DevForge DR Stamp (dr) in Pilot Light Standby' in env.nginx_conf
        assert 'Database Warm, Compute Scaled to 0\\n";' in env.nginx_conf
        assert "default_type text/plain;" in env.nginx_conf
        assert "listen 80;" in env.nginx_conf
        assert "\r" not in env.nginx_conf

        def _assert_graph(_resolved: list[str]) -> None:
            resources = {resource.name: resource.inputs for resource in environment_mocks.resources}
            assert set(resources) == {
                "devforge-dr-env", "devforge-dr-network", "devforge-dr-db-vol",
                "devforge-dr-db", "devforge-dr-lb",
            }
            assert resources["devforge-dr-network"]["name"] == "devforge-dr-net"
            assert resources["devforge-dr-network"]["driver"] == "bridge"
            assert resources["devforge-dr-db-vol"]["name"] == "devforge-dr-pgdata"
            database = resources["devforge-dr-db"]
            assert database["image"] == "postgres:16-alpine"
            assert database.get("ports", []) == []
            assert database["networksAdvanced"] == [{"name": "devforge-dr-net"}]
            assert database["volumes"] == [{
                "volumeName": "devforge-dr-pgdata",
                "containerPath": "/var/lib/postgresql/data",
            }]
            gateway = resources["devforge-dr-lb"]
            assert gateway["ports"] == [{"internal": 80, "external": 8090}]
            assert gateway["uploads"] == [{
                "file": "/etc/nginx/nginx.conf", "content": env.nginx_conf,
            }]

        return pulumi.Output.all(env.db_container.urn, env.load_balancer.urn).apply(_assert_graph)

    _verify_graph()


def test_failover_mode_scales_dr_stamp_to_three_balanced_replicas(
    environment_mocks: _EnvironmentMocks,
) -> None:
    """Garantiza que el gateway de failover distribuye trafico a las tres replicas."""
    @pulumi.runtime.test
    def _verify_graph() -> pulumi.Output[None]:
        config = _load_dr_config(dr_mode="failover", replicas=3)
        env = DevForgeEnvironment("devforge-dr-env", config)
        expected_apps = [f"devforge-dr-app-{index}" for index in range(1, 4)]
        assert env.dr_mode == "failover"
        assert len(env.app_containers) == 3
        assert env.upstream_hosts == tuple(f"{name}:80" for name in expected_apps)
        upstream = env.nginx_conf.split("upstream devforge_backend {", 1)[1].split("}", 1)[0]
        assert [line.strip() for line in upstream.strip().splitlines()] == [
            f"server {name}:80;" for name in expected_apps
        ]
        assert "proxy_pass http://devforge_backend;" in env.nginx_conf
        assert "return 503" not in env.nginx_conf

        def _assert_graph(_resolved: list[str]) -> None:
            applications = [
                resource.inputs["name"] for resource in environment_mocks.resources
                if resource.inputs.get("image") == "traefik/whoami:v1.10"
            ]
            assert sorted(applications) == expected_apps
            gateway = next(
                resource.inputs for resource in environment_mocks.resources
                if resource.name == "devforge-dr-lb"
            )
            assert gateway["uploads"][0]["content"] == env.nginx_conf

        return pulumi.Output.all(
            *(container.urn for container in env.app_containers), env.load_balancer.urn,
        ).apply(_assert_graph)

    _verify_graph()


def test_build_backup_restore_and_failover_plans_are_deterministic() -> None:
    """Garantiza comandos reproducibles, exportaciones independientes y entradas validas."""
    config = _load_dr_config()
    backup_plan = build_backup_restore_plan(config)
    backup_file = "backups/prod_to_dr_devforgedb.sql"
    assert backup_plan.to_dict() == {
        "source_stack": "prod",
        "target_stack": "dr",
        "source_db_container": "devforge-prod-db",
        "target_db_container": "devforge-dr-db",
        "db_name": "devforgedb",
        "db_user": "devforge_user",
        "backup_file_path": backup_file,
        "backup_command": "docker exec devforge-prod-db pg_dump -U devforge_user -d devforgedb"
                          f" --clean --if-exists > {backup_file}",
        "restore_command": f"Get-Content {backup_file} | docker exec -i devforge-dr-db"
                           " psql -U devforge_user -d devforgedb",
        "rpo_minutes": 15,
        "rto_seconds": 10,
    }
    assert backup_plan == build_backup_restore_plan(config, "backups/")
    exported_backup = backup_plan.to_dict()
    exported_backup["target_stack"] = "dev"
    assert backup_plan.to_dict()["target_stack"] == "dr"

    promotion_commands = (
        "pulumi config set devforge-cloud:dr_mode failover --stack dr",
        "pulumi config set devforge-cloud:replicas 3 --stack dr",
        "pulumi up --yes --stack dr",
    )
    failover = build_failover_transition(config)
    assert failover.promotion_commands == promotion_commands
    assert failover.to_dict() == {
        "stack_name": "dr",
        "previous_mode": "pilot-light",
        "target_mode": "failover",
        "previous_replicas": 0,
        "target_replicas": 3,
        "promotion_commands": list(promotion_commands),
    }
    assert failover == build_failover_transition(config, target_replicas=3)
    assert failover.to_dict()["promotion_commands"] is not failover.to_dict()["promotion_commands"]

    with pytest.raises(ValueError, match="backup_dir"):
        build_backup_restore_plan(config, "  ")
    with pytest.raises(ValueError, match="primary_stack"):
        build_backup_restore_plan(replace(config, primary_stack="dr"))
    with pytest.raises(ValueError, match="target_replicas"):
        build_failover_transition(config, target_replicas=0)
