# -*- coding: utf-8 -*-
"""
anim.py —— 动画的"渲染语言"与内置示例。

【为什么是「渲染语言」而不是「动作库」】

最初的想法是写几个动作：eyes()、horse()、rain()…… 用户输入「眼睛」
就播放 eyes。这个方案有个致命问题：**我写多少个，用户就只能看多少个**。
用户想要「一只打哈欠的猫」时，代码里没有，就卡住了。

改成「渲染语言」之后，每个动画只是一个函数：

    def draw(c: Canvas, t: float, p: dict) -> None

    t = 该帧的时间（秒，从动画开始算）
    p = 参数字典（颜色、速度、位置……由调用方给）

用户（或以后的 LLM）想要什么，就现写一个这样的函数。本文件里的
eyes / horse / rain / boing 只是**示例**，用来证明这套原语够用，
不是能力的边界。

【每一帧都从空白开始】

不要在帧之间保留状态 —— 每帧都是 canvas.clear() 之后重画。
理由：如果动画函数里藏着"上一帧"的状态，那它就没法随机跳转到
t=5.0 去渲染（做预览图、做并行渲染都要这个能力）。纯函数式更好用。

【安全】

以后 LLM 现写的 draw() 会在 agent.py 的沙箱里跑：只给 math/random，
不给 os/sys/socket。所以示例里也只用这几个 —— 保持一致。
"""

from __future__ import annotations

import math
import random
from typing import Callable, Dict, List, Tuple

from canvas import Canvas, HEIGHT, WIDTH


# 一个动画就是这么一个函数
DrawFn = Callable[[Canvas, float, Dict], None]


# ---------------------------------------------------------------------------
# 示例 1：会动的眼睛 —— 用户点名的第一个需求
# ---------------------------------------------------------------------------

