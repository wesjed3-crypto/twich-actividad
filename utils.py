from datetime import datetime
from queue import Queue
from typing import Any, Callable, Dict, List, Optional


_MAX_LOG_COUNT = 1000


class LogManager:
    """Gestiona los logs de la aplicación con una cola thread-safe.

    Los mensajes se almacenan en una cola que el GUI consume
    periódicamente desde el hilo principal para evitar problemas
    de concurrencia con CustomTkinter. También mantiene un historial
    completo para filtrado, búsqueda y exportación.
    El historial se poda automáticamente cuando supera _MAX_LOG_COUNT.
    """

    _instance: Optional['LogManager'] = None

    @classmethod
    def get_instance(cls) -> 'LogManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.log_queue: Queue = Queue()
        self._all_logs: List[Dict[str, str]] = []
        self._callbacks: List[Callable] = []

    def info(self, message: str) -> None:
        self._add_log("INFO", message)

    def warning(self, message: str) -> None:
        self._add_log("WARNING", message)

    def error(self, message: str) -> None:
        self._add_log("ERROR", message)

    def success(self, message: str) -> None:
        self._add_log("SUCCESS", message)

    def _add_log(self, level: str, message: str) -> None:
        now = datetime.now()
        entry = {
            "date": now.strftime("%Y-%m-%d"),
            "timestamp": now.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        self._all_logs.append(entry)
        if len(self._all_logs) > _MAX_LOG_COUNT:
            self._all_logs = self._all_logs[-_MAX_LOG_COUNT:]
        self.log_queue.put(entry)
        for cb in self._callbacks:
            try:
                cb(entry)
            except Exception:
                pass

    def register_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def get_logs(
        self,
        level: Optional[str] = None,
        search: Optional[str] = None,
        max_count: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """Retorna logs filtrados por nivel y/o texto de búsqueda.

        Args:
            level: Filtrar por nivel (INFO, WARNING, ERROR, SUCCESS).
            search: Texto a buscar en el mensaje.
            max_count: Máximo número de entradas a retornar.

        Returns:
            Lista de entradas de log filtradas.
        """
        result = self._all_logs
        if level:
            result = [e for e in result if e["level"] == level]
        if search:
            lower = search.lower()
            result = [e for e in result if lower in e["message"].lower()]
        if max_count is not None:
            result = result[-max_count:]
        return result

    def clear(self) -> None:
        """Limpia todo el historial de logs."""
        self._all_logs.clear()
        while not self.log_queue.empty():
            try:
                self.log_queue.get_nowait()
            except Exception:
                break

    def export_to_file(self, filepath: str) -> None:
        """Exporta todos los logs a un archivo de texto.

        Args:
            filepath: Ruta del archivo de destino.
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                for entry in self._all_logs:
                    f.write(
                        f"[{entry['date']} {entry['timestamp']}] "
                        f"[{entry['level']}] {entry['message']}\n"
                    )
        except Exception as e:
            self.error(f"Error al exportar logs: {e}")

    @property
    def count(self) -> int:
        return len(self._all_logs)
