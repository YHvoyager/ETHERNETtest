# -*- coding: utf-8 -*-
"""
sandbox.py —— 让「别人写的」渲染代码安全地跑起来。

【为什么需要沙箱】

这个工程最终形态是：用户对 LLM 说「显示一只打哈欠的猫」，LLM 现写一段
draw(c, t, p) 的代码，PC 端执行它，把帧发给板子。

也就是说 —— **执行一段由模型生成的、我们没看过的代码**。如果不加限制，
那段代码可以：

    import os; os.system("format C:")        # 删盘
    open("C:/Windows/...", "w")              # 改系统文件
    socket.socket().connect(...)             # 把数据发到外面
    while True: pass                          # 卡死你的电脑

所以必须沙箱。但要说清楚**这个沙箱的定位**：

    ⚠ 它防的是「模型写错代码」和「模型被提示注入」，不是防有备而来的攻击者。
      真正的攻击者能绕过纯 Python 的沙箱（比如通过 __subclasses__ 找
      file 对象）。你已经在本机跑 LLM 了，信任边界本来就在本机。

    它的真正价值：让"手滑"的代价从"删掉文件"降到"报个错"。
    做正确的事：限制 import、限制名字、加超时、别把 board 传进去。

【三道闸门】

    闸门 1  import 白名单 —— 只能 import math / random / canvas 这几个。
            用 __builtins__ 里换掉的 __import__ 实现。

    闸门 2  名字白名单 —— exec 的 globals 里只有画图 API，没有 open、
            eval、__import__、os、sys。连 dir() 都给了个安全的版本。

    闸门 3  超时 —— 在子线程里跑，超过时限就放弃这一帧。
            （Python 没法强杀线程，所以是"放弃等待"而不是"终止执行"。
              实践中够用：一帧渲染超过 1 秒本身就是 bug。）

最要紧的一条：**画布对象传进去，板子对象绝不传进去**。
LLM 的代码碰得到 Canvas，但碰不到 Board —— 它改不了 I2C、发不了包、
也读不到你的文件。
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional, Tuple

from canvas import Canvas

# 允许 import 的模块名 -> 实际模块对象
_ALLOWED_IMPORTS = ("math", "random")

# 允许出现在代码里的内置函数（少得可怜，是故意的）
_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "round": round,
    "int": int, "float": float, "bool": bool, "str": str,
    "len": len, "range": range, "enumerate": enumerate,
    "list": list, "tuple": tuple, "dict": dict, "set": set,
    "sum": sum, "sorted": sorted, "zip": zip, "map": map, "filter": filter,
    "True": True, "False": False, "None": None,
    "print": lambda *a, **k: None,   # 吞掉输出，别刷屏
}


class SandboxError(RuntimeError):
    """渲染代码本身有问题（语法错、用了禁用的东西、跑太久）。"""


def _guarded_import(name: str, globals_=None, locals_=None,
                    fromlist=(), level: int = 0) -> Any:
    """
    替换掉的 __import__。

    只放行 math / random。注意 fromlist：`from math import sin` 走的
    也是这里，name 会是 "math"，所以判据用顶层名。
    """
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORTS:
        raise SandboxError(
            "渲染代码不允许 import %r。可用的只有：%s"
            % (name, ", ".join(_ALLOWED_IMPORTS))
        )
    return __import__(name, globals_, locals_, fromlist, level)


def _make_globals() -> Dict[str, Any]:
    """
    给渲染代码准备的全局命名空间。

    里面有：允许的内建函数、__import__（受限）、__name__。
    没有：open / eval / exec / compile / globals / vars / dir / input。
    """
    import math
    import random

    g: Dict[str, Any] = {
        "__builtins__": dict(_SAFE_BUILTINS),
        "__name__": "__oled_anim__",
        "math": math,
        "random": random,
    }
    # 把受限的 import 塞进去
    g["__builtins__"]["__import__"] = _guarded_import

    # 常用数学函数直接摆到顶层，省得模型每次写 math.sin
    for fn in ("sin", "cos", "tan", "sqrt", "pi", "atan2", "hypot",
               "floor", "ceil", "radians", "degrees"):
        g[fn] = getattr(math, fn)
    g["randint"] = random.randint
    g["uniform"] = random.uniform
    return g


def compile_draw(code: str, func_name: str = "draw") -> Callable:
    """
    把源码编译成可调用的 draw 函数。

    期望的代码形态（也是最省事的形态）：

        def draw(c, t, p):
            c.circle(64, 32, 20, True, fill=True)

    编译期就检查：语法对不对、函数在不在、参数列表长不长。
    这些都在沙箱外面做 —— 编译本身不执行代码，是安全的。

    返回 (draw_fn, globals_dict)。
    """
    g = _make_globals()
    try:
        compiled = compile(code, "<llm_anim>", "exec")
    except SyntaxError as e:
        raise SandboxError("语法错误：%s（第 %s 行）" % (e.msg, e.lineno)) from None

    # exec 定义函数本身不危险：执行的是 def 语句，函数体要等调用才跑。
    try:
        exec(compiled, g)
    except SandboxError:
        raise
    except Exception as e:
        raise SandboxError("执行顶层代码出错：%s: %s" % (type(e).__name__, e)) from None

    fn = g.get(func_name)
    if fn is None:
        raise SandboxError("代码里没有定义 def %s(c, t, p)" % func_name)
    if not callable(fn):
        raise SandboxError("%s 不是函数" % func_name)

    import inspect
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None
    if sig is not None and len(sig.parameters) < 3:
        raise SandboxError(
            "def %s 需要三个参数 (c, t, p)，当前只有 %d 个"
            % (func_name, len(sig.parameters))
        )

    return fn, g


class Renderer:
    """
    一个沙箱渲染器：拿着一段代码，反复渲染不同时刻的帧。

    用法：
        r = Renderer(code)
        frame = r.render(t=1.5, params={"speed": 2.0})   # 1024 字节
    """

    def __init__(self, code: str, func_name: str = "draw",
                 timeout: float = 1.0) -> None:
        self.code = code
        self.func_name = func_name
        self.timeout = timeout
        self.fn, self.globals = compile_draw(code, func_name)

    def render_canvas(self, t: float,
                      params: Optional[Dict] = None) -> Canvas:
        """
        渲染一帧，返回 Canvas。

        超时用子线程实现。⚠ 超时后那个线程还在跑（Python 杀不掉），
        所以超时值不要设得太小，否则卡住的线程会越积越多。
        1 秒对 128x64 来说已经极其宽松（正常在 1 毫秒以内）。
        """
        c = Canvas()
        box: Dict[str, Any] = {}

        def _run() -> None:
            try:
                self.fn(c, float(t), params or {})
                box["ok"] = True
            except BaseException as e:  # noqa: BLE001 —— 沙箱里什么都可能抛
                box["err"] = "%s: %s" % (type(e).__name__, e)

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        th.join(self.timeout)

        if th.is_alive():
            raise SandboxError(
                "渲染超时（>%.1f 秒）。检查代码里有没有死循环，"
                "或者过大的 range()。" % self.timeout
            )
        if "err" in box:
            raise SandboxError("渲染时出错：%s" % box["err"])
        return c

    def render(self, t: float, params: Optional[Dict] = None) -> bytes:
        """渲染一帧，直接返回 1024 字节，可以丢给 Board.send_frame()。"""
        return self.render_canvas(t, params).pack()


# ---------------------------------------------------------------------------
# 自检：确认沙箱确实拦得住
# ---------------------------------------------------------------------------

def self_test() -> Tuple[int, int]:
    """
    跑一组攻击用例，返回 (拦住的个数, 总个数)。

    这个函数应该永远返回 (N, N)。如果某个用例没被拦住，
    说明沙箱漏了，得先修沙箱再让 LLM 写代码。
    """
    attacks = [
        ("import os",            "import os\n\ndef draw(c,t,p):\n    os.system('echo x')"),
        ("open 文件",            "def draw(c,t,p):\n    open('C:/tmp/x','w').write('a')"),
        ("eval",                 "def draw(c,t,p):\n    eval('1+1')"),
        ("exec",                 "def draw(c,t,p):\n    exec('x=1')"),
        ("__import__ 绕过",      "def draw(c,t,p):\n    __import__('os')"),
        ("无 draw 函数",         "x = 1"),
        ("语法错",               "def draw(c,t,p)\n    pass"),
        ("参数不够",             "def draw(c):\n    pass"),
        ("除零运行时错",         "def draw(c,t,p):\n    1/0"),
        ("死循环超时",           "def draw(c,t,p):\n    while True:\n        pass"),
    ]
    caught = 0
    for name, code in attacks:
        try:
            r = Renderer(code, timeout=0.3)
            r.render(0.0)
        except SandboxError:
            caught += 1
        except Exception as e:  # noqa: BLE001
            # 别的异常也算拦住了，但值得知道是什么
            caught += 1
        else:
            print("  [漏] %s" % name)
    return caught, len(attacks)


if __name__ == "__main__":
    ok, total = self_test()
    print("沙箱自检：%d/%d 拦住" % (ok, total))
