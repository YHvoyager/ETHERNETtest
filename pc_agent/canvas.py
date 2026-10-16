# -*- coding: utf-8 -*-
"""
canvas.py —— 128x64 画布，以及到板子帧格式的打包。

这是整个 PC 端的**核心资产**：所有渲染（无论是我预写的动画，还是以后 LLM
现写的代码）都只往这块内存画布上画，最后由 pack() 转成 1024 字节发出去。

【坐标系】
    原点在左上角，x 向右 0..127，y 向下 0..63。
    和常见的图像库一致，LLM 生成代码时不容易搞反。

【为什么自己写而不直接用 Pillow】
    1. 依赖越少越好 —— 板子端只要 1024 字节，不需要 PNG/JPEG 那套。
    2. 帧格式是 SSD1306 的页寻址，Pillow 转过去还要多一次位操作，
       自己画可以直接按需要写。
    3. 速度快：1024 字节的位图，纯 Python 画圆也就微秒级。

【显存格式（和板子端完全一致）】
    byte = gfx[(y >> 3) * 128 + x]
    bit  = y & 7
    像素亮 <=> (byte >> bit) & 1 == 1

    ⚠ 注意 bit0 在最上面。这是 SSD1306 页寻址的天然格式，板子收到后一个
    字节都不用改就能显示。所以这里的 set() 是唯一做位运算的地方。
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

WIDTH = 128
HEIGHT = 64
PAGES = HEIGHT // 8          # 8
FRAME_BYTES = WIDTH * PAGES  # 1024


class Canvas:
    """一块 128x64 的单色画布。所有绘制原语都是"就地改内存"。"""

    __slots__ = ("gfx",)

    def __init__(self) -> None:
        # 1024 字节，一字节一列 8 像素。0 = 全灭。
        self.gfx = bytearray(FRAME_BYTES)

    # ------------------------------------------------------------ 基础操作

    def clear(self, on: bool = False) -> "Canvas":
        """清空。on=True 是全亮（白屏）。"""
        fill = 0xFF if on else 0x00
        for i in range(FRAME_BYTES):
            self.gfx[i] = fill
        return self

    def set(self, x: int, y: int, on: bool = True) -> "Canvas":
        """画/擦一个点。越界静默忽略（画图代码算错边界是常事，不该崩）。"""
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            idx = (y >> 3) * WIDTH + x
            bit = 1 << (y & 7)
            if on:
                self.gfx[idx] |= bit
            else:
                self.gfx[idx] &= ~bit & 0xFF
        return self

    def get(self, x: int, y: int) -> bool:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            return bool((self.gfx[(y >> 3) * WIDTH + x] >> (y & 7)) & 1)
        return False

    def xor(self, x: int, y: int) -> "Canvas":
        """翻转一个点。做闪烁效果时不用先读。"""
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.gfx[(y >> 3) * WIDTH + x] ^= 1 << (y & 7)
        return self

    # ---------------------------------------------------------------- 图形

    def hline(self, x: int, y: int, w: int, on: bool = True) -> "Canvas":
        if w < 0:
            x, w = x + w, -w
        for i in range(w):
            self.set(x + i, y, on)
        return self

    def vline(self, x: int, y: int, h: int, on: bool = True) -> "Canvas":
        if h < 0:
            y, h = y + h, -h
        for i in range(h):
            self.set(x, y + i, on)
        return self

    def rect(self, x, y, w, h, on: bool = True) -> "Canvas":
        """空心矩形。"""
        self.hline(x, y, w, on)
        self.hline(x, y + h - 1, w, on)
        self.vline(x, y, h, on)
        self.vline(x + w - 1, y, h, on)
        return self

    def fill_rect(self, x, y, w, h, on: bool = True) -> "Canvas":
        """实心矩形。"""
        if w < 0:
            x, w = x + w, -w
        if h < 0:
            y, h = y + h, -h
        for j in range(y, y + h):
            self.hline(x, j, w, on)
        return self

    def line(self, x0, y0, x1, y1, on: bool = True) -> "Canvas":
        """Bresenham 直线。"""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0, on)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
        return self

    def circle(self, cx, cy, r, on: bool = True, fill: bool = False) -> "Canvas":
        """圆。fill=True 是实心。"""
        if r < 0:
            return self
        if fill:
            for dy in range(-r, r + 1):
                dx = int(math.sqrt(max(0, r * r - dy * dy)))
                self.hline(cx - dx, cy + dy, 2 * dx + 1, on)
        else:
            # 中点画圆
            x, y, d = r, 0, 1 - r
            while x >= y:
                for px, py in (
                    (cx + x, cy + y), (cx + y, cy + x),
                    (cx - y, cy + x), (cx - x, cy + y),
                    (cx - x, cy - y), (cx - y, cy - x),
                    (cx + y, cy - x), (cx + x, cy - y),
                ):
                    self.set(px, py, on)
                y += 1
                if d < 0:
                    d += 2 * y + 1
                else:
                    x -= 1
                    d += 2 * (y - x) + 1
        return self

    def ellipse(self, cx, cy, rx, ry, on: bool = True, fill: bool = False) -> "Canvas":
        """椭圆。rx/ry 是半径。"""
        if rx <= 0 or ry <= 0:
            return self
        if fill:
            for dy in range(-ry, ry + 1):
                t = 1.0 - (dy * dy) / float(ry * ry)
                if t < 0:
                    continue
                dx = int(rx * math.sqrt(t))
                self.hline(cx - dx, cy + dy, 2 * dx + 1, on)
        else:
            # 逐列求 y，简单可靠（椭圆求周长做参数化会有断点）
            for dx in range(-rx, rx + 1):
                t = 1.0 - (dx * dx) / float(rx * rx)
                if t < 0:
                    continue
                dy = int(round(ry * math.sqrt(t)))
                self.set(cx + dx, cy + dy, on)
                self.set(cx + dx, cy - dy, on)
            for dy in range(-ry, ry + 1):
                t = 1.0 - (dy * dy) / float(ry * ry)
                if t < 0:
                    continue
                dx = int(round(rx * math.sqrt(t)))
                self.set(cx + dx, cy + dy, on)
                self.set(cx - dx, cy + dy, on)
        return self

    def polygon(self, pts: Sequence[Tuple[int, int]], on: bool = True,
                fill: bool = False) -> "Canvas":
        """多边形。fill=True 用扫描线填充。"""
        if len(pts) < 2:
            return self
        if not fill:
            for i in range(len(pts)):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % len(pts)]
                self.line(x0, y0, x1, y1, on)
            return self

        ys = [p[1] for p in pts]
        for y in range(min(ys), max(ys) + 1):
            xs: List[int] = []
            for i in range(len(pts)):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % len(pts)]
                if y0 == y1:
                    continue
                if min(y0, y1) <= y < max(y0, y1):
                    xs.append(int(x0 + (y - y0) * (x1 - x0) / float(y1 - y0)))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self.hline(xs[i], y, xs[i + 1] - xs[i] + 1, on)
        return self

    def blit(self, x: int, y: int, w: int, h: int, bits: bytes,
             on: bool = True, invert: bool = False) -> "Canvas":
        """
        贴一张位图。bits 每字节 8 个像素，**按行、从左到右、高位在前**
        （和常见的 XBM/PNG 展开方式一致，方便外部工具生成）。

        这是显示中文/图标的正道：由 PC 端把字或图标渲染成位图再贴过来，
        板子上不需要带中文字库（那要几十 KB Flash）。
        """
        need = (w * h + 7) // 8
        if len(bits) < need:
            raise ValueError("位图数据不足：需要 %d 字节，收到 %d" % (need, len(bits)))

        for j in range(h):
            for i in range(w):
                bit_index = j * w + i
                byte = bits[bit_index >> 3]
                v = (byte >> (7 - (bit_index & 7))) & 1
                if invert:
                    v ^= 1
                self.set(x + i, y + j, bool(v) and on)
        return self

    def scroll(self, dx: int, dy: int) -> "Canvas":
        """整体平移画布内容（用于滚动）。空出来的地方补黑。"""
        if dx == 0 and dy == 0:
            return self
        old = self.gfx
        self.gfx = bytearray(FRAME_BYTES)
        for y in range(HEIGHT):
            sy = y - dy
            if not (0 <= sy < HEIGHT):
                continue
            for x in range(WIDTH):
                sx = x - dx
                if not (0 <= sx < WIDTH):
                    continue
                if (old[(sy >> 3) * WIDTH + sx] >> (sy & 7)) & 1:
                    self.set(x, y, True)
        return self

    def invert_rect(self, x, y, w, h) -> "Canvas":
        """反色一块矩形（高亮选中项、闪烁都用它）。"""
        for j in range(y, y + h):
            for i in range(x, x + w):
                if 0 <= i < WIDTH and 0 <= j < HEIGHT:
                    self.xor(i, j)
        return self

    # ---------------------------------------------------------------- 文字

    def text(self, x: int, y: int, s: str, on: bool = True) -> "Canvas":
        """
        画一行 ASCII 文字，用内置的 8x8 字体（每个字符占 6x8，行距 8）。

        只有 ASCII。中文请用 text_bitmap() 或 bitmap.py 里的字形表 ——
        板子上的第三方字库只有 4 个汉字「波特律动」，指望不上。
        """
        cx = x
        for ch in s:
            glyph = FONT_6X8.get(ch)
            if glyph is None:
                cx += 6
                continue
            for j, row in enumerate(glyph):
                for i in range(5):
                    if row & (1 << (4 - i)):
                        self.set(cx + i, y + j, on)
            cx += 6
        return self

    def text_bitmap(self, x, y, glyph: bytes, w: int, h: int,
                    on: bool = True) -> "Canvas":
        """贴一个汉字的点阵（见 bitmap.py 的 render_utf8）。"""
        return self.blit(x, y, w, h, glyph, on)

    # ---------------------------------------------------------------- 输出

    def pack(self) -> bytes:
        """
        转成板子要的 1024 字节。

        因为内部存的就是页寻址格式，这里其实什么都不用做 —— 这正是当初
        选这个内部格式的原因：打包零开销。
        """
        if len(self.gfx) != FRAME_BYTES:
            raise ValueError("画布尺寸不对：%d" % len(self.gfx))
        return bytes(self.gfx)

    def __bytes__(self) -> bytes:
        return self.pack()

    def to_ascii(self) -> str:
        """把画面渲染成字符画，终端里就能看效果，不用连着板子。"""
        lines = []
        for y in range(HEIGHT):
            lines.append("".join("#" if self.get(x, y) else "." for x in range(WIDTH)))
        return "\n".join(lines)

    def __repr__(self) -> str:
        return "<Canvas 128x64, %d bytes>" % len(self.gfx)


# ---------------------------------------------------------------------------
# 5x8 的内置 ASCII 字体（每字符 5 列 + 1 列间隔 = 6 px 宽）
# 每个字形是 8 行、每行低 5 位有效，最高位是左边第一个像素。
# ---------------------------------------------------------------------------

def _g(*rows: int) -> Tuple[int, ...]:
    return rows


FONT_6X8 = {
    " ": _g(0, 0, 0, 0, 0, 0, 0, 0),
    "!": _g(0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04, 0x00),
    '"': _g(0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "#": _g(0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A, 0x00),
    "$": _g(0x04, 0x0F, 0x14, 0x0E, 0x05, 0x1E, 0x04, 0x00),
    "%": _g(0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03, 0x00),
    "&": _g(0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D, 0x00),
    "'": _g(0x04, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "(": _g(0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02, 0x00),
    ")": _g(0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08, 0x00),
    "*": _g(0x00, 0x04, 0x15, 0x0E, 0x15, 0x04, 0x00, 0x00),
    "+": _g(0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00, 0x00),
    ",": _g(0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08),
    "-": _g(0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00, 0x00),
    ".": _g(0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C, 0x00),
    "/": _g(0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10, 0x00),
    "0": _g(0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E, 0x00),
    "1": _g(0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E, 0x00),
    "2": _g(0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F, 0x00),
    "3": _g(0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E, 0x00),
    "4": _g(0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02, 0x00),
    "5": _g(0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E, 0x00),
    "6": _g(0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E, 0x00),
    "7": _g(0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08, 0x00),
    "8": _g(0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E, 0x00),
    "9": _g(0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C, 0x00),
    ":": _g(0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00, 0x00),
    ";": _g(0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x04, 0x08, 0x00),
    "<": _g(0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02, 0x00),
    "=": _g(0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ">": _g(0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08, 0x00),
    "?": _g(0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04, 0x00),
    "@": _g(0x0E, 0x11, 0x17, 0x15, 0x17, 0x10, 0x0E, 0x00),
    "A": _g(0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11, 0x00),
    "B": _g(0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E, 0x00),
    "C": _g(0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E, 0x00),
    "D": _g(0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E, 0x00),
    "E": _g(0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F, 0x00),
    "F": _g(0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10, 0x00),
    "G": _g(0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F, 0x00),
    "H": _g(0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11, 0x00),
    "I": _g(0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E, 0x00),
    "J": _g(0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C, 0x00),
    "K": _g(0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11, 0x00),
    "L": _g(0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F, 0x00),
    "M": _g(0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11, 0x00),
    "N": _g(0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11, 0x00),
    "O": _g(0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E, 0x00),
    "P": _g(0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10, 0x00),
    "Q": _g(0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D, 0x00),
    "R": _g(0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11, 0x00),
    "S": _g(0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E, 0x00),
    "T": _g(0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x00),
    "U": _g(0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E, 0x00),
    "V": _g(0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04, 0x00),
    "W": _g(0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11, 0x00),
    "X": _g(0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11, 0x00),
    "Y": _g(0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04, 0x00),
    "Z": _g(0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F, 0x00),
    "[": _g(0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E, 0x00),
    "\\": _g(0x10, 0x08, 0x08, 0x04, 0x02, 0x02, 0x01, 0x00),
    "]": _g(0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E, 0x00),
    "^": _g(0x04, 0x0A, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00),
    "_": _g(0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F, 0x00),
    "`": _g(0x08, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "a": _g(0x00, 0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F, 0x00),
    "b": _g(0x10, 0x10, 0x1E, 0x11, 0x11, 0x11, 0x1E, 0x00),
    "c": _g(0x00, 0x00, 0x0E, 0x11, 0x10, 0x11, 0x0E, 0x00),
    "d": _g(0x01, 0x01, 0x0F, 0x11, 0x11, 0x11, 0x0F, 0x00),
    "e": _g(0x00, 0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E, 0x00),
    "f": _g(0x06, 0x09, 0x08, 0x1C, 0x08, 0x08, 0x08, 0x00),
    "g": _g(0x00, 0x0F, 0x11, 0x11, 0x0F, 0x01, 0x0E, 0x00),
    "h": _g(0x10, 0x10, 0x1E, 0x11, 0x11, 0x11, 0x11, 0x00),
    "i": _g(0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E, 0x00),
    "j": _g(0x02, 0x00, 0x06, 0x02, 0x02, 0x12, 0x0C, 0x00),
    "k": _g(0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12, 0x00),
    "l": _g(0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E, 0x00),
    "m": _g(0x00, 0x00, 0x1A, 0x15, 0x15, 0x11, 0x11, 0x00),
    "n": _g(0x00, 0x00, 0x1E, 0x11, 0x11, 0x11, 0x11, 0x00),
    "o": _g(0x00, 0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E, 0x00),
    "p": _g(0x00, 0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x00),
    "q": _g(0x00, 0x0F, 0x11, 0x11, 0x0F, 0x01, 0x01, 0x00),
    "r": _g(0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10, 0x00),
    "s": _g(0x00, 0x00, 0x0F, 0x10, 0x0E, 0x01, 0x1E, 0x00),
    "t": _g(0x08, 0x08, 0x1C, 0x08, 0x08, 0x09, 0x06, 0x00),
    "u": _g(0x00, 0x00, 0x11, 0x11, 0x11, 0x13, 0x0D, 0x00),
    "v": _g(0x00, 0x00, 0x11, 0x11, 0x11, 0x0A, 0x04, 0x00),
    "w": _g(0x00, 0x00, 0x11, 0x11, 0x15, 0x15, 0x0A, 0x00),
    "x": _g(0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x00),
    "y": _g(0x00, 0x11, 0x11, 0x11, 0x0F, 0x01, 0x0E, 0x00),
    "z": _g(0x00, 0x00, 0x1F, 0x02, 0x04, 0x08, 0x1F, 0x00),
    "{": _g(0x06, 0x04, 0x04, 0x08, 0x04, 0x04, 0x06, 0x00),
    "|": _g(0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x00),
    "}": _g(0x0C, 0x04, 0x04, 0x02, 0x04, 0x04, 0x0C, 0x00),
    "~": _g(0x00, 0x00, 0x08, 0x15, 0x02, 0x00, 0x00, 0x00),
}


def new() -> Canvas:
    """开一块新画布，等价于 Canvas()。"""
    return Canvas()
