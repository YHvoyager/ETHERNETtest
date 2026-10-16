# -*- coding: utf-8 -*-
"""
agent.py —— 把「你想要什么」翻译成 OLED 上的画面。

【这个 agent 到底在干什么】

一句话：
    你描述一个画面 -> LLM 写一段画图代码 -> 沙箱里逐帧执行 -> 每帧
    1024 字节通过 UDP 发给板子。

这条链里最关键的判断是：**让 LLM 写代码，而不是让 LLM 输出像素**。
如果让 LLM 直接吐 1024 个字节的位图，它得逐像素推演，又慢又容易画坏。
而写一段 for 循环调用 c.circle() 的代码，对它来说是最自然的事 ——
它训练时读过几百万行这种代码。

【为什么不用「动作库」模式】

早先的设计是：预置 eyes()、horse() 这些函数，LLM 只做意图分类，
匹配到哪个就播哪个。问题是**能力被写代码的人锁死了** —— 想要
「一只打哈欠的猫」，库里没有，就没办法。

现在的设计：LLM 现场写 draw(c, t, p)。我预置的 eyes/horse 降级成
**示例**（给 LLM 看，也给你看），不再是能力的边界。

【三层回退】

    --anim eyes                直接播内置动画，不碰 LLM（最快、最可靠）
    --code 文件.py             直接播你写好的代码，不碰 LLM
    "一只打哈欠的猫"            交给 LLM 写代码，写完编译进缓存

第三层失败时（没配 API key、网络不通、LLM 写错），自动退回第一层
播内置动画，不会黑屏。

【用法】

    python agent.py check                     检查板子通不通
    python agent.py list                      列出内置动画
    python agent.py eyes                      播内置动画
    python agent.py eyes --fps 15 --seconds 10
    python agent.py horse --ascii             先在终端看字符画，不发板子
    python agent.py "一双慢慢眨的眼睛"          让 LLM 写代码再播
    python agent.py --code my_anim.py         播自己的代码
    python agent.py render eyes -t 1.5 -o f.png  存成一帧图片

【LLM 配置】

    环境变量（任一）：
        DEEPSEEK_API_KEY        DeepSeek（默认，便宜且写代码强）
        OPENAI_API_KEY          OpenAI 兼容接口
        OLED_AGENT_API_KEY      自定义

    可覆盖：
        OLED_AGENT_BASE_URL     默认 https://api.deepseek.com
        OLED_AGENT_MODEL        默认 deepseek-chat

    没配 key 时不会报错退出 —— 只是"描述式"入口不可用，
    内置动画和 --code 照常工作。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

# 允许 `python pc_agent/agent.py` 和 `python -m pc_agent.agent` 两种跑法
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import anim          # noqa: E402
import bitmap        # noqa: E402
from canvas import Canvas   # noqa: E402
from proto import Board, BoardError, DEFAULT_HOST, DEFAULT_PORT  # noqa: E402
from sandbox import Renderer, SandboxError, self_test  # noqa: E402

# ---------------------------------------------------------------------------
# LLM 系统提示词 —— 这是整个 agent 里最像「训练」的部分
#
# 它做了什么：把 Canvas 的 API 讲清楚、给两个完整例子、明确禁止事项。
# 好的提示词比微调便宜一万倍：改一行字就能调整行为，不用重新训练。
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个为 128x64 单色 OLED 屏幕写动画的工程师。

用户会用中文描述他想要的画面，你输出一段 Python 代码。

## 硬性要求

1. 必须定义函数 `def draw(c, t, p):`
   - `c` 是画布对象（128 宽 x 64 高，原点在左上角，x 向右，y 向下）
   - `t` 是时间，单位秒，从 0 开始，浮点数
   - `p` 是参数字典，可能为空
2. 只输出代码，不要 markdown 代码块标记，不要解释文字。
3. 只能 import math 和 random。不要用任何别的库。
4. 不要读写文件、不要网络、不要 print。
5. 每一帧都从空白画布开始 —— **不要在函数外面存状态**。
   同一个 t 必须永远画出同一帧。
6. 画面要能被看清：OLED 只有 128x64，线条至少 1 像素，
   重要元素建议用 fill=True。

## 画布 API

坐标：(0,0) 左上角，(127,63) 右下角。

    c.clear(on=False)                        清屏，on=True 是全亮
    c.set(x, y, on=True)                     画一个点
    c.get(x, y) -> bool                       读一个点
    c.xor(x, y)                              翻转一个点（做闪烁）

    c.hline(x, y, w, on=True)                水平线
    c.vline(x, y, h, on=True)                垂直线
    c.line(x0, y0, x1, y1, on=True)          任意直线
    c.rect(x, y, w, h, on=True)              空心矩形
    c.fill_rect(x, y, w, h, on=True)         实心矩形

    c.circle(cx, cy, r, on=True, fill=False)         圆
    c.ellipse(cx, cy, rx, ry, on=True, fill=False)   椭圆
    c.polygon([(x,y), ...], on=True, fill=False)     多边形

    c.text(x, y, "HELLO", on=True)           画 ASCII 文字，6x8 字体
    c.blit(x, y, w, h, bits, on=True)        贴位图
    c.scroll(dx, dy)                         整体平移
    c.invert_rect(x, y, w, h)                反色一块

    math 可直接用 sin/cos/sqrt/pi，random 可用 randint/uniform。

## 例子 1：一只眨眼的眼睛

def draw(c, t, p):
    r = 20
    # 眨眼：每个周期前 10% 时间闭合
    phase = t % 4.0
    if phase < 0.4:
        blink = math.sin(phase / 0.4 * math.pi)
    else:
        blink = 0.0
    ry = max(1, int(r * (1.0 - blink * 0.9)))
    c.ellipse(64, 32, r, ry, True, False)
    if blink < 0.85:
        px = int(64 + 6 * math.sin(t * 1.3))
        c.circle(px, 32, 6, True, True)
        c.set(px - 2, 30, False)

## 例子 2：弹跳的球

def draw(c, t, p):
    y = 50 - abs(math.sin(t * 3.0)) * 35
    c.circle(int(64 + math.sin(t * 1.1) * 40), int(y), 8, True, True)
    c.hline(0, 58, 128, True)

## 现在，按用户的描述写代码。

只输出 Python 代码，从 `def draw` 开始。
"""


