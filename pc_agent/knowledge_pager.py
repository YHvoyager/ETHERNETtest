# -*- coding: utf-8 -*-
"""知识答案的 OLED 分页和 STM32 按键事件接收。"""

from __future__ import annotations

import socket
import threading
from typing import Dict, List, Optional, Sequence

import bitmap
from canvas import Canvas


class KnowledgePager:
    """用一个长期存在的 UDP socket 同时发帧和接收 KEY UP/DOWN。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sock: Optional[socket.socket] = None
        self._addr = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pages: List[str] = []
        self._page = 0
        self._seq = 0
        self._state: Dict[str, object] = {"page": 0, "pages": 0}

    def _ensure(self, host: str, port: int) -> None:
        with self._lock:
            if self._sock is not None and self._addr == (host, port):
                return
            self.close()
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.2)
            self._addr = (host, port)
            self._stop.clear()
            self._thread = threading.Thread(target=self._listen, name="stm32-key-listener", daemon=True)
            self._thread.start()
            # 让固件把这个 socket 的源端口记为最近的 PC peer。
            self._sock.sendto(b"PING", self._addr)

    def _listen(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            text = data.decode("utf-8", "replace").strip().upper()
            if text == "KEY UP":
                self._move(-1)
            elif text == "KEY DOWN":
                self._move(1)

    def _move(self, delta: int) -> None:
        with self._lock:
            if not self._pages:
                return
            new_page = max(0, min(len(self._pages) - 1, self._page + delta))
            if new_page == self._page:
                return
            self._page = new_page
            self._state["page"] = self._page
            self._send_page_locked()

    def _send_page_locked(self) -> None:
        if self._sock is None or self._addr is None or not self._pages:
            return
        canvas = Canvas()
        for line, chunk in enumerate(self._pages[self._page].split("\n")[:4]):
            w, h, bits = bitmap.render_text(chunk, size=16)
            canvas.blit(0, line * 16, min(w, 128), min(h, 16), bits)
        frame = canvas.pack()
        head = b"FBSEQ " + (self._seq & 0xFFFF).to_bytes(2, "little")
        try:
            self._sock.sendto(head + frame, self._addr)
            self._seq = (self._seq + 1) & 0xFFFF
        except OSError:
            pass

    def show(self, text: str, host: str, port: int) -> Dict[str, int]:
        """建立/复用监听器，保存答案并立即发送第 1 页。"""
        with self._lock:
            self._ensure(host, port)
            chars = [text[i:i + 8] for i in range(0, len(text), 8)] or ["未找到相关知识"]
            self._pages = ["\n".join(chars[i:i + 4]) for i in range(0, len(chars), 4)]
            self._page = 0
            self._state = {"page": 0, "pages": len(self._pages)}
            self._send_page_locked()
            return {"page": 0, "pages": len(self._pages)}

    def state(self) -> Dict[str, int]:
        with self._lock:
            return {"page": int(self._state.get("page", 0)), "pages": int(self._state.get("pages", 0))}

    def close(self) -> None:
        with self._lock:
            self._stop.set()
            sock, self._sock = self._sock, None
            self._addr = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


PAGER = KnowledgePager()

