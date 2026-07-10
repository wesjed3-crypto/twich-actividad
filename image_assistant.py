"""Asistente de imágenes para Discord Rich Presence.

Guía al usuario paso a paso para configurar los Art Assets
de su aplicación de Discord Developer Portal.
"""

import webbrowser
from typing import Any, Dict, Optional

import customtkinter as ctk

from utils import LogManager

DISCORD_DEV_URL = "https://discord.com/developers/applications"


class ImageAssistantDialog(ctk.CTkToplevel):
    STEPS = [
        (
            "¿Qué son los Art Assets?",
            "Los Art Assets son las imágenes que aparecen en tu tarjeta de "
            "Rich Presence de Discord.\n\n"
            "Cuando alguien ve tu perfil mientras estás en vivo, verá:\n\n"
            "• Una imagen GRANDE a la izquierda (como el logo de tu stream)\n"
            "• Una imagen PEQUEÑA en la esquina inferior derecha "
            "(como el logo de la plataforma)\n\n"
            "Estas imágenes hacen que tu presencia se vea profesional "
            "y atraen más clics.",
        ),
        (
            "Abrir Discord Developer Portal",
            "Para añadir imágenes, necesitas abrir el Portal de Desarrolladores "
            "de Discord.\n\n"
            "Allí verás tu aplicación y podrás acceder a la sección "
            "'Rich Presence Art Assets'.\n\n"
            "Haz clic en el botón de abajo para abrir la página.",
        ),
        (
            "¿Cómo subir imágenes?",
            "En la sección 'Rich Presence Art Assets' de tu aplicación:\n\n"
            "Formato recomendado: PNG\n"
            "Tamaño recomendado: 1024×1024 píxeles\n"
            "Tamaño máximo: 512 KB\n\n"
            "Consejos:\n"
            "• Usa imágenes cuadradas para mejor visualización\n"
            "• El nombre debe ser descriptivo (ej: twitch_logo)\n"
            "• La imagen grande debe representar tu marca\n"
            "• La imagen pequeña es opcional (ej: icono de plataforma)\n\n"
            "Una vez subida, el sistema tardará unos minutos en procesarla.",
        ),
        (
            "Configurar las claves",
            "Escribe las claves de las imágenes que subiste.\n\n"
            "La clave es el NOMBRE del archivo que pusiste en "
            "Discord Developer Portal (sin extensión).\n\n"
            "Ejemplo: si subiste 'twitch_logo.png', la clave es 'twitch_logo'.",
        ),
    ]

    def __init__(
        self,
        parent: ctk.CTk,
        config: Dict[str, Any],
        on_save: Any,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.config = config
        self.on_save = on_save
        self.log = LogManager.get_instance()
        self._step = 0

        self.title("Asistente de imágenes")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        w, h = 540, 520
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self._build_ui()
        self._show_step(0)

    def _build_ui(self) -> None:
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=24, pady=(24, 8))

        self._step_lbl = ctk.CTkLabel(
            self._content, text="", font=("Segoe UI", 10),
            text_color="#888888",
        )
        self._step_lbl.pack(pady=(0, 4))

        self._title_lbl = ctk.CTkLabel(
            self._content, text="", font=("Segoe UI", 16, "bold"),
        )
        self._title_lbl.pack(pady=(0, 10))

        self._text_lbl = ctk.CTkLabel(
            self._content, text="", font=("Segoe UI", 12),
            wraplength=480, justify="left",
        )
        self._text_lbl.pack(fill="both", expand=True)

        self._action_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        self._action_frame.pack(fill="x", pady=(8, 0))

        self._open_dev_btn = ctk.CTkButton(
            self._action_frame, text="Abrir Discord Developer Portal",
            command=self._open_dev_portal,
            font=("Segoe UI", 11), fg_color="#5865F2", hover_color="#4752C4",
        )

        self._key_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        self._key_frame.pack(fill="x", pady=(8, 0))

        ctk.CTkLabel(
            self._key_frame, text="Large Image Key:",
            font=("Segoe UI", 11),
        ).pack(pady=(4, 2))

        self._large_key_entry = ctk.CTkEntry(
            self._key_frame, placeholder_text="twitch_logo",
        )
        self._large_key_entry.pack(fill="x", pady=(0, 4))
        self._large_key_entry.insert(0, self.config.get("large_image_key", ""))

        ctk.CTkLabel(
            self._key_frame, text="Small Image Key:",
            font=("Segoe UI", 11),
        ).pack(pady=(4, 2))

        self._small_key_entry = ctk.CTkEntry(
            self._key_frame, placeholder_text="plataforma_icon",
        )
        self._small_key_entry.pack(fill="x", pady=(0, 4))
        self._small_key_entry.insert(0, self.config.get("small_image_key", ""))

        self._verification_lbl = ctk.CTkLabel(
            self._key_frame, text="",
            font=("Segoe UI", 11), wraplength=480,
        )
        self._verification_lbl.pack(pady=(8, 0))

        self._preview_frame = ctk.CTkFrame(self._content, corner_radius=10)
        self._preview_frame.pack(fill="x", pady=(8, 0))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(4, 16))

        self._prev_btn = ctk.CTkButton(
            btn_frame, text="← Anterior", command=self._prev_step,
            font=("Segoe UI", 11), fg_color="#444", hover_color="#555",
            width=100,
        )
        self._prev_btn.pack(side="left")

        self._next_btn = ctk.CTkButton(
            btn_frame, text="Siguiente →", command=self._next_step,
            font=("Segoe UI", 11), width=100,
        )
        self._next_btn.pack(side="right")

    def _show_step(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.STEPS):
            return
        title, text = self.STEPS[idx]
        self._step_lbl.configure(text=f"Paso {idx + 1} de {len(self.STEPS)}")
        self._title_lbl.configure(text=title)
        self._text_lbl.configure(text=text)

        for w in (self._action_frame, self._key_frame, self._preview_frame):
            w.pack_forget()

        self._prev_btn.configure(state="normal" if idx > 0 else "disabled")

        if idx == 1:
            self._action_frame.pack(fill="x", pady=(8, 0))
            self._text_lbl.configure(wraplength=480)
            if idx == len(self.STEPS) - 1:
                self._next_btn.configure(text="Finalizar →", command=self._finish)
            else:
                self._next_btn.configure(text="Siguiente →", command=self._next_step)
        elif idx == len(self.STEPS) - 1:
            self._key_frame.pack(fill="x", pady=(8, 0))
            self._update_preview()
            self._next_btn.configure(text="Guardar y cerrar", command=self._finish)
        else:
            self._text_lbl.configure(wraplength=480)
            self._next_btn.configure(text="Siguiente →", command=self._next_step)

    def _next_step(self) -> None:
        self._step += 1
        if self._step >= len(self.STEPS):
            self._step = len(self.STEPS) - 1
        self._show_step(self._step)

    def _prev_step(self) -> None:
        self._step -= 1
        if self._step < 0:
            self._step = 0
        self._show_step(self._step)

    def _open_dev_portal(self) -> None:
        webbrowser.open(DISCORD_DEV_URL)

    def _update_preview(self) -> None:
        for w in self._preview_frame.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self._preview_frame, text="Preview",
            font=("Segoe UI", 10, "bold"), text_color="#888888",
        ).pack(pady=(8, 4))

        preview_row = ctk.CTkFrame(self._preview_frame, fg_color="transparent")
        preview_row.pack(fill="x", padx=12, pady=(0, 8))

        large_key = self._large_key_entry.get().strip() or "sin clave"
        small_key = self._small_key_entry.get().strip() or "sin clave"

        ctk.CTkLabel(preview_row, text="🖼", font=("Segoe UI", 32)).pack(side="left", padx=(0, 12))
        info = ctk.CTkFrame(preview_row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=large_key, font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=f"Pequeña: {small_key}", font=("Segoe UI", 10), text_color="#888", anchor="w").pack(fill="x")

        ctk.CTkButton(
            self._preview_frame, text="Verificar imágenes",
            command=self._verify_keys, font=("Segoe UI", 10), height=24,
            fg_color="#444", hover_color="#555",
        ).pack(pady=(0, 8))

    def _verify_keys(self) -> None:
        self._verification_lbl.configure(
            text="La API de Discord no permite verificar art assets "
                 "de forma remota. Asegúrate de que los nombres coincidan "
                 "exactamente con los que subiste en el Developer Portal.",
            text_color="#ffaa00",
        )

    def _finish(self) -> None:
        self.config["large_image_key"] = self._large_key_entry.get().strip()
        self.config["small_image_key"] = self._small_key_entry.get().strip()
        if self.on_save:
            self.on_save(self.config)
        self.destroy()
