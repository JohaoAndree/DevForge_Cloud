"""Genera la configuracion determinista del balanceador Nginx."""


def build_upstream_hosts(stack_name: str, replicas: int) -> tuple[str, ...]:
    """Construye los destinos internos en orden ascendente de replica."""
    if replicas < 1:
        raise ValueError("replicas debe ser mayor o igual a 1")
    if not stack_name.strip():
        raise ValueError("stack_name no puede estar vacio")
    return tuple(
        f"devforge-{stack_name}-app-{index}:80"
        for index in range(1, replicas + 1)
    )


def render_nginx_load_balancer_conf(
    upstream_hosts: tuple[str, ...] | list[str],
) -> str:
    """Renderiza los destinos en el orden recibido con balanceo Round-Robin."""
    if not upstream_hosts:
        raise ValueError("upstream_hosts debe contener al menos un destino")
    upstream_servers = "\n".join(f"        server {host};" for host in upstream_hosts)
    return (
        "events {\n"
        "    worker_connections 1024;\n"
        "}\n"
        "\n"
        "http {\n"
        "    upstream devforge_backend {\n"
        f"{upstream_servers}\n"
        "    }\n"
        "\n"
        "    server {\n"
        "        listen 80;\n"
        "        location / {\n"
        "            proxy_pass http://devforge_backend;\n"
        "            proxy_set_header Host $host;\n"
        "            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
