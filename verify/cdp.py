#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zero-dependency Chrome DevTools Protocol client (stdlib only).

Implements just enough of RFC6455 to talk to a Chromium --remote-debugging-port
endpoint: HTTP target discovery, masked client frames, continuation frames,
ping/pong, and Runtime.evaluate / arbitrary CDP calls.

Usage:
    python cdp.py "<javascript expression>"     # evaluate on the main page
    python cdp.py --list                        # list page targets
"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from urllib.parse import urlparse

DEFAULT_PORT = 9222


def http_json(path, port=DEFAULT_PORT, timeout=6):
    url = "http://127.0.0.1:%d%s" % (port, path)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def version(port=DEFAULT_PORT, timeout=6):
    return http_json("/json/version", port, timeout)


def list_targets(port=DEFAULT_PORT, timeout=6):
    return http_json("/json/list", port, timeout)


def pick_target(port=DEFAULT_PORT, url_contains=None, title_contains=None, index=0, timeout=6):
    """Pick a page target. Prefers the Doubao main window when no filter given."""
    pages = [t for t in list_targets(port, timeout)
             if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        raise RuntimeError("no page targets on CDP port %d" % port)
    if url_contains:
        pages = [t for t in pages if url_contains.lower() in (t.get("url") or "").lower()]
    if title_contains:
        pages = [t for t in pages if title_contains.lower() in (t.get("title") or "").lower()]
    if not pages:
        # Fall back to all pages; the caller may know better than we do.
        pages = [t for t in list_targets(port, timeout)
                 if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    # Prefer a Doubao-looking target over devtools/about:blank pages.
    pages.sort(key=lambda t: (
        0 if ("doubao" in (t.get("url") or "").lower()
              or "doubao" in (t.get("title") or "").lower()
              or "豆包" in (t.get("title") or "")) else 1,
        t.get("title") == "",
    ))
    return pages[min(index, len(pages) - 1)]


class CDP:
    def __init__(self, ws_url, timeout=20):
        u = urlparse(ws_url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 80
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.timeout = timeout
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        req = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n\r\n"
        ) % (path, host, port, key)
        self.sock.sendall(req.encode("ascii"))

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake closed by peer")
            buf += chunk
        head, self._buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("websocket handshake failed: " + head.decode("utf-8", "replace")[:200])

        self._id = 0
        self.events = []
        self._fragments = b""

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise RuntimeError("socket closed while reading websocket frame")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, payload, opcode=1, fin=True):
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        b1 = (0x80 if fin else 0) | opcode
        n = len(data)
        if n < 126:
            hdr = struct.pack("!BB", b1, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", b1, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", b1, 0x80 | 127, n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(hdr + mask + masked)

    def _recv_message(self):
        while True:
            b0, b1 = self._recv_exact(2)
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else None
            data = self._recv_exact(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:                     # ping -> pong
                self._send_frame(data, opcode=0xA)
                continue
            if opcode == 0xA:                     # pong
                continue
            if opcode == 0x8:
                raise RuntimeError("websocket closed by peer")
            if opcode in (0x0, 0x1, 0x2):
                if opcode != 0x0:
                    self._fragments = b""
                self._fragments += data
                if not fin:
                    continue
                text = self._fragments.decode("utf-8", "replace")
                self._fragments = b""
                return text

    def call(self, method, params=None, timeout=None):
        self._id += 1
        mid = self._id
        frame = json.dumps({"id": mid, "method": method, "params": params or {}},
                           ensure_ascii=False)
        self._send_frame(frame)
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            self.sock.settimeout(max(0.1, min(5.0, deadline - time.time())))
            try:
                msg = self._recv_message()
            except socket.timeout:
                continue
            try:
                obj = json.loads(msg)
            except ValueError:
                continue
            if obj.get("id") == mid:
                if "error" in obj:
                    raise RuntimeError("%s -> %s" % (method, json.dumps(obj["error"], ensure_ascii=False)[:400]))
                return obj.get("result", {})
            self.events.append(obj)
        raise TimeoutError("CDP call timed out: %s" % method)

    def evaluate(self, expression, await_promise=False, timeout=None):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "userGesture": True,
        }, timeout=timeout)
        if result.get("exceptionDetails"):
            raise RuntimeError("evaluate exception: " +
                               json.dumps(result["exceptionDetails"], ensure_ascii=False)[:600])
        return result.get("result", {}).get("value")

    def collect_events(self, seconds=1.0):
        """Drain pending CDP events without waiting for a command response."""
        end = time.time() + seconds
        while time.time() < end:
            self.sock.settimeout(max(0.05, min(0.3, end - time.time())))
            try:
                self.events.append(json.loads(self._recv_message()))
            except (socket.timeout, ValueError, RuntimeError):
                break

    def close(self):
        try:
            self._send_frame(b"", opcode=0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    port = DEFAULT_PORT
    if args[0] == "--port" and len(args) > 2:
        port = int(args[1])
        args = args[2:]
    if args[0] == "--list":
        for t in list_targets(port):
            print(json.dumps({k: t.get(k) for k in ("type", "title", "url", "id")},
                             ensure_ascii=False))
        return 0
    target = pick_target(port)
    c = CDP(target["webSocketDebuggerUrl"])
    try:
        value = c.evaluate(" ".join(args))
        print(json.dumps(value, ensure_ascii=False, indent=2))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
