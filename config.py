import base64
import ctypes
import json
import os
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple

# ==============================================================================
# Windows Credential Manager (via ctypes, no external deps)
# ==============================================================================

class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPCWSTR),
        ("Comment", wintypes.LPCWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPCWSTR),
        ("UserName", wintypes.LPCWSTR),
    ]


_PCREDENTIAL = ctypes.POINTER(_CREDENTIAL)
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


def _cred_write(target: str, username: str, password: str) -> bool:
    try:
        adv32 = ctypes.windll.advapi32
        target_u = ctypes.create_unicode_buffer(target)
        user_u = ctypes.create_unicode_buffer(username)
        blob = password.encode("utf-16-le")
        blob_buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)

        cred = _CREDENTIAL()
        cred.Type = _CRED_TYPE_GENERIC
        cred.TargetName = ctypes.cast(target_u, wintypes.LPCWSTR)
        cred.UserName = ctypes.cast(user_u, wintypes.LPCWSTR)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = _CRED_PERSIST_LOCAL_MACHINE

        return bool(adv32.CredWriteW(ctypes.byref(cred), 0))
    except Exception:
        return False


def _cred_read(target: str) -> Optional[str]:
    try:
        adv32 = ctypes.windll.advapi32
        pcred = _PCREDENTIAL()
        if not adv32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            return None
        cred = pcred.contents
        data = (ctypes.c_byte * cred.CredentialBlobSize).from_address(
            ctypes.addressof(cred.CredentialBlob.contents)
        )
        pwd = bytes(data).decode("utf-16-le")
        adv32.CredFree(pcred)
        return pwd
    except Exception:
        return None


def _cred_delete(target: str) -> bool:
    try:
        adv32 = ctypes.windll.advapi32
        return bool(adv32.CredDeleteW(target, _CRED_TYPE_GENERIC, 0))
    except Exception:
        return False


# ==============================================================================
# .env loader (no external dependencies)
# ==============================================================================

_env_loaded = False


def _get_data_dir() -> str:
    """Returns the app data directory path."""
    appdata = os.environ.get("APPDATA", "")
    base = appdata if appdata else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "Obsidian Stream Connect")


