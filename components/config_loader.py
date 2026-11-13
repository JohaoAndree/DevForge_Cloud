"""Carga y valida el contrato de configuracion de cada entorno."""

from dataclasses import asdict, dataclass

import pulumi


VALID_DR_MODES: tuple[str, ...] = ("active", "pilot-light", "failover")


@dataclass(frozen=True)
class EnvironmentConfig:
    """Define la configuracion inmutable de un entorno aislado."""

    stack_name: str
    environment: str
    replicas: int
    lb_port: int
    enable_pgadmin: bool
    pgadmin_port: int
    db_name: str
    db_user: str
    network_name: str
    dr_mode: str = "active"
    primary_stack: str = "prod"
    rpo_minutes: int = 15
    rto_seconds: int = 10

    def to_export_dict(self) -> dict[str, str | int | bool]:
        """Devuelve una copia de todos los campos para exportacion."""
        return asdict(self)


def load_environment_config(
    config: pulumi.Config | None = None, stack_name: str | None = None
) -> EnvironmentConfig:
    """Carga parametros requeridos y rechaza topologias invalidas."""
    resolved_config = config if config is not None else pulumi.Config("devforge-cloud")
    resolved_stack = stack_name if stack_name is not None else pulumi.get_stack()
    environment = resolved_config.require("environment")
    replicas = resolved_config.require_int("replicas")
    lb_port = resolved_config.require_int("lb_port")
    enable_pgadmin = resolved_config.require_bool("enable_pgadmin")
    pgadmin_port = resolved_config.require_int("pgadmin_port")
    db_name = resolved_config.require("db_name")
    db_user = resolved_config.require("db_user")
    dr_mode = resolved_config.get("dr_mode") or "active"
    primary_stack = resolved_config.get("primary_stack") or "prod"
    rpo_minutes = resolved_config.get_int("rpo_minutes")
    rto_seconds = resolved_config.get_int("rto_seconds")
    rpo_minutes = rpo_minutes if rpo_minutes is not None else 15
    rto_seconds = rto_seconds if rto_seconds is not None else 10

    if dr_mode not in VALID_DR_MODES:
        raise ValueError(f"dr_mode debe ser uno de: {', '.join(VALID_DR_MODES)}")
    if dr_mode == "pilot-light" and replicas != 0:
        raise ValueError("replicas debe ser 0 en modo pilot-light")
    if dr_mode in ("active", "failover") and replicas < 1:
        raise ValueError("replicas debe ser mayor o igual a 1")
    if not 1 <= lb_port <= 65535:
        raise ValueError("lb_port debe estar entre 1 y 65535")
    if not 1 <= pgadmin_port <= 65535:
        raise ValueError("pgadmin_port debe estar entre 1 y 65535")
    if lb_port == pgadmin_port:
        raise ValueError("lb_port y pgadmin_port deben ser distintos")
    if environment in ("prod", "dr") and enable_pgadmin is True:
        raise ValueError(f"enable_pgadmin debe ser false en {environment}")
    if rpo_minutes < 1:
        raise ValueError("rpo_minutes debe ser mayor o igual a 1")
    if rto_seconds < 1:
        raise ValueError("rto_seconds debe ser mayor o igual a 1")

    return EnvironmentConfig(
        stack_name=resolved_stack,
        environment=environment,
        replicas=replicas,
        lb_port=lb_port,
        enable_pgadmin=enable_pgadmin,
        pgadmin_port=pgadmin_port,
        db_name=db_name,
        db_user=db_user,
        network_name=f"devforge-{resolved_stack}-net",
        dr_mode=dr_mode,
        primary_stack=primary_stack,
        rpo_minutes=rpo_minutes,
        rto_seconds=rto_seconds,
    )
