"""Bind behavior under genuine conflicts and immediately closed connections."""
import socket
import os
import pytest
from ktvibes.listener import reserve


def test_external_conflict_does_not_change_port():
    first = reserve(0, external=True)
    try:
        port = first.getsockname()[1]
        assert reserve(port, external=True) is None
        other = reserve(port, external=False)
        try:
            assert other.getsockname()[1] != port
        finally:
            other.close()
    finally:
        first.close()


@pytest.mark.skipif(os.name == 'nt', reason='TIME_WAIT reuse is POSIX-specific; Windows retains exclusive bind protection')
def test_repeated_restarts_reuse_same_port_after_connections():
    listener = reserve(0, external=True)
    port = listener.getsockname()[1]
    try:
        for _ in range(4):
            client = socket.create_connection(('127.0.0.1', port))
            peer, _ = listener.accept()
            peer.sendall(b'bye')
            peer.close()
            assert client.recv(3) == b'bye'
            assert client.recv(1) == b''
            client.close()
            listener.close()
            listener = reserve(port, external=True)
            assert listener is not None
            assert listener.getsockname()[1] == port
    finally:
        if listener:
            listener.close()
