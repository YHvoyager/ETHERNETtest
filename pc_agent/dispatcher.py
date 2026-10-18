# -*- coding: utf-8 -*-
"""
dispatcher.py —— 「你说一句话」→「一条可审计、可执行的指令」。

【它是什么 / 不是什么】

它**只做翻译**。不碰板子、不碰 UI、不播动画。输入一句自然语言，
输出一个结构化的 action。真正干活的是 agent.py 里已有的函数。

这样设计的原因：在任何前端出现之前，先能纯命令行验证「AI 理解得对不对」。
如果理解不准，做再漂亮的前端也没用。

【为什么先跑规则、再问 LLM】

    "清屏"、"开灯"、"ping"          —— 规则层更准、更快、不花钱、不幻觉
    "把这块屏弄干净点"、"灯闪一下"   —— 规则层接不住，交给 LLM

规则层是**确定性**的，所以自测集里它必须 100% 通过；LLM 层只记录通过率。
这个顺序不能反：让 LLM 先跑，它会用花言巧语把规则本该命中的也抢走。

【写操作确认】

分派器只负责**标记** needs_confirm，不负责弹框（弹框是前端的事）。
但命令行就能验证：不带 --yes 时只打印指令不执行。

    只读   PING INFO FB? R RB RB  OLED HELP       → 直接执行
    写(IO) LED IO OLED ON/OFF/CLR/FILL/TXT/...    → 要确认
    写(寄存器) W WB OLED RAW                       → 要确认，且单独标红
    其它   不在 reg_shell.c 命令表里的任何东西      → 拒绝（不猜）

白名单是**反着**来的：不是"黑名单里不能写"，而是"只承认 HELP 里列出的命令"。
LLM 编出任何不存在的命令，在这一步就死掉，永远到不了板子。

【用法】

    python dispatcher.py "把灯打开"              # 只打印指令，不执行
    python dispatcher.py "把灯打开" --yes         # 真发出去
    python dispatcher.py "把灯打开" --json        # 机器可读
    python dispatcher.py "把灯打开" --explain     # 看分派全过程
    python dispatcher.py --test                  # 跑自测集（不需要板子/LLM）
    python dispatcher.py --test --llm            # 连 LLM 层一起测（要 key）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import agent  # noqa: E402
import anim   # noqa: E402
from proto import Board, BoardError, DEFAULT_HOST, DEFAULT_PORT  # noqa: E402
from sandbox import SandboxError  # noqa: E402

# ---------------------------------------------------------------------------
# 词汇表和风险分级
# ---------------------------------------------------------------------------

# 动作表，闭合的，不许多。前 6 个对应 agent.py 里已有的 6 种能力；
# 最后一个是唯一一个"多条固件命令"的复合动作 —— 见下面 led_blink 的注释。
ACTIONS = ("anim", "cmd", "knowledge", "draw", "render", "query", "led_blink")

# reg_shell.c 里真实存在的命令（与 Core/Src/reg_shell.c:229 的 s_help_text 一一对应）。
# ⚠ 新增固件命令后必须回来同步，否则新命令会被当成"编出来的"拒掉。
FIRMWARE_CMDS = (
    "HELP", "IO", "INFO", "LED", "LED0", "LED1", "DS0", "DS1",
    "R", "W", "RB", "WB", "OLED", "BROADCAST", "PING", "FB?",
)

# 写寄存器：能改硬件行为，最危险的一类
REG_WRITE_CMDS = {"W", "WB"}

# 和板子状态无关、只影响 PC 端行为的查询命令
QUERY_ONLY = {"PING", "INFO", "FB?", "HELP", "OLED STAT"}

# RCC 只读区（与 reg_shell.c §3.7 的白名单一致）。
# ⚠ 注意 0x40023800~0x40023BFF **落在** GPIO 区间 0x40020000~0x40023FFF 里面，
#   所以判据必须**先判 RCC 再判 GPIO**，反过来就对 RCC 的写放行了。
RCC_READONLY_LO = 0x40023800
RCC_READONLY_HI = 0x40023BFF
GPIO_LO = 0x40020000
GPIO_HI = 0x40023FFF

# "OLED STAT" 是 OLED 的子命令，但它只读，单独拎出来
READONLY_OLED_SUBS = {"STAT"}

# 只读命令名白名单 —— ⚠ 判据顺序有个大坑，踩过：**命令头只读 ≠ 这条命令只读**。
#   "IO"（不带参数）是列状态，"IO 1 1" 是在写引脚；"OLED" 是屏幕示意，
#   "OLED CLR" 是写。早先写成 `if head in READONLY_CMDS: return False`，
#   "IO 1 1" 因为头是 IO 就被判成只读，**不加 --yes 直接写进了板子**。
#   所以这条白名单只用于最后兜底，LED/IO 和 OLED 必须先按参数单独判。
READONLY_CMDS = {"HELP", "INFO", "R", "RB", "PING", "FB?"}


def needs_confirm(cmd: str) -> bool:
    """
    True = 这是写操作，执行前必须让用户点头。

    ⚠ 判据故意**反过来**：只有"明确证明是只读"的才免确认，其余一律要确认。

    写成 `if cmd in WRITE_CMDS: return True` 的话，将来固件加一条新命令，
    它不在 WRITE_CMDS 里 → 被当成只读 → 悄悄打到板子上。反过来判，新命令
    默认要确认，宁可多点一次，也不给"新命令绕过确认"留缝。

    ⚠ 还有一层坑（踩过）：**命令头只读 ≠ 这条命令只读**。
    `IO`（不带参数）是列状态，`IO 1 1` 是在写引脚；`OLED`（不带子命令）
    是渲染示意，`OLED CLR` 是写。所以每个分支都得看**参数**，不能只看命令名。
    """
    tok = cmd.strip().upper().split()
    if not tok:
        return True
    head = tok[0]

    # ---- 带子命令的：看子命令 ----
    if head == "OLED":
        if len(tok) < 2:
            return False            # 裸 OLED = ASCII 屏幕示意，只读
        sub = tok[1]
        if sub in READONLY_OLED_SUBS:
            return False            # OLED STAT
        if sub == "TXT":
            return len(tok) > 4     # "OLED TXT 0 1"=指定像素只读；带文本才是写
        return True                 # INIT/ON/OFF/CLR/FILL/PIX/BAR/REFRESH/RAW

    # ---- 带编号的 IO 命令：看有没有"值" ----
    if head in ("LED", "IO"):
        if len(tok) < 2:
            return False            # 裸 LED / 裸 IO = 列状态
        if len(tok) < 3:
            # ⚠ 只有编号。固件实测回的是
            #   "ERR: usage: LED <n> [0|1|T]   (no value = toggle)"
            #   括号里说 "无值即翻转" —— 那是**写**。宁可多要一次确认，
            #   也别把"想看一下 LED 0 现在什么状态"变成悄悄翻转。
            return True
        val = tok[2]
        if val in ("0", "1", "ON", "OFF", "HIGH", "LOW"):
            return True             # ⚠ 这是写
        return val not in ("T", "TOGGLE")

    # ---- 其余按命令头查只读白名单 ----
    return head not in READONLY_CMDS


def validate_cmd(cmd: str) -> Optional[str]:
    """
    过一遍固件命令白名单 + 寄存器地址白名单。

    返回 None 表示合法，返回字符串表示拒绝理由。
    这层拦在板子之前，板子那边 reg_shell.c 还会再拦一次 —— 两道。
    """
    tok = cmd.strip().split()
    if not tok:
        return "空命令"
    head = tok[0].upper()

    if head not in FIRMWARE_CMDS:
        return "固件里没有命令 %r（不是猜错了，是真不存在）" % head

    if head in REG_WRITE_CMDS:
        if len(tok) < 3:
            return "%s 需要 <addr> <value>" % head
        try:
            addr = int(tok[1], 16)
        except ValueError:
            return "%s 的地址必须是十六进制：%r" % (head, tok[1])
        try:
            val = int(tok[2], 16)
        except ValueError:
            return "%s 的值必须是十六进制：%r" % (head, tok[2])
        # ⚠ WB 的字节上限必须**先查**。原来它写在 `return ... GPIO 区间` 这个
        #   分支之后，只有落到最后的 `return "不在白名单"` 才有可能被执行 ——
        #   等于对合法地址永远不检查，`WB 40020014 1FF` 会原样打到板子。
        if head == "WB" and val > 0xFF:
            return "WB 只写一个字节，值不能超过 0xFF（给的是 0x%X）" % val
        # 先判 RCC 再判 GPIO —— RCC 区间是 GPIO 区间的子集
        if RCC_READONLY_LO <= addr <= RCC_READONLY_HI:
            return "RCC 是只读区域，写它会掉时钟/变砖（0x%08X）" % addr
        if GPIO_LO <= addr <= GPIO_HI:
            return None                                    # GPIOA~K：可读写
        return "地址 0x%08X 不在白名单里" % addr

    return None


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------

class Plan(dict):
    """一条分派结果。用 dict 而不是 dataclass，是为了 --json 直接可序列化。"""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)

    def __getattr__(self, k: str) -> Any:     # 让 plan.action 也能写
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None


def _plan(action: Optional[str], arg: Any = None, by: str = "",
          needs_confirm_: bool = False, why: str = "",
          raw: str = "", **extra: Any) -> Plan:
    p = Plan(action=action, arg=arg, by=by, needs_confirm=needs_confirm_,
             why=why, raw=raw, **extra)
    return p


# ---------------------------------------------------------------------------
# 第 ① 层：规则
#
# 顺序原则：**写得越具体的规则越靠前**。否则"关屏"会先被"关...屏"吃掉，
# 或者"状态"被 LED 的规则抢走。每条规则自己收口，不靠顺序兜底但顺序要对。
# ---------------------------------------------------------------------------

_ANIM_WORDS = [
    # (正则, 动画名, 说明)  —— 越具体越靠前。
    # ⚠ 中文名词常常夹在别的词里："汽车站"、"马上升级"、"下雨天"。
    #   所以每个词都配了"排除词"，命中排除词就不算动画请求。
    (r"眨眼|眼睛|eye", "eyes", "眼睛"),
    (r"快眼|眼睛.*快|晃眼", "eyes_fast", "眼睛(快速)"),
    (r"马(?!上)|horse|奔跑的动物", "horse", "马"),
    (r"汽车|车(?!站)|car|行驶", "car", "汽车"),
    (r"烟花|鞭炮|爆炸|firework", "fireworks", "烟花"),
    (r"下雨|雨滴|雨(?!天)|rain", "rain", "雨"),
    (r"弹跳|弹一弹|boing|小球|皮球", "boing", "弹跳的球"),
    (r"滚动文字|文字|滚动|字样", "text", "滚动文字"),
]

# 屏幕上什么都没了 / 坏了 —— 这是排障请求，不是"播文字动画"
#
# ⚠ 写法方向极易搞错，踩过一次：中文是**述宾**语序，"没"在前、"字"在后只对
#   "没字"这种省略说法；实际口语是 "屏幕上一个字都没了" —— "字" 在前、"没" 在后。
#   所以两条方向都得写，缺一条就会漏掉一半说法。
_TROUBLE_RE = re.compile(
    r"没.{0,4}(字|图片|画面|内容)"          # 没字 / 没内容
    r"|(字|图片|画面|内容).{0,4}没"          # 字都没了 / 内容没了
    r"|(屏幕|显示屏|屏).{0,4}(没|不|黑|白)"  # 屏幕没亮 / 屏不亮 / 屏幕黑了
    r"|什么都没有|没反应|不显示|坏了|不动了"
)

# "在问状态"而不是"在叫我修"。
#   "刷屏卡不卡"里的"卡"会命中上面的"不动了"，"屏还在吗"同理。
#   这些是**只读询问**，绝不能转成一次写操作 —— 宁可漏判（掉到 LLM），
#   也不要让用户问一句就把屏给重置了。
_ASK_INFO_RE = re.compile(
    r"不卡|卡不|不亮|亮不|坏不|动不|还在|在吗|是否|吗|么样|怎么样|"
    r"哪|多少|状态|status|stat|情况", re.I)

# 要读但没说读哪个 → 列清单，别让 LLM 去猜一个地址
_READ_ANY_RE = re.compile(
    r"(读|看|查).{0,3}(寄存器|地址)|寄存器.{0,3}(值|多少|读)"
    # "读一下 GPIOB"：报了端口名、没报寄存器名，也没有"多少/什么值"。
    # ⚠ 必须要求**出现读动作**：光说 "GPIOB 是什么" 不算读取请求。
    r"|(读|看|查|read).{0,6}gpio\s*[a-k]\b(?!\s*(?:的\s*)?(?:moder|otyper"
    r"|ospeedr|pupdr|idr|odr|bsrr|lckr|afrl|afrh))", re.I)

# 寄存器读取："GPIOB 的 IDR 是多少" / "读 40020014"
#   ⚠ 端口和寄存器名**分开匹配**。别写成 `gpio\s*([a-k])\b(?:\s*(?P<reg>...))?`：
#     那样 "GPIOB 的 IDR" 在 "GPIOB" 处就匹配成功（b 后面是 \b），reg 组恒为
#     None，结果问哪个寄存器都回 ODR 的地址 —— 实测踩过。
_REG_READ_RE = re.compile(r"gpio\s*(?P<port>[a-k])\b|\b(?P<addr>[0-9a-f]{8})\b", re.I)
_REG_NAMES_RE = re.compile(
    r"(?P<reg>moder|otyper|ospeedr|pupdr|idr|odr|bsrr|lckr|afrl|afrh)\b", re.I)
# 寄存器偏移（端口基址 + 偏移），照 Core/Src/reg_shell.c 的白名单。
# 不在表里的名字只读基址 4 个字，不假装知道偏移。
_REG_OFFSETS = {
    "MODER": 0x00, "OTYPER": 0x04, "OSPEEDR": 0x08, "PUPDR": 0x0C,
    "IDR": 0x10, "ODR": 0x14, "BSRR": 0x18, "LCKR": 0x1C,
    "AFRL": 0x20, "AFRH": 0x24,
}

_TXT_LINE_RE = re.compile(r"(?:第\s*(\d)\s*行|(\d)\s*行|line\s*(\d))", re.I)

# LED 闪烁：默认 5 次、半周期 200ms、结束时回到灭。
# ⚠ 「回到灭」不是随手选的：闪完停在亮，用户下次看灯就分不清"这是闪完留下的
#   状态"还是"本来就这样"。回到灭让这条命令**幂等** —— 执行前后板子状态一样。
_LED_BLINK_DEFAULT_TIMES = 5
_LED_BLINK_DEFAULT_PERIOD = 0.2
LED_BLINK_MAX_TIMES = 50            # 上限：别让一句话占住板子几十秒
LED_BLINK_MIN_PERIOD = 0.05


def _led_blink_plan(low: str, text: str) -> Plan:
    """把"闪一下灯"翻译成**真正的 LED 命令序列**，而不是播动画。"""
    # ⚠ 只有**紧跟"灯"字的那个数字**有歧义：它可能是灯号，也可能是次数。
    #   踩过两次，方向相反：
    #     "闪灯 10 次"  → 只吃下 "1" 丢下 "0" → 误判 DS1（该是默认 DS0）
    #     "闪灯 1 次"   → 吃下 "1"             → 误判 DS1（该是默认 DS0，闪 1 次）
    #   判据：**灯号后面既不能跟数字，也不能跟量词**（次/下/遍/秒/毫秒）。
    #
    # ⚠ 而 "DS1" / "LED1" 是**明确的灯号声明**，后面的 "3 次" 是次数，
    #   两个分支绝不能共用同一条排除规则 —— 我第一版就是这么写坏的：
    #   "闪 DS1 3 次" 因为 1 后面跟了空格+3 而被整条否掉，退回默认 DS0。
    #   所以：带 ds/led 前缀的直接认，裸"灯"才走歧义判断。
    _AMBIG_TAIL = r"(?!\s*(?:\d|次|下|遍|秒|毫秒|ms))"
    m = (re.search(r"(?:led|ds)\s*([01])(?!\d)", low)          # DS1 / LED1：明确
         or re.search(r"灯\s*([01])" + _AMBIG_TAIL, low))       # 灯1 / 灯 1：要判
    num = m.group(1) if m else "0"

    times = _LED_BLINK_DEFAULT_TIMES
    period = _LED_BLINK_DEFAULT_PERIOD

    tm = re.search(r"([\d]+)\s*(?:次|下|遍)", low)
    if tm:
        times = max(1, min(LED_BLINK_MAX_TIMES, int(tm.group(1))))
    else:
        # 没说次数但说了总时长："闪2秒" → 按半周期折算次数
        sm = re.search(r"([\d.]+)\s*秒", low)
        if sm and float(sm.group(1)) > 0:
            times = max(1, min(LED_BLINK_MAX_TIMES,
                               int(float(sm.group(1)) / (2 * period)) or 1))

    pm = re.search(r"(?:间隔|每隔|每)\s*([\d.]+)\s*(?:毫秒|ms)", low)
    if pm:
        period = max(LED_BLINK_MIN_PERIOD, float(pm.group(1)) / 1000.0)

    return _plan("led_blink",
                 {"index": int(num), "times": times, "period": period},
                 by="rule#led",
                 why="LED 闪烁：DS%s %d 次，间隔 %dms"
                     % (num, times, int(period * 1000)))


# 规则层返回 (Plan, 命中的规则名) 或者 None（交给 LLM）
RuleHit = Optional[Plan]


def _rule(s: str) -> RuleHit:
    """s 已经小写化。返回 None 表示这条规则不认。"""
    return None


def match_rules(text: str) -> RuleHit:
    """规则层：确定性的关键词匹配。命中就返回 Plan，没命中返回 None。"""
    s = text.strip()
    low = s.lower()

    # ---- 屏幕电源：ON/OFF/CLR/FILL/INIT ----
    # ⚠ 排障类说法**不在这里**收口（放在下面屏幕命令之后）。踩过的坑：
    #   原先排障在最前面，把"屏幕没亮"整段抢走返回 OLED INIT，于是
    #   "刷屏卡不卡"（含"卡"→不动了）和"屏幕没亮，帮我开屏"（含"没亮"）
    #   全被判成排障。**用户说的是"开屏"就照开屏，别替他决定要不要重置。**

    # ⚠ 顺序：清屏 → 关屏 → 开屏 → 全亮 → INIT。
    #   "黑屏" 归**清屏**（用户说黑屏通常想擦干净画面）；要真熄屏说"关屏"。
    if re.search(r"清屏|清空屏|屏幕.{0,4}干净|黑屏|erase|清除", low):
        return _plan("cmd", "OLED CLR", by="rule#screen", why="清屏")
    if re.search(r"(关|熄|黑).{0,4}屏|屏.{0,4}(关掉|关了|熄灭)|off\s*屏", low):
        return _plan("cmd", "OLED OFF", by="rule#screen", why="关屏")
    # ⚠ 动词和"屏"字**必须在同一侧紧挨着**，不能写成 `(开|亮).{0,3}屏` 或
    #   `(开|亮)(屏幕|屏)?` 这种宽正则 —— 前者会把 "板子上的灯亮一下" 里的
    #   "亮...一下" 当成开屏，后者更糟：`(屏幕|屏)?` 是可选的，等于
    #   **裸的"打开/亮"也算开屏**，于是 "把灯打开"、"开灯" 全被判成 OLED ON。
    #   实测被自测集当场抓到。判屏必须要求"屏"字出现在两者之一的位置。
    if re.search(r"开 ?屏|亮 ?屏|点亮屏幕?"
                 r"|(唤醒|打开|点亮|亮起|亮一下)(了)?(屏幕?|屏)$"
                 r"|(屏幕?|屏).{0,4}(打开|点亮|亮起来|亮一下|唤醒|亮了)", low):
        return _plan("cmd", "OLED ON", by="rule#screen", why="开屏")
    if re.search(r"全亮|fill|整屏都亮", low):
        return _plan("cmd", "OLED FILL", by="rule#screen", why="全亮")
    if re.search(r"重新初始化|重init|re-?init|\binit\b", low):
        return _plan("cmd", "OLED INIT", by="rule#screen", why="重新初始化屏幕")

    # ---- 排障：只管"没有对应命令"的说法 ----
    # ⚠ 这里返回的是**可执行的下一步**（OLED INIT），不是一句提示。踩过的坑：
    #   早先返回 action=None + why="先发 OLED INIT…" —— 前端只能显示"没听懂"
    #   加一句建议，用户还得自己再打一遍。**建议本身就是一条命令**，
    #   该直接给出来让他点确认，而不是把活推回给用户。
    #   选 INIT 不选清屏：屏可能是被别的帧画满了，INIT 重走初始化并清屏，
    #   两种情况都覆盖；清屏只覆盖后者。
    #   _ASK_INFO_RE 挡掉"卡不卡/亮不亮/还在吗"这类**只读询问** ——
    #   宁可漏判掉到 LLM，也不能让用户问一句就把屏重置了。
    if (_TROUBLE_RE.search(low)
            and not re.search(r"灯|led|网络|网口|ping", low)
            and not _ASK_INFO_RE.search(low)):
        if re.search(r"没亮|不亮|不显示|黑|白", low):
            why = ("屏幕像是没亮。下一步：重新初始化屏幕并清屏（OLED INIT）；"
                   "还不行就发 OLED ON 开显示，或运行 python agent.py --check "
                   "看板子还在不在")
        else:
            why = "屏幕内容不对。下一步：重新初始化屏幕并清屏（OLED INIT）"
        return _plan("cmd", "OLED INIT", by="rule#trouble", raw=text, why=why)

    # ---- "要读，但没说读哪个" → 列清单 ----
    # ⚠ 放在寄存器规则**之前**：否则 "读一下寄存器" 会掉到 LLM，
    #   而 LLM 面对"差一个参数"的请求只会猜一个地址 —— 猜错比不猜更糟。
    if _READ_ANY_RE.search(low):
        return _plan("cmd", "HELP", by="rule#reg_any",
                     why="没说读哪个寄存器，先把能读的列出来：GPIOA~GPIOK 的 "
                         "MODER/OTYPER/OSPEEDR/PUPDR/IDR/ODR，"
                         "或者说 \"读一下 GPIOB 的 ODR\"")

    # ---- 寄存器读取：说端口名 → 自动算地址 ----
    # 地址映射照抄 Core/Src/reg_shell.c 的白名单：
    #   GPIOA..GPIOK = 0x40020000 起，每个端口 0x400；ODR 在端口基址 + 0x14。
    # ⚠ 只在**出现读动作**或**说了寄存器名**时才出命令，否则
    #   "GPIOB 是什么" 这种纯名词也会被当成读取请求。
    # ⚠ 写操作不能被这里截走："W 40023800 0" 里也有 8 位地址，
    #   它必须走到 _plan 里被 validate_cmd 拦成"RCC 只读"。
    m = _REG_READ_RE.search(low)
    if m and not re.search(r"\bw\b|\bwb\b|写|改|设|置设置|清|write|set", low):
        port = (m.group("port") or "").upper()
        addr_hex = (m.group("addr") or "").lower()
        rn = _REG_NAMES_RE.search(low)
        reg = (rn.group("reg") or "").upper() if rn else ""
        want_read = bool(re.search(r"读|看|查|多少|多少位|什么值|what|read", low))
        # 端口名后面跟了个**不认识的寄存器词**：只读基址 4 个字，别假装知道偏移
        stray = port and not reg and re.search(
            r"gpio\s*" + port.lower() + r"\s*(?:的\s*)?(?!的|是|在|有|为)([a-z]{3,})\b",
            low)
        if addr_hex or (port and (reg or want_read)):
            if addr_hex:
                addr = int(addr_hex, 16)
                count = 1
                label = "0x%08X" % addr
            else:
                base = 0x40020000 + (ord(port[-1]) - ord("A")) * 0x400
                if stray:
                    addr = base
                    count = 4
                    label = ("GPIO%s 基址 0x%08X（不认识寄存器 \"%s\"，只读前 4 个 "
                             "32 位字，列表见 HELP）" % (port[-1], addr, stray.group(1)))
                else:
                    off = _REG_OFFSETS.get(reg, 0x14)   # 没点名就默认 ODR
                    addr = base + off
                    count = 1
                    label = "GPIO%s %s(0x%08X)" % (port[-1], reg or "ODR", addr)
            return _plan("cmd", "R %08x %d" % (addr, count), by="rule#reg",
                         why="读 %s" % label,
                         extra={"addr": addr, "port": port[-1:] or None,
                                "reg": reg or None, "count": count})

    # ---- LED：必须带"灯"，否则"开车"会被当成开灯 ----
    if re.search(r"灯|led|led0|led1|ds[01]", low):
        # ⚠ 顺序原则：**先判"要做什么"，再判"是哪一盏"**。
        #   反过来（先判"这算不算 LED 请求"、再逐个判动作）就会踩坑：
        #   "在吗，在就闪DS0的灯" —— "闪"写在灯名前面，早先的代码在
        #   灯名分支里才去找"闪"，于是闪灯被漏掉、掉到后面的探活规则，
        #   最后变成"anim eyes"（屏幕上的眼睛）。**词序变了，语义没变。**
        # "亮不亮" 是查询，但里面也含"亮"，所以必须放在开灯判断之前
        if re.search(r"亮不亮|是不是亮的", low):
            return _plan("cmd", "LED", by="rule#led", why="查看 LED 状态")
        # "灯的状态" 也是查询
        if re.search(r"状态|什么颜色|查询|查一下", low):
            return _plan("cmd", "LED", by="rule#led", why="查看 LED 状态")
        # 闪/呼吸/跑马：这是**写操作**（要反复发 LED 命令），不是播动画。
        # 早先回退成 anim eyes，用户看到的是一双眼睛在屏幕上眨，莫名其妙。
        if re.search(r"闪|呼吸|交替|轮流|渐亮|跑马|blink", low):
            return _led_blink_plan(low, text)
        m = re.search(r"(?:led|ds)\s*([01])|灯\s*([01])", low)
        num = (m.group(1) or m.group(2)) if m else "0"
        # ⚠ "打开/点亮" 里也含"关/灭/熄"吗？不含。但"关闭"含"闭"，
        #   "不亮"含"亮" —— 所以先判关、再判开，且"不亮"在关里。
        if re.search(r"关|灭|熄|off|不亮", low):
            return _plan("cmd", "LED %s 0" % num, by="rule#led", why="关灯")
        if re.search(r"开|亮|点|on", low):
            return _plan("cmd", "LED %s 1" % num, by="rule#led", why="开灯")
        return None     # 提到灯但没说干什么 —— 别猜

    # ---- 探活 / 状态查询 ----
    if re.search(r"\bping\b|在吗|在不在|活着|还在|在线|通不通|连得上", low):
        return _plan("query", "PING", by="rule#query", why="探活")
    if re.search(r"帧统计|丢包|丢帧|乱序|收了多少帧", low):
        return _plan("query", "FB?", by="rule#query", why="帧统计")
    if re.search(r"刷屏|卡不卡|oled\s*stat|刷得怎么", low):
        return _plan("query", "OLED STAT", by="rule#query", why="刷屏状态")
    if re.search(r"帮助|怎么用|有哪些命令|help", low):
        return _plan("query", "HELP", by="rule#query", why="命令表")
    if re.search(r"信息|状态|版本|ip|地址|详情", low):
        return _plan("query", "INFO", by="rule#query", why="板子信息")

    # ---- 直接就是一条板子命令：以命令名开头的原样透传 ----
    # 判据是"命令表里认这个名字"，**不是**"有没有空格" —— "LED"、"INFO"、
    # "FB?" 这些单 token 命令同样要能透传。
    toks = s.split()
    head = toks[0].upper() if toks else ""
    if head in FIRMWARE_CMDS:
        cmd = s.upper()
        bad = validate_cmd(cmd)
        if bad:
            return _plan(None, cmd, by="rule#raw", why=bad)
        return _plan("query" if head in READONLY_CMDS else "cmd",
                     cmd, by="rule#raw", why="命令直通")

    # ---- 只渲染不发板子 ----
    if re.search(r"不发板子|别发|只看|先看|渲染一帧|预览|保存成图|png|截图", low):
        return _plan("render", None, by="rule#render", why="只渲染不发送")

    # ---- 内置动画 ----
    # ⚠ 裸名词（"汽车"）在真人对话里几乎都是别的意思（"我在汽车站"），
    #   所以**裸名词不认**，要求带一个"播放类"动词。宁可漏给 LLM，
    #   也别把闲聊当成点播动画 —— 后者用户会以为系统在乱动。
    #   注意"显示/看看"不算：它们是显示文字类需求的动词，归 TXT 那条。
    if re.search(r"播|放|来点|来段|来个|来只|来匹|动画|演示|演一下|显示", low):
        for pat, name, label in _ANIM_WORDS:
            if re.search(pat, low):
                # ⚠ 用户说了"播 10 秒"就得播 10 秒。规则层已经认出参数了，
                #   丢掉它等于逼用户再输一遍。只认常见的两种：秒数、倍速。
                extra = {}
                sec = re.search(r"([\d.]+)\s*秒", low)
                if sec:
                    extra["seconds"] = float(sec.group(1))
                spd = re.search(r"([\d.]+)\s*倍速", low)
                if spd:
                    extra["speed"] = float(spd.group(1))
                return _plan("anim", name, by="rule#anim",
                             why="内置动画：%s" % label, **extra)

    # ---- OLED 文本 ----
    m = re.search(r"(?:写|显示|显示|来句|打).{0,4}[\"\u201c'](.+?)[\"\u201d']", s)
    if m:
        line_m = _TXT_LINE_RE.search(s)
        line = int(line_m.group(1) or line_m.group(2) or line_m.group(3)) if line_m else 0
        return _plan("cmd", "OLED TXT %d %s" % (line, m.group(1).upper()),
                     by="rule#txt", why="在 OLED 上写文本",
                     needs_confirm_=True)

    return None


# ---------------------------------------------------------------------------
# 第 ② 层：LLM
#
# 只在规则层没命中时调用。LLM 只准输出 JSON，我们负责校验。
# 为什么不让 LLM 直接调工具：错误会一路传到板子上。先校验，错就拒。
# ---------------------------------------------------------------------------

DISPATCH_PROMPT = """你是一个指令分派器。把用户的一句话翻译成一条 JSON 指令。

