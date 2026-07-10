# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please open an issue with the label `security` or contact the maintainers directly.

We will acknowledge receipt within 48 hours and work on a fix as soon as possible.

## Best Practices

- Do **not** commit your `.env` file or any file containing real tokens, client IDs, or passwords.
- The OBS WebSocket password is stored in Windows Credential Manager, not in `config.json`.
- Your Discord Application ID is loaded from the `.env` file or entered manually in the UI; it is never hardcoded.
- All configuration files in `%APPDATA%/Obsidian Stream Connect/` are local to your machine and should not be shared.
