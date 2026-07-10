"""Obsidian Stream Connect - Punto de entrada de la aplicación.

Inicializa todos los componentes y lanza la interfaz gráfica.
Incluye manejador global de excepciones para evitar cierres
inesperados y preparación para actualizaciones automáticas.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ConfigManager
from discord_rpc import DiscordRPC
from obs_listener import OBSListener
from utils import LogManager

APP_VERSION = "1.0.0"


def global_exception_handler(exc_type, exc_value, exc_tb) -> None:
    """Captura excepciones no controladas y las registra sin cerrar la app.

    Si la excepción es KeyboardInterrupt, permite la salida normal.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    log = LogManager.get_instance()
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.error(f"Excepción no controlada:\n{error_msg}")


def check_for_updates() -> None:
    """Preparado para futuras actualizaciones automáticas.

    Actualmente registra en logs que la funcionalidad está
    preparada pero no implementa la descarga automática.
    """
    log = LogManager.get_instance()
    log.info("Sistema de actualizaciones listo (pendiente de implementar descarga automática)")


def parse_arguments() -> dict:
    """Analiza argumentos de línea de comandos.

    Soporta:
        --minimized: Iniciar minimizado a la bandeja.
        --tray: Iniciar directamente en la bandeja.

    Returns:
        Diccionario con opciones parseadas.
    """
    opts = {"minimized": False, "tray": False}
    for arg in sys.argv[1:]:
        if arg in ("--minimized", "-m"):
            opts["minimized"] = True
        if arg in ("--tray", "-t"):
            opts["tray"] = True
    return opts


def setup_startup_registry(enable: bool = True) -> None:
    """Configura el inicio automático con Windows.

    Añade o elimina la entrada en el registro de Windows
    para que la aplicación se inicie con el sistema.

    Args:
        enable: True para añadir, False para eliminar.
    """
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
        exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
        if enable:
            winreg.SetValueEx(key, "ObsidianStreamConnect", 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, "ObsidianStreamConnect")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def main() -> None:
    """Punto de entrada principal.

    Crea el gestor de configuración, el cliente de Discord RPC,
    el listener de OBS y la interfaz gráfica, conectando todos
    los componentes entre sí.
    """
    sys.excepthook = global_exception_handler

    opts = parse_arguments()
    log = LogManager.get_instance()
    log.info(f"Iniciando Obsidian Stream Connect v{APP_VERSION}...")

    config_manager = ConfigManager()
    discord_rpc = DiscordRPC()
    obs_listener = OBSListener()

    from gui import App

    app = App(config_manager, discord_rpc, obs_listener)

    check_for_updates()

    try:
        if opts["tray"]:
            app.after(100, app._minimize_to_tray)
        elif opts["minimized"]:
            app.after(100, app.iconify)

        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        discord_rpc.disconnect()
        obs_listener.disconnect()


if __name__ == "__main__":
    main()