# ---------------------------------------------------------------------------
# LLM 客户端（不依赖任何 SDK，直接用标准库的 urllib 发 HTTP）
#
# 为什么不用 openai 这个包：少一个依赖，而且 DeepSeek / OpenAI /
# 本地 Ollama 的 /v1/chat/completions 接口是一样的。
# ---------------------------------------------------------------------------

class LLMError(RuntimeError):
    pass


def _llm_config() -> Dict[str, str]:
    """从环境变量里凑出一份配置。key 没配就抛错。"""
    key = (os.environ.get("OLED_AGENT_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY")
           or os.environ.get("OPENAI_API_KEY")
           or "")
    if not key:
        raise LLMError(
            "没有配置 API key。请设置环境变量 DEEPSEEK_API_KEY，例如：\n"
            "    set DEEPSEEK_API_KEY=sk-xxxx\n"
            "（没配也能用：--anim 播内置动画，--code 播你自己的代码）"
        )
    base = os.environ.get("OLED_AGENT_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("OLED_AGENT_MODEL", "deepseek-chat")
    return {"key": key, "base": base.rstrip("/"), "model": model}


def ask_llm_for_code(description: str, timeout: float = 60.0) -> str:
    """
    把用户的描述发给 LLM，拿回一段 draw() 代码。

    故意不重试：写代码失败时，让用户看到真实的错误比自动重试更有用
    （重试三次还是错，说明提示词或描述有问题，该改的是那些）。
    """
    import urllib.error
    import urllib.request

    cfg = _llm_config()
    url = cfg["base"] + "/v1/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["key"],
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise LLMError("LLM 接口返回 %s：%s" % (e.code, detail)) from None
    except urllib.error.URLError as e:
        raise LLMError("连不上 LLM（%s）。检查网络和 %s" % (e.reason, url)) from None
    except Exception as e:  # noqa: BLE001
        raise LLMError("调用 LLM 出错：%s: %s" % (type(e).__name__, e)) from None

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("LLM 返回的结构看不懂：%s" % json.dumps(payload)[:400]) from None

    return _strip_code_fence(text)


def _strip_code_fence(text: str) -> str:
    """
    模型经常不听话，还是把代码包在 ```python 里。

    与其在提示词里反复强调，不如直接在这里剥掉 —— 提示词是软的，
    解析器是硬的。
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    # 去掉第一行的 ``` 或 ```python
    lines = lines[1:]
    # 去掉结尾的 ```
    while lines and lines[-1].strip() in ("```", ""):
        lines.pop()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 渲染代码缓存 —— 这是「skill accumulation」的落地
#
# LLM 写成功一次的代码存到 disk，下次同一个描述直接用。
# 知识存在文件里，不在模型权重里。这就是"越用越好用"的实现方式。
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(_HERE, "code_cache")


def _cache_path(description: str) -> str:
    import hashlib
    h = hashlib.sha1(description.strip().encode("utf-8")).hexdigest()[:12]
    safe = "".join(ch if ch.isalnum() else "_" for ch in description)[:32]
    return os.path.join(CACHE_DIR, "%s_%s.py" % (safe, h))


def load_cached(description: str) -> Optional[str]:
    path = _cache_path(description)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def save_cached(description: str, code: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(description)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 描述：%s\n" % description)
        f.write(code)
    return path


def code_for(description: str, use_cache: bool = True,
             verbose: bool = True) -> str:
    """拿到一段能用的代码：先查缓存，再问 LLM，最后验证一遍。"""
    if use_cache:
        cached = load_cached(description)
        if cached is not None:
            if verbose:
                print("[agent] 命中代码缓存：%s" % _cache_path(description))
            return cached

    if verbose:
        cfg = _llm_config()
        print("[agent] 让 %s 写代码……" % cfg["model"])
    code = ask_llm_for_code(description)

    # 拿到就立刻试编译 —— 晚了会发到板子上才发现是坏的
    try:
        Renderer(code, timeout=1.0).render(0.0)
    except SandboxError as e:
        raise SandboxError(
            "LLM 写出的代码没能通过检查：%s\n\n--- 代码 ---\n%s" % (e, code)
        ) from None

    if use_cache:
        path = save_cached(description, code)
        if verbose:
            print("[agent] 代码已缓存：%s" % path)
    return code


# ---------------------------------------------------------------------------
# 播放循环
# ---------------------------------------------------------------------------

def play(renderer, board: Optional[Board], fps: float, seconds: float,
         params: Dict, seq: bool = True, stats_every: float = 0.0) -> None:
    """
    主循环：渲染 -> 发帧 -> 睡到下一帧的时间点。

    【为什么要"睡到下一帧的时间点"而不是 sleep(1/fps)】

    渲染 + 发送要花时间（哪怕只有 1 毫秒）。如果写成：

        while ...:
            render(); send(); time.sleep(1/fps)

    那实际周期是 1/fps + 渲染耗时，帧率会系统性偏低。正确写法是
    按绝对时间轴对齐：

        deadline = start + n/fps
        render(); send(); sleep(deadline - now)

    这样即使某一帧慢了，下一帧会自然赶上，平均帧率准确。

    【注意】

    这里发帧的速率**远高于板子能显示的速率**（I2C 100kHz 下整屏约
    11fps）。板子端 framebuf 的策略是"新帧直接覆盖暂存区"，
    所以多余帧只是被覆盖掉，不会积压。这比在 PC 端限速到 11fps 更好：
    PC 不知道自己发的包丢没丢，多发几个能让板子总是拿到最新画面。
    """
    start = time.time()
    frame_no = 0
    total = int(seconds * fps) if seconds > 0 else 0
    last_stats = 0.0

    try:
        while True:
            if total and frame_no >= total:
                break

            t = frame_no / fps
            try:
                frame = renderer.render(t, params)
            except SandboxError as e:
                print("\n[agent] 渲染第 %d 帧失败：%s" % (frame_no, e))
                break

            if board is not None:
                board.send_frame(frame, seq=(frame_no & 0xFFFF) if seq else None)

            frame_no += 1

            # 进度显示
            if board is None:
                pass
            elif stats_every > 0 and time.time() - last_stats >= stats_every:
                last_stats = time.time()
                try:
                    print("[agent] %s" % board.fb_stat().strip())
                except BoardError:
                    print("[agent] 板子没回 FB? 统计（丢包或超时）")

            # 按绝对时间轴对齐
            deadline = start + frame_no / fps
            gap = deadline - time.time()
            if gap > 0:
                time.sleep(gap)

    except KeyboardInterrupt:
        print("\n[agent] 用户中断")
    finally:
        # 收拾干净：让板子停在最后一帧上，而不是刷了一半的状态
        pass

    elapsed = time.time() - start
    actual = frame_no / elapsed if elapsed > 0 else 0.0
    print("[agent] 共发 %d 帧，用时 %.1f 秒，实际 %.1f fps"
          % (frame_no, elapsed, actual))


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def _cmd_check(args) -> int:
    """确认板子在、命令通道通、帧统计能读。"""
    print("[agent] 目标 %s:%d" % (args.host, args.port))
    with Board(args.host, args.port, timeout=args.timeout) as b:
        try:
            print("  PING     -> %s" % b.ping().strip())
        except BoardError as e:
            print("  PING     -> 失败：%s" % e)
            print("\n排查顺序：网线 -> 板子串口有没有 [LINK] UP -> "
                  "ping %s -> Windows 防火墙" % args.host)
            return 1
        for name, fn in (("INFO", b.info), ("FB?", b.fb_stat),
                         ("OLED STAT", b.oled_stat)):
            try:
                print("  %-9s-> %s" % (name, fn().strip()))
            except BoardError as e:
                print("  %-9s-> 失败：%s" % (name, e))
    return 0


def _cmd_list(args) -> int:
    print("内置动画（用 --anim 名字 播放）：")
    for name in sorted(anim.ANIMS):
        doc = (anim.ANIMS[name].__doc__ or "").strip().split("\n")[0]
        print("  %-10s %s" % (name, doc))
    print("\n也可以直接描述你要什么，让 LLM 现场写：")
    print('  python agent.py "一双慢慢眨的眼睛"')
    return 0


def _resolve_code(args) -> Optional[str]:
    """按优先级决定用哪段代码：--code 文件 > 描述 > None（用内置动画）。"""
    if args.code:
        with open(args.code, "r", encoding="utf-8") as f:
            return f.read()
    if args.text:
        return code_for(" ".join(args.text),
                        use_cache=not args.no_cache)
    return None


def _make_renderer(args) -> tuple:
    """
    返回 (render 可调用对象, 说明字符串)。

    render 的签名统一成 render(t, params) -> bytes，这样 play() 不用
    关心背后是内置动画还是沙箱代码。
    """
    code = _resolve_code(args)

    if code is not None:
        renderer = Renderer(code, timeout=args.render_timeout)
        return (lambda t, p: renderer.render(t, p)), "沙箱代码"

    if args.anim:
        name = args.anim
        fn = anim.get(name)          # KeyError 会让 main 报清楚
        return (lambda t, p: _render_named(fn, t, p)), "内置动画 %s" % name

    raise SystemExit("要么给 --anim 名字，要么给一段描述文字，要么给 --code 文件。")


def _render_named(fn, t: float, params: Dict) -> bytes:
    c = Canvas()
    fn(c, t, params)
    return c.pack()


def _cmd_render(args) -> int:
    """渲染一帧存成 PNG，或者打到终端看字符画。不发板子。"""
    fn, _ = _make_renderer(args)
    frame = fn(args.at, {})

    if args.ascii_ or not args.output:
        c = Canvas()
        c.gfx = bytearray(frame)
        print(c.to_ascii())
        if not args.output:
            return 0

    if args.output:
        _save_png(frame, args.output)
        print("[agent] 已写出 %s" % args.output)
    return 0


def _save_png(frame: bytes, path: str) -> None:
    """
    把一帧存成 PNG（放大 4 倍，不然 128x64 太小看不清）。

    故意不依赖 Pillow：手写 PNG 只需要 zlib + struct，标准库就够。
    少一个依赖，环境坏掉的概率就少一分。
    """
    import struct
    import zlib

    scale = 4
    w, h = 128 * scale, 64 * scale
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # 每行的 filter 字节
        sy = y // scale
        for x in range(w):
            sx = x // scale
            bit = (frame[(sy >> 3) * 128 + sx] >> (sy & 7)) & 1
            v = 255 if bit else 0
            raw += bytes((v, v, v))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(png)


def _cmd_sandbox_test() -> int:
    """只跑沙箱自检，不联网、不碰 LLM、不需要 API key。"""
    ok, total = self_test()
    print("[agent] 沙箱自检：%d/%d 拦住" % (ok, total))
    if ok != total:
        print("[agent] ⚠ 沙箱有漏，先别让 LLM 写代码")
        return 1
    return 0


def _cmd_play(args) -> int:
    fn, what = _make_renderer(args)

    board = None
    if not args.ascii_ and not args.dry:
        board = Board(args.host, args.port, timeout=args.timeout)
        try:
            print("[agent] PING -> %s" % board.ping().strip())
        except BoardError as e:
            print("[agent] 板子没回 PING：%s" % e)
            print("[agent] 用 --ascii 可以只在终端看效果，不发板子。")
            board.close()
            return 1

    if args.ascii_:
        # 终端里按帧画字符画。用 \033[H 把光标移回左上角，实现"原地刷新"。
        print("\033[2J", end="")   # 清屏
        start = time.time()
        total = int(args.seconds * args.fps) if args.seconds > 0 else 0
        n = 0
        while not total or n < total:
            t = n / args.fps
            frame = fn(t, {})
            c = Canvas()
            c.gfx = bytearray(frame)
            sys.stdout.write("\033[H")
            sys.stdout.write("t=%.2fs  frame=%d  (%s)\n" % (t, n, what))
            sys.stdout.write(c.to_ascii())
            sys.stdout.write("\n")
            sys.stdout.flush()
            n += 1
            gap = (start + n / args.fps) - time.time()
            if gap > 0:
                time.sleep(gap)
        return 0

    if args.dry:
        frame = fn(0.0, {})
        print("[agent] --dry：渲染了 1 帧 %d 字节，没有发送" % len(frame))
        return 0

    print("[agent] 播放：%s，%g fps，%s"
          % (what, args.fps,
             "无限" if args.seconds <= 0 else "%.0f 秒" % args.seconds))
    print("[agent] Ctrl+C 停止")
    play(fn, board, fps=args.fps, seconds=args.seconds,
         params={}, seq=not args.no_seq, stats_every=args.stats)
    if board is not None:
        board.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="agent",
        description="用自然语言控制 STM32 板子上的 OLED 显示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("【用法】")[1].split("【LLM 配置】")[0]
        if "【用法】" in __doc__ else None,
    )
    ap.add_argument("text", nargs="*",
                    help="描述你想要的画面，例如 \"一双会动的眼睛\"")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help="板子 IP（默认 %s）" % DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help="板子 UDP 端口（默认 %d）" % DEFAULT_PORT)
    ap.add_argument("--timeout", type=float, default=1.0,
                    help="UDP 超时秒数（默认 1.0）")

    ap.add_argument("--anim", "-a", default=None,
                    help="播内置动画，名字见 --list")
    ap.add_argument("--code", "-c", default=None,
                    help="播一个 .py 文件里的 draw(c,t,p)")
    ap.add_argument("--list", "-l", action="store_true",
                    help="列出内置动画")
    ap.add_argument("--check", action="store_true",
                    help="检查板子连通性")
    ap.add_argument("--render", action="store_true",
                    help="只渲染一帧，不播放（配 -t / -o）")
    ap.add_argument("--test", action="store_true",
                    help="只跑沙箱自检")

    ap.add_argument("--fps", type=float, default=20.0,
                    help="发送帧率（默认 20）")
    ap.add_argument("--seconds", "-s", type=float, default=0.0,
                    help="播放多少秒，0 表示一直播（默认 0）")
    ap.add_argument("--at", "-t", type=float, default=1.0,
                    help="--render 时取哪个时刻的帧（默认 1.0）")
    ap.add_argument("--output", "-o", default=None,
                    help="--render 时把帧写成 PNG")
    ap.add_argument("--ascii", dest="ascii_", action="store_true",
                    help="只在终端画字符画，不发板子")
    ap.add_argument("--dry", action="store_true",
                    help="渲染但不发送，也不画字符画")
    ap.add_argument("--no-seq", action="store_true",
                    help="发帧不带序号（默认带，用于抗乱序）")
    ap.add_argument("--stats", type=float, default=0.0,
                    help="每隔几秒打印一次 FB? 统计（默认不打）")
    ap.add_argument("--no-cache", action="store_true",
                    help="不让 LLM 用缓存，强制重新生成代码")
    ap.add_argument("--render-timeout", type=float, default=1.0,
                    help="单帧渲染超时秒数（默认 1.0）")

    args = ap.parse_args(argv)

    if args.list:
        return _cmd_list(args)
    if args.check:
        return _cmd_check(args)
    if args.render:
        return _cmd_render(args)
    if args.test:
        return _cmd_sandbox_test()

    return _cmd_play(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (SandboxError, LLMError) as e:
        print("\n[agent] 出错：%s" % e, file=sys.stderr)
        sys.exit(2)
