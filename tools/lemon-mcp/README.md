# Lemon MCP

Servidor MCP que pilota Lemon Studio por su control-plane. Ver `lemon_mcp.md`.

Arranque rapido:

```bash
lemonstudio --control /tmp/lemon.sock --control-level edit proyecto.flp
python lemon_mcp.py --smoke      # comprueba que el socket responde
python lemon_mcp.py              # sirve MCP por stdio
```

Registrado en Claude Code, por ejemplo:

```bash
claude mcp add lemon -- python /ruta/tools/lemon-mcp/lemon_mcp.py
```