只输出 JSON，不要 markdown，不要解释。格式：

{"action": "<六选一>", "arg": <字符串或null>, "confidence": <0到1的数字>}

六种 action：
  anim      播内置动画，arg 是动画名，只能取：%(anim_names)s
  cmd       给板子发一条命令，arg 是命令原文（全大写）
  query     查看状态，arg 只能是：%(query_cmds)s
  knowledge 从知识库取内容（目前还没有知识库，arg 填科目名）
  draw      让 LLM 现写一段画图代码，arg 是重新组织过的画面描述
  render    只渲染一帧看看效果，不发板子，arg 为 null
  led_blink 让板载 LED 闪几下（会真的发 LED 命令），arg 为对象：
            {"index": 0或1, "times": 次数, "period": 半周期秒数}

板子支持的完整命令（只能从这里面挑，编造的一律无效）：
%(firmware)s

规则：
  1. 用户说法太模糊、或者跟控制板子/显示内容无关（问天气、讲笑话、闲聊），
     输出 {"action": null, "arg": null, "confidence": 0}。**不要瞎猜。**
  2. 读写寄存器的命令一律 action=cmd，不要把地址换算成别的格式。
  3. arg 里的命令必须逐字来自上面的命令表。
""" % {
    "anim_names": ", ".join(sorted(anim.ANIMS)),
    "query_cmds": ", ".join(sorted(QUERY_ONLY)),
    "firmware": " / ".join(FIRMWARE_CMDS),
}


def ask_llm_for_plan(text: str, explain: Optional[List[str]] = None,
                     timeout: float = 30.0) -> RuleHit:
    """
    问一次 LLM，拿回 Plan。失败/不合格一律返回 None（= 拒绝）。

    explain 不为 None 时，往里面塞全过程，供 --explain 打印。
    """
    import urllib.error
    import urllib.request

    log = explain if explain is not None else []
    try:
        cfg = agent._llm_config()
    except agent.LLMError as e:
        log.append("LLM 不可用：%s" % e)
        return None

    url = agent._chat_url(cfg["base"])
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": DISPATCH_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    log.append("POST %s  model=%s  temperature=0" % (url, cfg["model"]))

    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["key"]},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        raw = payload["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.append("调用失败：%s: %s" % (type(e).__name__, e))
        return None

    raw = agent._strip_code_fence(raw)
    log.append("LLM 原始返回：%s" % raw.strip()[:300])
    return _parse_llm_json(raw, text, log)


def _parse_llm_json(raw: str, text: str, log: List[str]) -> RuleHit:
    """把 LLM 的 JSON 变成 Plan，并且**逐字段校验**。任何一步不过就拒绝。"""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # 模型偶尔在 JSON 前后加废话，只取第一个 { 到最后一个 }
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b <= a:
            log.append("校验失败：不是 JSON")
            return None
        try:
            obj = json.loads(raw[a:b + 1])
        except json.JSONDecodeError:
            log.append("校验失败：不是 JSON")
            return None

    action = obj.get("action")
    arg = obj.get("arg")
    conf = obj.get("confidence", 0)

    if action is None:
        log.append("LLM 判定为无法分派（置信度 %s）" % conf)
        return None
    if action not in ACTIONS:
        log.append("校验失败：action=%r 不在 %s 里" % (action, ACTIONS))
        return None
    if action == "anim":
        if arg not in anim.ANIMS:
            log.append("校验失败：动画名 %r 不存在" % arg)
            return None
    if action in ("cmd", "query"):
        if not isinstance(arg, str) or not arg.strip():
            log.append("校验失败：cmd/query 缺少命令原文")
            return None
        bad = validate_cmd(arg)
        if bad:
            log.append("校验失败（命令白名单）：%s" % bad)
            return None
        if action == "query" and arg.upper() not in QUERY_ONLY:
            log.append("校验失败：%r 不是只读查询命令" % arg)
            return None
    if action == "draw" and not (isinstance(arg, str) and arg.strip()):
        log.append("校验失败：draw 缺少画面描述")
        return None
    if action == "led_blink":
        if not isinstance(arg, dict):
            log.append("校验失败：led_blink 的 arg 必须是对象")
            return None
        # 逐字段校验。LLM 可能给字符串、负数、超大次数 —— 一律夹到安全范围。
        try:
            idx = int(arg.get("index", 0))
            times = int(arg.get("times", _LED_BLINK_DEFAULT_TIMES))
            period = float(arg.get("period", _LED_BLINK_DEFAULT_PERIOD))
        except (TypeError, ValueError):
            log.append("校验失败：led_blink 参数不是数字")
            return None
        if idx not in (0, 1):
            log.append("校验失败：LED 编号只能是 0 或 1")
            return None
        arg = {"index": idx,
               "times": max(1, min(LED_BLINK_MAX_TIMES, times)),
               "period": max(LED_BLINK_MIN_PERIOD, min(2.0, period))}

    log.append("校验通过：action=%s arg=%r" % (action, arg))
    return _plan(action, arg, by="llm", why="LLM 分派（置信度 %s）" % conf)


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------

def _finalize(hit: Plan, text: str) -> Plan:
    """
    给 Plan 补上 raw / needs_confirm。

    ⚠ **needs_confirm 必须对每一条 cmd/query 都重算**，不能用 match_rules
    里随手写死的值。踩过一次：LED 规则返回的是 _plan("cmd", "LED 0 1")，
    _plan 默认 needs_confirm_=False，而 dispatch() 里又只用
    `if action == "cmd"` 去补 —— 结果 "把灯打开" 被判成只读、
    不加 --yes 就直接打到板子上了。安全相关的判断只能有一个出处。
    """
    hit["raw"] = text
    if hit["action"] in ("cmd", "query"):
        hit["needs_confirm"] = needs_confirm(hit["arg"] or "")
    elif hit["action"] == "led_blink":
        # 闪灯当然也是写操作。判据不写死 True，而是拿它最终要发的命令去问
        # needs_confirm —— 安全判断只有一个出处，这条也不例外。
        hit["needs_confirm"] = True
    else:
        hit["needs_confirm"] = False
    return hit


def dispatch(text: str, use_llm: bool = True,
             explain: Optional[List[str]] = None) -> Plan:
    """
    一句话 → 一条 Plan。

    规则层先跑；没命中才问 LLM；LLM 也不行就**明确拒绝**。
    能明确拒绝的系统，比"总是猜个结果"的系统好用 —— 后者出错时
    你都不知道错在哪一步。
    """
    text = (text or "").strip()
    log = explain if explain is not None else []

    if not text:
        p = _plan(None, None, by="", why="空输入", raw=text)
        p["needs_confirm"] = False
        return p

    hit = match_rules(text)
    if hit is not None:
        log.append("规则层命中")
        if hit["action"] == "cmd":
            bad = validate_cmd(hit["arg"] or "")
            if bad:
                return _plan(None, hit["arg"], by=hit["by"], why=bad, raw=text)
        return _finalize(hit, text)

    log.append("规则层未命中 → 交给 LLM")
    if not use_llm:
        return _plan(None, None, by="", why="规则层未命中，且 --no-llm", raw=text)

    hit = ask_llm_for_plan(text, log)
    if hit is None:
        return _plan(None, None, by="llm", raw=text,
                     why="无法确定要做什么（规则和 LLM 都没把握）"
                         " —— 换个说法，或明确说 \"播动画\"/\"清屏\"/\"开灯\"")
    return _finalize(hit, text)


# ---------------------------------------------------------------------------
# 执行器：把 Plan 变成"真的做了什么"
#
# ⚠ --yes 只针对 needs_confirm 的写操作。只读查询不需要确认。
# ---------------------------------------------------------------------------

def execute(plan: Plan, host: str, port: int, timeout: float,
            assume_yes: bool) -> int:
    """执行一条 Plan。返回进程退出码（0 成功）。"""
    action = plan["action"]
    if action is None:
        print("[dispatcher] 未执行：%s" % plan["why"])
        return 2

    # 不是写操作，直接跑
    if action in ("render",):
        print("[dispatcher] 下一步：agent.py --render ...  （阶段一只打印，不调用）")
        return 0
    if action in ("knowledge", "draw"):
        print("[dispatcher] action=%s 要到阶段三/现有 --code|描述 通道才能执行"
              % action)
        return 0

    if action == "led_blink":
        return _exec_led_blink(plan, host, port, timeout, assume_yes)

    cmd = plan["arg"] if action in ("cmd", "query") else None
    if cmd is None:
        print("[dispatcher] %s 的执行器还没接" % action)
        return 0

    if plan["needs_confirm"] and not assume_yes:
        print("[dispatcher] ⚠ 这是写操作，需要确认。确认后加 --yes：")
        print("            python dispatcher.py \"%s\" --yes" % plan["raw"])
        return 3

    with Board(host, port, timeout=timeout) as b:
        try:
            reply = b.send_text(cmd)
        except BoardError as e:
            print("[dispatcher] 板子没回包：%s" % e)
            return 1
    print("[dispatcher] → %s" % cmd)
    print("[board] %s" % reply.strip())
    return 0


def _exec_led_blink(plan: Plan, host: str, port: int, timeout: float,
                    assume_yes: bool) -> int:
    """
    真的让 LED 闪：连发 (开,关) × times 条 LED 命令。

    ⚠ 为什么不复用 `_cmd_play()` 那种"一次一条命令"的路子：
       固件没有"闪灯"这条命令，闪烁只能是 PC 端按时间发多条。
       这也是为什么 led_blink 要单独当一个 action —— 其它 action 都是**一条**指令。

    ⚠ 为什么放在**同一个 Board 会话**里循环：
       每次 `Board(...)` 都新建 socket、重新 bind 临时端口，5 次闪就 10 个 socket。
       一个 with 里循环又快又稳。

    ⚠ 结束时**一定要回到灭**：中途 Ctrl+C 也要走 finally。闪完停在一片亮灯
       会让用户分不清"这是闪完的状态"还是"本来就亮"。
    """
    arg = plan["arg"] or {}
    idx = int(arg.get("index", 0))
    times = int(arg.get("times", _LED_BLINK_DEFAULT_TIMES))
    period = float(arg.get("period", _LED_BLINK_DEFAULT_PERIOD))

    if plan["needs_confirm"] and not assume_yes:
        print("[dispatcher] ⚠ 这是写操作（会真的发 %d 条 LED 命令），需要确认。"
              % (times * 2))
        print("            确认后加 --yes：")
        print("            python dispatcher.py \"%s\" --yes" % plan["raw"])
        return 3

    on_cmd = "LED %d 1" % idx
    off_cmd = "LED %d 0" % idx
    print("[dispatcher] → 闪 DS%d %d 次，间隔 %dms（共 %d 条命令，约 %.1f 秒）"
          % (idx, times, int(period * 1000), times * 2, times * period * 2))

    last_reply = ""
    with Board(host, port, timeout=timeout) as b:
        try:
            for i in range(times):
                try:
                    last_reply = b.send_text(on_cmd)
                    time.sleep(period)
                    b.send_text(off_cmd)
                    time.sleep(period)
                except BoardError as e:
                    print("[dispatcher] 第 %d 次闪烁时板子没回包：%s" % (i + 1, e))
                    return 1
                print("  %d/%d  %s" % (i + 1, times, last_reply.strip()[:40]))
        except KeyboardInterrupt:
            print("\n[dispatcher] 中断，把灯恢复成灭")
            return 130
        finally:
            # 无论如何都别把灯留在亮的状态
            try:
                b.send_text(off_cmd)
            except Exception:
                pass
    print("[dispatcher] ✅ 闪完了，灯已恢复成灭")
    return 0


# ---------------------------------------------------------------------------
# 日志与自测
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(_HERE, "dispatch_log.jsonl")


def log_plan(plan: Plan, executed: bool) -> None:
    """
    追加一行 jsonl。**这是能不能相信这个系统的唯一证据**：
    出问题能查出是规则错了还是模型错了。
    """
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "raw": plan.get("raw", ""),
        "action": plan.get("action"),
        "arg": plan.get("arg"),
        "by": plan.get("by"),
        "needs_confirm": plan.get("needs_confirm", False),
        "executed": executed,
        "why": plan.get("why", ""),
    }
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass    # 日志写不进去不该阻断主流程


CASES_PATH = os.path.join(_HERE, "dispatch_cases.jsonl")


def load_cases(path: str = CASES_PATH) -> List[Dict[str, Any]]:
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(json.loads(line))
    return cases


def run_tests(use_llm: bool = False, verbose: bool = False) -> int:
    """
    跑自测集。

    规则层必须 100% 通过 —— 它是确定性的，过不了就是规则写错了。
    LLM 层只统计通过率（模型有随机性，不能当硬门槛）。
    """
    cases = load_cases()
    rule_total = rule_pass = 0
    llm_total = llm_pass = 0
    failures: List[Tuple[str, str, Any, Any]] = []
    rule_unresolved: List[str] = []

    for c in cases:
        raw = c["raw"]
        want_action = c.get("action")
        want_arg = c.get("arg")

        # ---- 只看规则层 ----
        hit = match_rules(raw)
        if hit is not None:
            rule_total += 1
            got_action = hit["action"]
            got_arg = hit["arg"]
            ok = (got_action == want_action
                  and (want_arg is None or got_arg == want_arg))
            if ok:
                rule_pass += 1
            else:
                failures.append((raw, "rule", (want_action, want_arg),
                                 (got_action, got_arg)))
        else:
            rule_unresolved.append(raw)

        # ---- 规则接不住的，必须**期望被拒绝**（除非开了 --llm 重新评） ----
        if hit is None and want_action is not None:
            failures.append((raw, "rule-miss", (want_action, want_arg), None))
            rule_total += 1

        if use_llm:
            plan = dispatch(raw, use_llm=True)
            llm_total += 1
            ok = plan["action"] == want_action and (
                want_arg is None or plan["arg"] == want_arg)
            if ok:
                llm_pass += 1
            elif verbose:
                print("  [llm 未过] %-24s 期望 %r/%r  得到 %r/%r"
                      % (raw, want_action, want_arg,
                         plan["action"], plan["arg"]))
        else:
            plan = dispatch(raw, use_llm=False)

        # ---- 安全属性：每条给出的 cmd 都必须算过 needs_confirm ----
        # 踩过："把灯打开" 因为 needs_confirm 没重算，不加 --yes 就直接执行了。
        if plan["action"] in ("cmd", "query"):
            rule_total += 1
            expect = needs_confirm(plan["arg"] or "")
            if plan["needs_confirm"] == expect:
                rule_pass += 1
            else:
                failures.append((raw, "needs_confirm", expect,
                                 plan["needs_confirm"]))

    print("\n[dispatcher] 自测集：%d 条" % len(cases))
    print("  规则层：%d/%d 通过（必须 100%%）" % (rule_pass, rule_total))
    if rule_unresolved:
        print("  规则层未命中（将交给 LLM）：%d 条" % len(rule_unresolved))
        if verbose:
            for r in rule_unresolved:
                print("    - %s" % r)
    if use_llm:
        print("  LLM 层：%d/%d 通过" % (llm_pass, llm_total))

    if failures:
        print("\n  失败明细：")
        for raw, kind, want, got in failures[:20]:
            print("    [%s] %-22s 期望 %r  得到 %r" % (kind, raw, want, got))

    return 0 if not failures else 1


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dispatcher",
        description="把一句话翻译成一条可审计的板子指令（只翻译，不猜）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""例子：
  python dispatcher.py "把灯打开"                只打印指令，不执行
  python dispatcher.py "把灯打开" --yes           真发出去
  python dispatcher.py "把这块屏弄干净点"         规则接不住 → 交给 LLM
  python dispatcher.py "把灯打开" --explain       看分派全过程
  python dispatcher.py --test                    跑自测集（不碰板子/LLM）
""")
    ap.add_argument("text", nargs="*", help="你说的一句话")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--yes", "-y", action="store_true",
                    help="确认执行写操作（不分 --yes 就只打印指令）")
    ap.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    ap.add_argument("--explain", "-x", action="store_true", help="打印分派全过程")
    ap.add_argument("--no-llm", action="store_true", help="只用规则层")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="只翻译不执行（默认行为，显式列出方便脚本用）")
    ap.add_argument("--test", action="store_true", help="跑自测集")
    ap.add_argument("--llm", action="store_true", help="--test 时连 LLM 层一起测")
    ap.add_argument("--verbose", "-v", action="store_true")

    args = ap.parse_args(argv)

    if args.test:
        return run_tests(use_llm=args.llm, verbose=args.verbose)

    text = " ".join(args.text)
    if not text:
        ap.print_help()
        return 1

    explain: List[str] = []
    plan = dispatch(text, use_llm=not args.no_llm,
                    explain=explain if args.explain else None)

    if args.json:
        out = {k: plan.get(k) for k in
               ("raw", "action", "arg", "by", "needs_confirm", "why")}
        if plan.get("warn"):
            out["warn"] = plan["warn"]
        print(json.dumps(out, ensure_ascii=False))
        rc = 0 if plan["action"] is not None else 2
        log_plan(plan, executed=False)
        return rc

    if args.explain:
        for line in explain:
            print("  | %s" % line)
        print()

    if plan["action"] is None:
        print("  ✗ 无法分派")
        print("    原因：%s" % plan["why"])
        log_plan(plan, executed=False)
        return 2

    risk = ("只读" if not plan["needs_confirm"]
            else ("写寄存器 ⚠" if _is_reg_write(plan) else "写操作"))
    if plan["action"] == "led_blink":
        arg = plan["arg"] or {}
        print("  理解：led_blink DS%s %s 次"
              % (arg.get("index", 0), arg.get("times")))
    else:
        print("  理解：%s %s" % (plan["action"],
                                 "" if plan["arg"] is None else plan["arg"]))
    print("  来源：%s   %s" % (plan["by"], risk))
    if plan.get("warn"):
        print("  注意：%s" % plan["warn"])

    executed = (args.yes and not args.dry_run) or (
        not plan["needs_confirm"] and not args.dry_run
        and plan["action"] in ("cmd", "query", "led_blink"))
    rc = execute(plan, args.host, args.port, args.timeout, args.yes)
    log_plan(plan, executed=executed)
    return rc


def _is_reg_write(plan: Plan) -> bool:
    # ⚠ arg 不一定是字符串：led_blink 的 arg 是 dict。早先这里直接 .strip()，
    #   遇到 dict 就 AttributeError —— 而这条路径只在"要显示风险等级"时才走，
    #   --json 分支碰不到它，所以自测集和 JSON 测试全都漏掉了。
    arg = plan.get("arg")
    if not isinstance(arg, str):
        return False
    toks = arg.strip().upper().split()
    return bool(toks) and toks[0] in REG_WRITE_CMDS


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (SandboxError, agent.LLMError) as e:
        print("\n[dispatcher] 出错：%s" % e, file=sys.stderr)
        sys.exit(2)
