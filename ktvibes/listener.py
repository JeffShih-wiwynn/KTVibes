"""Reserve a listener without changing external tunnel destinations."""
import os
import socket


def reserve(preferred: int, *, external: bool):
    candidates = [preferred] if external else [*range(preferred, min(preferred + 5, 65536)), *range(preferred + 10000, min(preferred + 10005, 65536))]
    for port in candidates:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('0.0.0.0', port))
            listener.listen(2048)
            return listener
        except OSError:
            listener.close()
    return None
