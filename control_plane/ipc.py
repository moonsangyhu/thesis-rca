"""Length-bounded Unix socket transport for signed Controller commands."""

from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import struct
from pathlib import Path
from typing import Any

from .audit import CommandAuditLog
from .commands import ThesisCommandRouter
from .protocol import (
    CommandEnvelope,
    EnvelopeError,
    EnvelopeSigner,
    encode_response,
    validate_freshness,
)

MAX_REQUEST_BYTES = 16 * 1024


class ControllerEndpoint:
    def __init__(self, router: ThesisCommandRouter, signer: EnvelopeSigner):
        self.router = router
        self.signer = signer
        self.audit = CommandAuditLog(router.controller.runtime_root)

    def handle(self, value: dict[str, Any]) -> dict:
        try:
            envelope = CommandEnvelope.parse(value)
            if not self.signer.verify(envelope):
                return {"status": "rejected", "reason": "invalid_envelope_signature"}
            validate_freshness(envelope)
        except EnvelopeError as exc:
            return {"status": "rejected", "reason": str(exc)}
        result = self.router.handle(envelope)
        self.audit.append(envelope, result)
        return result


def peer_uid(connection: socket.socket) -> int | None:
    if hasattr(connection, "getpeereid"):
        uid, _gid = connection.getpeereid()
        return int(uid)
    if hasattr(socket, "LOCAL_PEERCRED"):
        # Darwin exposes xucred through SOL_LOCAL(0)/LOCAL_PEERCRED. Python's
        # socket module exports the option but not SOL_LOCAL or xucred itself.
        raw = connection.getsockopt(0, socket.LOCAL_PEERCRED, 12)
        _version, uid = struct.unpack("=Ii", raw[:8])
        return int(uid)
    if hasattr(socket, "SO_PEERCRED"):
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return int(uid)
    return None


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server = self.server
        uid = peer_uid(self.request)
        if uid is None or uid not in server.allowed_peer_uids:
            self.wfile.write(encode_response({"status": "rejected", "reason": "peer_not_allowed"}))
            return
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            self.wfile.write(encode_response({"status": "rejected", "reason": "request_too_large"}))
            return
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.wfile.write(encode_response({"status": "rejected", "reason": "invalid_json"}))
            return
        self.wfile.write(encode_response(server.endpoint.handle(value)))


class UnixControllerServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(
        self,
        socket_path: Path,
        endpoint: ControllerEndpoint,
        *,
        allowed_peer_uids: set[int],
    ):
        self.socket_path = Path(socket_path)
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.socket_path.exists():
            raise FileExistsError(f"refusing to replace existing socket path: {self.socket_path}")
        self.endpoint = endpoint
        self.allowed_peer_uids = frozenset(allowed_peer_uids)
        if not self.allowed_peer_uids:
            raise ValueError("at least one peer uid is required")
        super().__init__(str(self.socket_path), _RequestHandler)
        os.chmod(self.socket_path, 0o600)
        self._bound_inode = self.socket_path.stat().st_ino

    def server_close(self) -> None:
        super().server_close()
        try:
            current = self.socket_path.stat()
            if current.st_ino == self._bound_inode and stat.S_ISSOCK(current.st_mode):
                self.socket_path.unlink()
        except FileNotFoundError:
            pass


def send_command(socket_path: Path, envelope: CommandEnvelope, timeout: float = 5.0) -> dict:
    payload = encode_response(envelope.to_dict())
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("request too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(payload)
        received = b""
        while not received.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            received += chunk
            if len(received) > MAX_REQUEST_BYTES:
                raise ValueError("response too large")
    return json.loads(received)