def _eye(c: Canvas, cx: int, cy: int, r: int, look_x: float, look_y: float,
         blink: float) -> None:
    """
    画一只眼睛。

    look_x / look_y 是瞳孔的偏移量（-1..1），blink 是眨眼程度（0=睁，1=闭）。
    这三个参数把「眼球运动」和「眨眼」解耦了，调用者可以各自驱动。
    """
    if blink > 0.85:
        # 完全闭上：一条线
        c.fill_rect(cx - r, cy - 1, 2 * r, 2, True)
        return

    # 眼白：空心椭圆
    ry = int(r * (1.0 - blink * 0.9))
    if ry < 1:
        ry = 1
    c.ellipse(cx, cy, r, ry, True, False)

    # 瞳孔：负责"看向哪里"
    pr = max(2, r // 3)
    px = int(cx + look_x * (r - pr - 2))
    py = int(cy + look_y * (ry - pr - 1))
    c.circle(px, py, pr, True, True)

    # 高光：一点反而让眼睛活了
    if r >= 8:
        c.set(px - pr // 2, py - pr // 2, False)


def eyes_fast(c: Canvas, t: float, p: Dict) -> None:
    """
    一双**明显在动**的眼睛 —— 专门用来验证"以太网实时改画面"。

    和 eyes() 的区别：瞳孔以 1 秒为周期走到左右极限（±0.95），
    幅度拉满、周期缩短到 1 秒。这样即使板子只刷到 10fps，
    每两次刷新之间瞳孔也会移动一大段，肉眼绝对看得出在动。

    参数：
        period      瞳孔来回一次多少秒，默认 1.0
        look_speed  保留兼容，未使用
    """
    period = float(p.get("period", 1.0))

    # 方波式摆动：前半周期冲向左，后半周期冲向右，两端各停一小会
    phase = (t / period) % 1.0
    if phase < 0.45:
        lx = -0.95
    elif phase < 0.5:
        lx = -0.95 + (phase - 0.45) / 0.05 * 1.9
    elif phase < 0.95:
        lx = 0.95
    else:
        lx = 0.95 - (phase - 0.5 - 0.45) / 0.05 * 1.9

    ly = 0.45 * math.sin(t * 2.0 * math.pi / (period * 2.0))

    r = 18
    _eye(c, 34, 30, r, lx, ly, 0.0)
    _eye(c, 94, 30, r, lx, ly, 0.0)


def eyes(c: Canvas, t: float, p: Dict) -> None:
    """
    一双会动的眼睛。

    行为：瞳孔缓慢游移（两个不同周期的正弦叠加，看起来不机械），
    每隔几秒眨一次眼，偶尔"左顾右盼"。

    参数：
        look_speed  瞳孔游移速度，默认 0.6
        blink_every 平均几秒眨一次，默认 3.5
    """
    look_speed = float(p.get("look_speed", 0.6))
    blink_every = float(p.get("blink_every", 3.5))

    # 瞳孔位置：两个不同频率叠加，避免看起来像钟摆
    lx = 0.75 * math.sin(t * look_speed * 1.7) + 0.25 * math.sin(t * look_speed * 4.3)
    ly = 0.55 * math.sin(t * look_speed * 2.3 + 1.1)

    # 眨眼：用 t 直接算，保证纯函数
    phase = t / blink_every
    frac = phase - math.floor(phase)
    # 眨眼只占一个周期的前 8%，这样看起来是"偶尔眨一下"
    if frac < 0.08:
        blink = math.sin(frac / 0.08 * math.pi)
    else:
        blink = 0.0

    r = 18
    _eye(c, 34, 30, r, lx, ly, blink)
    _eye(c, 94, 30, r, lx, ly, blink)


# ---------------------------------------------------------------------------
# 示例 2：奔跑的马 —— 用户点名的第二个需求
# ---------------------------------------------------------------------------

def _horse_leg(c: Canvas, hip_x: int, hip_y: int, angle: float,
               upper: int, lower: int, phase: float) -> None:
    """
    一条腿，用两段加粗线段表示，带膝关节。

    angle 是大腿的摆动角（弧度），phase 用来让小腿错开相位 ——
    真实动物跑动时小腿滞后于大腿，这一点点滞后就是"像活的"和
    "像钟摆"的区别。

    线宽 2：1 像素的腿在 128x64 上看不清，会显得像蜘蛛。
    """
    knee_x = int(hip_x + upper * math.sin(angle))
    knee_y = int(hip_y + upper * math.cos(angle))
    lower_angle = angle - 0.9 * math.sin(phase)
    hoof_x = int(knee_x + lower * math.sin(lower_angle))
    hoof_y = int(knee_y + lower * math.cos(lower_angle))

    # 大腿：加粗的线
    _thick_line(c, hip_x, hip_y, knee_x, knee_y)
    # 小腿
    _thick_line(c, knee_x, knee_y, hoof_x, hoof_y)
    # 蹄子：一小块实心，落地时有分量感
    c.fill_rect(hoof_x - 1, hoof_y - 1, 3, 2, True)


def _thick_line(c: Canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    """2 像素粗的线（向右下偏移一个像素再画一遍）。"""
    c.line(x0, y0, x1, y1, True)
    c.line(x0 + 1, y0, x1 + 1, y1, True)


def horse(c: Canvas, t: float, p: Dict) -> None:
    """
    一匹奔跑的马（侧面剪影）。

    参数：
        speed  步频，默认 6.0
        dir    1 = 朝右跑（默认），-1 = 朝左跑

    画面里马身高度约占 40px（y=14..58），水平方向来回跑。
    为了不被屏幕边缘裁掉头，跑动范围比屏幕小一圈。
    """
    speed = float(p.get("speed", 6.0))
    d = int(p.get("dir", 1))

    # 整体上下起伏（跑步时的颠簸）
    bob = int(2.0 * math.sin(t * speed * 2.0))

    # 地面
    ground = 58
    c.hline(0, ground, WIDTH, True)

    # 水平位置：围绕屏幕中心来回跑。振幅 26，保证头尾都留在屏内。
    cx = int(WIDTH // 2 + 26 * math.sin(t * 0.7))

    # --- 腿（先画，身体会盖住髋部，看起来才连得上）---
    hip_y = ground - 20 + bob
    swing = math.sin(t * speed)
    swing2 = math.sin(t * speed + math.pi)   # 对角腿反相

    _horse_leg(c, cx - 13, hip_y, 0.55 * swing, 10, 9, t * speed)
    _horse_leg(c, cx - 3, hip_y, 0.55 * swing2, 10, 9, t * speed + 1.5)
    _horse_leg(c, cx + 3, hip_y, 0.55 * swing2, 10, 9, t * speed + 1.5)
    _horse_leg(c, cx + 13, hip_y, 0.55 * swing, 10, 9, t * speed)

    # --- 身体：实心躯干，宽 42 高 13 ---
    body_y = ground - 32 + bob
    c.fill_rect(cx - 21, body_y, 42, 13, True)
    c.fill_rect(cx - 23, body_y + 3, 4, 8, True)     # 臀
    c.fill_rect(cx + 19, body_y + 2, 5, 10, True)    # 胸

    # --- 脖子：从胸部斜向右上，用一组短横条堆出来，保证是实心的 ---
    neck_cx = cx + 24
    neck_ty = body_y - 13
    for i in range(13):
        # i=0 在下方靠身体，i=12 在上方靠头
        seg_y = neck_ty + i
        seg_x = neck_cx + (12 - i) // 2
        c.fill_rect(seg_x, seg_y, 7, 2, True)

    # --- 头：接在脖子顶端 ---
    head_x = neck_cx + 4
    head_y = neck_ty - 8
    c.fill_rect(head_x, head_y, 13, 9, True)
    c.fill_rect(head_x + 9, head_y + 5, 7, 5, True)   # 口鼻
    c.set(head_x + 4, head_y + 2, False)              # 眼睛（挖空）
    c.set(head_x + 4, head_y + 3, False)
    c.fill_rect(head_x + 1, head_y - 4, 3, 4, True)   # 耳朵

    # --- 鬃毛：沿脖子左侧向下，随速度飘 ---
    for i in range(11):
        mx = neck_cx + (12 - i) // 2 - 1
        my = neck_ty + i
        wob = int(2.5 * math.sin(t * speed * 1.5 + i * 0.5))
        c.line(mx, my, mx - 4 + wob, my + 1, True)

    # --- 尾巴：从臀部左后方甩出去 ---
    tail_x = cx - 23
    tail_y = body_y + 4
    for i in range(10):
        wob = int(4.0 * math.sin(t * speed * 1.2 + i * 0.6))
        c.line(tail_x - i, tail_y + i // 2, tail_x - i - 2, tail_y + i // 2 + wob // 2, True)


# ---------------------------------------------------------------------------
# 示例 3：几何动画，用来验证原语和帧率
# ---------------------------------------------------------------------------

def rain(c: Canvas, t: float, p: Dict) -> None:
    """雨滴 + 水花。用来验证「大范围逐像素绘制」的速度。"""
    random.seed(1234)  # 保证纯函数：同一个 t 一定画出同一帧
    for i in range(70):
        x = random.randint(0, WIDTH - 1)
        speed = random.uniform(60.0, 140.0)
        y = (random.uniform(0, HEIGHT) + t * speed) % HEIGHT
        c.vline(x, int(y), 3, True)


def boing(c: Canvas, t: float, p: Dict) -> None:
    """一个弹跳的圆，带拖影。验证圆/椭圆的填充性能。"""
    for k in range(6):
        tt = t - k * 0.045
        if tt < 0:
            continue
        y = HEIGHT - 20 - abs(math.sin(tt * 3.0)) * 34
        x = WIDTH / 2 + math.sin(tt * 1.5) * 40
        on = (k == 0)
        c.circle(int(x), int(y), max(2, 8 - k), on, fill=on)


# ---------------------------------------------------------------------------
# 示例 4：文字动画 —— 验证中文点阵通路
# ---------------------------------------------------------------------------

def scrolling_text(c: Canvas, t: float, p: Dict) -> None:
    """
    文字从右向左滚动。

    参数：
        text  要滚动的字符串
        face  字体名（Windows 字体）
        size  字号

    中文点阵在 PC 端渲染（见 bitmap.py），板子只收位图 —— 所以这里
    可以显示任意中文，不受板子上只有 4 个汉字字库的限制。
    """
    import bitmap  # 延迟导入：不用中文时不碰 GDI

    text = str(p.get("text", "你好，世界"))
    face = str(p.get("face", bitmap.DEFAULT_FACE))
    size = int(p.get("size", 16))
    speed = float(p.get("speed", 40.0))

    w, h, bits = bitmap.render_text(text, face, size)

    # 滚动位置。
    #
    # 如果按 (t * speed) % total 从屏幕右边滚进来，那么 t=0 时文字
    # 完全在屏幕外 —— 播放的前一两秒观众什么都看不到，会以为坏了。
    # 所以这里从一个"文字已经在屏幕内"的位置起算：初始偏移是 -w，
    # 也就是文字左边缘刚好在 x=0，然后往左滚出去，再从右边进来。
    #
    # 结果：t=0 立刻能看到完整文字，之后无缝循环。
    total = WIDTH + w
    x = int(-((t * speed) % total))
    y = (HEIGHT - h) // 2
    c.blit(x, y, w, h, bits, True)


# ---------------------------------------------------------------------------
# 示例 5：行驶的汽车 —— 用户点名的需求
#
# 这是「参照答案」：以后 LLM 现写的汽车可以跟它对比。
# 结构上刻意分成"车身 / 车窗 / 轮子 / 地面"四块，方便按需改动。
# 两个轮子各有自己的辐条角度，这样看起来是真在转，而不是两个死圆。
# ---------------------------------------------------------------------------

def _wheel(c: Canvas, cx: int, cy: int, r: int, angle: float) -> None:
    """一个轮子：外圈 + 轮毂 + 4 根辐条。angle 是辐条旋转角（弧度）。"""
    c.circle(cx, cy, r, True, False)          # 外胎（空心圆）
    c.circle(cx, cy, max(1, r // 3), True, False)   # 轮毂
    for k in range(4):
        a = angle + k * (math.pi / 2.0)
        x1 = int(cx + math.cos(a) * (r - 2))
        y1 = int(cy + math.sin(a) * (r - 2))
        c.line(cx, cy, x1, y1, True)


def car(c: Canvas, t: float, p: Dict) -> None:
    """
    一辆在路上行驶的汽车（侧面剪影，向左开）。

    参数（都可选）：
        speed   行驶速度，默认 40 像素/秒
        wheel   轮子半径，默认 6
        地面高度固定在第 54 行（轮胎底部刚好压住地面线）

    构图（128x64 里）：
        车身   y 42..54
        车顶   y 34..42（带一点弧度，用矩形 + 斜线凑）
        轮子   圆心 y=54，r=6，所以轮胎底在 y=60
        地面   两条横线，做出路面感
    """
    speed = float(p.get("speed", 40.0))
    r = int(p.get("wheel", 6))

    # 车身位置：从左往右开出去再绕回来（用取模，无缝循环）
    span = WIDTH + 80      # 128 + 车身宽度余量
    cy_top = int(48 + 4 * math.sin(t * 3.0))   # 轻微颠簸
    front = int((WIDTH + 20) - (t * speed) % span)  # 车头 x 坐标，随时间左移

    body_x = front - 70     # 车身左上角
    body_y = cy_top - 14
    body_w = 70
    body_h = 14

    # --- 地面：固定的两条线，给"在行驶"提供参照物 ---
    c.hline(0, 61, 128, True)
    for i in range(0, 128, 16):
        # 路面虚线随车移动（滚动），这样静止画面也能看出"在动"
        dx = int((-t * speed) % 16)
        c.hline(i + dx, 56, 6, True)

    # --- 车身 ---
    c.fill_rect(body_x, body_y, body_w, body_h, True)

    # --- 车顶（比车身窄，靠后一些）---
    roof_w = 36
    roof_x = body_x + 16
    roof_y = body_y - 8
    c.fill_rect(roof_x, roof_y, roof_w, 8, True)
    # 斜切前后两块，做出流线感
    c.line(roof_x, roof_y + 8, roof_x - 6, body_y, False)
    c.line(roof_x + roof_w, roof_y + 8, roof_x + roof_w + 6, body_y, False)

    # --- 车窗（挖空）---
    c.fill_rect(roof_x + 4, roof_y + 2, 12, 5, False)
    c.fill_rect(roof_x + 20, roof_y + 2, 12, 5, False)

    # --- 车灯 ---
    c.fill_rect(body_x - 2, body_y + 3, 3, 4, True)     # 前灯
    c.fill_rect(body_x + body_w - 1, body_y + 3, 2, 4, True)  # 尾灯

    # --- 两个轮子 ---
    # 轮子转的角速度 = 车速 / 半径（纯滚动条件），看起来才不打滑
    spin = -(t * speed) / max(1, r)
    w1x = body_x + 14
    w2x = body_x + body_w - 16
    for wx in (w1x, w2x):
        c.circle(wx, body_y + body_h + r - 2, r, False, False)  # 先擦出轮廓
        _wheel(c, wx, body_y + body_h + r - 2, r, spin)


# ---------------------------------------------------------------------------
# 示例 6：烟花 —— LLM 不好写的东西，用来看粒子和随机
# ---------------------------------------------------------------------------

def fireworks(c: Canvas, t: float, p: Dict) -> None:
    """
    烟花：多次爆炸，每次炸出一圈粒子。

    刻意用 random.seed(固定值) 保证纯函数 —— 同一个 t 永远画同一帧，
    否则"PC 渲染的帧"和"你单独 render 出来检查的帧"会不一样，
    调试会疯掉。
    """
    random.seed(20241016)
    period = 1.6
    burst = int(t / period)

    for b in range(2):                      # 同时最多两朵，避免太乱
        n = burst - b
        if n < 0:
            continue
        age = (t - n * period) / period     # 0..1
        if not (0.0 <= age <= 1.0):
            continue
        # 爆炸位置的伪随机漂移（用 n 当种子，保证可复现）
        random.seed(999 + n)
        cx = 30 + random.randint(0, 68)
        cy = 14 + random.randint(0, 16)
        radius = 2 + age * 24
        for k in range(24):
            a = k * (2.0 * math.pi / 24.0) + n
            # 重力：粒子越往后越往下垂
            px = int(cx + math.cos(a) * radius)
            py = int(cy + math.sin(a) * radius + age * age * 16)
            c.set(px, py, True)
        if age < 0.25:                       # 中心还有余亮
            c.circle(cx, cy, max(1, int(4 * (1 - age * 4))), True, False)


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

ANIMS: Dict[str, DrawFn] = {
    "eyes": eyes,
    "eyes_fast": eyes_fast,
    "horse": horse,
    "car": car,
    "fireworks": fireworks,
    "rain": rain,
    "boing": boing,
    "text": scrolling_text,
}


def get(name: str) -> DrawFn:
    """按名字取动画。名字大小写不敏感。"""
    fn = ANIMS.get(name.lower())
    if fn is None:
        raise KeyError(
            "没有名为 %r 的动画。现有的：%s"
            % (name, ", ".join(sorted(ANIMS)))
        )
    return fn


def render_frame(name: str, t: float, params: Dict | None = None) -> bytes:
    """
    渲染某一时刻的一帧，直接返回 1024 字节。

    这是给"先存成图片/先看字符画再决定发不发"用的。
    """
    c = Canvas()
    get(name)(c, t, params or {})
    return c.pack()
