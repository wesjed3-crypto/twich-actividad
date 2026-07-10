"""Sistema de actualización automática desde GitHub Releases."""

import json
import os
import ssl
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Callable, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

import customtkinter as ctk

from utils import LogManager

GITHUB_REPO = "wesjed3-crypto/twich-actividad"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
SKIP_FILE = "skip_version.txt"


def _parse_version(v: str) -> tuple:
    try:
        v = v.lstrip("v")
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0, 0, 0)


class Updater:
    def __init__(self, current_version: str, data_dir: str) -> None:
        self.current_version = current_version
        self.data_dir = data_dir
        self.log = LogManager.get_instance()

        self.latest_version: Optional[str] = None
        self.release_url: Optional[str] = None
        self.release_notes: Optional[str] = None
        self.download_url: Optional[str] = None
        self._checked = False

    def check(self, include_beta: bool = False, callback: Optional[Callable] = None) -> None:
        def _run():
            self._checked = True
            try:
                self.log.info("Verificando actualizaciones...")
                ctx = ssl.create_default_context()
                req = Request(GITHUB_API, headers={"User-Agent": "ObsidianStreamConnect/1.0"})
                resp = urlopen(req, timeout=10, context=ctx)
                data = json.loads(resp.read().decode("utf-8"))

                tag = data.get("tag_name", "").lstrip("v")
                self.latest_version = tag or "0.0.0"
                self.release_url = data.get("html_url", RELEASES_URL)
                self.release_notes = data.get("body", "Sin notas de versión.")

                for asset in data.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith((".exe", ".zip", ".7z")):
                        self.download_url = asset.get("browser_download_url", "")
                        break

                self.log.info(f"Versión actual: v{self.current_version}, última: v{self.latest_version}")

                if _parse_version(self.latest_version) > _parse_version(self.current_version):
                    self.log.success(f"Nueva versión disponible: v{self.latest_version}")
                    if callback:
                        callback(True, self.latest_version, self.release_notes, self.download_url, self.release_url)
                else:
                    self.log.info("Ya tienes la última versión.")
                    if callback:
                        callback(False, None, None, None, None)
            except URLError:
                self.log.warning("No se pudo conectar con GitHub para verificar actualizaciones.")
                if callback:
                    callback(False, None, None, None, None)
            except Exception as e:
                self.log.warning(f"Error al verificar actualizaciones: {e}")
                if callback:
                    callback(False, None, None, None, None)

        threading.Thread(target=_run, daemon=True).start()

    def is_skipped(self, version: str) -> bool:
        path = os.path.join(self.data_dir, SKIP_FILE)
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip() == version
        return False

    def skip_version(self, version: str) -> None:
        path = os.path.join(self.data_dir, SKIP_FILE)
        with open(path, "w") as f:
            f.write(version)

    def open_releases(self) -> None:
        webbrowser.open(RELEASES_URL)


class UpdateDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        updater: Updater,
        version: str,
        notes: str,
        download_url: Optional[str],
        release_url: str,
    ) -> None:
        super().__init__(parent)
        self.updater = updater
        self.version = version
        self.download_url = download_url
        self.release_url = release_url
        self._downloading = False

        self.title("Nueva versión disponible")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = 520, 480
        self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(
            frame, text="🔄 Nueva versión disponible",
            font=("Segoe UI", 16, "bold"),
        ).pack(pady=(0, 4))

        info_frame = ctk.CTkFrame(frame, fg_color="transparent")
        info_frame.pack(fill="x", pady=(0, 8))

        r1 = ctk.CTkFrame(info_frame, fg_color="transparent")
        r1.pack(fill="x", pady=2)
        ctk.CTkLabel(r1, text="Versión instalada:", font=("Segoe UI", 11), width=130, anchor="w").pack(side="left")
        ctk.CTkLabel(r1, text=f"v{updater.current_version}", font=("Segoe UI", 11), text_color="#888").pack(side="left")

        r2 = ctk.CTkFrame(info_frame, fg_color="transparent")
        r2.pack(fill="x", pady=2)
        ctk.CTkLabel(r2, text="Última versión:", font=("Segoe UI", 11), width=130, anchor="w").pack(side="left")
        ctk.CTkLabel(r2, text=f"v{version}", font=("Segoe UI", 11, "bold"), text_color="#00cc66").pack(side="left")

        sep = ctk.CTkFrame(frame, height=1, fg_color="#444")
        sep.pack(fill="x", padx=10, pady=(4, 8))

        ctk.CTkLabel(
            frame, text="Cambios:",
            font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(fill="x", pady=(0, 4))

        notes_box = ctk.CTkTextbox(frame, height=140, font=("Segoe UI", 11), wrap="word")
        notes_box.pack(fill="x", pady=(0, 12))
        notes_box.insert("1.0", notes or "Sin notas de versión.")
        notes_box.configure(state="disabled")

        self._progress_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self._progress_frame.pack(fill="x", pady=(0, 8))
        self._progress_label = ctk.CTkLabel(self._progress_frame, text="", font=("Segoe UI", 10))
        self._progress_label.pack()
        self._progress_bar = ctk.CTkProgressBar(self._progress_frame, width=460)
        self._progress_bar.pack()
        self._progress_bar.set(0)
        self._progress_frame.pack_forget()

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self._btn_update = ctk.CTkButton(
            btn_frame, text="Actualizar ahora",
            command=self._on_update,
            font=("Segoe UI", 11), fg_color="#1a5c2a", hover_color="#1f7a36",
        )
        self._btn_update.grid(row=0, column=0, padx=2, sticky="ew")

        ctk.CTkButton(
            btn_frame, text="Recordar más tarde",
            command=self.destroy,
            font=("Segoe UI", 11), fg_color="#444", hover_color="#555",
        ).grid(row=0, column=1, padx=2, sticky="ew")

        ctk.CTkButton(
            btn_frame, text="Omitir esta versión",
            command=self._on_skip,
            font=("Segoe UI", 11), fg_color="#553333", hover_color="#774444",
        ).grid(row=0, column=2, padx=2, sticky="ew")

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_update(self) -> None:
        if self._downloading:
            return

        if not self.download_url:
            self.updater.open_releases()
            self.destroy()
            return

        self._downloading = True
        self._btn_update.configure(state="disabled", text="Descargando...")
        self._progress_frame.pack(fill="x", pady=(0, 8))
        threading.Thread(target=self._download, daemon=True).start()

    def _on_skip(self) -> None:
        self.updater.skip_version(self.version)
        self.destroy()

    def _download(self) -> None:
        try:
            import tempfile
            ctx = ssl.create_default_context()
            req = Request(self.download_url, headers={"User-Agent": "ObsidianStreamConnect/1.0"})
            resp = urlopen(req, timeout=30, context=ctx)
            total = int(resp.headers.get("Content-Length", 0))
            chunk_size = 8192
            downloaded = 0

            ext = os.path.splitext(self.download_url)[1] or ".exe"
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            temp_path = temp.name

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                temp.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total
                    self.after(0, lambda p=pct: self._progress_bar.set(p))
                    self.after(0, lambda d=downloaded, t=total: self._progress_label.configure(
                        text=f"Descargado {d // 1024} KB de {t // 1024} KB"
                    ))
            temp.close()

            self.after(0, lambda: self._progress_label.configure(text="Descarga completada. Instalando..."))
            self.after(0, lambda: self._progress_bar.set(1))

            time.sleep(0.5)

            if ext == ".exe":
                self._install_exe(temp_path)
            else:
                self.updater.open_releases()
                self.destroy()

        except Exception as e:
            self.after(0, lambda: self._progress_label.configure(text=f"Error: {e}"))
            self.after(0, lambda: self._btn_update.configure(state="normal", text="Reintentar"))
            self._downloading = False

    def _install_exe(self, new_exe: str) -> None:
        current = os.path.abspath(sys.argv[0])
        if not current.endswith(".exe"):
            self.updater.open_releases()
            self.destroy()
            return

        bat_path = os.path.join(os.path.dirname(current), "_update.bat")
        bat_content = (
            f'@echo off\n'
            f'timeout /t 2 /nobreak >nul\n'
            f'del /f /q "{current}"\n'
            f'move /y "{new_exe}" "{current}"\n'
            f'start "" "{current}"\n'
            f'del /f /q "%~f0"\n'
        )
        with open(bat_path, "w") as f:
            f.write(bat_content)

        self.after(300, lambda: self._perform_quit(bat_path))

    def _perform_quit(self, bat_path: str) -> None:
        subprocess.Popen(
            [bat_path], shell=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.master.destroy()
        sys.exit(0)
