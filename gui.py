import os
import threading
import time
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk

from config import ConfigManager, get_default_client_id, PREDEFINED_PROFILES
from discord_rpc import DiscordRPC
from obs_listener import OBSListener, StreamState
from utils import LogManager

APP_VERSION = "1.0.0"

from diagnostic import DiagnosticDialog, DiagnosticRunner
from image_assistant import ImageAssistantDialog
from updater import Updater, UpdateDialog


class StatusIndicator(ctk.CTkFrame):
    def __init__(self, master, label: str, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.configure(fg_color="transparent")
        self._active = False

        self.dot = ctk.CTkLabel(
            self, text="●", font=("Segoe UI", 20), text_color="#555555"
        )
        self.dot.pack(side="left", padx=(0, 4))

        self.label = ctk.CTkLabel(self, text=label, font=("Segoe UI", 11))
        self.label.pack(side="left")

    def set_status(self, active: bool, connected: Optional[bool] = None) -> None:
        self._active = active
        if active:
            base = "#00cc66"
        elif connected is not None and connected:
            base = "#ffaa00"
        else:
            base = "#ff4444"
        self.dot.configure(text_color=base)

    def pulse_tick(self, cycle: int) -> None:
        if not self._active:
            return
        shades = ["#00cc66", "#00e673", "#00ff80", "#00e673"]
        self.dot.configure(text_color=shades[cycle % len(shades)])


class ToolTip:
    """Tooltip flotante sin hijos, con CTkToplevel, retardo de 300ms y posicionamiento junto al cursor.

    - No añade ningún widget hijo al control objetivo.
    - Crea un CTkToplevel sin decoración (overrideredirect=True).
    - El contenido (CTkLabel) va dentro del CTkToplevel, nunca dentro del widget objetivo.
    - Se posiciona junto al cursor.
    - Solo un tooltip visible a la vez.
    - Al salir el ratón, destruye completamente el CTkToplevel.
    - Cancela correctamente cualquier after() pendiente.
    - Compatible con cualquier widget de CustomTkinter.
    """

    _tip_window: Optional[ctk.CTkToplevel] = None
    _tip_label: Optional[ctk.CTkLabel] = None
    _after_id: Optional[str] = None
    _current_widget: Optional[Any] = None

    def __init__(self, master: Any, text: str) -> None:
        self.master = master
        self.text = text
        master.bind("<Enter>", self._on_enter, add="+")
        master.bind("<Leave>", self._on_leave, add="+")

    # ---- Shared window lifecycle ----

    @classmethod
    def _get_window(cls) -> None:
        if cls._tip_window is not None:
            return
        cls._tip_window = ctk.CTkToplevel()
        cls._tip_window.wm_overrideredirect(True)
        cls._tip_window.attributes("-topmost", True)
        cls._tip_window.withdraw()

        frame = ctk.CTkFrame(cls._tip_window, corner_radius=8)
        frame.pack(padx=2, pady=2)
        cls._tip_label = ctk.CTkLabel(
            frame, wraplength=260, justify="left",
            font=("Segoe UI", 11),
        )
        cls._tip_label.pack(padx=10, pady=8)

        # Cerrar tooltip si la ventana principal pierde visibilidad
        root = cls._tip_window.winfo_toplevel()
        root.bind("<Unmap>", lambda _: cls.hide_all(), add="+")

    @classmethod
    def hide_all(cls) -> None:
        """Cierra cualquier tooltip visible y cancela temporizadores pendientes."""
        if cls._after_id is not None and cls._current_widget is not None:
            try:
                cls._current_widget.after_cancel(cls._after_id)
            except Exception:
                pass
        cls._after_id = None
        cls._current_widget = None
        if cls._tip_window is not None:
            try:
                cls._tip_window.destroy()
            except Exception:
                pass
        cls._tip_window = None
        cls._tip_label = None

    # ---- Eventos enter / leave ----

    def _on_enter(self, event: Any = None) -> None:
        cls = self.__class__
        cls._get_window()

        # Cancelar cualquier temporizador anterior
        if cls._after_id is not None:
            try:
                cls._current_widget.after_cancel(cls._after_id)
            except Exception:
                pass
            cls._after_id = None

        # Ocultar tooltip previo inmediatamente
        if cls._tip_window is not None:
            cls._tip_window.withdraw()

        cls._current_widget = self.master
        cls._after_id = self.master.after(300, self._show)

    def _on_leave(self, event: Any = None) -> None:
        cls = self.__class__

        # Solo cancelar temporizador si este widget es el actual
        if cls._current_widget is self.master:
            if cls._after_id is not None:
                try:
                    self.master.after_cancel(cls._after_id)
                except Exception:
                    pass
                cls._after_id = None
            cls._current_widget = None

        # Destruir tooltip inmediatamente
        if cls._tip_window is not None:
            try:
                cls._tip_window.destroy()
            except Exception:
                pass
        cls._tip_window = None
        cls._tip_label = None

    # ---- Mostrar con posicionamiento inteligente ----

    def _show(self) -> None:
        cls = self.__class__
        cls._after_id = None

        # Verificar que el widget sigue siendo el activo y está visible
        try:
            if not self.master.winfo_viewable():
                return
            if cls._current_widget is not self.master:
                return
        except Exception:
            return

        # Configurar texto
        cls._tip_label.configure(text=self.text)
        cls._tip_window.update_idletasks()

        # Calcular posición junto al cursor
        x = self.master.winfo_pointerx() + 15
        y = self.master.winfo_pointery() + 15

        tw = cls._tip_window.winfo_reqwidth()
        th = cls._tip_window.winfo_reqheight()
        sw = self.master.winfo_screenwidth()
        sh = self.master.winfo_screenheight()

        # Ajustar si se sale de la pantalla
        if x + tw > sw:
            x = sw - tw - 5
        if y + th > sh:
            y = sh - th - 5
        if x < 0:
            x = 5
        if y < 0:
            y = 5

        cls._tip_window.geometry(f"+{int(x)}+{int(y)}")
        cls._tip_window.deiconify()
        cls._tip_window.lift()


class LogWindow(ctk.CTkTextbox):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.configure(state="disabled", font=("Consolas", 11))

        self._colors = {
            "INFO": "#888888",
            "SUCCESS": "#00cc66",
            "WARNING": "#ffaa00",
            "ERROR": "#ff4444",
        }
        for level, color in self._colors.items():
            self.tag_config(level.lower(), foreground=color)

    def add_log(self, entry: Dict[str, str]) -> None:
        tag = entry["level"].lower()
        date_str = entry.get("date", "")
        ts = entry["timestamp"]
        text = f"[{date_str} {ts}] [{entry['level']}] {entry['message']}\n"
        self.configure(state="normal")
        self.insert("end", text, tag)
        self.see("end")
        self.configure(state="disabled")


class OBSAuthDialog(ctk.CTkToplevel):
    """Diálogo modal para introducir la contraseña de OBS con soporte para reintento."""

    def __init__(self, parent: ctk.CTk, obs_listener: Any, port: int, config: Dict[str, Any], config_manager: Any) -> None:
        super().__init__(parent)
        self.obs_listener = obs_listener
        self.port = port
        self.config = config
        self.config_manager = config_manager
        self.result: Optional[str] = None

        self.title(f"Autenticación OBS — puerto {port}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w, h = 380, 230
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text=f"OBS en puerto {port} requiere autenticación.",
            font=("Segoe UI", 13), wraplength=340,
        ).grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")

        ctk.CTkLabel(
            self, text="Contraseña del WebSocket:", font=("Segoe UI", 11),
        ).grid(row=1, column=0, padx=20, pady=(5, 2), sticky="w")

        self.password_entry = ctk.CTkEntry(self, show="*", width=340)
        self.password_entry.grid(row=2, column=0, padx=20, pady=(0, 8), sticky="ew")
        self.password_entry.focus_set()
        self.password_entry.bind("<Return>", lambda _: self._on_connect())

        self.remember_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self, text="Recordar contraseña", variable=self.remember_var,
        ).grid(row=3, column=0, padx=20, pady=(0, 5), sticky="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=20, pady=(5, 10), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_cancel = ctk.CTkButton(btn_frame, text="Cancelar", command=self._on_cancel)
        self.btn_cancel.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.btn_connect = ctk.CTkButton(btn_frame, text="Conectar", command=self._on_connect)
        self.btn_connect.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.error_label = ctk.CTkLabel(self, text="", text_color="#ff4444", font=("Segoe UI", 11))
        self.error_label.grid(row=5, column=0, padx=20, pady=(0, 10), sticky="w")

        self.wait_window()

    def _on_connect(self) -> None:
        pw = self.password_entry.get()
        if not pw:
            self.error_label.configure(text="Introduce una contraseña")
            return
        self.error_label.configure(text="")
        self.btn_connect.configure(state="disabled", text="Conectando...")
        self.btn_cancel.configure(state="disabled")
        self.password_entry.configure(state="disabled")
        threading.Thread(target=self._try_connect, args=(pw,), daemon=True).start()

    def _try_connect(self, password: str) -> None:
        try:
            success = self.obs_listener.connect("localhost", self.port, password)
            if success:
                self.after(0, lambda: self._on_connect_success(password))
            else:
                self.after(0, self._on_connect_error)
        except Exception as e:
            self.after(0, lambda: self._on_connect_error(str(e)))

    def _on_connect_success(self, password: str) -> None:
        self.result = password
        if self.remember_var.get():
            self.config["obs_password"] = password
            self.config_manager.save(self.config)
        self.destroy()

    def _on_connect_error(self, msg: Optional[str] = None) -> None:
        self.btn_connect.configure(state="normal", text="Conectar")
        self.btn_cancel.configure(state="normal")
        self.password_entry.configure(state="normal")
        self.password_entry.focus_set()
        if msg and ("auth" in msg.lower() or "password" in msg.lower() or "unauthorized" in msg.lower()):
            self.error_label.configure(text="Contraseña incorrecta. Intenta de nuevo.")
        else:
            self.error_label.configure(text=msg or "Contraseña incorrecta. Intenta de nuevo.")

    def _on_cancel(self) -> None:
        self.obs_listener.clear_password_wait()
        self.destroy()


class App(ctk.CTk):
    def __init__(
        self,
        config_manager: ConfigManager,
        discord_rpc: DiscordRPC,
        obs_listener: OBSListener,
    ) -> None:
        super().__init__()

        self.config_manager = config_manager
        self.discord_rpc = discord_rpc
        self.obs_listener = obs_listener
        self.log_manager = LogManager.get_instance()

        self.config: Dict[str, Any] = config_manager.load()
        self.entries: Dict[str, ctk.CTkEntry] = {}

        self._save_timer: Optional[str] = None
        self._auto_save_enabled = True
        self._dirty: bool = False
        self._tray_icon: Optional[Any] = None
        self._in_tray = False
        self._theme_dark = self.config.get("theme_dark", True)
        self._pulse_cycle = 0

        self._sync_state: str = "synced"
        self._auto_update_enabled: bool = self.config.get("auto_update_enabled", False)
        self._auto_update_var = ctk.BooleanVar(value=self._auto_update_enabled)
        self._update_timer: Optional[str] = None
        self._last_update_time: Optional[str] = None
        self._presence_active: bool = False

        self.updater = Updater(APP_VERSION, config_manager.data_dir)

        self._setup_window()
        self._build_top_bar()
        self._build_main_area()
        self._build_log_toolbar()
        self._build_log_area()
        self._build_status_bar()
        self._load_config_to_ui()
        self._wire_callbacks()
        self._setup_tray()

        self.after(200, self._poll_logs)
        self.after(1000, self._health_check)
        self.after(3000, self._auto_connect_all)
        if not self.config_manager.welcome_shown:
            self.after(500, self._show_guide_dialog)
        self.after(5000, self._check_updates_startup)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<FocusOut>", self._on_focus_lost, add="+")
        self._bind_shortcuts()

    def _setup_window(self) -> None:
        self.title(f"Obsidian Stream Connect v{APP_VERSION}")
        geom = self.config.get("window_geometry", "1080x780")
        self.geometry(geom)
        self.minsize(960, 680)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)
        mode = "Dark" if self._theme_dark else "Light"
        ctk.set_appearance_mode(mode)

    def _build_top_bar(self) -> None:
        bar = ctk.CTkFrame(self, height=44, corner_radius=0)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(4, weight=1)
        bar.pack_propagate(False)

        ctk.CTkLabel(
            bar,
            text="⚡ Obsidian Stream Connect",
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left", padx=(14, 10))

        ctk.CTkLabel(
            bar,
            text=f"v{APP_VERSION}",
            font=("Segoe UI", 9),
            text_color="#666666",
        ).pack(side="left", padx=(0, 20))

        self.st_discord = StatusIndicator(bar, "Discord")
        self.st_discord.pack(side="left", padx=5)

        self.st_obs = StatusIndicator(bar, "OBS")
        self.st_obs.pack(side="left", padx=5)

        self.st_stream = StatusIndicator(bar, "Stream")
        self.st_stream.pack(side="left", padx=5)

        self.st_rpc = StatusIndicator(bar, "RPC")
        self.st_rpc.pack(side="left", padx=5)

        self._help_var = ctk.StringVar(value="Ayuda")
        self._help_var.trace_add("write", lambda *a: self._on_help_selected())
        self._help_menu = ctk.CTkOptionMenu(
            bar, values=["Ayuda", "Guía inicial", "README", "GitHub",
                         "Reportar error", "Licencia", "Changelog",
                         "---", "Buscar actualizaciones", "Diagnóstico", "---", "Acerca de"],
            variable=self._help_var,
            font=("Segoe UI", 10), height=26,
            fg_color="#444", dropdown_font=("Segoe UI", 10),
        )
        self._help_menu.pack(side="right", padx=(0, 4))

        self._theme_btn = ctk.CTkButton(
            bar, text="☀", width=32, height=28,
            font=("Segoe UI", 12),
            command=self._toggle_theme,
            fg_color="transparent", hover_color="#333333",
        )
        self._theme_btn.pack(side="right", padx=(0, 10))

        self._lbl_discord_status = ctk.CTkLabel(
            bar, text="", font=("Segoe UI", 9), text_color="#666666"
        )
        self._lbl_discord_status.pack(side="right", padx=(0, 4))

    def _build_main_area(self) -> None:
        left = ctk.CTkScrollableFrame(self, width=320)
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(5, 0))
        left.grid_columnconfigure(1, weight=1)

        right = ctk.CTkScrollableFrame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(5, 0))
        right.grid_columnconfigure(1, weight=1)

        self._build_obs_section(left)
        self._build_obs_stats_section(left)
        self._build_discord_section(left)

        self._build_template_selector(right)
        self._build_preview(right)
        self._build_tabs(right)

    def _build_obs_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 5))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame, text="OBS WebSocket", font=("Segoe UI", 12, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(8, 2), padx=8)

        self._lbl_obs_status = ctk.CTkLabel(
            frame, text="● Esperando OBS...",
            font=("Segoe UI", 11), text_color="#888888",
        )
        self._lbl_obs_status.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        self._advanced_obs_visible = False
        self._btn_advanced_obs = ctk.CTkButton(
            frame, text="Configuración avanzada", font=("Segoe UI", 10),
            command=self._on_advanced_obs_toggle,
            fg_color="#444", hover_color="#555",
            height=22,
        )
        self._btn_advanced_obs.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 2))

        self._obs_advanced_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self._obs_advanced_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        self._obs_advanced_frame.grid_columnconfigure(1, weight=1)
        # Hidden by default
        self._obs_advanced_frame.grid_remove()

        row = 0
        for label, attr, ph, show in [
            ("Host:", "obs_host", "localhost", None),
            ("Puerto:", "obs_port", "4455", None),
            ("Clave:", "obs_password", "opcional", "*"),
        ]:
            ctk.CTkLabel(self._obs_advanced_frame, text=label, font=("Segoe UI", 11)).grid(
                row=row, column=0, sticky="w", padx=8, pady=2
            )
            entry = ctk.CTkEntry(self._obs_advanced_frame, placeholder_text=ph, show=show or "")
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
            entry.bind("<KeyRelease>", lambda e: self._schedule_auto_save(), add="+")
            setattr(self, f"_{attr}", entry)
            row += 1

        detect_btn = ctk.CTkButton(
            self._obs_advanced_frame, text="Detectar OBS", font=("Segoe UI", 10),
            command=self._on_detect_obs, fg_color="#444", hover_color="#555",
            height=22, width=80,
        )
        detect_btn.grid(row=row, column=0, columnspan=2, pady=(2, 0), padx=8, sticky="w")
        row += 1

        self.btn_obs = ctk.CTkButton(
            self._obs_advanced_frame, text="Conectar OBS", command=self._toggle_obs,
        )
        self.btn_obs.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))

    def _build_obs_stats_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 5))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text="Estado de OBS", font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=8, pady=(8, 2))

        self._stats_labels: Dict[str, ctk.CTkLabel] = {}
        for key, label in [
            ("scene_name", "Escena:"),
            ("bitrate", "Bitrate:"),
            ("fps", "FPS:"),
            ("resolution", "Resolución:"),
            ("stream_time", "Tiempo:"),
        ]:
            row_f = ctk.CTkFrame(frame, fg_color="transparent")
            row_f.pack(fill="x", padx=8, pady=1)
            ctk.CTkLabel(row_f, text=label, font=("Segoe UI", 10), width=70).pack(side="left")
            lbl = ctk.CTkLabel(row_f, text="--", font=("Segoe UI", 10), text_color="#888")
            lbl.pack(side="left")
            self._stats_labels[key] = lbl

    def _build_discord_section(self, parent) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 5))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame, text="Discord RPC", font=("Segoe UI", 12, "bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(8, 2), padx=8)

        ctk.CTkLabel(frame, text="App ID:", font=("Segoe UI", 11)).grid(
            row=1, column=0, sticky="w", padx=8, pady=2
        )

        self._discord_client_id = ctk.CTkEntry(
            frame, placeholder_text="Application ID"
        )
        self._discord_client_id.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=2)
        self._discord_client_id.bind("<KeyRelease>", lambda e: self._schedule_auto_save(), add="+")

        btn_row = 2
        self.btn_discord = ctk.CTkButton(
            frame, text="Conectar Discord", command=self._toggle_discord,
        )
        self.btn_discord.grid(row=btn_row, column=0, sticky="ew", padx=(8, 2), pady=(4, 8))

        self.btn_test_rpc = ctk.CTkButton(
            frame, text="Probar RPC", command=self._on_test_rpc,
            fg_color="#444", hover_color="#555",
        )
        self.btn_test_rpc.grid(row=btn_row, column=1, columnspan=2, sticky="ew", padx=(2, 8), pady=(4, 8))

    def _build_template_selector(self, parent) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 5))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame, text="Plantilla", font=("Segoe UI", 12, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(8, 4), padx=8)

        self._profile_var = ctk.StringVar(value=self.config_manager.current_profile)
        self._profile_menu = ctk.CTkOptionMenu(
            frame, variable=self._profile_var,
            values=self.config_manager.list_profiles(),
            command=self._on_template_selected,
            font=("Segoe UI", 11),
        )
        self._profile_menu.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=(8, 4))

        ctk.CTkButton(
            frame, text="+", width=30, font=("Segoe UI", 12, "bold"),
            command=self._on_template_save,
        ).grid(row=0, column=2, padx=(0, 8), pady=(8, 4))

    def _build_preview(self, parent) -> None:
        frame = ctk.CTkFrame(parent, corner_radius=10)
        frame.pack(fill="x", pady=(0, 5))
        frame.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            frame, text="Vista Previa",
            font=("Segoe UI", 10, "bold"),
            text_color="#888888",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(8, 4))

        self._preview_icon = ctk.CTkLabel(
            frame, text="⚡", font=("Segoe UI", 28),
            width=48, height=48, corner_radius=8,
            fg_color="#1a8cff", text_color="white",
        )
        self._preview_icon.grid(row=1, column=0, rowspan=4, padx=(12, 8), pady=(0, 8), sticky="n")

        self._preview_type = ctk.CTkLabel(
            frame, text="🎮 Jugando",
            font=("Segoe UI", 10),
            text_color="#72767d", anchor="w",
        )
        self._preview_type.grid(row=1, column=1, columnspan=3, sticky="w", padx=(0, 12), pady=(2, 0))

        self._preview_title = ctk.CTkLabel(
            frame, text="Obsidian Stream Connect",
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        )
        self._preview_title.grid(row=2, column=1, columnspan=3, sticky="w", padx=(0, 12), pady=(0, 0))

        self._preview_details = ctk.CTkLabel(
            frame, text="Transmitiendo en vivo",
            font=("Segoe UI", 11),
            text_color="#b9bbbe", anchor="w",
        )
        self._preview_details.grid(row=3, column=1, columnspan=3, sticky="w", padx=(0, 12), pady=(0, 0))

        self._preview_state = ctk.CTkLabel(
            frame, text=" ",
            font=("Segoe UI", 11),
            text_color="#b9bbbe", anchor="w",
        )
        self._preview_state.grid(row=4, column=1, columnspan=3, sticky="w", padx=(0, 12), pady=(0, 0))

        self._preview_timer = ctk.CTkLabel(
            frame, text="00:00:00",
            font=("Segoe UI", 10),
            text_color="#72767d",
        )
        self._preview_timer.grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 2))

        self._preview_btn1 = ctk.CTkLabel(
            frame, text="",
            font=("Segoe UI", 10, "bold"),
            text_color="#00a8fc",
        )
        self._preview_btn1.grid(row=5, column=2, sticky="e", padx=(0, 4), pady=(4, 2))

        self._preview_btn2 = ctk.CTkLabel(
            frame, text="",
            font=("Segoe UI", 10, "bold"),
            text_color="#00a8fc",
        )
        self._preview_btn2.grid(row=5, column=3, sticky="e", padx=(0, 12), pady=(4, 2))

        ctk.CTkLabel(
            frame, text="", font=("Segoe UI", 4)
        ).grid(row=6, column=0, columnspan=4)

    def _create_config_field(self, parent, label: str, key: str, placeholder: str, tip_text: str, row: int) -> ctk.CTkEntry:
        lbl_frame = ctk.CTkFrame(parent, fg_color="transparent")
        lbl_frame.grid(row=row, column=0, sticky="w", padx=8, pady=2)
        ctk.CTkLabel(lbl_frame, text=label, font=("Segoe UI", 11)).pack(side="left")
        ToolTip(lbl_frame, text=tip_text)
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder)
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
        entry.bind("<KeyRelease>", lambda e, k=key: self._on_field_change(), add="+")
        self.entries[key] = entry
        return entry

    def _build_tabs(self, parent) -> None:
        self._tab_view = ctk.CTkTabview(parent, command=self._on_tab_changed)
        self._tab_view.pack(fill="both", expand=True, pady=(0, 4))

        self._tab_general = self._tab_view.add("General")
        self._tab_images = self._tab_view.add("Imágenes")
        self._tab_buttons = self._tab_view.add("Botones")
        self._tab_advanced = self._tab_view.add("Avanzado")

        self._tab_view.grid_columnconfigure(1, weight=1)

        self._build_general_tab()
        self._build_images_tab()
        self._build_buttons_tab()
        self._build_advanced_tab()

    def _build_general_tab(self) -> None:
        parent = self._tab_general
        parent.grid_columnconfigure(1, weight=1)

        fields = [
            ("Nombre de actividad:", "activity_name", "Streaming en Twitch",
             "Texto principal que aparece en la tarjeta de Discord"),
            ("Descripción:", "details", "¡En vivo ahora!",
             "Segunda línea de texto en la presencia"),
            ("Estado:", "state", "",
             "Texto adicional debajo de la descripción"),
        ]

        row = 0
        for label, key, placeholder, tip_text in fields:
            self._create_config_field(parent, label, key, placeholder, tip_text, row)
            row += 1

        row += 1
        at_frame = ctk.CTkFrame(parent, fg_color="transparent")
        at_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 2))
        at_frame.grid_columnconfigure(1, weight=1)

        lbl_frame = ctk.CTkFrame(at_frame, fg_color="transparent")
        lbl_frame.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(lbl_frame, text="Tipo de actividad:", font=("Segoe UI", 11)).pack(side="left")
        ToolTip(lbl_frame, "Tipo de presencia mostrada en Discord:\nJugando / Transmitiendo / Escuchando / Viendo / Compitiendo")

        self._ACTIVITY_LABELS: Dict[str, str] = {
            "playing": "🎮 Jugando",
            "streaming": "📡 Transmitiendo",
            "listening": "🎧 Escuchando",
            "watching": "👁️ Viendo",
            "competing": "🏆 Compitiendo",
        }
        self._ACTIVITY_KEYS: Dict[str, str] = {v: k for k, v in self._ACTIVITY_LABELS.items()}

        self._activity_type_var = ctk.StringVar(value=self._ACTIVITY_LABELS["playing"])
        self._activity_type_menu = ctk.CTkOptionMenu(
            at_frame,
            values=list(self._ACTIVITY_LABELS.values()),
            variable=self._activity_type_var,
            command=lambda v: self._on_field_change(),
            font=("Segoe UI", 11),
        )
        self._activity_type_menu.grid(row=0, column=1, sticky="ew", padx=(8, 8))

        row += 1
        timer_frame = ctk.CTkFrame(parent, fg_color="transparent")
        timer_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))

        self.show_timer_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            timer_frame, text="Mostrar temporizador",
            variable=self.show_timer_var,
            font=("Segoe UI", 11),
            command=self._on_field_change,
        ).pack(side="left")
        ToolTip(timer_frame, "Muestra el tiempo transcurrido del stream en la presencia")

        row += 1
        auto_frame = ctk.CTkFrame(parent, fg_color="transparent")
        auto_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))

        ctk.CTkCheckBox(
            auto_frame, text="Actualizar automáticamente",
            variable=self._auto_update_var,
            font=("Segoe UI", 11),
            command=self._on_auto_update_toggle,
        ).pack(side="left")
        ToolTip(auto_frame, "Al activarlo, los cambios se enviarán a Discord automáticamente al escribir")

        self._lbl_sync_state = ctk.CTkLabel(
            auto_frame, text="    ● Sincronizado",
            font=("Segoe UI", 10), text_color="#00cc66"
        )
        self._lbl_sync_state.pack(side="left", padx=(8, 0))

        row += 1
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        self.btn_update = ctk.CTkButton(
            btn_row, text="Actualizar actividad",
            command=self._on_manual_update,
            fg_color="#1a5c2a", hover_color="#1f7a36",
            font=("Segoe UI", 11),
        )
        self.btn_update.grid(row=0, column=0, padx=(0, 2), sticky="ew")

        ctk.CTkButton(
            btn_row, text="Probar RPC",
            command=self._on_test_rpc,
            fg_color="#444", hover_color="#555",
            font=("Segoe UI", 11),
        ).grid(row=0, column=1, padx=(2, 0), sticky="ew")

    def _build_images_tab(self) -> None:
        parent = self._tab_images
        parent.grid_columnconfigure(1, weight=1)

        fields = [
            ("Large Image Key:", "large_image_key", "logo",
             "Clave de la imagen grande registrada en el Developer Portal de Discord"),
            ("Large Image Text:", "large_image_text", "Twitch Stream",
             "Tooltip de la imagen grande"),
            ("Small Image Key:", "small_image_key", "",
             "Clave de la imagen pequeña (opcional)"),
            ("Small Image Text:", "small_image_text", "",
             "Tooltip de la imagen pequeña"),
        ]

        for i, (label, key, placeholder, tip_text) in enumerate(fields):
            self._create_config_field(parent, label, key, placeholder, tip_text, i)

        ctk.CTkLabel(
            parent, text="",
            font=("Segoe UI", 6),
        ).grid(row=len(fields), column=0)
        ctk.CTkLabel(
            parent, text="Las imágenes deben configurarse en discord.com/developers",
            font=("Segoe UI", 10), text_color="#888888",
            wraplength=300, justify="left",
        ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        ctk.CTkButton(
            parent, text="🖼 Asistente de imágenes",
            command=self._on_image_assistant,
            font=("Segoe UI", 11), fg_color="#444", hover_color="#555",
        ).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))

    def _build_buttons_tab(self) -> None:
        parent = self._tab_buttons
        parent.grid_columnconfigure(1, weight=1)

        fields = [
            ("Botón 1 - Texto:", "button1_name", "Ver Stream",
             "Texto del primer botón (máx. 32 caracteres)"),
            ("Botón 1 - URL:", "button1_url", "https://twitch.tv/",
             "Enlace del primer botón (debe comenzar con http:// o https://)"),
            ("Botón 2 - Texto:", "button2_name", "",
             "Texto del segundo botón (opcional)"),
            ("Botón 2 - URL:", "button2_url", "",
             "Enlace del segundo botón"),
        ]

        for i, (label, key, placeholder, tip_text) in enumerate(fields):
            self._create_config_field(parent, label, key, placeholder, tip_text, i)

        ctk.CTkLabel(
            parent, text="",
            font=("Segoe UI", 6),
        ).grid(row=len(fields), column=0)
        ctk.CTkLabel(
            parent, text="Las URLs deben comenzar con http:// o https://",
            font=("Segoe UI", 10), text_color="#888888",
            wraplength=300, justify="left",
        ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

    def _build_advanced_tab(self) -> None:
        parent = self._tab_advanced
        parent.grid_columnconfigure(1, weight=1)

        row = 0

        ctk.CTkLabel(
            parent, text="Conexiones", font=("Segoe UI", 12, "bold")
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        row += 1

        lbl_frame = ctk.CTkFrame(parent, fg_color="transparent")
        lbl_frame.grid(row=row, column=0, sticky="w", padx=8, pady=2)
        ctk.CTkLabel(lbl_frame, text="App ID:", font=("Segoe UI", 11)).pack(side="left")
        ToolTip(lbl_frame, "ID de aplicación de Discord Developer Portal. Por defecto usa la ID de Obsidian Stream Connect.")
        row += 1

        self._advanced_discord_client_id = ctk.CTkEntry(
            parent, placeholder_text="Application ID"
        )
        self._advanced_discord_client_id.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=2)
        self._advanced_discord_client_id.bind("<KeyRelease>", lambda e: self._schedule_auto_save(), add="+")
        row += 1

        row += 1
        ctk.CTkLabel(
            parent, text="Comportamiento", font=("Segoe UI", 12, "bold")
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        row += 1

        self._minimize_to_tray_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            parent,
            text="Minimizar a la bandeja del sistema al cerrar",
            variable=self._minimize_to_tray_var,
            font=("Segoe UI", 11),
            command=self._schedule_auto_save,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        self._start_with_windows_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            parent,
            text="Iniciar con Windows",
            variable=self._start_with_windows_var,
            font=("Segoe UI", 11),
            command=self._on_start_with_windows_toggle,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        self._start_minimized_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            parent, text="Iniciar minimizado",
            variable=self._start_minimized_var,
            font=("Segoe UI", 11),
            command=self._schedule_auto_save,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        row += 1
        ctk.CTkLabel(
            parent, text="Actualizaciones", font=("Segoe UI", 12, "bold")
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        row += 1

        self._check_updates_var = ctk.BooleanVar(
            value=self.config.get("check_updates_on_startup", True)
        )
        ctk.CTkCheckBox(
            parent, text="Buscar actualizaciones al iniciar",
            variable=self._check_updates_var,
            font=("Segoe UI", 11),
            command=self._schedule_auto_save,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        self._auto_download_var = ctk.BooleanVar(
            value=self.config.get("auto_download_updates", False)
        )
        ctk.CTkCheckBox(
            parent, text="Descargar automáticamente",
            variable=self._auto_download_var,
            font=("Segoe UI", 11),
            command=self._schedule_auto_save,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        self._notify_beta_var = ctk.BooleanVar(
            value=self.config.get("notify_beta_versions", False)
        )
        ctk.CTkCheckBox(
            parent, text="Notificar versiones beta",
            variable=self._notify_beta_var,
            font=("Segoe UI", 11),
            command=self._schedule_auto_save,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        row += 1
        ctk.CTkButton(
            parent, text="🔍 Diagnóstico del sistema",
            command=self._on_diagnostic,
            font=("Segoe UI", 11), fg_color="#444", hover_color="#555",
        ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
        row += 1

        row += 1
        lbl_frame = ctk.CTkFrame(parent, fg_color="transparent")
        lbl_frame.grid(row=row, column=0, sticky="w", padx=8, pady=2)
        ctk.CTkLabel(lbl_frame, text="Perfiles:", font=("Segoe UI", 11)).pack(side="left")
        row += 1

        btn_font = ("Segoe UI", 10)
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=2)
        btn_row.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            btn_row, text="+ Nuevo", command=self._on_profile_new,
            font=btn_font, height=22,
        ).grid(row=0, column=0, padx=1, sticky="ew")
        ctk.CTkButton(
            btn_row, text="Duplicar", command=self._on_profile_duplicate,
            font=btn_font, height=22,
        ).grid(row=0, column=1, padx=1, sticky="ew")
        ctk.CTkButton(
            btn_row, text="Eliminar", command=self._on_profile_delete,
            font=btn_font, height=22, fg_color="#663333", hover_color="#884444",
        ).grid(row=0, column=2, padx=1, sticky="ew")
        row += 1

        btn_row2 = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row2.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=2)
        btn_row2.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            btn_row2, text="Renombrar", command=self._on_profile_rename,
            font=btn_font, height=22,
        ).grid(row=0, column=0, padx=1, sticky="ew")
        ctk.CTkButton(
            btn_row2, text="Exportar", command=self._on_profile_export,
            font=btn_font, height=22,
        ).grid(row=0, column=1, padx=1, sticky="ew")
        ctk.CTkButton(
            btn_row2, text="Importar", command=self._on_profile_import,
            font=btn_font, height=22,
        ).grid(row=0, column=2, padx=1, sticky="ew")
        row += 2

        ctk.CTkButton(
            parent, text="Restablecer valores predeterminados",
            command=self._on_reset,
            fg_color="#553333", hover_color="#774444",
            font=("Segoe UI", 10),
        ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))

    def _update_preview(self, *args) -> None:
        config = self._get_config_from_ui()

        at_key = config.get("activity_type", "playing")
        at_label = self._ACTIVITY_LABELS.get(at_key, "🎮 Jugando")
        self._preview_type.configure(text=at_label)

        name = config.get("activity_name", "").strip() or "Obsidian Stream Connect"
        details = config.get("details", "").strip()
        state_text = config.get("state", "").strip()

        self._preview_title.configure(text=name)
        self._preview_details.configure(text=details if details else "Transmitiendo en vivo")
        self._preview_state.configure(text=state_text if state_text else " ")

        show_timer = config.get("show_timer", True)
        if show_timer and self.obs_listener.streaming and self.obs_listener.get_stream_start_time():
            secs = int(time.time() - self.obs_listener.get_stream_start_time())
            h, r = divmod(secs, 3600)
            m, s = divmod(r, 60)
            self._preview_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        elif show_timer:
            self._preview_timer.configure(text="00:00:00")
        else:
            self._preview_timer.configure(text="")

        btn1_name = config.get("button1_name", "").strip()
        btn1_url = config.get("button1_url", "").strip()
        btn2_name = config.get("button2_name", "").strip()
        btn2_url = config.get("button2_url", "").strip()

        self._preview_btn1.configure(
            text=f"[{btn1_name}]" if btn1_name and btn1_url else ""
        )
        self._preview_btn2.configure(
            text=f"[{btn2_name}]" if btn2_name and btn2_url else ""
        )

    def _load_config_to_ui(self) -> None:
        for key, entry in self.entries.items():
            val = self.config.get(key, "")
            entry.delete(0, "end")
            entry.insert(0, str(val))

        self._obs_host.delete(0, "end")
        self._obs_host.insert(0, str(self.config.get("obs_host", "localhost")))
        self._obs_port.delete(0, "end")
        self._obs_port.insert(0, str(self.config.get("obs_port", 4455)))
        self._obs_password.delete(0, "end")
        self._obs_password.insert(0, str(self.config.get("obs_password", "")))

        app_id = str(self.config.get("discord_client_id", get_default_client_id()))
        self._discord_client_id.delete(0, "end")
        self._discord_client_id.insert(0, app_id)
        self._advanced_discord_client_id.delete(0, "end")
        self._advanced_discord_client_id.insert(0, app_id)

        self.show_timer_var.set(self.config.get("show_timer", True))
        self._minimize_to_tray_var.set(self.config.get("minimize_to_tray", True))
        self._start_minimized_var.set(self.config.get("start_minimized", False))
        self._start_with_windows_var.set(self.config.get("start_with_windows", False))

        at = self.config.get("activity_type", "playing")
        self._activity_type_var.set(self._ACTIVITY_LABELS.get(at, self._ACTIVITY_LABELS["playing"]))

        tab = self.config.get("_selected_tab", "General")
        if tab in self._tab_view._tab_dict:
            self._tab_view.set(tab)
        lf = self.config.get("_log_filter", "Todos")
        self._log_filter_var.set(lf)
        ls = self.config.get("_log_search", "")
        self._log_search_var.set(ls)

        self._update_preview()

    def _sync_discord_ids(self) -> str:
        advanced_id = self._advanced_discord_client_id.get().strip()
        main_id = self._discord_client_id.get().strip()
        sync_id = advanced_id or main_id or get_default_client_id()
        self._discord_client_id.delete(0, "end")
        self._discord_client_id.insert(0, sync_id)
        self._advanced_discord_client_id.delete(0, "end")
        self._advanced_discord_client_id.insert(0, sync_id)
        return sync_id

    def _get_config_from_ui(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        for key, entry in self.entries.items():
            config[key] = entry.get()

        config["discord_client_id"] = self._sync_discord_ids()

        config["obs_host"] = self._obs_host.get()
        port_raw = self._obs_port.get()
        config["obs_port"] = int(port_raw) if port_raw.isdigit() else 4455
        config["obs_password"] = self._obs_password.get()
        config["show_timer"] = self.show_timer_var.get()
        config["activity_type"] = self._ACTIVITY_KEYS.get(
            self._activity_type_var.get(), "playing"
        )
        config["minimize_to_tray"] = self._minimize_to_tray_var.get()
        config["start_minimized"] = self._start_minimized_var.get()
        config["start_with_windows"] = self._start_with_windows_var.get()
        config["theme_dark"] = self._theme_dark
        config["auto_update_enabled"] = self._auto_update_enabled
        config["check_updates_on_startup"] = self._check_updates_var.get()
        config["auto_download_updates"] = self._auto_download_var.get()
        config["notify_beta_versions"] = self._notify_beta_var.get()
        config["window_geometry"] = self.geometry()
        config["_selected_tab"] = self._tab_view.get()
        config["_log_filter"] = self._log_filter_var.get()
        config["_log_search"] = self._log_search_var.get()
        return config

    def _wire_callbacks(self) -> None:
        self.obs_listener.on_state_change(self._on_state_change)
        self.obs_listener.on_password_required(self._on_obs_password_required)

    def _poll_logs(self) -> None:
        q = self.log_manager.log_queue
        while not q.empty():
            try:
                self.log_window.add_log(q.get_nowait())
            except Exception:
                break
        self.after(500, self._poll_logs)

    def _health_check(self) -> None:
        self._pulse_cycle += 1

        dc = self.discord_rpc.connected
        oc = self.obs_listener.connected
        os_ = self.obs_listener.streaming
        st_rpc = dc and os_

        self.st_discord.set_status(dc)
        self.st_obs.set_status(oc)
        self.st_stream.set_status(os_)
        self.st_rpc.set_status(st_rpc)

        for s in [self.st_discord, self.st_obs, self.st_stream, self.st_rpc]:
            s.pulse_tick(self._pulse_cycle)

        if dc != getattr(self, '_hc_dc', None):
            self._hc_dc = dc
            self._sb_discord.configure(
                text=f"Discord: {'Conectado' if dc else 'Desconectado'}",
                text_color="#00cc66" if dc else "#ff4444",
            )
        if oc != getattr(self, '_hc_oc', None):
            self._hc_oc = oc
            self._sb_obs.configure(
                text=f"OBS: {'Conectado' if oc else 'Desconectado'}",
                text_color="#00cc66" if oc else "#ff4444",
            )
        if st_rpc != getattr(self, '_hc_rpc', None):
            self._hc_rpc = st_rpc
            self._sb_rpc.configure(
                text=f"RPC: {'Activa' if st_rpc else 'Inactiva'}",
                text_color="#00cc66" if st_rpc else "#888888",
            )

        if not dc:
            running = self.discord_rpc.is_discord_running()
            lbl = f"Discord: {'Abierto' if running else 'Cerrado'}"
            if lbl != getattr(self, '_hc_dlbl', None):
                self._hc_dlbl = lbl
                self._lbl_discord_status.configure(
                    text=lbl,
                    text_color="#00cc66" if running else "#ff4444",
                )

        if oc:
            stats = self.obs_listener.get_stream_stats()
            self._stats_labels["scene_name"].configure(text=stats["scene_name"] or "--")
            self._stats_labels["bitrate"].configure(
                text=f"{stats['bitrate']} Kbps" if stats["bitrate"] else "--"
            )
            self._stats_labels["fps"].configure(
                text=f"{stats['fps']:.1f}" if stats["fps"] else "--"
            )
            res_w, res_h = stats["width"], stats["height"]
            self._stats_labels["resolution"].configure(
                text=f"{res_w}x{res_h}" if res_w and res_h else "--"
            )
            secs = stats["stream_time_secs"]
            if secs:
                h, r = divmod(secs, 3600)
                m, s = divmod(r, 60)
                self._stats_labels["stream_time"].configure(text=f"{h:02d}:{m:02d}:{s:02d}")
            else:
                self._stats_labels["stream_time"].configure(text="--")
        else:
            for lbl in self._stats_labels.values():
                lbl.configure(text="--")

        if self._last_update_time:
            self._sb_last_update.configure(
                text=f"Última act.: {self._last_update_time}",
                text_color="#00cc66" if self._sync_state == "synced" else "#ffaa00",
            )

        self.after(2000, self._health_check)

    def _auto_connect_all(self) -> None:
        app_id = self.config.get("discord_client_id", "").strip()
        if app_id:
            def _try_discord():
                if self.discord_rpc.is_discord_running():
                    ok = self.discord_rpc.connect(app_id)
                    self.after(0, lambda: self._finish_discord_toggle(ok))
                    if ok:
                        self.log_manager.success("Discord conectado automáticamente")
                else:
                    self.log_manager.info("Discord no detectado para auto-conexión")
            threading.Thread(target=_try_discord, daemon=True).start()

        password = self.config.get("obs_password", "")
        self.obs_listener.start_auto_discovery(saved_password=password)
        self.log_manager.info("Descubrimiento automático de OBS iniciado")

    def _toggle_obs(self) -> None:
        if self.obs_listener.connected:
            self.obs_listener.disconnect()
            self.btn_obs.configure(text="Conectar OBS")
            return
        config = self._get_config_from_ui()

        def _run():
            self.after(0, lambda: self.btn_obs.configure(
                text="Conectando...", state="disabled"
            ))
            ok = self.obs_listener.connect(
                config["obs_host"], config["obs_port"], config["obs_password"]
            )
            self.after(0, lambda: self._finish_obs_toggle(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _finish_obs_toggle(self, ok: bool) -> None:
        self.btn_obs.configure(
            text="Desconectar OBS" if ok else "Conectar OBS",
            state="normal",
        )

    def _on_detect_obs(self) -> None:
        def _run():
            port = self.obs_listener.auto_detect_port()
            if port:
                self.after(0, lambda: self._obs_port.delete(0, "end"))
                self.after(0, lambda: self._obs_port.insert(0, str(port)))
                self.log_manager.success(f"OBS detectado en puerto {port}")
            else:
                self.log_manager.warning("No se encontró OBS en los puertos comunes")

        threading.Thread(target=_run, daemon=True).start()

    def _on_advanced_obs_toggle(self) -> None:
        self._advanced_obs_visible = not self._advanced_obs_visible
        if self._advanced_obs_visible:
            self._obs_advanced_frame.grid()
            self._btn_advanced_obs.configure(text="Ocultar configuración avanzada")
        else:
            self._obs_advanced_frame.grid_remove()
            self._btn_advanced_obs.configure(text="Configuración avanzada")

    def _on_obs_password_required(self, port: int) -> None:
        self.log_manager.warning(f"OBS en puerto {port} requiere contraseña")
        def _prompt():
            self.deiconify()
            self.lift()
            self.focus_force()
            self.log_manager.info("Mostrando diálogo OBSAuthDialog.")
            try:
                dlg = OBSAuthDialog(
                    self, self.obs_listener, port,
                    self.config, self.config_manager,
                )
            except Exception as e:
                self.log_manager.error(f"Error al crear diálogo de contraseña: {e}")
                self.obs_listener.clear_password_wait()
                return
            pw = dlg.result
            if pw is not None:
                self.log_manager.info("Contraseña introducida.")
                self.obs_listener.update_password(pw)
                self._obs_password.delete(0, "end")
                self._obs_password.insert(0, pw)
                self.config["obs_password"] = pw
                self.config_manager.save(self.config)
                self.log_manager.success("Contraseña de OBS guardada")
        self.after(0, _prompt)

    def _toggle_discord(self) -> None:
        if self.discord_rpc.connected:
            self.discord_rpc.disconnect()
            self.btn_discord.configure(text="Conectar Discord")
            self.st_discord.set_status(False)
            return
        client_id = self._discord_client_id.get().strip()
        if not client_id:
            self.log_manager.error("El Application ID de Discord es obligatorio")
            return

        def _run():
            self.after(0, lambda: self.btn_discord.configure(
                text="Conectando...", state="disabled"
            ))
            ok = self.discord_rpc.connect(client_id)
            self.after(0, lambda: self._finish_discord_toggle(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _finish_discord_toggle(self, ok: bool) -> None:
        self.btn_discord.configure(
            text="Desconectar Discord" if ok else "Conectar Discord",
            state="normal",
        )
        self.st_discord.set_status(ok)

    def _on_test_rpc(self) -> None:
        if not self.discord_rpc.connected:
            self.log_manager.error("Conecta Discord primero antes de probar")
            return

        def _run():
            config = self._get_config_from_ui()
            ok = self.discord_rpc.test_presence(config)
            self.after(0, lambda: self.log_manager.success(
                "RPC de prueba enviada correctamente" if ok else "Error al enviar RPC de prueba"
            ))

        threading.Thread(target=_run, daemon=True).start()

    def _on_state_change(self, old_state: Optional[StreamState], new_state: StreamState) -> None:
        self.after(0, lambda: self._apply_state_to_ui(new_state))

        if new_state == StreamState.STREAM_ACTIVE:
            if not self._presence_active:
                self._presence_active = True
                self._start_presence_sync()

        if old_state == StreamState.STREAM_ACTIVE and new_state != StreamState.STREAM_ACTIVE:
            if self._presence_active:
                self._presence_active = False
                self._clear_presence_sync()

    def _apply_state_to_ui(self, state: StreamState) -> None:
        self.st_obs.set_status(self.obs_listener.connected)
        self.st_stream.set_status(self.obs_listener.streaming)
        st_rpc = self.discord_rpc.connected and self.obs_listener.streaming
        self.st_rpc.set_status(st_rpc)

        state_map = {
            StreamState.OBS_NOT_FOUND: ("● OBS no encontrado", "#888888"),
            StreamState.CONNECTING: ("● Conectando...", "#1a8cff"),
            StreamState.OBS_CONNECTED: ("● OBS conectado", "#00cc66"),
            StreamState.STREAM_INACTIVE: ("● Stream inactivo", "#888888"),
            StreamState.STREAM_STARTING: ("● Iniciando stream...", "#ffaa00"),
            StreamState.STREAM_ACTIVE: ("● Stream activo", "#00cc66"),
            StreamState.STREAM_STOPPING: ("● Finalizando stream...", "#ffaa00"),
            StreamState.STREAM_STOPPED: ("● Stream detenido", "#ff4444"),
            StreamState.CONNECTION_ERROR: ("● Error de conexión", "#ff4444"),
            StreamState.RECONNECTING: ("● Reconectando...", "#ffaa00"),
        }
        text, color = state_map.get(state, ("● Estado desconocido", "#888888"))
        self._lbl_obs_status.configure(text=text, text_color=color)

        self._sb_stream.configure(
            text=f"Stream: {'Activo' if self.obs_listener.streaming else 'Inactivo'}",
            text_color="#00cc66" if self.obs_listener.streaming else "#888888",
        )

    def _start_presence_sync(self) -> None:
        def _run():
            config = self._get_config_from_ui()
            start_time = self.obs_listener.get_stream_start_time()
            ok = self.discord_rpc.update_presence(config, start_time)
            self.after(0, lambda o=ok: self.st_rpc.set_status(o))
            if ok:
                def _on_ok():
                    self._last_update_time = time.strftime("%H:%M:%S")
                    self._set_sync_state("synced")
                self.after(0, _on_ok)
                self.log_manager.success("Presencia iniciada con el stream")
        threading.Thread(target=_run, daemon=True).start()

    def _clear_presence_sync(self) -> None:
        def _run():
            ok = self.discord_rpc.clear_presence()
            self.after(0, lambda: self.st_stream.set_status(False))
            self.after(0, lambda: self.st_rpc.set_status(False))
        threading.Thread(target=_run, daemon=True).start()

    def _toggle_theme(self) -> None:
        self._theme_dark = not self._theme_dark
        mode = "Dark" if self._theme_dark else "Light"
        ctk.set_appearance_mode(mode)
        self._theme_btn.configure(text="🌙" if self._theme_dark else "☀")
        self.log_manager.info(f"Tema cambiado a {'oscuro' if self._theme_dark else 'claro'}")
        self._schedule_auto_save()

    def _on_template_selected(self, name: str) -> None:
        self.config = self.config_manager.load_profile(name)
        self._load_config_to_ui()
        self._schedule_auto_save()
        self.log_manager.info(f"Plantilla cargada: {name}")
        if self._auto_update_enabled:
            self._schedule_presence_update()

    def _on_template_save(self) -> None:
        dlg = ctk.CTkInputDialog(
            title="Guardar plantilla",
            text="Nombre para guardar la configuración actual:",
        )
        name = dlg.get_input()
        if not name or not name.strip():
            return
        name = name.strip()
        config = self._get_config_from_ui()
        self.config_manager.save_profile(name, config)
        self._profile_var.set(name)
        self._refresh_profile_menu()
        self.log_manager.success(f"Plantilla guardada: {name}")

    def _on_tab_changed(self, tab_name: str = "") -> None:
        self._update_preview()
        self._dirty = True

    def _on_field_change(self) -> None:
        self._dirty = True
        self._update_preview()
        self._schedule_auto_save()
        if self._auto_update_enabled:
            self._schedule_presence_update()

    def _schedule_presence_update(self) -> None:
        if self._update_timer:
            self.after_cancel(self._update_timer)
        self._update_timer = self.after(500, self._do_presence_update)
        self._set_sync_state("pending")

    def _do_presence_update(self) -> None:
        self._update_timer = None
        config = self._get_config_from_ui()
        start_time = self.obs_listener.get_stream_start_time() if self.obs_listener.streaming else None

        if not self.discord_rpc.connected:
            self.log_manager.warning("No se puede actualizar: Discord no conectado")
            self._set_sync_state("error")
            return

        if not self.discord_rpc.has_changes_since_last_update(config, start_time):
            self._set_sync_state("synced")
            return

        def _run():
            self.after(0, lambda: self._set_sync_state("updating"))
            ok = self.discord_rpc.update_presence(config, start_time, force=True)
            self.after(0, lambda: self._on_update_result(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _on_update_result(self, ok: bool) -> None:
        if ok:
            self._set_sync_state("synced")
            self._last_update_time = time.strftime("%H:%M:%S")
            self.log_manager.success("Actividad actualizada correctamente")
        else:
            self._set_sync_state("error")
            self.log_manager.error("Error al actualizar la actividad")

    def _set_sync_state(self, state: str) -> None:
        self._sync_state = state
        colors = {
            "synced": ("#00cc66", "    ● Sincronizado"),
            "pending": ("#ffaa00", "    ● Cambios pendientes"),
            "updating": ("#1a8cff", "    ● Actualizando..."),
            "error": ("#ff4444", "    ● Error al actualizar"),
        }
        color, text = colors.get(state, ("#888888", "    ● ---"))
        self._lbl_sync_state.configure(text=text, text_color=color)

    def _on_auto_update_toggle(self) -> None:
        self._auto_update_enabled = self._auto_update_var.get()
        state_msg = "activada" if self._auto_update_enabled else "desactivada"
        self.log_manager.info(f"Actualización automática {state_msg}")
        if self._auto_update_enabled:
            self._schedule_presence_update()

    def _on_manual_update(self) -> None:
        config = self._get_config_from_ui()
        start_time = self.obs_listener.get_stream_start_time() if self.obs_listener.streaming else None

        if not self.discord_rpc.connected:
            self.log_manager.error("Conecta Discord primero antes de actualizar")
            return

        if not self.discord_rpc.has_changes_since_last_update(config, start_time):
            self.log_manager.info("La actividad ya está actualizada — no hay cambios")
            self._set_sync_state("synced")
            return

        def _run():
            self.after(0, lambda: self._set_sync_state("updating"))
            ok = self.discord_rpc.update_presence(config, start_time, force=True)
            self.after(0, lambda: self._on_update_result(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _schedule_auto_save(self) -> None:
        self._dirty = True
        if self._save_timer:
            self.after_cancel(self._save_timer)
        self._save_timer = self.after(800, self._do_auto_save)

    def _do_auto_save(self) -> None:
        if not self._dirty:
            return
        try:
            config = self._get_config_from_ui()
            errors = self.config_manager.validate(config)
            if errors:
                for field, msg in errors.items():
                    self.log_manager.warning(f"{field}: {msg}")
            self.config_manager.save(config)
            self.config = config
            self._dirty = False
        except Exception:
            pass

    def _on_reset(self) -> None:
        self.config = self.config_manager.reset_to_defaults()
        self._theme_dark = self.config.get("theme_dark", True)
        self._auto_update_enabled = bool(self.config.get("auto_update_enabled", False))
        self._auto_update_var.set(self._auto_update_enabled)
        mode = "Dark" if self._theme_dark else "Light"
        ctk.set_appearance_mode(mode)
        self._load_config_to_ui()
        self._schedule_auto_save()
        self.log_manager.info("Configuración restablecida a valores predeterminados")

    def _on_start_with_windows_toggle(self) -> None:
        enabled = self._start_with_windows_var.get()
        try:
            from main import setup_startup_registry
            setup_startup_registry(enabled)
            self.log_manager.success(
                f"Inicio con Windows {'activado' if enabled else 'desactivado'}"
            )
        except Exception as e:
            self.log_manager.error(f"Error al configurar inicio con Windows: {e}")
        self._schedule_auto_save()

    def _on_profile_new(self) -> None:
        dlg = ctk.CTkInputDialog(
            title="Nuevo perfil",
            text="Nombre del nuevo perfil:",
        )
        name = dlg.get_input()
        if not name or not name.strip():
            return
        name = name.strip()
        config = self._get_config_from_ui()
        self.config_manager.save_profile(name, config)
        self._profile_var.set(name)
        self._refresh_profile_menu()
        self.log_manager.success(f"Perfil creado: {name}")

    def _on_profile_duplicate(self) -> None:
        current = self._profile_var.get()
        dlg = ctk.CTkInputDialog(
            title="Duplicar perfil",
            text=f"Nombre para la copia de '{current}':",
        )
        name = dlg.get_input()
        if not name or not name.strip():
            return
        name = name.strip()
        config = self._get_config_from_ui()
        self.config_manager.save_profile(name, config)
        self._profile_var.set(name)
        self._refresh_profile_menu()
        self.log_manager.success(f"Perfil duplicado: {current} → {name}")

    def _on_profile_rename(self) -> None:
        current = self._profile_var.get()
        if current in PREDEFINED_PROFILES:
            self.log_manager.error("No se puede renombrar una plantilla predefinida")
            return
        dlg = ctk.CTkInputDialog(
            title="Renombrar perfil",
            text=f"Nuevo nombre para '{current}':",
        )
        name = dlg.get_input()
        if not name or not name.strip() or name.strip() == current:
            return
        name = name.strip()
        if self.config_manager.rename_profile(current, name):
            self._profile_var.set(name)
            self._refresh_profile_menu()
            self.log_manager.success(f"Perfil renombrado: {current} → {name}")
        else:
            self.log_manager.error(f"No se pudo renombrar el perfil")

    def _on_profile_delete(self) -> None:
        name = self._profile_var.get()
        if name in PREDEFINED_PROFILES:
            self.log_manager.error("No se puede eliminar una plantilla predefinida")
            return
        if self.config_manager.delete_profile(name):
            self._refresh_profile_menu()
            self._profile_var.set(self.config_manager.current_profile)
            self._on_template_selected(self.config_manager.current_profile)
            self.log_manager.success(f"Perfil eliminado: {name}")
        else:
            self.log_manager.error(f"No se pudo eliminar el perfil: {name}")

    def _on_profile_export(self) -> None:
        from tkinter import filedialog
        name = self._profile_var.get()
        path = filedialog.asksaveasfilename(
            title=f"Exportar perfil: {name}",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if path:
            try:
                self.config_manager.export_profile(name, path)
                self.log_manager.success(f"Perfil exportado: {path}")
            except Exception as e:
                self.log_manager.error(f"Error al exportar: {e}")

    def _on_profile_import(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Importar perfil",
            filetypes=[("JSON", "*.json")],
        )
        if path:
            ok, result = self.config_manager.import_profile(path)
            if ok:
                self._profile_var.set(result)
                self._refresh_profile_menu()
                self._on_template_selected(result)
                self.log_manager.success(f"Perfil importado: {result}")
            else:
                self.log_manager.error(f"Error al importar: {result}")

    def _refresh_profile_menu(self) -> None:
        self._profile_menu.configure(values=self.config_manager.list_profiles())

    def _build_log_toolbar(self) -> None:
        frame = ctk.CTkFrame(self, height=32, corner_radius=0)
        frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        frame.grid_columnconfigure(1, weight=1)

        self._log_search_var = ctk.StringVar()
        search_e = ctk.CTkEntry(
            frame, placeholder_text="Buscar en logs...",
            font=("Segoe UI", 10), height=22,
            textvariable=self._log_search_var,
        )
        search_e.grid(row=0, column=0, padx=(10, 4), pady=3, sticky="w")
        search_e.bind("<KeyRelease>", lambda e: self._apply_log_filter())

        self._log_filter_var = ctk.StringVar(value="Todos")
        filter_m = ctk.CTkOptionMenu(
            frame, values=["Todos", "INFO", "SUCCESS", "WARNING", "ERROR"],
            variable=self._log_filter_var,
            command=lambda v: self._apply_log_filter(),
            font=("Segoe UI", 10), height=22,
        )
        filter_m.grid(row=0, column=1, padx=4, pady=3, sticky="w")

        ctk.CTkButton(
            frame, text="Limpiar", font=("Segoe UI", 10),
            command=self._on_clear_logs, height=22, width=60,
            fg_color="#444", hover_color="#555",
        ).grid(row=0, column=2, padx=4, pady=3)

        ctk.CTkButton(
            frame, text="Exportar", font=("Segoe UI", 10),
            command=self._on_export_logs, height=22, width=60,
            fg_color="#444", hover_color="#555",
        ).grid(row=0, column=3, padx=(4, 10), pady=3)

    def _build_log_area(self) -> None:
        self.log_window = LogWindow(self, height=140)
        self.log_window.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(2, 0))

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, height=26, corner_radius=0)
        bar.grid(row=4, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(3, weight=1)

        self._sb_discord = ctk.CTkLabel(
            bar, text="Discord: --", font=("Segoe UI", 9), text_color="#888"
        )
        self._sb_discord.pack(side="left", padx=(10, 8))

        self._sb_obs = ctk.CTkLabel(
            bar, text="OBS: --", font=("Segoe UI", 9), text_color="#888"
        )
        self._sb_obs.pack(side="left", padx=8)

        self._sb_stream = ctk.CTkLabel(
            bar, text="Stream: --", font=("Segoe UI", 9), text_color="#888"
        )
        self._sb_stream.pack(side="left", padx=8)

        self._sb_rpc = ctk.CTkLabel(
            bar, text="RPC: --", font=("Segoe UI", 9), text_color="#888"
        )
        self._sb_rpc.pack(side="left", padx=8)

        self._sb_last_update = ctk.CTkLabel(
            bar, text="Última act.: --", font=("Segoe UI", 9), text_color="#888"
        )
        self._sb_last_update.pack(side="left", padx=8)

        self._btn_redes = ctk.CTkButton(
            bar, text="Mis redes", font=("Segoe UI", 9),
            command=self._open_networks,
            fg_color="transparent", hover_color="#333",
            text_color="#888", height=18, width=60,
        )
        self._btn_redes.pack(side="right", padx=(0, 2))
        ToolTip(self._btn_redes, "Visita las redes oficiales de Wesjed")

        ctk.CTkLabel(
            bar, text=f"v{APP_VERSION}", font=("Segoe UI", 9), text_color="#555"
        ).pack(side="right", padx=(0, 10))

    def _apply_log_filter(self) -> None:
        level = self._log_filter_var.get()
        search = self._log_search_var.get()
        level = None if level == "Todos" else level
        search = search.strip() or None
        logs = self.log_manager.get_logs(level=level, search=search)

        self.log_window.configure(state="normal")
        self.log_window.delete("1.0", "end")
        self.log_window.configure(state="disabled")
        for entry in logs:
            self.log_window.add_log(entry)

    def _on_clear_logs(self) -> None:
        self.log_manager.clear()
        self.log_window.configure(state="normal")
        self.log_window.delete("1.0", "end")
        self.log_window.configure(state="disabled")
        self.log_manager.info("Logs limpiados")

    def _on_export_logs(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Exportar logs",
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.log_manager.export_to_file(path)
            self.log_manager.success(f"Logs exportados: {path}")

    def _on_close(self) -> None:
        self._dirty = True
        self._do_auto_save()
        if self._minimize_to_tray_var.get():
            self._minimize_to_tray()
        else:
            self._on_quit()

    def _on_focus_lost(self, event: Any = None) -> None:
        if event and event.widget == self:
            ToolTip.hide_all()

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-s>", lambda e: self._on_manual_update())
        self.bind("<Control-r>", lambda e: self._toggle_obs())
        self.bind("<Control-q>", lambda e: self._on_quit())
        self.bind("<F5>", lambda e: self._toggle_discord())
        self.bind("<F1>", lambda e: self._show_help())

    def _on_quit(self) -> None:
        ToolTip.hide_all()
        if self._update_timer:
            self.after_cancel(self._update_timer)
            self._update_timer = None
        if self._save_timer:
            self.after_cancel(self._save_timer)
            self._save_timer = None
        self._dirty = True
        self._do_auto_save()
        self.discord_rpc.disconnect()
        self.obs_listener.disconnect()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.destroy()

    def _minimize_to_tray(self) -> None:
        ToolTip.hide_all()
        self.withdraw()
        self._in_tray = True
        self.log_manager.info("Ventana minimizada a la bandeja del sistema")

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        self._in_tray = False

    def _setup_tray(self) -> None:
        try:
            import pystray
            from pystray import MenuItem as item

            icon_img = self._create_tray_icon()
            if icon_img is None:
                self.log_manager.warning("No se pudo crear el icono de bandeja")
                return

            def tray_show():
                self.after(0, self._show_window)

            def tray_hide():
                self.after(0, self._minimize_to_tray)

            def tray_reconnect():
                self.after(0, self._tray_reconnect)

            def tray_update():
                self.after(0, self._on_manual_update)

            def tray_quit():
                self.after(0, self._on_quit)

            menu = [
                item("Mostrar ventana", tray_show, default=True),
                item("Ocultar ventana", tray_hide),
                item("Reconectar OBS/Discord", tray_reconnect),
                item("Actualizar presencia", tray_update),
                item("Salir", tray_quit),
            ]

            self._tray_icon = pystray.Icon(
                "obsidian_stream_connect", icon_img, "Obsidian Stream Connect", menu
            )
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except ImportError:
            self.log_manager.warning("pystray no instalado - bandeja del sistema no disponible")

    def _create_tray_icon(self):
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([4, 4, 60, 60], fill="#1a8cff")
            draw.ellipse([12, 12, 52, 52], fill="#0d5eb8")
            draw.text((20, 20), "OS", fill="white")
            return img
        except ImportError:
            try:
                from PIL import Image
                return Image.new("RGBA", (64, 64), (50, 50, 50, 255))
            except ImportError:
                return None

    def _tray_reconnect(self) -> None:
        if self.obs_listener.connected:
            self.log_manager.info("Reconectando OBS...")
            cfg = self._get_config_from_ui()
            threading.Thread(
                target=lambda: self.obs_listener.connect(
                    cfg["obs_host"], cfg["obs_port"], cfg["obs_password"]
                ),
                daemon=True,
            ).start()
        if self.discord_rpc.connected:
            cid = self._discord_client_id.get().strip()
            if cid:
                threading.Thread(
                    target=lambda: self.discord_rpc.connect(cid),
                    daemon=True,
                ).start()

    # --- Image Assistant ---

    def _on_image_assistant(self) -> None:
        config = self._get_config_from_ui()

        def _on_save(new_cfg: Dict[str, Any]) -> None:
            self.config.update(new_cfg)
            self._load_config_to_ui()
            self._schedule_auto_save()
            self.log_manager.success("Imágenes actualizadas desde el asistente")

        ImageAssistantDialog(self, config, _on_save)

    # --- Diagnostic ---

    def _on_diagnostic(self) -> None:
        runner = DiagnosticRunner(
            self.config, self.config_manager,
            self.discord_rpc, self.obs_listener,
        )
        DiagnosticDialog(self, runner)

    # --- Updater ---

    def _check_updates_startup(self) -> None:
        if not self.config.get("check_updates_on_startup", True):
            return
        self.updater.check(
            include_beta=self.config.get("notify_beta_versions", False),
            callback=self._on_update_checked,
        )

    def _on_check_updates_menu(self) -> None:
        self.log_manager.info("Buscando actualizaciones...")
        self.updater.check(
            include_beta=self.config.get("notify_beta_versions", False),
            callback=self._on_update_checked,
        )

    def _on_update_checked(
        self,
        available: bool,
        version: Optional[str],
        notes: Optional[str],
        download_url: Optional[str],
        release_url: Optional[str],
    ) -> None:
        if available and version:
            if self.updater.is_skipped(version):
                self.log_manager.info(f"Versión v{version} omitida por el usuario")
                return
            self.after(0, lambda: self._show_update_dialog(
                version, notes or "", download_url, release_url or "",
            ))
        elif not available:
            self.log_manager.info("Ya tienes la última versión disponible")

    def _show_update_dialog(
        self, version: str, notes: str, download_url: Optional[str], release_url: str,
    ) -> None:
        UpdateDialog(self, self.updater, version, notes, download_url, release_url)

    # --- Help menu items ---

    def _show_help_guide(self) -> None:
        self._show_guide_dialog()

    def _show_readme(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/wesjed3-crypto/twich-actividad#readme")

    def _show_github(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/wesjed3-crypto/twich-actividad")

    def _show_report(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/wesjed3-crypto/twich-actividad/issues/new")

    def _show_license(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/wesjed3-crypto/twich-actividad/blob/main/LICENSE")

    def _show_changelog(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/wesjed3-crypto/twich-actividad/blob/main/CHANGELOG.md")

    def _show_about(self) -> None:
        AboutDialog(self)

    def _open_networks(self) -> None:
        import webbrowser
        webbrowser.open("https://guns.lol/wesjed")

    def _show_help(self) -> None:
        self._show_guide_dialog()

    def _show_guide_dialog(self) -> None:
        if hasattr(self, '_wizard') and self._wizard and self._wizard.winfo_exists():
            self._wizard.lift()
            self._wizard.focus()
            return
        self._wizard = WelcomeWizard(self, self.config_manager)

    def _help_menu_command(self, action: str) -> None:
        actions = {
            "guide": self._show_guide_dialog,
            "readme": self._show_readme,
            "github": self._show_github,
            "report": self._show_report,
            "license": self._show_license,
            "changelog": self._show_changelog,
            "check_updates": self._on_check_updates_menu,
            "diagnostic": self._on_diagnostic,
            "about": self._show_about,
        }
        fn = actions.get(action)
        if fn:
            fn()

    def _on_help_selected(self) -> None:
        v = self._help_var.get()
        self._help_var.set("Ayuda")
        if v == "Ayuda" or v == "---":
            return
        mapping = {
            "Guía inicial": "guide",
            "README": "readme",
            "GitHub": "github",
            "Reportar error": "report",
            "Licencia": "license",
            "Changelog": "changelog",
            "Buscar actualizaciones": "check_updates",
            "Diagnóstico": "diagnostic",
            "Acerca de": "about",
        }
        action = mapping.get(v)
        if action:
            self._help_menu_command(action)


class AboutDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        self.title(f"Acerca de Obsidian Stream Connect v{APP_VERSION}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = 400, 440
        self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(frame, text="⚡", font=("Segoe UI", 36)).pack(pady=(0, 4))
        ctk.CTkLabel(frame, text="Obsidian Stream Connect", font=("Segoe UI", 18, "bold")).pack()
        ctk.CTkLabel(frame, text=f"Versión {APP_VERSION}", font=("Segoe UI", 12),
                     text_color="#888888").pack(pady=(0, 4))

        ctk.CTkLabel(
            frame, text="Desarrollado por Wesjed",
            font=("Segoe UI", 13, "bold"), text_color="#1a8cff",
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            frame, text="Aplicación para conectar Discord Rich Presence\ncon OBS Studio.",
            font=("Segoe UI", 11), text_color="#888888", justify="center",
        ).pack(pady=(0, 12))

        sep = ctk.CTkFrame(frame, height=1, fg_color="#444")
        sep.pack(fill="x", padx=20, pady=(0, 12))

        info_frame = ctk.CTkFrame(frame, fg_color="transparent")
        info_frame.pack(fill="x")

        rows = [
            ("Python", "3.12+"),
            ("CustomTkinter", "Interfaz gráfica"),
            ("pypresence", "Discord RPC"),
            ("obsws-python", "OBS WebSocket"),
            ("pystray", "Bandeja del sistema"),
            ("Pillow", "Imágenes"),
            ("Licencia", "MIT"),
        ]
        for label, value in rows:
            r = ctk.CTkFrame(info_frame, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=label, font=("Segoe UI", 11), width=130, anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=value, font=("Segoe UI", 11), text_color="#888888", anchor="w").pack(
                side="left", padx=(8, 0)
            )

        sep2 = ctk.CTkFrame(frame, height=1, fg_color="#444")
        sep2.pack(fill="x", padx=20, pady=(12, 8))

        ctk.CTkLabel(
            frame, text="© 2026 Wesjed. Todos los derechos reservados.",
            font=("Segoe UI", 10), text_color="#666666",
        ).pack(pady=(0, 10))

        def _open_networks():
            import webbrowser
            webbrowser.open("https://guns.lol/wesjed")

        def _open_github():
            import webbrowser
            webbrowser.open("https://github.com/wesjed3-crypto/twich-actividad")

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x")
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row, text="Visitar mis redes",
            command=_open_networks,
            font=("Segoe UI", 11), fg_color="#1a8cff", hover_color="#0d5eb8",
        ).grid(row=0, column=0, padx=(0, 3), sticky="ew")

        ctk.CTkButton(
            btn_row, text="GitHub",
            command=_open_github,
            font=("Segoe UI", 11), fg_color="#444", hover_color="#555",
        ).grid(row=0, column=1, padx=(3, 0), sticky="ew")

        ctk.CTkButton(
            frame, text="Cerrar", command=self.destroy,
            font=("Segoe UI", 11), fg_color="#333", hover_color="#444",
        ).pack(pady=(8, 0))


class WelcomeWizard(ctk.CTkToplevel):
    PAGES = [
        ("¡Bienvenido!",
         "Este asistente te guiará en los primeros pasos para configurar Obsidian Stream Connect.\n\n"
         "La aplicación conecta tu stream de OBS Studio con Discord Rich Presence para mostrar "
         "automáticamente tu actividad cuando estás en vivo."),
        ("¿Qué necesitas?",
         "Antes de empezar, asegúrate de tener:\n\n"
         "• OBS Studio 28+ con WebSocket habilitado\n"
         "• Discord abierto en tu PC\n"
         "• Una aplicación creada en discord.com/developers\n"
         "  (o usa la ID de aplicación por defecto)"),
        ("Discord Rich Presence",
         "La presencia muestra en tu perfil de Discord:\n\n"
         "• Nombre de la actividad (ej: \"Streaming en Twitch\")\n"
         "• Descripción y estado personalizados\n"
         "• Imagen grande y pequeña (opcional)\n"
         "• Botones con enlaces (opcional)\n"
         "• Temporizador del tiempo en vivo"),
        ("Conexión con OBS",
         "OBS WebSocket permite al programa:\n\n"
         "• Detectar automáticamente cuándo inicias un stream\n"
         "• Mostrar estadísticas en tiempo real (FPS, bitrate, etc.)\n"
         "• Reconectar automáticamente si la conexión se pierde\n\n"
         "La contraseña se guarda de forma segura en Windows."),
        ("Perfiles y personalización",
         "Puedes crear múltiples perfiles para diferentes tipos de stream:\n\n"
         "• Twitch, YouTube, Kick, TikTok — plantillas incluidas\n"
         "• Perfiles personalizados con tus propios textos\n"
         "• Exporta e importa perfiles para compartir\n\n"
         "También puedes cambiar entre tema oscuro y claro."),
        ("¡Todo listo!",
         "Haz clic en 'Verificar' para comprobar que todo funciona correctamente.\n\n"
         "Si algo falla, el asistente te indicará exactamente qué revisar.\n\n"
         "Puedes volver a abrir esta guía desde Ayuda → Guía inicial.\n\n"
         "Desarrollado por Wesjed — © 2026"),
    ]

    def __init__(self, parent: ctk.CTk, config_manager: Any) -> None:
        super().__init__(parent)
        self.parent = parent
        self.config_manager = config_manager
        self._page = 0

        self.title("Asistente de bienvenida")
        self.resizable(False, False)
        self.transient(parent)

        w, h = 520, 440
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self._build_ui()
        self._show_page(0)

        self.grab_set()

    def _build_ui(self) -> None:
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=24, pady=(24, 8))

        self._title_lbl = ctk.CTkLabel(
            self._content, text="", font=("Segoe UI", 18, "bold"),
        )
        self._title_lbl.pack(pady=(0, 12))

        self._text_lbl = ctk.CTkLabel(
            self._content, text="", font=("Segoe UI", 12),
            wraplength=460, justify="left",
        )
        self._text_lbl.pack(fill="both", expand=True)

        self._error_lbl = ctk.CTkLabel(
            self._content, text="", font=("Segoe UI", 11),
            text_color="#ff4444", wraplength=460,
        )
        self._error_lbl.pack(pady=(4, 0))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(4, 16))

        self._prev_btn = ctk.CTkButton(
            btn_frame, text="← Anterior", command=self._prev_page,
            font=("Segoe UI", 11), fg_color="#444", hover_color="#555",
            width=100,
        )
        self._prev_btn.pack(side="left")

        self._next_btn = ctk.CTkButton(
            btn_frame, text="Siguiente →", command=self._next_page,
            font=("Segoe UI", 11), width=100,
        )
        self._next_btn.pack(side="right")

    def _show_page(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.PAGES):
            return
        title, text = self.PAGES[idx]
        self._title_lbl.configure(text=title)
        self._text_lbl.configure(text=text)
        self._error_lbl.configure(text="")

        self._prev_btn.configure(state="normal" if idx > 0 else "disabled")
        if idx == len(self.PAGES) - 1:
            self._next_btn.configure(text="Verificar ✓", command=self._verify)
        else:
            self._next_btn.configure(text="Siguiente →", command=self._next_page)

    def _next_page(self) -> None:
        self._page += 1
        if self._page >= len(self.PAGES):
            self._page = len(self.PAGES) - 1
        self._show_page(self._page)

    def _prev_page(self) -> None:
        self._page -= 1
        if self._page < 0:
            self._page = 0
        self._show_page(self._page)

    def _verify(self) -> None:
        checks: list[tuple[str, bool]] = []

        from discord_rpc import DiscordRPC
        checks.append(("Discord abierto", DiscordRPC.is_discord_running()))

        # OBS running
        checks.append(("OBS ejecutándose", self.parent.obs_listener.is_obs_running()))

        # WebSocket reachable
        port = self.parent.obs_listener.auto_detect_port()
        checks.append(("WebSocket OBS accesible", port is not None))

        # Application ID
        cid = self.parent._discord_client_id.get().strip()
        has_cid = bool(cid) and cid.isdigit() and len(cid) >= 10
        checks.append(("Application ID válido", has_cid))

        # Password check
        checks.append(("Contraseña OBS configurada", True))

        # Rich Presence
        rpc_ok = self.parent.discord_rpc.connected
        checks.append(("Conexión Discord RPC", rpc_ok))

        errors = [name for name, ok in checks if not ok]
        if errors:
            self._error_lbl.configure(
                text="Problemas detectados:\n• " + "\n• ".join(errors)
                + "\n\nCorrige los errores y vuelve a intentar.",
            )
            self._next_btn.configure(text="Verificar ✓")
        else:
            self._error_lbl.configure(text="", text_color="#00cc66")
            self._error_lbl.configure(text="✓ Todo correcto. ¡Disfruta del stream!")
            self._next_btn.configure(
                text="Cerrar", command=self._finish,
                fg_color="#1a5c2a", hover_color="#1f7a36",
            )

    def _finish(self) -> None:
        self.config_manager.welcome_shown = True
        cfg = self.parent.config_manager.load()
        self.parent.config_manager.save(cfg)
        self.destroy()


