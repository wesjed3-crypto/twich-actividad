import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

from pypresence import ActivityType, Presence
from pypresence.exceptions import PyPresenceException
from pypresence.payloads import Payload

from utils import LogManager


class DiscordRPC:
    """Maneja la conexión con Discord Rich Presence.

    Proporciona métodos para conectar, actualizar y limpiar la
    presencia de Discord. Es thread-safe mediante un Lock.
    Incluye deduplicación de envíos, detección de Discord,
    test de presencia y monitor de reconexión.
    """

    def __init__(self) -> None:
        self.client_id: Optional[str] = None
        self.rpc: Optional[Presence] = None
        self.connected: bool = False
        self._lock = threading.Lock()
        self.log = LogManager.get_instance()
        self._last_payload_hash: Optional[str] = None
        self._running: bool = False
        self._monitor_thread: Optional[threading.Thread] = None

    def connect(self, client_id: str) -> bool:
        with self._lock:
            try:
                if self.rpc:
                    try:
                        self.rpc.close()
                    except Exception:
                        pass

                self.rpc = Presence(client_id)
                self.rpc.connect()
                self.client_id = client_id
                self.connected = True
                self.log.success(f"Conectado a Discord (Client ID: {client_id})")
                self._start_monitor()
                return True

            except (PyPresenceException, ConnectionRefusedError, FileNotFoundError) as e:
                self.connected = False
                self.log.error(f"Error al conectar con Discord: {e}")
                return False
            except Exception as e:
                self.connected = False
                self.log.error(f"Error inesperado al conectar con Discord: {e}")
                return False

    def update_presence(
        self,
        config: Dict[str, Any],
        stream_start_time: Optional[float] = None,
        force: bool = False,
    ) -> bool:
        """Actualiza la presencia de Discord.

        Args:
            config: Diccionario con los campos de configuración.
            stream_start_time: Timestamp de inicio del stream (opcional).
            force: Si True, envía aunque los datos no hayan cambiado.

        Returns:
            True si la actualización fue exitosa.
        """
        with self._lock:
            if not self._ensure_connected():
                return False

            payload = self._build_payload(config, stream_start_time)
            payload_hash = self._hash_payload(payload)

            if not force and payload_hash == self._last_payload_hash:
                self.log.info("Presencia sin cambios, omitiendo envío")
                return True

            try:
                at_str = config.get("activity_type", "playing")
                at_value = self._ACTIVITY_TYPE_VALUE.get(at_str, 0)

                if at_value not in self.VALID_ACTIVITY_TYPES:
                    self.log.warning(
                        f"Tipo de actividad '{at_str}' ({at_value}) no soportado por Discord RPC. "
                        f"Usando 'Jugando' como fallback."
                    )
                    at_value = 0

                if at_value != 0:
                    clean = {k: v for k, v in payload.items() if not k.startswith("_")}
                    full = Payload.set_activity(pid=os.getpid(), **clean)
                    act = full.data.get("args", {}).get("activity", {})
                    if act is not None:
                        act["type"] = at_value
                    self.rpc.update(payload_override=full)
                else:
                    self.rpc.update(**payload)
                self._last_payload_hash = payload_hash
                self.log.success("Rich Presence actualizada correctamente")
                return True
            except PyPresenceException as e:
                self.log.error(f"Error al actualizar presencia: {e}")
                self.connected = False
                return False
            except Exception as e:
                self.log.error(f"Error inesperado al actualizar presencia: {e}")
                return False

    def test_presence(self, config: Dict[str, Any]) -> bool:
        """Envía una presencia de prueba sin asociarla a un stream.

        Útil para previsualizar la configuración. Usa force=True
        para asegurar el envío.

        Args:
            config: Diccionario con los campos de configuración.

        Returns:
            True si se actualizó correctamente.
        """
        return self.update_presence(config, stream_start_time=None, force=True)

    def clear_presence(self) -> bool:
        with self._lock:
            if not self.connected or not self.rpc:
                return True
            try:
                result = self.rpc.clear()
                self._last_payload_hash = None
                if result is not None:
                    self.log.success("Discord confirmó: presencia eliminada — ya no se muestra actividad")
                else:
                    self.log.info("Rich Presence eliminada")
                return True
            except PyPresenceException as e:
                self.log.warning(f"Error al limpiar presencia: {e}")
                self.connected = False
                return False
            except Exception as e:
                self.log.warning(f"Error inesperado al limpiar presencia: {e}")
                return False

    def disconnect(self) -> None:
        self._running = False
        with self._lock:
            try:
                if self.rpc:
                    self.rpc.close()
            except Exception:
                pass
            self.connected = False
            self.rpc = None
            self._last_payload_hash = None
            self.log.info("Desconectado de Discord")

    def _ensure_connected(self) -> bool:
        if self.connected and self.rpc:
            return True
        if self.client_id:
            self.log.warning("Discord desconectado, intentando reconectar...")
            return self.connect(self.client_id)
        self.log.error("No se puede actualizar presencia: Discord no conectado")
        return False

    @staticmethod
    def _valid_url(url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    @staticmethod
    def _hash_payload(payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    VALID_ACTIVITY_TYPES: set[int] = {0, 2, 3, 5}

    _ACTIVITY_TYPE_VALUE: Dict[str, int] = {
        "playing": 0,
        "streaming": 1,
        "listening": 2,
        "watching": 3,
        "competing": 5,
    }

    def _build_payload(
        self, config: Dict[str, Any], stream_start_time: Optional[float] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}

        at_str = config.get("activity_type", "playing")
        payload["_activity_type"] = at_str

        details = config.get("activity_name", "")
        extra_details = config.get("details", "")
        if details and extra_details:
            payload["details"] = f"{details} | {extra_details}"
        elif extra_details:
            payload["details"] = extra_details
        elif details:
            payload["details"] = details

        state = config.get("state", "")
        if state:
            payload["state"] = state

        large_key = config.get("large_image_key", "")
        large_text = config.get("large_image_text", "")
        if large_key:
            payload["large_image"] = large_key
            if large_text:
                payload["large_text"] = large_text

        small_key = config.get("small_image_key", "")
        small_text = config.get("small_image_text", "")
        if small_key:
            payload["small_image"] = small_key
            if small_text:
                payload["small_text"] = small_text

        if config.get("show_timer", True) and stream_start_time:
            payload["start"] = int(stream_start_time)

        buttons = []
        btn1_name = config.get("button1_name", "").strip()
        btn1_url = config.get("button1_url", "").strip()
        if btn1_name and btn1_url and self._valid_url(btn1_url):
            buttons.append({"label": btn1_name, "url": btn1_url})
        btn2_name = config.get("button2_name", "").strip()
        btn2_url = config.get("button2_url", "").strip()
        if btn2_name and btn2_url and self._valid_url(btn2_url):
            buttons.append({"label": btn2_name, "url": btn2_url})
        if buttons:
            payload["buttons"] = buttons

        return payload

    def has_changes_since_last_update(
        self, config: Dict[str, Any], stream_start_time: Optional[float] = None
    ) -> bool:
        """Verifica si la configuración actual difiere del último envío.

        Compara el hash del payload actual contra el último enviado.
        Útil para decidir si es necesario enviar una actualización.

        Returns:
            True si hay cambios pendientes.
        """
        payload = self._build_payload(config, stream_start_time)
        return self._hash_payload(payload) != self._last_payload_hash

    # --- Detección de Discord ---

    @staticmethod
    def is_discord_running() -> bool:
        """Verifica si el proceso de Discord está ejecutándose."""
        try:
            if sys.platform == "win32":
                cmd = "tasklist /FI \"IMAGENAME eq Discord.exe\" /NH"
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=3
                )
                return "Discord.exe" in result.stdout
            else:
                result = subprocess.run(
                    ["pgrep", "-x", "Discord"],
                    capture_output=True, timeout=3,
                )
                return result.returncode == 0
        except Exception:
            return False

    # --- Monitor de reconexión ---

    def _start_monitor(self) -> None:
        self._running = True
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self._monitor_thread.start()

    def try_reconnect(self) -> bool:
        """Intenta reconectar con Discord usando el client_id actual."""
        if self.client_id:
            return self.connect(self.client_id)
        return False

    def _monitor_loop(self) -> None:
        while self._running:
            time.sleep(5)
            if not self._running:
                break
            if not self.connected and self.client_id:
                if self.is_discord_running():
                    self.log.info("Discord detectado, intentando reconexión automática...")
                    self.connect(self.client_id)
                else:
                    self.log.info("Discord no está ejecutándose, esperando...")
