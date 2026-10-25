"""Localhost Web Server Manager for Pentagon.

Allows users and autonomous agents to run, host, and preview generated websites
and interactive deliverables on dedicated localhost ports (e.g. http://localhost:8080).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)


def find_free_port(start: int = 8080, max_attempts: int = 200) -> int:
    """Find the next available TCP port on localhost."""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    # Ephemeral fallback
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _WebsiteRequestHandler(BaseHTTPRequestHandler):
    """Serve the generated website HTML on localhost with proper headers."""

    html_content: bytes = b""
    title: str = "Pentagon Live Website"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            msg = b'{"status": "ok", "service": "pentagon-localhost-runner"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        elif self.path in ("/", "/index.html", "") or not self.path.startswith("/api/"):
            data = self.html_content
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Served-By", "Pentagon-Localhost-Server")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard output logging for background servers
        pass


class LocalhostServerManager:
    """Singleton manager tracking and controlling live localhost servers."""

    def __init__(self) -> None:
        self._servers: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start_server(
        self,
        html: str | bytes,
        title: str = "Live Deliverable",
        port: int | None = None,
        file_id: str | None = None,
    ) -> dict[str, Any]:
        """Start a dedicated local web server serving the given HTML on localhost."""
        if isinstance(html, str):
            html_bytes = html.encode("utf-8")
        else:
            html_bytes = html

        with self._lock:
            # Check if this file_id already has an active server running
            if file_id:
                for active_port, info in list(self._servers.items()):
                    if info.get("file_id") == file_id:
                        # Update the content in case it was modified
                        info["handler_cls"].html_content = html_bytes
                        info["handler_cls"].title = title
                        return {
                            "ok": True,
                            "url": info["url"],
                            "port": active_port,
                            "server_id": info["server_id"],
                            "title": title,
                            "file_id": file_id,
                            "reused": True,
                        }

            target_port = port or find_free_port()
            server_id = f"srv_{uuid.uuid4().hex[:8]}"

            # Create custom request handler class for this specific server
            handler_cls = type(
                f"Handler_{server_id}",
                (_WebsiteRequestHandler,),
                {"html_content": html_bytes, "title": title},
            )

            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", target_port), handler_cls)
            except OSError as exc:
                logger.warning("Port %s busy, finding another: %s", target_port, exc)
                target_port = find_free_port(start=target_port + 1)
                httpd = ThreadingHTTPServer(("127.0.0.1", target_port), handler_cls)

            thread = threading.Thread(
                target=httpd.serve_forever,
                name=f"PentagonLocalhost_{target_port}",
                daemon=True,
            )
            thread.start()

            url = f"http://localhost:{target_port}"
            server_info = {
                "server_id": server_id,
                "port": target_port,
                "url": url,
                "title": title,
                "file_id": file_id,
                "httpd": httpd,
                "thread": thread,
                "handler_cls": handler_cls,
                "started_at": time.time(),
                "status": "running",
            }
            self._servers[target_port] = server_info
            logger.info("Started localhost server for '%s' at %s (id=%s)", title, url, server_id)

            return {
                "ok": True,
                "url": url,
                "port": target_port,
                "server_id": server_id,
                "title": title,
                "file_id": file_id,
                "reused": False,
            }

    def stop_server(self, port_or_id: int | str) -> bool:
        """Stop an active localhost server by port or server_id."""
        with self._lock:
            target_port = None
            if isinstance(port_or_id, int):
                target_port = port_or_id
            else:
                for p, s in self._servers.items():
                    if s.get("server_id") == port_or_id or s.get("file_id") == port_or_id:
                        target_port = p
                        break

            if target_port is None or target_port not in self._servers:
                return False

            info = self._servers.pop(target_port)
            try:
                info["httpd"].shutdown()
                info["httpd"].server_close()
            except Exception as e:
                logger.warning("Error closing server on port %s: %e", target_port, e)
            logger.info("Stopped localhost server on port %s", target_port)
            return True

    def list_servers(self) -> list[dict[str, Any]]:
        """List all currently active localhost servers."""
        with self._lock:
            out = []
            for port, s in self._servers.items():
                out.append({
                    "server_id": s["server_id"],
                    "port": port,
                    "url": s["url"],
                    "title": s["title"],
                    "file_id": s.get("file_id"),
                    "uptime_seconds": round(time.time() - s["started_at"], 1),
                    "status": s["status"],
                })
            return out

    def get_server_for_file(self, file_id: str) -> dict[str, Any] | None:
        """Get running server details for a file_id, if active."""
        with self._lock:
            for port, s in self._servers.items():
                if s.get("file_id") == file_id:
                    return {
                        "server_id": s["server_id"],
                        "port": port,
                        "url": s["url"],
                        "title": s["title"],
                        "file_id": file_id,
                        "uptime_seconds": round(time.time() - s["started_at"], 1),
                        "status": "running",
                    }
            return None


# Global singleton instance
LOCALHOST_MANAGER = LocalhostServerManager()
