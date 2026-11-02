#!/usr/bin/env python3
"""Servidor MCP que pilota Lemon Studio por su control-plane (JSON-RPC 2.0 por socket local).

Lemon Studio expone un control-plane para que herramientas y asistentes lean y editen el proyecto:
una peticion JSON por linea, una respuesta por linea, en un socket Unix. Este servidor lo envuelve
como herramientas MCP, sin reimplementar nada: cada herramienta es una llamada `apply`, `propose`,
`state`, `params` o `save` sobre ese protocolo.

Arranque de Lemon (socket por defecto /tmp/lemon.sock, nivel de escritura):

    lemonstudio --control /tmp/lemon.sock --control-level edit proyecto.flp
    lemonstudio --serve /tmp/lemon.sock --control-level read proyecto.flp   # sin ventana

Uso de este servidor:

    python lemon_mcp.py                     # habla MCP por stdio
    python lemon_mcp.py --smoke             # prueba el socket y sale, sin MCP

Variables:
    LEMON_SOCKET   ruta del socket (defecto /tmp/lemon.sock)
    LEMON_TOKEN    token para `hello` cuando Lemon escucha en un puerto
"""
from __future__ import annotations

import json
import os
import socket
import sys

SOCKET = os.environ.get("LEMON_SOCKET", "/tmp/lemon.sock")
TOKEN = os.environ.get("LEMON_TOKEN", "")


class ControlError(RuntimeError):
    """Error devuelto por Lemon o por el transporte."""


