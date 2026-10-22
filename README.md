# DevForge Cloud

Aprovisionador declarativo de entornos multi-entorno (`dev` y `prod`) con **Pulumi + Python** sobre **Docker local**. Con un solo comando (`pulumi up`) levanta una red privada, una base de datos PostgreSQL con volumen persistente, N réplicas de una aplicación de ejemplo y un balanceador Nginx Round-Robin. Reemplaza los scripts imperativos de *DevForge v1.0* (PowerShell + `winget`) por infraestructura como código con estado, idempotencia y detección de *drift*.

> **Alcance actual:** ADR-001 a ADR-003 están implementados (base del proyecto, stacks `dev`/`prod`, componente `DevForgeEnvironment` con balanceo). *Policy as Code*, adaptador cloud y GitHub Actions (ADR-004) están especificados en `docs/adrs/ADR-004.md`, pero **aún no existen en el repositorio**.

## Tecnologías

| Componente | Detalle |
| :--- | :--- |
| Lenguaje | Python `>=3.10` |
| IaC | Pulumi (`pulumi>=3.100.0,<4.0.0`) con `pulumi-docker>=4.5.0,<5.0.0` |
| Pruebas | `pytest>=8.0.0,<9.0.0`, `pyyaml>=6.0.1,<7.0.0` |
| Runtime | Docker (Docker Desktop en el entorno de referencia: Windows 11) |
| Imágenes | `postgres:16-alpine`, `traefik/whoami:v1.10`, `nginx:1.27-alpine`, `dpage/pgadmin4:latest` (solo `dev`) |

## Qué crea cada stack

Todos los recursos llevan el nombre del stack como prefijo (`devforge-<stack>-…`), por lo que `dev` y `prod` pueden coexistir en el mismo Docker.

| | `dev` | `prod` |
| :--- | :--- | :--- |
| Réplicas de la app (`whoami`) | 1 | 3 |
| Balanceador (Nginx) en el host | `http://localhost:8080` | `http://localhost:80` |
| pgAdmin | `http://localhost:5050` | no se despliega |
| Red Docker | `devforge-dev-net` | `devforge-prod-net` |
| Volumen de PostgreSQL | `devforge-dev-pgdata` | `devforge-prod-pgdata` |

PostgreSQL y las réplicas **no publican puertos** al host: solo el balanceador (y pgAdmin en `dev`) son accesibles desde fuera.

**Outputs del stack:** `metadata`, `environment_config`, `network_name`, `service_url`, `pgadmin_url`, `upstream_hosts`.

```
.
├── __main__.py              # Punto de entrada: carga config, crea el entorno, exporta outputs
├── components/
│   ├── config_loader.py     # EnvironmentConfig (inmutable) y validaciones
│   ├── network_factory.py   # Red bridge aislada por stack
│   ├── load_balancer_conf.py# Upstreams y nginx.conf (Round-Robin)
│   └── environment_stack.py # ComponentResource DevForgeEnvironment
├── tests/                   # pytest con mocks de Pulumi (no usan Docker)
├── docs/                    # ADR-001..004, walkthroughs y contexto maestro
├── Pulumi.yaml              # Proyecto "devforge-cloud", runtime Python con virtualenv "venv"
├── Pulumi.dev.yaml          # Configuración del stack dev
├── Pulumi.prod.yaml         # Configuración del stack prod
└── requirements.txt
```

## Requisitos previos

