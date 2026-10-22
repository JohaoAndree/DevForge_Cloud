"""Carga y valida el contrato de configuracion de cada entorno."""

from dataclasses import asdict, dataclass

import pulumi


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

    if replicas < 1:
        raise ValueError("replicas debe ser mayor o igual a 1")
    if not 1 <= lb_port <= 65535:
        raise ValueError("lb_port debe estar entre 1 y 65535")
    if not 1 <= pgadmin_port <= 65535:
        raise ValueError("pgadmin_port debe estar entre 1 y 65535")
    if lb_port == pgadmin_port:
        raise ValueError("lb_port y pgadmin_port deben ser distintos")
    if environment == "prod" and enable_pgadmin is True:
        raise ValueError("enable_pgadmin debe ser false en prod")

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
    )