class Cliente:
    """Una conexion al control-plane. Una peticion, una respuesta, y se cierra."""

    def __init__(self, ruta: str = SOCKET, token: str = TOKEN, nombre: str = "mcp") -> None:
        self.ruta = ruta
        self.token = token
        self.nombre = nombre
        self._id = 0

    def _conectar(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(self.ruta)
        return s

    def llamar(self, metodo: str, params: dict | None = None) -> object:
        """Envia una peticion JSON-RPC y devuelve `result`, o lanza ControlError con el mensaje."""
        self._id += 1
        peticion = {"jsonrpc": "2.0", "id": self._id, "method": metodo, "params": params or {}}
        with self._conectar() as s:
            f = s.makefile("rwb")
            f.write((json.dumps(peticion) + "\n").encode())
            f.flush()
            linea = f.readline()
        if not linea:
            raise ControlError("Lemon cerro la conexion sin responder")
        respuesta = json.loads(linea)
        if "error" in respuesta:
            err = respuesta["error"]
            raise ControlError(f"{err.get('code')}: {err.get('message')}")
        return respuesta.get("result")

    def hello(self) -> dict:
        return self.llamar("hello", {"name": self.nombre, "token": self.token})

    def cerrar(self) -> None:
        """Nada que cerrar: cada llamada abre y cierra su conexion."""


def cliente() -> Cliente:
    return Cliente()


def _cmd(op: str, **campos) -> dict:
    """Un comando del control-plane, sin las claves vacias."""
    return {"op": op, **{k: v for k, v in campos.items() if v is not None}}


def _aplicar(comandos: list[dict], nombre: str) -> object:
    if not comandos:
        raise ControlError("no hay comandos que aplicar")
    return cliente().llamar("apply", {"commands": comandos, "name": nombre})


def servidor():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("lemon")

    # --- lectura ---------------------------------------------------------

    @mcp.tool()
    def estado() -> dict:
        """Proyecto completo: tempo, compas, canales, mezclador, patrones y playlist con sus ids."""
        return cliente().llamar("state")

    @mcp.tool()
    def notas(patron: int) -> list:
        """Notas de un patron."""
        return cliente().llamar("notes", {"pattern": patron})

    @mcp.tool()
    def plugins() -> dict:
        """Instrumentos y efectos que aceptan add_channel y add_effect."""
        return cliente().llamar("plugins")

    @mcp.tool()
    def parametros(dueno: int) -> list:
        """Parametros de un plugin (canal o slot): id, nombre, grupo, unidad, valor y rango."""
        return cliente().llamar("params", {"owner": dueno})

    @mcp.tool()
    def historial() -> dict:
        """Pasos de undo/redo y donde esta el proyecto en ellos."""
        return cliente().llamar("history")

    @mcp.tool()
    def eventos(desde: int = 0) -> dict:
        """Que cambio tras el evento `desde`."""
        return cliente().llamar("events", {"since": desde})

    # --- ajustes ---------------------------------------------------------

    @mcp.tool()
    def poner_tempo(bpm: float) -> object:
        """Tempo, de 10 a 522."""
        return _aplicar([_cmd("set_tempo", bpm=bpm)], "MCP: tempo")

    @mcp.tool()
    def poner_compas(numerador: int, denominador: int) -> object:
        """Compas; denominador 2, 4, 8 o 16."""
        return _aplicar([_cmd("set_time_signature", numerator=numerador, denominator=denominador)], "MCP: compas")

    @mcp.tool()
    def poner_volumen_principal(volumen: float) -> object:
        """Volumen principal, 0 a 1 (0.8 es unidad)."""
        return _aplicar([_cmd("set_main_volume", volume=volumen)], "MCP: volumen")

    # --- canales ---------------------------------------------------------

    @mcp.tool()
    def anadir_canal(nombre: str | None = None, plugin: str | None = None,
                     muestra: str | None = None, pista: int | None = None) -> object:
        """Crea un canal: sampler con `muestra` cargada, o el generador `plugin`, en la pista de mezcla `pista`."""
        return _aplicar([_cmd("add_channel", name=nombre, plugin=plugin, sample=muestra, track=pista)], "MCP: canal")

    @mcp.tool()
    def borrar_canal(canal: int) -> object:
        """Borra un canal con sus notas, clips y automatizacion."""
        return _aplicar([_cmd("delete_channel", channel=canal)], "MCP: borrar canal")

    @mcp.tool()
    def ajustar_canal(canal: int, nombre: str | None = None, color: str | None = None,
                      volumen: float | None = None, pan: float | None = None,
                      tono: float | None = None, activo: bool | None = None,
                      pista: int | None = None) -> object:
        """Cambia propiedades de un canal. `pan` de -1 a 1, `tono` en cents, `color` #rrggbb."""
        return _aplicar([_cmd("set_channel", channel=canal, name=nombre, color=color,
                              volume=volumen, pan=pan, pitch=tono, enabled=activo, track=pista)],
                        "MCP: canal")

    @mcp.tool()
    def cargar_muestra(canal: int, ruta: str) -> object:
        """Carga una muestra en un canal sampler; ruta vacia la quita."""
        return _aplicar([_cmd("load_sample", channel=canal, path=ruta)], "MCP: muestra")

    # --- mezclador -------------------------------------------------------

    @mcp.tool()
    def anadir_pista(en: int | None = None) -> object:
        """Anade una pista de mezcla, en la posicion `en` o al final."""
        return _aplicar([_cmd("add_track", at=en)], "MCP: pista")

    @mcp.tool()
    def ajustar_pista(pista: int, nombre: str | None = None, color: str | None = None,
                      volumen: float | None = None, pan: float | None = None,
                      estereo: float | None = None, activo: bool | None = None,
                      efectos_activos: bool | None = None) -> object:
        """Cambia una pista de mezcla."""
        return _aplicar([_cmd("set_track", track=pista, name=nombre, color=color, volume=volumen,
                              pan=pan, stereo=estereo, enabled=activo,
                              effects_enabled=efectos_activos)], "MCP: pista")

    @mcp.tool()
    def enviar(desde_pista: int, a_pista: int, nivel: float | None = None) -> object:
        """Enruta una pista a otra; nivel 0 es solo sidechain."""
        return _aplicar([_cmd("set_send", **{"from": desde_pista, "to": a_pista}, level=nivel)], "MCP: envio")

    @mcp.tool()
    def anadir_efecto(pista: int, plugin: str, slot: int | None = None) -> object:
        """Pone un efecto en un slot de la pista (0..9, o el primero libre)."""
        return _aplicar([_cmd("add_effect", track=pista, plugin=plugin, slot=slot)], "MCP: efecto")

    @mcp.tool()
    def quitar_efecto(pista: int, slot: int) -> object:
        """Quita el efecto de un slot."""
        return _aplicar([_cmd("remove_effect", track=pista, slot=slot)], "MCP: quitar efecto")

    @mcp.tool()
    def ajustar_parametro(dueno: int, parametro: int, valor: float) -> object:
        """Fija un parametro de plugin, 0 a 1 (los ids salen de `parametros`)."""
        return _aplicar([_cmd("set_param", owner=dueno, param=parametro, value=valor)], "MCP: parametro")

    # --- patrones y notas ------------------------------------------------

    @mcp.tool()
    def anadir_patron(nombre: str, color: str | None = None) -> object:
        """Crea un patron."""
        return _aplicar([_cmd("add_pattern", name=nombre, color=color)], "MCP: patron")

    @mcp.tool()
    def poner_notas(patron: int, notas: list[dict], canal: int | None = None) -> object:
        """Sustituye las notas del canal (o todas). Nota: channel, position, length, key, velocity, pan."""
        return _aplicar([_cmd("set_notes", pattern=patron, notes=notas, channel=canal)], "MCP: notas")

    @mcp.tool()
    def anadir_notas(patron: int, notas: list[dict]) -> object:
        """Anade notas a un patron, sin borrar las que haya."""
        return _aplicar([_cmd("add_notes", pattern=patron, notes=notas)], "MCP: notas")

    @mcp.tool()
    def anadir_clip(pista: int, posicion: int, patron: int | None = None,
                    duracion: int | None = None) -> object:
        """Pone un clip de patron en la playlist. Posiciones y duraciones en ticks."""
        return _aplicar([_cmd("add_clip", track=pista, position=posicion, pattern=patron,
                              length=duracion)], "MCP: clip")

    # --- proyecto --------------------------------------------------------

    @mcp.tool()
    def guardar(ruta: str | None = None) -> object:
        """Guarda el proyecto; sin ruta, sobre su propio fichero."""
        return cliente().llamar("save", {"path": ruta} if ruta else {})

    @mcp.tool()
    def deshacer() -> object:
        """Deshace el ultimo paso."""
        return cliente().llamar("undo")

    @mcp.tool()
    def rehacer() -> object:
        """Rehace el paso deshecho."""
        return cliente().llamar("redo")

    @mcp.tool()
    def proponer(comandos: list[dict], nombre: str = "MCP: propuesta") -> object:
        """Envia comandos sin aplicarlos: el usuario acepta o descarta en la app."""
        return cliente().llamar("propose", {"commands": comandos, "name": nombre})

    @mcp.tool()
    def aceptar(propuesta: int) -> object:
        """Acepta una propuesta pendiente."""
        return cliente().llamar("accept", {"proposal": propuesta})

    @mcp.tool()
    def descartar(propuesta: int) -> object:
        """Descarta una propuesta pendiente."""
        return cliente().llamar("discard", {"proposal": propuesta})

    return mcp


def smoke() -> int:
    """Comprueba el socket sin arrancar MCP."""
    c = cliente()
    try:
        print("hello:", c.hello())
        estado = c.llamar("state")
        print("estado: canales=%d patrones=%d" % (len(estado.get("channels", [])),
                                                  len(estado.get("patterns", []))))
        print("plugins:", len(c.llamar("plugins").get("instruments", [])), "instrumentos")
        return 0
    except ControlError as e:
        print("fallo:", e)
        return 1


def main() -> int:
    if "--smoke" in sys.argv:
        return smoke()
    servidor().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
