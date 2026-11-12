"""Define los planes declarativos de respaldo y conmutacion de un stack."""

from dataclasses import asdict, dataclass

from components.config_loader import EnvironmentConfig


@dataclass(frozen=True)
class BackupRestorePlan:
    """Describe el respaldo logico y su restauracion entre stacks."""

    source_stack: str
    target_stack: str
    source_db_container: str
    target_db_container: str
    db_name: str
    db_user: str
    backup_file_path: str
    backup_command: str
    restore_command: str
    rpo_minutes: int
    rto_seconds: int

    def to_dict(self) -> dict[str, str | int]:
        """Devuelve una copia de los campos para exportacion."""
        return asdict(self)


@dataclass(frozen=True)
class FailoverTransitionSpec:
    """Describe el estado inicial y la promocion declarativa de un stack."""

    stack_name: str
    previous_mode: str
    target_mode: str
    previous_replicas: int
    target_replicas: int
    promotion_commands: tuple[str, ...]

    def to_dict(self) -> dict[str, str | int | list[str]]:
        """Devuelve una copia exportable con los comandos en una lista."""
        exported = asdict(self)
        exported["promotion_commands"] = list(self.promotion_commands)
        return exported


def build_backup_restore_plan(
    env_config: EnvironmentConfig, backup_dir: str = "backups",
) -> BackupRestorePlan:
    """Construye los comandos de respaldo y restauracion para el entorno."""
    if not backup_dir.strip():
        raise ValueError("backup_dir no puede estar vacio")
    if env_config.environment == "dr" and env_config.primary_stack == env_config.stack_name:
        raise ValueError("primary_stack debe ser distinto del stack de recuperacion")

    source_db = f"devforge-{env_config.primary_stack}-db"
    target_db = f"devforge-{env_config.stack_name}-db"
    backup_file = (
        f"{backup_dir.rstrip('/')}/"
        f"{env_config.primary_stack}_to_{env_config.stack_name}_{env_config.db_name}.sql"
    )
    backup_command = (
        f"docker exec {source_db} pg_dump -U {env_config.db_user} -d {env_config.db_name}"
        f" --clean --if-exists > {backup_file}"
    )
    restore_command = (
        f"Get-Content {backup_file} | docker exec -i {target_db}"
        f" psql -U {env_config.db_user} -d {env_config.db_name}"
    )
    return BackupRestorePlan(
        source_stack=env_config.primary_stack,
        target_stack=env_config.stack_name,
        source_db_container=source_db,
        target_db_container=target_db,
        db_name=env_config.db_name,
        db_user=env_config.db_user,
        backup_file_path=backup_file,
        backup_command=backup_command,
        restore_command=restore_command,
        rpo_minutes=env_config.rpo_minutes,
        rto_seconds=env_config.rto_seconds,
    )


def build_failover_transition(
    env_config: EnvironmentConfig, target_replicas: int = 3,
) -> FailoverTransitionSpec:
    """Calcula los comandos para activar el sello con replicas disponibles."""
    if target_replicas < 1:
        raise ValueError("target_replicas debe ser mayor o igual a 1")

    stack_name = env_config.stack_name
    return FailoverTransitionSpec(
        stack_name=stack_name,
        previous_mode=env_config.dr_mode,
        target_mode="failover",
        previous_replicas=env_config.replicas,
        target_replicas=target_replicas,
        promotion_commands=(
            f"pulumi config set devforge-cloud:dr_mode failover --stack {stack_name}",
            f"pulumi config set devforge-cloud:replicas {target_replicas} --stack {stack_name}",
            f"pulumi up --yes --stack {stack_name}",
        ),
    )
