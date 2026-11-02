---
name: lemon_mcp
kind: app
lang: py
domain: audio
description: "Servidor MCP que pilota Lemon Studio por su control-plane JSON-RPC: leer el proyecto, crear canales, patrones y notas, mezclar, mover parametros de plugin y guardar, con undo en cada cambio."
tags: [mcp, lemon-studio, daw, control, json-rpc]
---

# lemon_mcp

Envuelve el control-plane de Lemon Studio como herramientas MCP. No reimplementa el protocolo ni
toca el audio: cada herramienta es una llamada `apply`, `propose`, `state`, `params` o `save` sobre
el socket que expone Lemon Studio.

## Por qué existe

Lemon Studio ya trae un control-plane pensado para asistentes: JSON-RPC 2.0 por socket local, con
niveles `read`, `propose` y `edit`, y cada cambio como un paso de undo con nombre del cliente. Este
servidor se limita a ponerle nombres MCP y validar argumentos, en vez de inventar otro transporte.

## Arranque

Lemon Studio, con el socket y nivel de escritura:

```bash
lemonstudio --control /tmp/lemon.sock --control-level edit proyecto.flp
```

Sin ventana (servicio o pruebas):

```bash
lemonstudio --serve /tmp/lemon.sock --control-level edit proyecto.flp
```

El servidor MCP:

```bash
python lemon_mcp.py            # MCP por stdio
python lemon_mcp.py --smoke    # comprueba socket y proyecto, sin MCP
```

Variables: `LEMON_SOCKET` (defecto `/tmp/lemon.sock`) y `LEMON_TOKEN` cuando Lemon escucha en un
puerto en vez de un socket.

## Herramientas

Lectura: `estado`, `notas`, `plugins`, `parametros`, `historial`, `eventos`.

Composición: `poner_tempo`, `poner_compas`, `poner_volumen_principal`, `anadir_canal`,
`borrar_canal`, `ajustar_canal`, `cargar_muestra`, `anadir_patron`, `poner_notas`, `anadir_notas`,
`anadir_clip`.

Mezcla: `anadir_pista`, `ajustar_pista`, `enviar`, `anadir_efecto`, `quitar_efecto`,
`ajustar_parametro`.

Proyecto: `guardar`, `deshacer`, `rehacer`, `proponer`, `aceptar`, `descartar`.

Toda escritura va por `apply`, así que deja un paso de undo con el nombre "MCP: ..." que el usuario
puede deshacer como cualquier otro. `proponer` no cambia nada: deja la propuesta para que la persona
la acepte en la app.

## Limitaciones

- Las posiciones y duraciones van en ticks (usa `estado.ppq` para convertir).
- Los ids de canal, patron y pista salen de `estado`; no se guardan en el fichero del proyecto.
- Los nombres de parametro dependen de que el plugin este cargado y exponga `params`.
- `--control-level read` deja el servidor en solo lectura: las herramientas de escritura fallaran
  con el codigo -32001.
