"""
blacklist.py - Registro en memoria de tokens invalidados (logout).
Al estar en el mismo proceso que el servidor HTTP y el hilo RabbitMQ RPC,
ambos comparten la misma instancia y pueden consultar/escribir el set.
"""
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
# {token: exp_timestamp}  — guardamos la expiración para poder limpiar periódicamente
_blacklisted: dict[str, float] = {}


def add(token: str, exp: float | None = None) -> None:
    with _lock:
        _blacklisted[token] = exp or 0.0


def contains(token: str) -> bool:
    with _lock:
        return token in _blacklisted


def purge_expired() -> None:
    """Elimina tokens cuya expiración ya pasó para no acumular memoria."""
    now = datetime.now(timezone.utc).timestamp()
    with _lock:
        expired = [t for t, exp in _blacklisted.items() if exp and exp < now]
        for t in expired:
            del _blacklisted[t]
