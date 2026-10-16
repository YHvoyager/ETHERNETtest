# -*- coding: utf-8 -*-
"""
bitmap.py —— 把一个汉字渲染成 16x16 点阵，然后贴到画布上。

【为什么需要这个模块】

板子上的第三方字库（Core/Src/font.c）里的中文只有 4 个字：「波特律动」。
想在 OLED 上显示任意中文，两条路：

    A. 板子上带完整中文字库 —— 16x16 点阵每字 32 字节，常用 3500 字
       就是 112KB Flash。本工程 Flash 1MB，理论上放得下，但要把字库
       塞进固件、还要改第三方驱动的查表逻辑，代价不小。

    B. PC 端渲染成点阵再传过去 —— 这是本工程选的路。板子只需要
       「收 1024 字节画一屏」这一件事（framebuf 已经在做），
       PC 端想显示什么就渲染什么，板子侧零改动。

选 B 的关键理由：**内容的复杂度应该留在 PC 端**。板子只有 180MHz 的
Cortex-M4 和 1MB Flash，而 PC 有无限的时间和内存。以后 AI 要显示
什么新东西，改的是 PC 端代码，不用重新烧固件。

【点阵怎么来的】

用 Windows 自带的字体渲染，不需要装任何东西：

    ctypes 调 gdi32 的 CreateFontW + TextOutW，让 Windows 把字画到
    一块 16x16 的单色位图里，再用 GetDIBits 取回像素。

    这样得到的点阵和「点阵字库」的观感一致 —— 因为 Windows 在这么小
    的尺寸下本来就会走点阵/灰度抗锯齿，我们二值化一下就是标准点阵字。

    常见中文字体（SimSun 宋体、SimHei 黑体、Microsoft YaHei 雅黑）
    都可用。默认用宋体：小字号下笔画最清楚。

【缓存】

同一个字渲染一次就够了，进程内缓存；可选落盘到 pc_agent/.fontcache/，
下次启动直接读，省掉 GDI 调用。
"""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

GLYPH_W = 16
GLYPH_H = 16
GLYPH_BYTES = (GLYPH_W * GLYPH_H) // 8  # 32 字节

DEFAULT_FACE = "SimSun"  # 宋体，小字号笔画清楚
_DOT_THRESHOLD = 96      # 灰阶 >= 此值算 "亮点"，见 _render_sized() 里的说明

# 进程内缓存：字 -> 32 字节点阵
_cache: Dict[Tuple[str, str, int], bytes] = {}


# ---------------------------------------------------------------------------
# Windows GDI 渲染
# ---------------------------------------------------------------------------

# 只在 Windows 上可用；其他平台会在 render_char 里抛清楚的错。
if os.name == "nt":
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3)]

    _BI_RGB = 0
    _DIB_RGB_COLORS = 0
    _SRCCOPY = 0x00CC0020
    _TRANSPARENT = 1
    _FW_NORMAL = 400
    _ANTIALIASED_QUALITY = 4
    _DEFAULT_CHARSET = 1
else:  # pragma: no cover
    _gdi32 = _user32 = None


