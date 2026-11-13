<!--
GUIA (borrar al usar)
- Evidencia de comprension, no changelog: no listar archivos ni cambios (eso es el Registro de la especificacion y git).
- No duplicar el ADR: enlazar sus secciones (§4 Decision, §7 Alcance, §9 Criterios).
- Fuentes: Resumen final, Registro y `git log`. Afirmar solo lo verificado.
- Seccion sin contenido: "No aplica". Extension objetivo: <= 1,5 paginas.
- Diagrama Mermaid opcional en "Como funciona", solo si el flujo no es lineal.
-->

# Walkthrough - ADR-NNN

- **Especificación:** [ADR-NNN](../adr/ADR-NNN.md) · Alternativa N · Pasos X–Y de Z
- **Rama / commit verificado:** `<rama>` · `<hash>`
- **Fecha:** DD-MM-AAAA

## Qué se implementó y por qué

<!-- 2-4 oraciones: capacidad nueva, resultado observable y brecha que cubre. Enlazar la decisión (§4-§5) sin repetirla. Mencionar solo desviaciones de §7. -->

## Cómo funciona

1. **<Responsabilidad>** (`ruta/archivo.py`). Qué recibe, qué devuelve, qué invariante garantiza.
2. **<Responsabilidad>** (`ruta/archivo.py`). …
3. **Composición** (`bootstrap.py`). Cómo se inyectan las dependencias.

**Ejemplo.** Éxito: entrada → recorrido → salida. Fallo: causa → comportamiento → evidencia conservada.

## Decisiones de implementación

<!-- Una fila por cada `Asumido:` del Resumen final y por cada restricción del dominio que moldeó el diseño y no está en el ADR. -->

| Decisión | Motivo |
|---|---|
| … | … |

## Cómo se verificó

| Criterio (§9) | Evidencia (prueba o comando) |
|---|---|
| … | `tests/…::test_…` |

| Comando | Resultado |
|---|---|
| `<comando>` | N aprobadas |

Entorno: Python X.Y.Z · particularidades (p. ej. `--basetemp`).

## Límites y puntos abiertos

- **No demostrado:** lo que las pruebas no acreditan (hardware real, concurrencia).
- **Determinismo:** qué es determinista (entradas → salidas) y qué no.
- **Limitaciones conocidas:** simplificaciones deliberadas. Los riesgos ya aceptados están en ADR §6; no repetirlos.
- **Observaciones a la especificación:** problemas no bloqueantes reportados (la especificación no se modifica).
- **Fuera de alcance:** … → ADR-YYY.