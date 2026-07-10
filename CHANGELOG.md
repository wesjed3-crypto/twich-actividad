# Changelog

## [1.0.0] - 2026-07-10
### Added
- Asistente de bienvenida interactivo al primer inicio (6 paginas).
- Menu de ayuda completo: Guia inicial, README, GitHub, Reportar error, Licencia, Changelog, Acerca de.
- Ventana Acerca de renovada con creditos de Wesjed.
- Boton "Mis redes" en la barra de estado y en ventana About (https://guns.lol/wesjed).
- Atajos de teclado: CTRL+S (actualizar), CTRL+R (OBS), CTRL+Q (salir), F5 (Discord), F1 (ayuda).
- Opcion de renombrar perfiles.
- Icono de aplicacion generado en codigo (Pillow).
- Sistema "dirty flag" para evitar escrituras innecesarias de config.json.

### Changed
- Creditos actualizados: todas las referencias de desarrollador ahora indican Wesjed.
- Rendimiento optimizado: health-check con deteccion de cambios reales, polling reducido a 500ms.
- Persistencia completa de configuracion: pestana activa, filtro de logs, busqueda.
- Configuracion movida a `%APPDATA%/Obsidian Stream Connect/`.
- Soporte para archivo `.env` con `DISCORD_CLIENT_ID`.
- Almacenamiento seguro de contrasena OBS en Windows Credential Manager.
- Version actualizada a 1.0.0 estable.

### Fixed
- Eliminados datos personales, IDs y rutas absolutas del codigo fuente.
- Importaciones no utilizadas eliminadas.
- Tooltips con ventana compartida y posicionamiento inteligente.

## [0.9.0] - 2025-06-15
### Added
- Maquina de estados de OBS con 10 estados (`StreamState`).
- Selector de tipo de actividad (Playing, Streaming, Listening, Watching, Competing).
- Auto-descubrimiento de OBS WebSocket en puertos comunes.
- Sistema de plantillas de perfil.

### Fixed
- Manejo robusto de desconexion/reconexion de OBS.