- **Python 3.10 o superior** (`python --version`).
- **Docker** instalado y **con el motor en ejecución**. En Windows, abre Docker Desktop y espera a que indique que el motor está activo; `docker info` debe responder sin error.
- **Pulumi CLI** instalado ([instrucciones](https://www.pulumi.com/docs/install/)). Es un ejecutable aparte: `pip install -r requirements.txt` solo instala el SDK de Python. Tras instalarlo, abre una terminal nueva y comprueba `pulumi version`. El repositorio no fija versión (la demo `dev` se ejecutó con v3.271.0).
- Puertos libres en el host: `8080` y `5050` (`dev`), `80` (`prod`).
- Acceso a internet: Docker Hub (imágenes) y, en la primera ejecución, la descarga automática del plugin `docker` de Pulumi.

No se necesita cuenta de Pulumi Cloud ni de ningún proveedor cloud: el estado se guarda localmente.

## Instalación y configuración

Todos los comandos se ejecutan **desde la raíz del repositorio**. Los ejemplos usan PowerShell (entorno de referencia del proyecto); en Linux/macOS reemplaza `venv\Scripts\python` por `venv/bin/python` y `$env:VAR = "x"` por `export VAR=x`.

**1. Crear el entorno virtual e instalar dependencias** (debe existir `venv/` antes de usar Pulumi, porque `Pulumi.yaml` apunta a él):

```powershell
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

**2. Usar el backend de estado local** (ADR-002):

```powershell
pulumi login --local
```

Pulumi responde `Logged in to … (file://~)`: el estado se guarda en tu carpeta de usuario, no dentro del repositorio.

**3. Definir la passphrase del estado local.** Debe estar definida en **cada terminal** donde ejecutes `pulumi`. Usa un valor de desarrollo no vacío (en PowerShell, asignar `""` elimina la variable):

```powershell
$env:PULUMI_CONFIG_PASSPHRASE = "devforge-local"
```

**4. (Opcional) Descargar las imágenes antes del primer despliegue:**

```powershell
docker pull postgres:16-alpine
docker pull traefik/whoami:v1.10
docker pull nginx:1.27-alpine
docker pull dpage/pgadmin4:latest
```

**5. (Recomendado) Ejecutar las pruebas ahora**, antes de crear stacks (ver [Pruebas funcionales](#pruebas-funcionales)).

## Guía de demo paso a paso

> **Estado de validación:** las tres demos (`dev`, autorreparación y `prod`), el registro del servidor en pgAdmin, la limpieza (`destroy`, `stack rm`, `git restore`) la suite `pytest`, `compileall -q .` y la limitación de Nginx descrita en la Demo 2 se ejecutaron en Windows con PowerShell 7, Docker Desktop, Python 3.14.2 y Pulumi v3.271.0 (plugin `docker` 4.11.2), con los resultados descritos abajo; `dev` y `prod` estuvieron activos a la vez.

Basta **una terminal** (PowerShell en la raíz del repositorio, con la passphrase definida y Docker Desktop abierto).

### Demo 1 — Stack `dev`

**1. Crear el stack.** Pulumi toma automáticamente `Pulumi.dev.yaml`:

```powershell
pulumi stack init dev
```

> **Pulumi modifica `Pulumi.dev.yaml`:** al crear el stack añade la línea `encryptionsalt` y reescribe `replicas`, `lb_port`, `enable_pgadmin` y `pgadmin_port` como strings (`"1"`, `"8080"`, `"true"`…). Con esos cambios, `test_stack_isolation.py` espera enteros y booleanos, por lo que fallan hasta 3 pruebas (2 si solo has creado `dev`). Ejecuta `pytest` **antes** de crear los stacks, o restaura los YAML al terminar (ver *Limpieza*). No hagas commit de esos cambios.

**2. Previsualizar y desplegar:**

```powershell
pulumi preview
pulumi up --yes
```

Esperado: `pulumi up` termina sin errores con `+ 8 created`: el `Stack`, el componente `DevForgeEnvironment` y 6 recursos hijos (red, volumen, base de datos, pgAdmin, 1 réplica y balanceador). La primera vez, Pulumi descarga e instala el plugin `docker`.

**3. Consultar los outputs:**

```powershell
pulumi stack output service_url
pulumi stack output pgadmin_url
pulumi stack output upstream_hosts
```

Esperado: `http://localhost:8080`, `http://localhost:5050` y `["devforge-dev-app-1:80"]`.

**4. Probar el servicio** (`curl.exe`, no `curl`, para evitar el alias de PowerShell):

```powershell
curl.exe http://localhost:8080
```

Esperado: respuesta de `traefik/whoami` cuya primera línea es `Name: devforge-dev-app-1`, seguida de `Hostname`, `IP`, y las cabeceras recibidas (incluida `X-Forwarded-For`, que añade el balanceador). También puedes abrir `http://localhost:8080` en el navegador.

**5. Verificar contenedores y aislamiento:**

```powershell
docker ps --filter "name=devforge-dev"
docker port devforge-dev-db
```

Esperado: cuatro contenedores (`devforge-dev-db`, `-pgadmin`, `-app-1`, `-lb`). Solo `-lb` (`0.0.0.0:8080->80/tcp`) y `-pgadmin` (`0.0.0.0:5050->80/tcp`) muestran un puerto del host; `-db` y `-app-1` muestran únicamente `5432/tcp` y `80/tcp` (puertos internos de la imagen, no publicados). `docker port devforge-dev-db` **no imprime nada**.

**6. (Opcional) Abrir pgAdmin y conectarlo a la base de datos:** `http://localhost:5050`.

Primero inicia sesión en pgAdmin (credenciales del propio pgAdmin, no de PostgreSQL):

| Campo | Valor |
| :--- | :--- |
| Email | `admin@example.com` |
| Contraseña | `devforge-dev-local-secret` |

Luego registra el servidor: clic derecho en **Servers → Register → Server…** y completa:

| Pestaña | Campo | Valor |
| :--- | :--- | :--- |
| General | Name | `devforge-dev` (cualquier nombre) |
| Connection | Host name/address | `devforge-dev-db` |
| Connection | Port | `5432` |
| Connection | Maintenance database | `devforgedb` |
| Connection | Username | `devforge_user` |
| Connection | Password | `devforge-dev-local-secret` |
| Connection | Save password? | Opcional: actívalo para no escribirla de nuevo |

Pulsa **Save**. Esperado: el servidor `devforge-dev` aparece bajo *Servers* y se expande hasta *Databases → devforgedb*.

Reemplaza los valores por defecto del formulario (`postgres` en *Maintenance database* y `admin` en *Username*): la base y el usuario de este proyecto son `devforgedb` y `devforge_user`, definidos en `Pulumi.dev.yaml`. El host es el nombre del contenedor de la base de datos, que pgAdmin resuelve porque ambos están en la red `devforge-dev-net`; PostgreSQL no es accesible desde el host (`localhost:5432`).

> La contraseña se deriva del nombre del stack (`devforge-<stack>-local-secret`) y es predecible. Es válida solo para esta demo local; no la uses con datos reales.

### Demo 2 — Autorreparación (*self-healing*) en `dev`

Elimina una réplica por fuera de Pulumi y deja que el motor la reconcilie:

```powershell
docker rm -f devforge-dev-app-1
pulumi preview --refresh
pulumi up --refresh --yes
docker ps --filter "name=devforge-dev-app-1"
```

Esperado: `preview` muestra `+ devforge-dev-app-1 create` con `7 unchanged`; `up` termina con `+ 1 created` y el contenedor reaparece en `docker ps` con un ID nuevo. Sin `--refresh`, Pulumi no consulta el estado real de Docker antes de calcular diferencias.

Comprueba que el servicio sigue respondiendo: `curl.exe http://localhost:8080` debe devolver de nuevo `Name: devforge-dev-app-1`, ahora con un `Hostname` distinto (el de la réplica recreada). En la ejecución registrada, Docker reasignó a la réplica la misma IP interna que tenía antes.

> **Limitación comprobada:** Nginx resuelve los nombres de los upstreams solo al arrancar. Si la réplica recreada recibe una IP distinta (se reprodujo ocupando la IP original con otro contenedor), el balanceador sigue enviando el tráfico a la IP anterior: no avisa y puede responder otro contenedor (sin la línea `Name: devforge-dev-app-1`) o devolver `502`. Solución provisional: `docker restart devforge-dev-lb`; tras reiniciarlo, `curl.exe http://localhost:8080` vuelve a mostrar `Name: devforge-dev-app-1` con la IP de la réplica nueva (`docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" devforge-dev-app-1`).

### Demo 3 — Stack `prod` con balanceo Round-Robin

`prod` usa el puerto 80 y `dev` el 8080, así que pueden estar activos a la vez.

```powershell
pulumi stack init prod
pulumi up --yes
pulumi stack output upstream_hosts
1..6 | ForEach-Object { curl.exe -s http://localhost:80 | Select-String "^Name:" }
```

Esperado: `pulumi up` termina con `+ 9 created` (el `Stack`, el componente y 7 hijos: volumen, red, base de datos, 3 réplicas y balanceador) y `upstream_hosts` lista `devforge-prod-app-1:80`, `-app-2:80` y `-app-3:80`. Las seis respuestas muestran `Name: devforge-prod-app-1`, `-app-2`, `-app-3`, `-app-1`, `-app-2`, `-app-3` (Nginx reparte en Round-Robin). pgAdmin no se despliega en `prod`: `pgadmin_url` no aparece en sus outputs.

En Linux/macOS: `for i in 1 2 3 4 5 6; do curl -s http://localhost:80 | grep '^Name:'; done`.

### Limpieza

```powershell
pulumi destroy --yes          # sobre el stack seleccionado
pulumi stack select dev
pulumi destroy --yes
```

`destroy` elimina los recursos declarados, **incluido el volumen de PostgreSQL**: los datos se pierden.

**Restaurar la configuración versionada** (necesario antes de ejecutar `pytest` si ya creaste los stacks):

```powershell
pulumi stack rm dev --yes
pulumi stack rm prod --yes
git restore Pulumi.dev.yaml Pulumi.prod.yaml
```

`stack rm` elimina el stack del backend local (por defecto también su `Pulumi.<stack>.yaml`) y `git restore` devuelve los YAML originales. Para repetir las demos, vuelve a crear los stacks con `pulumi stack init`.

## Pruebas funcionales

Las pruebas automatizadas usan *mocks* del motor de Pulumi: validan el grafo de recursos declarado y **no necesitan Docker en ejecución**.

> Ejecútalas con `Pulumi.dev.yaml` y `Pulumi.prod.yaml` sin modificar: tras `pulumi stack init`, Pulumi reescribe esos archivos y fallan hasta 3 pruebas (ver *Limpieza* para restaurarlos con `git restore`).

```powershell
venv\Scripts\python -m pytest
venv\Scripts\python -m compileall -q .
```

| Suite | Qué valida |
| :--- | :--- |
| `test_project_bootstrap.py` | Manifiesto `Pulumi.yaml` (runtime Python + `venv`) y output `metadata` |
| `test_stack_isolation.py` | Valores exactos de los YAML, configuración inmutable, validaciones, nombres y driver de la red, outputs del orquestador |
| `test_environment_stack.py` | Orden de upstreams y `nginx.conf`, jerarquía de recursos, puertos, volumen, réplicas y secreto de PostgreSQL en `dev` y `prod` |

Resultado esperado: `25 passed` (ejecución registrada: Python 3.14.2, pytest 8.4.2, 1.61 s) y `compileall` sin ninguna salida. No omitas el `.` final de `compileall`.

Las pruebas **no** cubren el reparto HTTP real, la recuperación ante fallos ni los tiempos de despliegue; eso se comprueba con las demos anteriores.

## Problemas frecuentes

| Síntoma | Causa y solución |
| :--- | :--- |
| `failed to connect to the docker API at npipe:////./pipe/docker_engine` | Docker Desktop no está en ejecución. Ábrelo, espera a que el motor arranque y confirma con `docker info`. |
| `pulumi: El término "pulumi" no se reconoce…` | Falta instalar la CLI de Pulumi, o la terminal se abrió antes de instalarla. Instálala, abre una terminal nueva y comprueba `pulumi version`. |
| Pulumi pide una passphrase o falla al descifrar | Falta `PULUMI_CONFIG_PASSPHRASE` en esa terminal. Defínela con el mismo valor usado al crear el stack. |
| Pulumi no encuentra el entorno virtual o los módulos | Crea `venv` e instala `requirements.txt` antes de `pulumi up` (pasos 1 y 2 de la instalación). |
| El puerto `80`, `8080` o `5050` ya está en uso | Libera el puerto o cambia `lb_port` / `pgadmin_port` en `Pulumi.<stack>.yaml`. Nota: `test_stack_isolation.py` compara esos valores exactos, así que la prueba fallará hasta que los restaures. |
| `pytest` falla en `test_stack_yaml_files_define_non_colliding_topologies` y `test_load_environment_config_preserves_immutable_contract` | Pulumi reescribió `Pulumi.<stack>.yaml` con valores string y `encryptionsalt` (`git diff Pulumi.dev.yaml` lo muestra). Restaura los archivos con `git restore Pulumi.dev.yaml Pulumi.prod.yaml`. |
| Tras recrear una réplica, `curl` responde otro contenedor o `502` | Nginx conserva la IP anterior de la réplica (ver la limitación en la Demo 2). Reinicia el balanceador: `docker restart devforge-<stack>-lb`. Comprobado en `dev`; no probado en `prod`. |
| `compileall` imprime muchos `PermissionError` sobre `C:\Python314\Lib\…` | Falta el `.` final: sin ruta, `compileall` recorre toda la instalación de Python. Usa `venv\Scripts\python -m compileall -q .`. |
| `ValueError: enable_pgadmin debe ser false en prod` | `prod` no admite pgAdmin. Deja `enable_pgadmin: false` en `Pulumi.prod.yaml`. |
| `ValueError: lb_port y pgadmin_port deben ser distintos` / `replicas debe ser mayor o igual a 1` / puerto fuera de 1–65535 | Valores inválidos en `Pulumi.<stack>.yaml`; corrígelos según el mensaje. |

## Documentación adicional

- `docs/adrs/ADR-001.md` a `ADR-004.md`: decisiones de arquitectura.
- `docs/walkthroughs/`: explicación de la implementación de ADR-001 a ADR-003.
- `docs/specs/context-master.md`: contexto maestro de diseño.
- `agents.md`: reglas de trabajo para agentes y convenciones de código del proyecto.