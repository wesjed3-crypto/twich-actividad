# Obsidian Stream Connect

**Obsidian Stream Connect** sincroniza tu estado de streaming de OBS Studio con Discord Rich Presence. Cuando inicias o detienes un stream en OBS, tu estado de Discord se actualiza automáticamente.

## Características

- **Detección automática de OBS** — Descubre OBS WebSocket en los puertos comunes sin configuración manual.
- **Rich Presence personalizable** — Título, detalles, imágenes, botones y tipo de actividad.
- **Vista previa en tiempo real** — La tarjeta de presencia se actualiza al instante mientras configuras.
- **Asistente de bienvenida** — Guía interactiva de 6 páginas con verificación automática al finalizar.
- **10 estados de stream** — Seguimiento preciso del ciclo de vida de OBS.
- **Perfiles y plantillas** — Guarda, duplica, renombra, exporta e importa configuraciones.
- **Menú de ayuda integrado** — Acceso directo a README, GitHub, reporte de errores y changelog.
- **Atajos de teclado** — CTRL+S, CTRL+R, CTRL+Q, F5, F1.
- **Inicio automático** — Opción para iniciar con Windows y minimizar a la bandeja del sistema.
- **Tema claro/oscuro** — Interfaz adaptable.
- **Seguro** — La contraseña de OBS se almacena en Windows Credential Manager, nunca en texto plano.

## Requisitos

- Windows 10/11
- Python 3.10+
- OBS Studio 28+ con [OBS WebSocket](https://obsproject.com/forum/resources/obs-websocket-5.0.0-rc3.1589/) habilitado

## Instalación

```bash
git clone https://github.com/wesjed3-crypto/twich-actividad.git
cd twich-actividad
pip install -r requirements.txt
```

Copia `.env.example` a `.env` y configura tu Discord Application ID:

```
DISCORD_CLIENT_ID=123456789012345678
```

Ejecuta:

```bash
python main.py
```

## Configuración

### Discord

1. Crea una aplicación en [Discord Developer Portal](https://discord.com/developers/applications).
2. Copia el **Application ID** al campo correspondiente en la app o al archivo `.env`.
3. Sube los assets (imágenes) de Rich Presence en la sección **Rich Presence > Art Assets**.

### OBS

1. Abre OBS Studio.
2. Ve a **Herramientas > WebSocket > Configuración del Servidor**.
3. Habilita el WebSocket y opcionalmente establece una contraseña.
4. La aplicación detectará OBS automáticamente o puedes ingresar los datos manualmente.

## Compilación a .exe

```bash
pip install pyinstaller
pyinstaller ObsidianStreamConnect.spec
```

El ejecutable se generará en `dist/ObsidianStreamConnect.exe`.

## Desarrollador

Este proyecto ha sido desarrollado por **Wesjed**.

Redes oficiales: https://guns.lol/wesjed

## Licencia

[MIT](LICENSE)
