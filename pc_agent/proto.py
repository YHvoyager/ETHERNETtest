# -*- coding: utf-8 -*-
"""
proto.py —— 板子 UDP 文本命令通道的封装。

板子的命令接口是「一行文本一条命令，回一行文本」的纯文本协议，
所有命令都已经在固件的 Core/Src/reg_shell.c 里实现，本文件不做任何
板子端改动，只是把它包装成 Python 能用的对象。

为什么另开字节通道：
    文本写帧（OLED TXT / OLED PIX）一条命令才改几个像素，
    全屏 1024 字节要上千条命令，30fps 根本不可能。
    而 framebuf 应用（固件里 FB 命令）收的是**原始二进制的 1024 字节帧**，
    一个 UDP 包就发完 —— 这才是能跑动画的路径。
    所以本文件同时提供 send_text() 和 send_frame() 两个入口。

⚠ UDP 是不可靠的。发帧序列时靠 FBSEQ 的序号让板子丢弃乱序/重复帧，
   避免出现"上一帧的后半段 + 这一帧的前半段"这种撕裂画面。
"""

from __future__ import annotations

import socket
import time
from typing import Optional, Tuple

DEFAULT_HOST = "192.168.1.30"
DEFAULT_PORT = 8080

# 一帧的字节数：128 x 64 / 8
FRAME_BYTES = 1024


class BoardError(RuntimeError):
    """板子回了 ERR，或者干脆没回。"""


# 心跳长什么样：`Echo_Service_Poll()` 每秒推一次，文案在 echo_service.c:638 ——
#   `STM32F429 在线，已收 N 条，命令 M 条`
# ⚠ 别把它和 `INFO` 搞混：`INFO` 的回应是 `board 192.168.1.30 tick=... io_count=2`
#   （reg_shell.c:392）。两者完全不同，早先我把心跳当成了 INFO 的回应，
#   白白怀疑了一轮"回包错位"。
_HEARTBEAT_PREFIXES = ("STM32F429", "心跳")


def _is_heartbeat(text: str) -> bool:
    """
    这条回包是不是"不请自来"的每秒心跳？

    判据用文案前缀白名单，但**判不准就当成回应**（宁可错收一条，也不要空等超时）。
    命令回包都是 `[OK]/[ERR]/FB:/PONG/board/0x...` 这类开头，与心跳不重叠。
    """
    t = text.lstrip()
    for p in _HEARTBEAT_PREFIXES:
        if t.startswith(p):
            return True
    return False


class Board:
    """一块跑着 ETHERNETtest 固件的板子。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 1.0,
    ) -> None:
        self.host = host
        self.port = port
        self.addr = (host, port)
        # 用 UDP。bind 到任意本地端口，让板子能回包到这个端口。
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    # ---------------------------------------------------------------- 关闭

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "Board":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ 文本通道

    def send_text(self, line: str, expect_reply: bool = True) -> str:
        """
        发一条文本命令，返回板子的回包。

        回包是板子回给"最后来包的那台 PC"的，所以这里必须先把命令发出去，
        板子才知道该回给谁。

        ⚠ 必须**先排空积压**再发命令。板子有两种"不请自来"的包：
            1. 每秒一次的 UDP 心跳（echo_service 的 Echo_Service_Poll）
            2. 上一条命令还没被读走的回包（板子有时一条命令回两行）
          原来这里只 recvfrom 一次，收到哪个算哪个 —— 结果一次错位之后
          后面**每条命令都拿到上一条的回应**，表现为"FB? 回了 INFO"。
          这种错位不会报错，只会让数据静默错位，是最难发现的一类。
        """
        if isinstance(line, str):
            payload = line.encode("ascii", "replace")
        else:
            payload = line

        if not expect_reply:
            self.sock.sendto(payload, self.addr)
            return ""

        # 1) 排空积压：用极短超时连续读到"读不到为止"
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(0.02)
        try:
            while True:
                try:
                    self.sock.recvfrom(2048)
                except socket.timeout:
                    break
        finally:
            self.sock.settimeout(old_timeout)

        # 2) 发出去，等回应；等到的心跳不算回应
        self.sock.sendto(payload, self.addr)
        deadline = time.time() + (old_timeout or 1.0)
        while time.time() < deadline:
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                break
            text = data.decode("utf-8", "replace")
            if _is_heartbeat(text):
                continue          # 心跳不是对这条命令的回应，丢掉继续等
            return text

        raise BoardError(
            "板子没有回包（超时）。检查：网线、板子是否在 %s、"
            "Windows 防火墙、以及是否用了正确的端口。" % (self.host,)
        )

    def ping(self) -> str:
        """最便宜的一次往返，用来确认板子在线。"""
        return self.send_text("PING")

    # ------------------------------------------------------------ 二进制通道

    def send_frame(self, buf: bytes, seq: Optional[int] = None) -> None:
        """
        发一帧整屏位图 —— **不等回包**。

        为什么不等：动画要 20~30fps，如果每帧都等一次回包，本地 socket
        超时/丢包会直接卡住整条流水线。帧丢失的代价只是一帧旧画面，
        而等待的代价是动画顿住。所以发帧一律 fire-and-forget。

        buf 必须是 1024 字节：8 页 x 128 列，每字节一列里的 8 个像素，
        **bit0 在最上面**（SSD1306 的页寻址格式，见 pack_frame()）。
        """
        if len(buf) != FRAME_BYTES:
            raise ValueError("一帧必须正好 %d 字节，收到 %d" % (FRAME_BYTES, len(buf)))

        if seq is None:
            # 不带头：FB <1024 字节>，板子只认"长度正好 1024"的包
            self.sock.sendto(buf, self.addr)
        else:
            # 带头：FBSEQ + <seq:u16 LE> + 1024 字节 = 1032 字节，固件按这个长度匹配
            head = b"FBSEQ " + (seq & 0xFFFF).to_bytes(2, "little")
            self.sock.sendto(head + buf, self.addr)

    # ------------------------------------------------------------ 常用命令

    def oled_init(self) -> str:
        return self.send_text("OLED INIT")

    def oled_off(self) -> str:
        return self.send_text("OLED OFF")

    def oled_on(self) -> str:
        return self.send_text("OLED ON")

    def oled_stat(self) -> str:
        return self.send_text("OLED STAT")

    def oled_txt(self, line: int, text: str) -> str:
        """
        文字走**文本命令**。

        这样屏幕的显存由板子自己维护，PC 端不需要下载 ASCII 字库。
        缺点是每次只能改 16px 高的一行，而且波特律动是全屏重绘模型。
        """
        return self.send_text("OLED TXT %d %s" % (line, text))

    def fb_stat(self) -> str:
        """看固件收帧的统计：好帧 / 坏长度 / 乱序丢弃。"""
        return self.send_text("FB?")

    def info(self) -> str:
        return self.send_text("INFO")

    def led(self, name: str, value: int) -> str:
        return self.send_text("LED %s %d" % (name, value))