def _load_dotenv(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            os.environ.setdefault(k, v)


def _ensure_env() -> None:
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    d = _get_data_dir()
    _load_dotenv(os.path.join(d, ".env"))
    _load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def get_default_client_id() -> str:
    _ensure_env()
    return os.environ.get("DISCORD_CLIENT_ID", "")


# ==============================================================================
# Password vault (Credential Manager + base64 fallback)
# ==============================================================================

_CRED_TARGET = "ObsidianStreamConnect"
_CRED_USER = "obs_websocket"


def _store_password(password: str) -> str:
    """Returns base64 fallback string (empty if stored in Credential Manager)."""
    if not password:
        return ""
    try:
        if _cred_write(_CRED_TARGET, _CRED_USER, password):
            return ""
    except Exception:
        pass
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


def _load_password(encoded: str = "") -> str:
    pwd = _cred_read(_CRED_TARGET)
    if pwd:
        return pwd
    if encoded:
        try:
            return base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        except Exception:
            pass
    return ""


def _delete_stored_password() -> None:
    _cred_delete(_CRED_TARGET)


# ==============================================================================
# Config constants
# ==============================================================================

DEFAULT_CONFIG: Dict[str, Any] = {
    "obs_host": "localhost",
    "obs_port": 4455,
    "discord_client_id": "",
    "activity_name": "Streaming en Twitch",
    "details": "¡En vivo ahora!",
    "state": "",
    "large_image_key": "logo",
    "large_image_text": "Twitch Stream",
    "small_image_key": "",
    "small_image_text": "",
    "button1_name": "Ver Stream",
    "button1_url": "https://twitch.tv/",
    "button2_name": "",
    "button2_url": "",
    "show_timer": True,
    "activity_type": "playing",
    "theme_dark": True,
    "auto_update_enabled": False,
    "minimize_to_tray": True,
    "start_minimized": False,
    "start_with_windows": False,
    "window_geometry": "1080x780",
}

_DEFAULT_COMMENTS: Dict[str, str] = {
    "_comment_obs": "=== CONFIGURACIÓN DE OBS WEBSOCKET ===",
    "_comment_obs_host": "Dirección del servidor OBS WebSocket (por defecto: localhost)",
    "_comment_obs_port": "Puerto del servidor OBS WebSocket (por defecto: 4455)",
    "_comment_obs_password": "Contraseña almacenada en Windows Credential Manager",
    "_comment_discord": "=== CONFIGURACIÓN DE DISCORD ===",
    "_comment_discord_client_id": "Application ID de Discord (también desde .env con DISCORD_CLIENT_ID)",
    "_comment_presence": "=== CONFIGURACIÓN DE RICH PRESENCE ===",
    "_comment_activity_name": "Nombre principal de la actividad (se muestra como título)",
    "_comment_details": "Primera línea de texto debajo del nombre",
    "_comment_state": "Segunda línea de texto (estado actual, puede estar vacío)",
    "_comment_images": "=== CONFIGURACIÓN DE IMÁGENES ===",
    "_comment_large_image_key": "Clave del asset de imagen grande en Discord Developer Portal",
    "_comment_large_image_text": "Tooltip de la imagen grande",
    "_comment_small_image_key": "Clave del asset de imagen pequeña (opcional)",
    "_comment_small_image_text": "Tooltip de la imagen pequeña",
    "_comment_buttons": "=== CONFIGURACIÓN DE BOTONES ===",
    "_comment_button1_name": "Texto del primer botón (máx. 32 caracteres)",
    "_comment_button1_url": "URL del primer botón (http:// o https://)",
    "_comment_button2_name": "Texto del segundo botón (opcional)",
    "_comment_button2_url": "URL del segundo botón (http:// o https://)",
    "_comment_timer": "=== TEMPORIZADOR ===",
    "_comment_show_timer": "Muestra contador de tiempo transcurrido desde que inició el stream",
    "_comment_appearance": "=== APARIENCIA ===",
    "_comment_auto_update": "=== ACTUALIZACIONES AUTOMÁTICAS ===",
    "_comment_behavior": "=== COMPORTAMIENTO ===",
}

PROFILE_KEYS: List[str] = [
    "discord_client_id", "activity_name", "details", "state",
    "large_image_key", "large_image_text",
    "small_image_key", "small_image_text",
    "button1_name", "button1_url", "button2_name", "button2_url",
    "show_timer", "activity_type",
]

PREDEFINED_PROFILES: Dict[str, Dict[str, Any]] = {
    "Twitch": {
        "activity_name": "Streaming en Twitch",
        "details": "¡En vivo ahora!",
        "state": "twitch.tv/",
        "large_image_key": "twitch_logo",
        "large_image_text": "Twitch",
        "button1_name": "Ver en Twitch",
        "button1_url": "https://twitch.tv/",
    },
    "Kick": {
        "activity_name": "Streaming en Kick",
        "details": "¡En vivo ahora!",
        "state": "kick.com/",
        "large_image_key": "kick_logo",
        "large_image_text": "Kick",
        "button1_name": "Ver en Kick",
        "button1_url": "https://kick.com/",
    },
    "YouTube": {
        "activity_name": "Streaming en YouTube",
        "details": "¡En vivo ahora!",
        "state": "youtube.com/@",
        "large_image_key": "yt_logo",
        "large_image_text": "YouTube",
        "button1_name": "Ver en YouTube",
        "button1_url": "https://youtube.com/",
    },
    "TikTok": {
        "activity_name": "Streaming en TikTok",
        "details": "¡En vivo ahora!",
        "state": "tiktok.com/@",
        "large_image_key": "tiktok_logo",
        "large_image_text": "TikTok",
        "button1_name": "Ver en TikTok",
        "button1_url": "https://tiktok.com/",
    },
    "Gaming": {
        "activity_name": "Jugando en vivo",
        "details": "Transmitiendo gameplay",
        "state": "¡Acompaña la partida!",
        "large_image_key": "gaming_logo",
        "large_image_text": "Gaming",
        "button1_name": "Ver directo",
        "button1_url": "https://twitch.tv/",
    },
    "Just Chatting": {
        "activity_name": "Charlando en vivo",
        "details": "¡Hablemos un rato!",
        "state": "Just Chatting",
        "large_image_key": "chat_logo",
        "large_image_text": "Just Chatting",
        "button1_name": "Únete a la charla",
        "button1_url": "https://twitch.tv/",
    },
    "Coding": {
        "activity_name": "Programando en vivo",
        "details": "Escribiendo código",
        "state": "Live coding",
        "large_image_key": "code_logo",
        "large_image_text": "Programming",
        "button1_name": "Ver código",
        "button1_url": "https://github.com/",
    },
    "Podcast": {
        "activity_name": "Podcast en vivo",
        "details": "Transmitiendo podcast",
        "state": "Nuevo episodio",
        "large_image_key": "podcast_logo",
        "large_image_text": "Podcast",
        "button1_name": "Escuchar",
        "button1_url": "https://twitch.tv/",
    },
    "Música": {
        "activity_name": "Música en vivo",
        "details": "Produciendo música",
        "state": "En el estudio",
        "large_image_key": "music_logo",
        "large_image_text": "Music",
        "button1_name": "Escuchar música",
        "button1_url": "https://twitch.tv/",
    },
}


# ==============================================================================
# ConfigManager
# ==============================================================================

class ConfigManager:
    """Gestiona la configuración de la aplicación.

    Lee y escribe un archivo JSON en %APPDATA%/Obsidian Stream Connect/.
    Preserva los campos _comment del JSON (que sirven como documentación).
    Soporta perfiles múltiples, validación y auto-guardado.
    La contraseña de OBS se almacena en Windows Credential Manager.
    """

    def __init__(self, config_path: Optional[str] = None, data_dir: Optional[str] = None) -> None:
        self._data_dir = data_dir or _get_data_dir()
        self.config_path = config_path or os.path.join(self._data_dir, "config.json")
        self.profiles_dir = os.path.join(self._data_dir, "profiles")
        self._logs_dir = os.path.join(self._data_dir, "logs")
        self._cache_dir = os.path.join(self._data_dir, "cache")
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._current_profile: str = "Personalizado"
        self._migrated: bool = False
        self._welcome_shown: bool = False

        self._ensure_dirs()
        self._maybe_migrate_old_config()
        _ensure_env()

    # --- Directory management ---

    def _ensure_dirs(self) -> None:
        for d in [self._data_dir, self.profiles_dir, self._logs_dir, self._cache_dir]:
            os.makedirs(d, exist_ok=True)

    def _maybe_migrate_old_config(self) -> None:
        if os.path.exists(self.config_path):
            return
        old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        if os.path.exists(old_path):
            import shutil
            shutil.copy2(old_path, self.config_path)
            self._migrated = True

    @property
    def migrated(self) -> bool:
        return self._migrated

    @property
    def logs_dir(self) -> str:
        return self._logs_dir

    @property
    def cache_dir(self) -> str:
        return self._cache_dir

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @property
    def welcome_shown(self) -> bool:
        return self._welcome_shown

    @welcome_shown.setter
    def welcome_shown(self, value: bool) -> None:
        self._welcome_shown = value

    # --- Config load/save ---

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            filtered = {k: v for k, v in data.items() if not k.startswith("_")}
            self._config.update(filtered)
            self._current_profile = data.get("_last_profile", "Personalizado")
            self._welcome_shown = data.get("_welcome_shown", False)

            encoded = data.get("_obs_password_encoded", "")
            pwd = _load_password(encoded)
            self._config["obs_password"] = pwd

            return dict(self._config)
        except FileNotFoundError:
            self.save(self._config)
            return dict(self._config)
        except Exception as e:
            raise RuntimeError(f"Error al cargar configuración: {e}")

    def save(self, config: Dict[str, Any]) -> None:
        try:
            password = config.get("obs_password", "") or self._config.get("obs_password", "")
            self._config.update(config)

            existing: Dict[str, Any] = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            comments = {k: v for k, v in existing.items() if k.startswith("_")}
            if not comments:
                comments = dict(_DEFAULT_COMMENTS)

            encoded = _store_password(password)

            out_config = dict(self._config)
            out_config.pop("obs_password", None)
            output = {**comments, **out_config, "_last_profile": self._current_profile, "_welcome_shown": self._welcome_shown}
            if encoded:
                output["_obs_password_encoded"] = encoded
            elif "_obs_password_encoded" in existing:
                _delete_stored_password()

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)

            self._config["obs_password"] = password
        except Exception as e:
            raise RuntimeError(f"Error al guardar configuración: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

    def reset_to_defaults(self) -> Dict[str, Any]:
        self._config = dict(DEFAULT_CONFIG)
        return dict(self._config)

    # --- Validation ---

    def validate(self, config: Dict[str, Any]) -> Dict[str, str]:
        errors: Dict[str, str] = {}
        cid = config.get("discord_client_id", "").strip()
        if cid and (not cid.isdigit() or len(cid) < 10):
            errors["discord_client_id"] = "El Application ID debe ser un número de al menos 10 dígitos"

        for key in ["button1_url", "button2_url"]:
            url = config.get(key, "").strip()
            if url and not (url.startswith("http://") or url.startswith("https://")):
                errors[key] = f"La URL debe comenzar con http:// o https://"

        port = config.get("obs_port", 4455)
        if not isinstance(port, int) or port < 1 or port > 65535:
            errors["obs_port"] = "El puerto debe estar entre 1 y 65535"

        return errors

    # --- Profiles ---

    @property
    def current_profile(self) -> str:
        return self._current_profile

    @current_profile.setter
    def current_profile(self, name: str) -> None:
        self._current_profile = name

    def list_profiles(self) -> List[str]:
        names: List[str] = []
        if os.path.isdir(self.profiles_dir):
            for f in sorted(os.listdir(self.profiles_dir)):
                if f.endswith(".json"):
                    names.append(f[:-5])
        for p in PREDEFINED_PROFILES:
            if p not in names:
                names.append(p)
        if "Personalizado" not in names:
            names.append("Personalizado")
        return names

    def is_predefined(self, name: str) -> bool:
        return name in PREDEFINED_PROFILES

    def save_profile(self, name: str, config: Dict[str, Any]) -> None:
        profile = {k: config.get(k) for k in PROFILE_KEYS}
        profile["_profile_name"] = name
        path = os.path.join(self.profiles_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=4, ensure_ascii=False)

    def load_profile(self, name: str) -> Dict[str, Any]:
        if name in PREDEFINED_PROFILES:
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(PREDEFINED_PROFILES[name])
            self._current_profile = name
            return cfg

        path = os.path.join(self.profiles_dir, f"{name}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = dict(DEFAULT_CONFIG)
            cfg.update({k: v for k, v in data.items() if not k.startswith("_")})
            self._current_profile = name
            return cfg

        self._current_profile = "Personalizado"
        return dict(DEFAULT_CONFIG)

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        if old_name in PREDEFINED_PROFILES:
            return False
        old_path = os.path.join(self.profiles_dir, f"{old_name}.json")
        new_path = os.path.join(self.profiles_dir, f"{new_name}.json")
        if not os.path.exists(old_path):
            return False
        try:
            os.rename(old_path, new_path)
            if self._current_profile == old_name:
                self._current_profile = new_name
            return True
        except Exception:
            return False

    def delete_profile(self, name: str) -> bool:
        if name in PREDEFINED_PROFILES:
            return False
        path = os.path.join(self.profiles_dir, f"{name}.json")
        if os.path.exists(path):
            os.remove(path)
            if self._current_profile == name:
                self._current_profile = "Personalizado"
            return True
        return False

    def export_profile(self, name: str, export_path: str) -> None:
        config = self.load_profile(name)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    def import_profile(self, import_path: str) -> Tuple[bool, str]:
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("_profile_name") or os.path.splitext(
                os.path.basename(import_path)
            )[0]
            profile = {k: data.get(k) for k in PROFILE_KEYS}
            profile["_profile_name"] = name
            dest = os.path.join(self.profiles_dir, f"{name}.json")
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=4, ensure_ascii=False)
            return True, name
        except Exception as e:
            return False, str(e)
