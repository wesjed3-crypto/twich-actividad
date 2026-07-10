"""Módulo de diagnóstico del sistema.

Realiza comprobaciones exhaustivas del estado de todos los
componentes de la aplicación y ofrece opciones de reparación.
"""

import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk

from utils import LogManager

DIAGNOSTIC_VERSION = "1.0"


class DiagnosticCheck:
    def __init__(self, name: str, description: str, fix_hint: str = "") -> None:
        self.name = name
        self.description = description
        self.fix_hint = fix_hint
        self.status: str = "pending"
        self.message: str = ""

    def set_ok(self, msg: str = "") -> None:
        self.status = "ok"
        self.message = msg or "Correcto"

    def set_warning(self, msg: str, hint: str = "") -> None:
        self.status = "warning"
        self.message = msg
        if hint:
            self.fix_hint = hint

    def set_error(self, msg: str, hint: str = "") -> None:
        self.status = "error"
        self.message = msg
        if hint:
            self.fix_hint = hint

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "fix_hint": self.fix_hint,
        }


class DiagnosticRunner:
    def __init__(
        self,
        config: Dict[str, Any],
        config_manager: Any,
        discord_rpc: Any,
        obs_listener: Any,
    ) -> None:
        self.config = config
        self.config_manager = config_manager
        self.discord_rpc = discord_rpc
        self.obs_listener = obs_listener
        self.log = LogManager.get_instance()
        self.checks: List[DiagnosticCheck] = []
        self._running = False

    def run_all(self, progress_callback: Any = None) -> None:
        self._running = True
        self.checks = []

        checks_list = [
            self._check_discord_installed,
            self._check_discord_running,
            self._check_discord_rpc_available,
            self._check_app_id_valid,
            self._check_discord_connected,
            self._check_obs_installed,
            self._check_obs_running,
            self._check_obs_ws_active,
            self._check_obs_port,
            self._check_obs_password,
            self._check_obs_connected,
            self._check_stream_detection,
            self._check_appdata_folder,
            self._check_config_file,
            self._check_logs_dir,
            self._check_internet,
            self._check_github,
            self._check_python_version,
            self._check_app_version,
        ]

        total = len(checks_list)
        for i, check_fn in enumerate(checks_list):
            if not self._running:
                break
            try:
                check_fn()
            except Exception as e:
                c = DiagnosticCheck("Error", "Error inesperado durante la comprobación")
                c.set_error(str(e))
                self.checks.append(c)
            if progress_callback:
                progress_callback(i + 1, total)

    def stop(self) -> None:
        self._running = False

    # --- individual checks ---

    def _check_discord_installed(self) -> None:
        c = DiagnosticCheck(
            "Discord instalado",
            "Verifica si Discord está instalado en el sistema",
            "Descarga e instala Discord desde https://discord.com/download",
        )
        if sys.platform == "win32":
            paths = [
                os.path.expandvars("%LOCALAPPDATA%\\Discord"),
                os.path.expandvars("%APPDATA%\\Discord"),
                "C:\\Program Files\\Discord",
                "C:\\Program Files (x86)\\Discord",
            ]
            found = any(os.path.isdir(p) for p in paths)
            if found:
                c.set_ok("Discord instalado en el sistema")
            else:
                c.set_warning("No se encontró Discord en ubicaciones típicas")
        else:
            c.set_warning("No se pudo verificar instalación en este sistema")
        self.checks.append(c)

    def _check_discord_running(self) -> None:
        c = DiagnosticCheck(
            "Discord abierto",
            "Verifica si Discord se está ejecutando",
            "Abre Discord en tu PC",
        )
        from discord_rpc import DiscordRPC
        if DiscordRPC.is_discord_running():
            c.set_ok("Discord está en ejecución")
        else:
            c.set_error("Discord no está ejecutándose", "Abre Discord e intenta de nuevo")
        self.checks.append(c)

    def _check_discord_rpc_available(self) -> None:
        c = DiagnosticCheck(
            "Discord RPC disponible",
            "Verifica que la conexión RPC está lista",
            "Asegúrate de tener Discord abierto y haber iniciado sesión",
        )
        try:
            import pypresence
            c.set_ok("Librería pypresence disponible")
        except ImportError:
            c.set_error("pypresence no está instalado", "Ejecuta: pip install pypresence")
        self.checks.append(c)

    def _check_app_id_valid(self) -> None:
        c = DiagnosticCheck(
            "Application ID válido",
            "Verifica que el Application ID de Discord sea válido",
            "Crea una aplicación en https://discord.com/developers/applications",
        )
        cid = self.config.get("discord_client_id", "").strip()
        if cid and cid.isdigit() and len(cid) >= 10:
            c.set_ok(f"Application ID: {cid}")
        elif cid:
            c.set_error("Application ID inválido (debe ser un número de 10+ dígitos)")
        else:
            c.set_warning("Application ID no configurado")
        self.checks.append(c)

    def _check_discord_connected(self) -> None:
        c = DiagnosticCheck(
            "Conexión Discord RPC",
            "Verifica que la conexión RPC esté activa",
            "Conecta Discord usando el botón en la interfaz principal",
        )
        if self.discord_rpc.connected:
            c.set_ok("RPC conectado correctamente")
        else:
            c.set_warning("RPC no conectado")
        self.checks.append(c)

    def _check_obs_installed(self) -> None:
        c = DiagnosticCheck(
            "OBS instalado",
            "Verifica si OBS Studio está instalado",
            "Descarga OBS desde https://obsproject.com",
        )
        if sys.platform == "win32":
            paths = [
                "C:\\Program Files\\obs-studio",
                "C:\\Program Files (x86)\\obs-studio",
                os.path.expandvars("%LOCALAPPDATA%\\Programs\\obs-studio"),
            ]
            found = any(os.path.isdir(p) for p in paths)
            if found:
                c.set_ok("OBS instalado en el sistema")
            else:
                c.set_warning("No se encontró OBS en ubicaciones típicas")
        else:
            c.set_warning("No se pudo verificar en este sistema")
        self.checks.append(c)

    def _check_obs_running(self) -> None:
        c = DiagnosticCheck(
            "OBS abierto",
            "Verifica si OBS Studio se está ejecutando",
            "Abre OBS Studio",
        )
        if self.obs_listener.is_obs_running():
            c.set_ok("OBS está en ejecución")
        else:
            c.set_error("OBS no está ejecutándose", "Abre OBS Studio e intenta de nuevo")
        self.checks.append(c)

    def _check_obs_ws_active(self) -> None:
        c = DiagnosticCheck(
            "Servidor WebSocket activo",
            "Verifica que el WebSocket de OBS esté accesible",
            "Habilita WebSocket en OBS: Herramientas → WebSocket Server Settings",
        )
        port = self.obs_listener.auto_detect_port()
        if port is not None:
            c.set_ok(f"WebSocket detectado en puerto {port}")
        else:
            c.set_error(
                "No se detectó WebSocket de OBS",
                "Asegúrate de tener OBS abierto y WebSocket Server habilitado",
            )
        self.checks.append(c)

    def _check_obs_port(self) -> None:
        c = DiagnosticCheck(
            "Puerto correcto",
            "Verifica que el puerto configurado sea accesible",
            "Revisa la configuración avanzada de OBS en la interfaz",
        )
        port = self.config.get("obs_port", 4455)
        if isinstance(port, int) and 1 <= port <= 65535:
            c.set_ok(f"Puerto configurado: {port}")
        else:
            c.set_error(f"Puerto inválido: {port}")
        self.checks.append(c)

    def _check_obs_password(self) -> None:
        c = DiagnosticCheck(
            "Contraseña correcta",
            "Verifica que la contraseña de OBS esté configurada",
            "Si OBS requiere contraseña, configúrala en OBS WebSocket Settings",
        )
        pwd = self.config.get("obs_password", "")
        port = self.obs_listener.auto_detect_port()
        if port is not None:
            test = self.obs_listener.needs_password("localhost", port)
            if test and not pwd:
                c.set_error("OBS requiere contraseña pero no está configurada")
            elif test and pwd:
                c.set_ok("Contraseña configurada")
            else:
                c.set_ok("OBS no requiere contraseña")
        else:
            c.set_warning("No se pudo verificar (OBS no detectado)")
        self.checks.append(c)

    def _check_obs_connected(self) -> None:
        c = DiagnosticCheck(
            "Conexión con OBS",
            "Verifica que la conexión con OBS esté activa",
            "Conecta OBS usando el botón en la interfaz principal",
        )
        if self.obs_listener.connected:
            c.set_ok("OBS conectado correctamente")
        else:
            c.set_warning("OBS no conectado")
        self.checks.append(c)

    def _check_stream_detection(self) -> None:
        c = DiagnosticCheck(
            "Detección del stream",
            "Verifica que se detecte correctamente el estado del stream",
            "Inicia un stream en OBS para probar la detección",
        )
        if self.obs_listener.streaming:
            c.set_ok("Stream detectado correctamente")
        elif self.obs_listener.connected:
            c.set_warning("OBS conectado pero sin stream activo")
        else:
            c.set_warning("No se puede verificar (OBS no conectado)")
        self.checks.append(c)

    def _check_appdata_folder(self) -> None:
        c = DiagnosticCheck(
            "Carpeta AppData",
            "Verifica que la carpeta de datos sea accesible",
            "",
        )
        data_dir = self.config_manager.data_dir
        if os.path.isdir(data_dir):
            c.set_ok(f"Datos en: {data_dir}")
        else:
            try:
                os.makedirs(data_dir, exist_ok=True)
                c.set_ok(f"Carpeta creada: {data_dir}")
            except Exception as e:
                c.set_error(f"No se puede acceder a AppData: {e}")
        self.checks.append(c)

    def _check_config_file(self) -> None:
        c = DiagnosticCheck(
            "Configuración",
            "Verifica que el archivo de configuración sea válido",
            "Si está dañado, puedes restablecer los valores predeterminados",
        )
        cfg_path = self.config_manager.config_path
        if os.path.exists(cfg_path):
            try:
                import json
                with open(cfg_path) as f:
                    json.load(f)
                c.set_ok("Archivo de configuración válido")
            except Exception as e:
                c.set_error(f"Configuración dañada: {e}", "Usa 'Restablecer valores predeterminados'")
        else:
            c.set_warning("No se encontró archivo de configuración (se creará al guardar)")
        self.checks.append(c)

    def _check_logs_dir(self) -> None:
        c = DiagnosticCheck(
            "Logs",
            "Verifica que el directorio de logs sea accesible",
            "",
        )
        logs_dir = self.config_manager.logs_dir
        if os.path.isdir(logs_dir):
            c.set_ok(f"Logs en: {logs_dir}")
        else:
            try:
                os.makedirs(logs_dir, exist_ok=True)
                c.set_ok("Directorio de logs listo")
            except Exception as e:
                c.set_error(f"No se puede crear directorio de logs: {e}")
        self.checks.append(c)

    def _check_internet(self) -> None:
        c = DiagnosticCheck(
            "Internet",
            "Verifica conexión a internet",
            "Revisa tu conexión de red",
        )
        try:
            import urllib.request
            urllib.request.urlopen("https://www.google.com", timeout=5)
            c.set_ok("Conexión a internet disponible")
        except Exception:
            c.set_error("Sin conexión a internet")
        self.checks.append(c)

    def _check_github(self) -> None:
        c = DiagnosticCheck(
            "GitHub accesible",
            "Verifica acceso a GitHub para actualizaciones",
            "Revisa tu conexión o configuración de firewall",
        )
        try:
            import urllib.request
            urllib.request.urlopen("https://github.com", timeout=5)
            c.set_ok("GitHub accesible")
        except Exception:
            c.set_warning("GitHub no accesible (puede afectar actualizaciones)")
        self.checks.append(c)

    def _check_python_version(self) -> None:
        c = DiagnosticCheck(
            "Versión de Python",
            "Versión del intérprete de Python",
            "",
        )
        v = sys.version
        c.set_ok(v.split()[0])
        self.checks.append(c)

    def _check_app_version(self) -> None:
        c = DiagnosticCheck(
            "Versión del programa",
            "Versión instalada de Obsidian Stream Connect",
            "",
        )
        from gui import APP_VERSION
        c.set_ok(f"v{APP_VERSION}")
        self.checks.append(c)

    def get_summary(self) -> Dict[str, Any]:
        errors = [c for c in self.checks if c.status == "error"]
        warnings = [c for c in self.checks if c.status == "warning"]
        return {
            "total": len(self.checks),
            "errors": len(errors),
            "warnings": len(warnings),
            "ok": len(self.checks) - len(errors) - len(warnings),
            "error_details": [c.to_dict() for c in errors],
            "warning_details": [c.to_dict() for c in warnings],
        }

    def export_text(self) -> str:
        lines = [
            "=" * 60,
            "INFORME DE DIAGNÓSTICO",
            "=" * 60,
            f"Fecha: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Versión del programa: v{DIAGNOSTIC_VERSION}",
            f"Sistema operativo: {platform.system()} {platform.release()}",
            f"Python: {sys.version.split()[0]}",
            "",
            "-" * 60,
            "RESULTADOS",
            "-" * 60,
            "",
        ]
        for c in self.checks:
            icon = {"ok": "✓", "warning": "⚠", "error": "✗"}.get(c.status, "?")
            lines.append(f"{icon} {c.name}")
            lines.append(f"   {c.message}")
            if c.fix_hint:
                lines.append(f"   Solución: {c.fix_hint}")
            lines.append("")

        summary = self.get_summary()
        lines.extend([
            "-" * 60,
            "RESUMEN",
            "-" * 60,
            f"Total: {summary['total']}",
            f"✓ Correctos: {summary['ok']}",
            f"⚠ Advertencias: {summary['warnings']}",
            f"✗ Errores: {summary['errors']}",
            "",
            "=" * 60,
        ])
        return "\n".join(lines)

    def export_json(self) -> str:
        data = {
            "fecha": datetime.datetime.now().isoformat(),
            "version_programa": DIAGNOSTIC_VERSION,
            "version_app": self.config.get("_app_version", "desconocida"),
            "sistema_operativo": f"{platform.system()} {platform.release()}",
            "python": sys.version,
            "checks": [c.to_dict() for c in self.checks],
            "resumen": self.get_summary(),
            "config": {k: v for k, v in self.config.items() if not k.startswith("_") and k != "obs_password"},
        }
        return json.dumps(data, indent=2, ensure_ascii=False)


class DiagnosticDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        runner: DiagnosticRunner,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.runner = runner
        self.log = LogManager.get_instance()
        self._running = False

        self.title("Diagnóstico del sistema")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = 640, 520
        self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        self.minsize(520, 400)

        self._build_ui()
        self._start_diagnostic()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top, text="🔍 Diagnóstico del sistema",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self._progress_bar = ctk.CTkProgressBar(top, width=200)
        self._progress_bar.grid(row=0, column=1, padx=(12, 8), sticky="ew")
        self._progress_bar.set(0)

        self._progress_lbl = ctk.CTkLabel(top, text="0%", font=("Segoe UI", 10), width=40)
        self._progress_lbl.grid(row=0, column=2, sticky="w")

        # scrollable results
        self._results_frame = ctk.CTkScrollableFrame(self)
        self._results_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 8))
        self._results_frame.grid_columnconfigure(0, weight=1)

        self._result_widgets: Dict[str, Any] = {}

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        bottom.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        ctk.CTkButton(
            bottom, text="↻ Repetir", command=self._restart,
            font=("Segoe UI", 10), fg_color="#444", hover_color="#555",
        ).grid(row=0, column=0, padx=2, sticky="ew")

        ctk.CTkButton(
            bottom, text="📄 Exportar TXT", command=self._export_txt,
            font=("Segoe UI", 10), fg_color="#444", hover_color="#555",
        ).grid(row=0, column=1, padx=2, sticky="ew")

        ctk.CTkButton(
            bottom, text="📋 Exportar JSON", command=self._export_json,
            font=("Segoe UI", 10), fg_color="#444", hover_color="#555",
        ).grid(row=0, column=2, padx=2, sticky="ew")

        ctk.CTkButton(
            bottom, text="📋 Copiar informe", command=self._copy_report,
            font=("Segoe UI", 10), fg_color="#444", hover_color="#555",
        ).grid(row=0, column=3, padx=2, sticky="ew")

        ctk.CTkButton(
            bottom, text="Cerrar", command=self.destroy,
            font=("Segoe UI", 10), fg_color="#333", hover_color="#444",
        ).grid(row=0, column=4, padx=2, sticky="ew")

    def _start_diagnostic(self) -> None:
        self._running = True
        for w in self._result_widgets.values():
            w.destroy()
        self._result_widgets = {}
        self._progress_bar.set(0)
        self._progress_lbl.configure(text="0%")

        def _progress(current: int, total: int) -> None:
            pct = current / total
            self.after(0, lambda: self._progress_bar.set(pct))
            self.after(0, lambda: self._progress_lbl.configure(text=f"{int(pct * 100)}%"))

        def _done() -> None:
            self._running = False
            self._progress_lbl.configure(text="100%")
            self._progress_bar.set(1)
            self.log.success("Diagnóstico completado")
            summary = self.runner.get_summary()
            if summary["errors"]:
                self.log.error(f"Diagnóstico: {summary['errors']} error(es) encontrados")
            if summary["warnings"]:
                self.log.warning(f"Diagnóstico: {summary['warnings']} advertencia(s)")

        def _run():
            self.runner.run_all(progress_callback=_progress)
            self.after(0, _done)
            self.after(0, self._display_results)

        threading.Thread(target=_run, daemon=True).start()

    def _display_results(self) -> None:
        for c in self.runner.checks:
            row = ctk.CTkFrame(self._results_frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(1, weight=1)

            icon = {"ok": "✓", "warning": "⚠", "error": "✗", "pending": "○"}.get(c.status, "?")
            color = {"ok": "#00cc66", "warning": "#ffaa00", "error": "#ff4444", "pending": "#888"}.get(c.status, "#888")

            ctk.CTkLabel(row, text=icon, font=("Segoe UI", 14), text_color=color, width=24).grid(
                row=0, column=0, sticky="n"
            )

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=1, sticky="ew", padx=(4, 0))
            ctk.CTkLabel(info, text=c.name, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
            ctk.CTkLabel(info, text=c.message, font=("Segoe UI", 10), text_color="#888", anchor="w", wraplength=450).pack(fill="x")
            if c.fix_hint and c.status in ("error", "warning"):
                ctk.CTkLabel(
                    info, text=f"💡 {c.fix_hint}",
                    font=("Segoe UI", 10), text_color="#ffaa00", anchor="w", wraplength=450,
                ).pack(fill="x")

            self._result_widgets[c.name] = row

    def _restart(self) -> None:
        self._start_diagnostic()

    def _export_txt(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Exportar diagnóstico",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.runner.export_text())
                self.log.success(f"Diagnóstico exportado: {path}")
            except Exception as e:
                self.log.error(f"Error al exportar: {e}")

    def _export_json(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Exportar diagnóstico (JSON)",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.runner.export_json())
                self.log.success(f"Diagnóstico exportado: {path}")
            except Exception as e:
                self.log.error(f"Error al exportar: {e}")

    def _copy_report(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.runner.export_text())
        self.log.success("Informe copiado al portapapeles")
