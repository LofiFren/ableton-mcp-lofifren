"""Minimal direct-socket client for the AbletonMCP remote script.

Bypasses the MCP server entirely so we can test from any Python environment.
The protocol is plain JSON over a TCP socket on localhost:9877.
"""
from __future__ import annotations
import json
import socket
from typing import Any, Dict, List, Optional


HOST = "localhost"
PORT = 9877


class AbletonClient:
    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self) -> None:
        if self.sock is not None:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self.sock = s

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def __enter__(self) -> "AbletonClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _recv_json(self) -> Dict[str, Any]:
        assert self.sock is not None
        chunks: List[bytes] = []
        while True:
            chunk = self.sock.recv(8192)
            if not chunk:
                if not chunks:
                    raise RuntimeError("Ableton closed the connection with no data")
                break
            chunks.append(chunk)
            try:
                data = b"".join(chunks)
                return json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue
        # If we got here we ran out of data without parsing
        data = b"".join(chunks)
        return json.loads(data.decode("utf-8"))

    def send(self, command_type: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.connect()
        assert self.sock is not None
        payload = json.dumps({"type": command_type, "params": params or {}}).encode("utf-8")
        self.sock.sendall(payload)
        response = self._recv_json()
        if response.get("status") == "error":
            raise RuntimeError(
                "Ableton error for {0}: {1}".format(command_type, response.get("message", "?"))
            )
        return response.get("result", {})

    def batch(self, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.send("batch_commands", {"commands": commands})


if __name__ == "__main__":
    # Quick smoke test: just print session info.
    with AbletonClient() as ab:
        info = ab.send("get_session_info")
        print(json.dumps(info, indent=2))
