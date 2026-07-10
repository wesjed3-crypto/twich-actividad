import socket
import subprocess
import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

import obsws_python as obs

from utils import LogManager


class StreamState(Enum):
    OBS_NOT_FOUND = "OBS no encontrado"
    CONNECTING = "Conectando..."
    OBS_CONNECTED = "OBS conectado"
    STREAM_INACTIVE = "Stream inactivo"
    STREAM_STARTING = "Iniciando stream..."
    STREAM_ACTIVE = "Stream activo"
    STREAM_STOPPING = "Finalizando stream..."
    STREAM_STOPPED = "Stream detenido"
    CONNECTION_ERROR = "Error de conexión"
    RECONNECTING = "Reconectando..."


_STATE_IS_CONNECTED = {
    StreamState.OBS_CONNECTED,
    StreamState.STREAM_INACTIVE,
    StreamState.STREAM_ACTIVE,
    StreamState.STREAM_STARTING,
    StreamState.STREAM_STOPPING,
    StreamState.STREAM_STOPPED,
}

_STATE_IS_STREAMING = {
    StreamState.STREAM_ACTIVE,
    StreamState.STREAM_STARTING,
}


class OBSListener:
    def __init__(self) -> None:
        self.req_client: Optional[obs.ReqClient] = None
        self.event_client: Optional[obs.EventClient] = None

        self._state: StreamState = StreamState.OBS_NOT_FOUND
        self._host: str = "localhost"
        self._port: int = 4455
        self._password: str = ""
        self._lock = threading.RLock()
        self._running: bool = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._callbacks: Dict[str, Optional[Callable]] = {
            "state_change": None,
            "password_required": None,
        }
        self._stream_start_time: Optional[float] = None
        self.log = LogManager.get_instance()

        # Cached stats
        self._scene_name: str = ""
        self._bitrate: int = 0
        self._fps: float = 0.0
        self._output_width: int = 0
        self._output_height: int = 0
        self._stream_time_secs: int = 0

        # Auto-discovery state
        self._discovery_running: bool = False
        self._saved_password: str = ""
        self._waiting_for_password: bool = False

    # --- Properties ---

    @property
    def state(self) -> StreamState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state in _STATE_IS_CONNECTED

    @property
    def streaming(self) -> bool:
        return self._state in _STATE_IS_STREAMING

    # --- Callbacks ---

    def on_state_change(self, callback: Callable) -> None:
        self._callbacks["state_change"] = callback

    def on_password_required(self, callback: Callable) -> None:
        self._callbacks["password_required"] = callback

    # --- State machine ---

    def _set_state(self, new_state: StreamState) -> None:
        old: Optional[StreamState] = None
        with self._lock:
            if self._state == new_state:
                return
            old = self._state
            self._state = new_state
        if old is not None:
            self.log.info(f"{old.value} → {new_state.value}")
        self._trigger("state_change", old, new_state)

    # --- Conexión ---

    def connect(self, host: str, port: int, password: str) -> bool:
        self._set_state(StreamState.CONNECTING)
        with self._lock:
            try:
                self._host = host
                self._port = port
                self._password = password

                self._disconnect_clients()

                self.req_client = obs.ReqClient(
                    host=host, port=port, password=password, timeout=3,
                )

                self.event_client = obs.EventClient(
                    host=host, port=port, password=password, timeout=3,
                )

                @self.event_client.callback.register
                def stream_state_changed(data: Any) -> None:
                    self._handle_stream_state(data)

                resp = self.req_client.get_stream_status()
                was_streaming = getattr(resp, "output_active", False)

                self._refresh_stats()

                self._waiting_for_password = False

                if was_streaming:
                    self._stream_start_time = time.time()
                    self.log.info("Stream detectado como activo (previo a la conexión)")
                else:
                    self._stream_start_time = None

                self.log.success(f"Conectado a OBS en {host}:{port}")

            except Exception as e:
                err_str = str(e).lower()
                is_auth = ("auth" in err_str or "password" in err_str
                           or "unauthorized" in err_str)
                if is_auth:
                    self.log.warning(f"Autenticación fallida en OBS: {e}")
                else:
                    self.log.error(f"Error al conectar con OBS: {e}")
                self._set_state(StreamState.CONNECTION_ERROR)
                return False

        if was_streaming:
            self._set_state(StreamState.STREAM_ACTIVE)
        else:
            self._set_state(StreamState.STREAM_INACTIVE)
        return True

    def disconnect(self) -> None:
        self._running = False
        self._discovery_running = False
        was_connected = False
        with self._lock:
            was_connected = self._state in _STATE_IS_CONNECTED
            self._disconnect_clients()
        if was_connected:
            self.log.info("Desconectado de OBS")
        self._set_state(StreamState.OBS_NOT_FOUND)

    def get_stream_start_time(self) -> Optional[float]:
        return self._stream_start_time

    def _disconnect_clients(self) -> None:
        for client in (self.event_client, self.req_client):
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
        self.event_client = None
        self.req_client = None

    # --- Manejador de estado del stream (evento + poll) ---

    def _handle_stream_state(self, data: Any) -> None:
        is_active = getattr(data, "output_active", False)
        with self._lock:
            was_active = self.streaming
            if is_active and not was_active:
                self._stream_start_time = time.time()
                self._set_state(StreamState.STREAM_STARTING)
                self._set_state(StreamState.STREAM_ACTIVE)
            elif not is_active and was_active:
                self._stream_start_time = None
                self._stream_time_secs = 0
                self._set_state(StreamState.STREAM_STOPPING)
                self._set_state(StreamState.STREAM_STOPPED)
                self._set_state(StreamState.STREAM_INACTIVE)

    def _trigger(self, event: str, *args: Any) -> None:
        cb = self._callbacks.get(event)
        if cb is not None:
            try:
                if args:
                    cb(*args)
                else:
                    cb()
            except Exception as e:
                self.log.error(f"Error en callback {event}: {e}")

    # --- Ciclo de vida unificado ---

    def start_auto_discovery(self, saved_password: str = "") -> None:
        self._saved_password = saved_password
        self._running = True
        self._discovery_running = True
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._lifecycle_loop, daemon=True
            )
            self._monitor_thread.start()

    def stop_auto_discovery(self) -> None:
        self._discovery_running = False

    def update_password(self, new_password: str) -> None:
        self._saved_password = new_password
        self._password = new_password

    def clear_password_wait(self) -> None:
        self._waiting_for_password = False

    def _lifecycle_loop(self) -> None:
        while self._running and self._discovery_running:
            time.sleep(3)
            if not self._running or not self._discovery_running:
                break
            try:
                if self.connected:
                    self._lifecycle_monitor()
                else:
                    self._lifecycle_discover()
            except Exception as e:
                self.log.error(f"Error en ciclo de vida: {e}")

    def _poll_stream_status(self) -> None:
        try:
            if not self.connected or not self.req_client:
                return
            resp = self.req_client.get_stream_status()
            active = getattr(resp, "output_active", False)
            if active != self.streaming:
                self.log.info(f"Poll detectó cambio de stream: streaming={active}")
                self._handle_stream_state(resp)
        except Exception as e:
            self.log.info(f"Error en poll de stream: {e}")

    def _lifecycle_monitor(self) -> None:
        try:
            if self.req_client is not None:
                self.req_client.get_version()
            self._poll_stream_status()
            self._refresh_stats()
        except Exception:
            with self._lock:
                self._stream_start_time = None
                self._stream_time_secs = 0
            self.log.warning("Conexión con OBS perdida")
            self._set_state(StreamState.CONNECTION_ERROR)

    def _lifecycle_discover(self) -> None:
        if self._waiting_for_password:
            return

        if not self.is_obs_running():
            self._set_state(StreamState.OBS_NOT_FOUND)
            return

        port = self.auto_detect_port()
        if port is None:
            self._set_state(StreamState.OBS_NOT_FOUND)
            return

        self.log.info(f"OBS detectado en puerto {port}")
        self._port = port
        self._set_state(StreamState.CONNECTING)

        self.log.info("Conexión sin contraseña...")
        if self.connect("localhost", port, ""):
            self.log.success("OBS conectado (sin contraseña)")
            return

        if self.needs_password(host="localhost", port=port):
            self.log.info("OBS requiere autenticación.")
            if self._saved_password:
                self.log.info("Reintentando conexión con contraseña guardada...")
                if self.connect("localhost", port, self._saved_password):
                    self.log.success("OBS conectado (contraseña guardada)")
                    return
            self._waiting_for_password = True
            self.log.info("Emtiendo evento password_required.")
            self._trigger("password_required", port)
            return

        self._set_state(StreamState.OBS_NOT_FOUND)

    def _refresh_stats(self) -> None:
        if not self.connected or not self.req_client:
            return
        try:
            scene_resp = self.req_client.get_current_program_scene()
            self._scene_name = getattr(scene_resp, "scene_name", "") or getattr(
                scene_resp, "currentProgramSceneName", ""
            ) or getattr(scene_resp, "currentPreviewSceneName", "")

            stream_resp = self.req_client.get_stream_status()
            self._bitrate = getattr(stream_resp, "bitrate", 0) or 0

            stats_resp = self.req_client.get_stats()
            self._fps = float(getattr(stats_resp, "fps", 0) or 0)
            self._stream_time_secs = int(getattr(stats_resp, "stream_time_secs", 0) or 0)

            video_resp = self.req_client.get_video_settings()
            self._output_width = getattr(video_resp, "output_width", 0) or getattr(
                video_resp, "base_width", 0
            ) or 0
            self._output_height = getattr(video_resp, "output_height", 0) or getattr(
                video_resp, "base_height", 0
            ) or 0

        except Exception:
            pass

    def get_scene_name(self) -> str:
        return self._scene_name

    def get_stream_stats(self) -> Dict[str, Any]:
        return {
            "bitrate": self._bitrate,
            "fps": self._fps,
            "width": self._output_width,
            "height": self._output_height,
            "stream_time_secs": self._stream_time_secs,
            "scene_name": self._scene_name,
        }

    # --- Auto-detección ---

    @staticmethod
    def auto_detect_port(host: str = "localhost") -> Optional[int]:
        for port in (4455, 4444):
            try:
                s = socket.create_connection((host, port), timeout=1)
                s.close()
                return port
            except Exception:
                continue
        return None

    @staticmethod
    def is_obs_running() -> bool:
        try:
            if sys.platform == "win32":
                cmd = "tasklist /FI \"IMAGENAME eq obs64.exe\" /NH"
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=3
                )
                if "obs64.exe" in result.stdout or "obs32.exe" in result.stdout:
                    return True
            else:
                result = subprocess.run(
                    ["pgrep", "-i", "obs"],
                    capture_output=True, timeout=3,
                )
                if result.returncode == 0:
                    return True
        except Exception:
            pass
        return OBSListener.auto_detect_port() is not None

    def try_auto_connect(self, saved_password: str = "") -> bool:
        port = self.auto_detect_port()
        if port is None:
            self.log.warning("OBS no detectado: no se encontró WebSocket activo")
            return False

        if self.connect("localhost", port, ""):
            self.log.success(f"Conexión automática a OBS en puerto {port} (sin contraseña)")
            return True

        if saved_password:
            self.log.info("Intentando conexión con contraseña guardada...")
            if self.connect("localhost", port, saved_password):
                self.log.success("Conexión automática a OBS con contraseña guardada")
                return True

        self.log.warning(f"OBS detectado en puerto {port} pero requiere contraseña")
        return False

    @staticmethod
    def needs_password(host: str = "localhost", port: int = 4455) -> bool:
        try:
            client = obs.ReqClient(host=host, port=port, password="", timeout=2)
            client.disconnect()
            return False
        except Exception as e:
            err = str(e).lower()
            if "auth" in err or "password" in err or "unauthorized" in err:
                return True
            if "connection refused" in err or "timed out" in err:
                return False
            return True