def render_char(ch: str, face: str = DEFAULT_FACE, size: int = 16,
                threshold: int = 128) -> bytes:
    """
    把单个字符渲染成 GLYPH_BYTES(32) 字节的点阵。

    位序和 canvas.blit() 一致：**按行、从左到右、高位在前**。
    也就是说 bits[0] 的最高位是 (0,0)，最低位是 (7,0)。

    threshold 是二值化阈值：GDI 给的抗锯齿灰阶 >= threshold 就算亮。
    16px 下阈值 128 得到的笔画粗细最接近点阵字库。
    """
    key = (ch, face, size)
    if key in _cache:
        return _cache[key]

    if _gdi32 is None:
        raise RuntimeError(
            "位图渲染依赖 Windows GDI，当前平台不支持。"
            "请改用自带字库的方案，或预先在 Windows 上导出点阵。"
        )

    hdc_screen = _user32.GetDC(None)
    if not hdc_screen:
        raise RuntimeError("GetDC 失败")
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    if not hdc_mem:
        _user32.ReleaseDC(None, hdc_screen)
        raise RuntimeError("CreateCompatibleDC 失败")

    hbmp = None
    old_bmp = None
    old_font = None
    font = None
    try:
        # 单色（1bpp）位图。宽必须是 4 字节对齐的整数倍吗？不是 ——
        # 只有"扫描线按 4 字节对齐"，我们用 GetDIBits 取回时会处理。
        hbmp = _gdi32.CreateCompatibleBitmap(hdc_screen, GLYPH_W, GLYPH_H)
        if not hbmp:
            raise RuntimeError("CreateCompatibleBitmap 失败")
        old_bmp = _gdi32.SelectObject(hdc_mem, hbmp)

        # 背景刷黑（0 = 灭），文字写白（1 = 亮）
        brush = _gdi32.CreateSolidBrush(0x000000)
        rect = wintypes.RECT(0, 0, GLYPH_W, GLYPH_H)
        _user32.FillRect(hdc_mem, ctypes.byref(rect), brush)
        _gdi32.DeleteObject(brush)

        font = _gdi32.CreateFontW(
            -size, 0, 0, 0, _FW_NORMAL, 0, 0, 0,
            _DEFAULT_CHARSET, 0, 0, _ANTIALIASED_QUALITY, 0,
            ctypes.c_wchar_p(face),
        )
        if not font:
            raise RuntimeError("CreateFontW 失败（字体名 %r 不存在？）" % face)
        old_font = _gdi32.SelectObject(hdc_mem, font)

        _gdi32.SetBkMode(hdc_mem, _TRANSPARENT)
        _gdi32.SetTextColor(hdc_mem, 0x00FFFFFF)
        _user32.DrawTextW(
            hdc_mem, ctypes.c_wchar_p(ch), 1, ctypes.byref(rect),
            0x00000000,  # 左对齐、顶对齐，不裁剪
        )

        # 取回像素。biHeight 取负 = 自上而下的行序，省得再翻转。
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = GLYPH_W
        bmi.bmiHeader.biHeight = -GLYPH_H
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32  # 要 32bpp 才能拿到灰度（抗锯齿）
        bmi.bmiHeader.biCompression = _BI_RGB

        buf = (ctypes.c_ubyte * (GLYPH_W * GLYPH_H * 4))()
        got = _gdi32.GetDIBits(hdc_mem, hbmp, 0, GLYPH_H,
                               ctypes.byref(buf), ctypes.byref(bmi),
                               _DIB_RGB_COLORS)
        if got == 0:
            raise RuntimeError("GetDIBits 失败")

    finally:
        if old_font:
            _gdi32.SelectObject(hdc_mem, old_font)
        if font:
            _gdi32.DeleteObject(font)
        if old_bmp:
            _gdi32.SelectObject(hdc_mem, old_bmp)
        if hbmp:
            _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(None, hdc_screen)

    # 32bpp BGRA -> 1bpp，按行、高位在前
    out = bytearray(GLYPH_BYTES)
    for j in range(GLYPH_H):
        for i in range(GLYPH_W):
            off = (j * GLYPH_W + i) * 4
            # BGRA 的 B/G/R 近似相等（灰度），取 B 通道即可
            lum = buf[off]
            if lum >= threshold:
                bit_index = j * GLYPH_W + i
                out[bit_index >> 3] |= 0x80 >> (bit_index & 7)

    result = bytes(out)
    _cache[key] = result
    return result


def render_text(text: str, face: str = DEFAULT_FACE,
                size: int = 16) -> Tuple[int, int, bytes]:
    """
    把一串字符渲染成一张位图，返回 (宽, 高, bits)。

    所有字符横向排布，**每个字符固定占 16 像素宽**（等宽）。
    不管实际字形是 16x16 还是 8x16，都居中放进自己的格子里 ——
    这样 PC 端排版简单，也不需要在板子上做变宽字体的处理。

    bits 的格式同 render_char：按行、高位在前。
    """
    if not text:
        return 0, GLYPH_H, b""

    w = GLYPH_W * len(text)
    h = GLYPH_H
    row_bytes = (w + 7) // 8
    out = bytearray(row_bytes * h)

    for k, ch in enumerate(text):
        glyph = render_char(ch, face, size)
        x0 = k * GLYPH_W
        for j in range(GLYPH_H):
            for i in range(GLYPH_W):
                src_bit = (j * GLYPH_W + i)
                if not (glyph[src_bit >> 3] >> (7 - (src_bit & 7))) & 1:
                    continue
                dst_bit = j * w + (x0 + i)
                out[dst_bit >> 3] |= 0x80 >> (dst_bit & 7)

    return w, h, bytes(out)


def char12(ch: str, face: str = DEFAULT_FACE) -> bytes:
    """12x12 的小号点阵（2 字节/行 x 12 行 = 24 字节）。"""
    return _render_sized(ch, face, 12, 12, 12)


def char24(ch: str, face: str = DEFAULT_FACE) -> bytes:
    """24x24 的大号点阵。"""
    return _render_sized(ch, face, 24, 24, 24)


def _render_sized(ch: str, face: str, size: int, w: int, h: int) -> bytes:
    """
    任意尺寸的单字点阵。输出按行、高位在前，行宽按字节对齐。

    字号越大点阵越好看，但也要画布放得下：24x24 的话 128 宽只能放 5 个字。
    """
    key = (ch, face, -size)  # size 取负做 key，和 16x16 的默认项区分开
    if key in _cache:
        return _cache[key]

    if _gdi32 is None:
        raise RuntimeError("位图渲染依赖 Windows GDI，当前平台不支持。")

    hdc_screen = _user32.GetDC(None)
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = _gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old_bmp = _gdi32.SelectObject(hdc_mem, hbmp)

    brush = _gdi32.CreateSolidBrush(0x000000)
    rect = wintypes.RECT(0, 0, w, h)
    _user32.FillRect(hdc_mem, ctypes.byref(rect), brush)
    _gdi32.DeleteObject(brush)

    font = _gdi32.CreateFontW(
        -size, 0, 0, 0, _FW_NORMAL, 0, 0, 0,
        _DEFAULT_CHARSET, 0, 0, _ANTIALIASED_QUALITY, 0,
        ctypes.c_wchar_p(face),
    )
    old_font = _gdi32.SelectObject(hdc_mem, font)
    _gdi32.SetBkMode(hdc_mem, _TRANSPARENT)
    _gdi32.SetTextColor(hdc_mem, 0x00FFFFFF)
    _user32.DrawTextW(hdc_mem, ctypes.c_wchar_p(ch), 1,
                      ctypes.byref(rect), 0x00000000)

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = _BI_RGB

    buf = (ctypes.c_ubyte * (w * h * 4))()
    _gdi32.GetDIBits(hdc_mem, hbmp, 0, h, ctypes.byref(buf),
                     ctypes.byref(bmi), _DIB_RGB_COLORS)

    _gdi32.SelectObject(hdc_mem, old_font)
    _gdi32.DeleteObject(font)
    _gdi32.SelectObject(hdc_mem, old_bmp)
    _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(hdc_mem)
    _user32.ReleaseDC(None, hdc_screen)

    row_bytes = (w + 7) // 8
    out = bytearray(row_bytes * h)
    for j in range(h):
        for i in range(w):
            # GDI 开着抗锯齿，笔画边缘是灰阶。判 "亮" 的阈值越低笔画越粗：
            #   128（半亮）→ 16px 宋体的横竖会断成虚线，看不清
            #    96        → 笔画连上，且不至于糊成一片
            # 用 <100 会开始出现 "墨团"（撇捺粘连）。
            if buf[(j * w + i) * 4] >= _DOT_THRESHOLD:
                bit_index = j * w + i
                out[bit_index >> 3] |= 0x80 >> (bit_index & 7)

    result = bytes(out)
    _cache[key] = result
    return result


def to_ascii(glyph: bytes, w: int = GLYPH_W, h: int = GLYPH_H) -> str:
    """
    把点阵显示成字符画，**在终端里肉眼验证字形对不对**。

    这个函数是排查中文渲染问题的第一工具：它不联网、不碰板子，
    只把 render_char() 的输出翻译成能看的字符。
    """
    row_bytes = (w + 7) // 8
    lines = []
    for j in range(h):
        line = []
        for i in range(w):
            bit_index = j * w + i
            v = (glyph[(bit_index >> 3)] >> (7 - (bit_index & 7))) & 1
            line.append("#" if v else ".")
        lines.append("".join(line))
    return "\n".join(lines)
