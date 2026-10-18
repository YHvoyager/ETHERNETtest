# -*- coding: utf-8 -*-
"""
api.py —— 「前端说人话」和「dispatcher 翻译出的指令」之间的 HTTP 层。

    浏览器 ──POST /dispatch──> api.py ──> dispatcher.dispatch()   （只翻译）
                                       └─> 生成一次性 token，**不执行**
    浏览器 ──POST /confirm───> api.py ──> 验 token ──> 真正执行

【本文件只做外壳，不重写任何判断】

分派（规则/LLM）在 dispatcher.py，执行在 dispatcher.execute()，
安全分级在 dispatcher.needs_confirm()。这里**一行策略都不复制** ——
判断只有一份，自测集才测得到真实的那一份。

【为什么确认用一次性 token，而不是服务端记住"待确认队列"】

服务端不存任何待确认状态。指令原文 + 随机 nonce + 过期时间被编进 token，
用本机密钥算 HMAC 签名。用户点"确认"时带着 token 回来，服务端验签、
验过期、验 nonce 没用过 —— 全部通过才执行。

  好处：重启不丢、多进程不会状态不一致、不存在"忘了清队列"导致旧指令被点火
  代价：token 能不能用只看签名和过期，服务端不记得它

nonce 只用于"同一个 token 点两次" —— 这是防手滑，不是防攻击者。

【为什么长任务要异步】

`led_blink` 闪 50 次要 20 秒。同步 HTTP 的话这 20 秒里服务不响应，
连状态栏都不刷新。所以提交后立刻返回 job_id，前端轮询 /job/<id>。

【为什么默认只听 127.0.0.1】

板子在 192.168.1.30，PC 在 192.168.1.100。若服务监听 0.0.0.0，
同一网段任何人打开 http://192.168.1.100:8765 都能点亮你的灯、发任意命令。
**默认安全，越权访问要显式 --host 0.0.0.0**。

【还有一层：Host 头校验】

只看 127.0.0.1 挡不住恶意网页 —— 你浏览器里的网页可以往 127.0.0.1 发请求
（DNS rebinding）。所以非 /healthz 的请求必须 Host 是 localhost/127.0.0.1，
否则 403。这挡的是"网页偷偷调你的板子"，不是"你自己访问"。

【用法】

    python api.py                                  # http://127.0.0.1:8765
    python api.py --host 0.0.0.0 --port 9000       # 局域网可访问（自行承担风险）
    python api.py --no-llm                         # 只用规则层
    python api.py --open                           # 起服务后自动开浏览器
    python api.py --selftest                       # 不开端口，直接测 HTTP 接口

    PING / dispatch 都走真实板子 192.168.1.30，只用 GET /healthz 可看板子状态。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import secrets
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import agent            # noqa: E402
import anim             # noqa: E402
import dispatcher       # noqa: E402
from proto import Board, BoardError, DEFAULT_HOST, DEFAULT_PORT  # noqa: E402
from sandbox import SandboxError  # noqa: E402

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

TOKEN_TTL = 120.0              # 确认 token 有效期（秒）。写操作等太久就该重说一遍
MAX_TEXT_BYTES = 8 * 1024      # 单次请求体上限，防手滑把整个文件 POST 进来
MAX_JOBS = 200                 # 内存里最多留多少个已完成 job（FIFO 淘汰）
SKIP_HOSTCHECK = ("/healthz",) # 不需要 Host 校验的路径

# 本机密钥：只在这台 PC 上有效，**不进版本库**。
# ⚠ 刻意不用环境变量/命令行传：那会出现在进程列表里，而且每次重启都要重新给。
KEY_PATH = os.path.join(_HERE, ".api_key")


def _load_or_create_key() -> bytes:
    """读本机密钥，没有就生成一个 32 字节随机的。"""
    if os.path.exists(KEY_PATH):
        raw = open(KEY_PATH, "rb").read().strip()
        if len(raw) >= 16:
            return raw
    raw = secrets.token_bytes(32)
    with open(KEY_PATH, "wb") as f:
        f.write(raw)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return raw


KEY = _load_or_create_key()


# ---------------------------------------------------------------------------
# 一次性 token
#
# 载荷是 base64url(JSON) + "." + base64url(HMAC-SHA256)。两个 base64 段。
# 选 JSON 而不是 "指令|时间" 这种拼串，是为了防止指令里出现分隔符时解析串位。
# ---------------------------------------------------------------------------

def _b64e(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    import base64
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(body: str) -> str:
    return _b64e(hmac.new(KEY, body.encode("ascii"), hashlib.sha256).digest())


def issue_token(plan: Dict[str, Any]) -> str:
    """
    给一条待确认的 Plan 发一张票。

    ⚠ 只把 **执行所必需** 的东西放进票里：raw / action / arg。
    不放 needs_confirm —— 它在验票时会用 dispatcher.needs_confirm() 重算，
    票里写什么都改变不了"这是不是写操作"。**安全判据不能由票自己声明。**
    """
    payload = {
        "raw": plan.get("raw", ""),
        "action": plan.get("action"),
        "arg": plan.get("arg"),
        "sub": plan.get("sub"),
        # ⚠ 把来源也带上。踩过：执行时日志里 by 记成 "confirm"，
        #   于是查日志看不出这条指令是规则翻译的还是 LLM 猜的 ——
        #   而"能追到是谁翻译的"正是这份日志存在的唯一理由。
        "by": plan.get("by", ""),
        "why": plan.get("why", ""),
        "nonce": secrets.token_hex(12),
        "exp": time.time() + TOKEN_TTL,
    }
    body = _b64e(json.dumps(payload, ensure_ascii=False,
                            sort_keys=True).encode("utf-8"))
    return body + "." + _sign(body)


def verify_token(token: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """验票。返回 (payload, 错误原因)。payload 为 None 表示不通过。"""
    if not token or not isinstance(token, str):
        return None, "缺少 token"
    parts = token.split(".")
    if len(parts) != 2:
        return None, "token 格式不对"
    body, sig = parts
    if not hmac.compare_digest(sig, _sign(body)):
        return None, "token 签名不对（可能被改过，或不是这台机器发的）"
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        return None, "token 内容损坏"
    if float(payload.get("exp", 0)) < time.time():
        return None, "token 已过期（%.0f 秒内有效），请重新说一遍" % TOKEN_TTL
    return payload, ""


class NonceStore:
    """记住用过的 nonce，同一个 token 第二次来直接拒。"""

    def __init__(self, ttl: float = TOKEN_TTL) -> None:
        self._lock = threading.Lock()
        self._used: Dict[str, float] = {}
        self._ttl = ttl

    def claim(self, nonce: str) -> bool:
        now = time.time()
        with self._lock:
            # 顺手清掉过期的，不给它无限长大
            for k in [k for k, t in self._used.items() if t < now]:
                self._used.pop(k, None)
            if nonce in self._used:
                return False
            self._used[nonce] = now + self._ttl
            return True


NONCES = NonceStore()


# ---------------------------------------------------------------------------
# 执行
#
# ⚠ 为什么不直接调 dispatcher.execute()：
#   它用 print() 输出、只返回退出码，拿不到板子的回包正文。HTTP 需要回包文本。
#   但**安全判据仍然全部来自 dispatcher**（needs_confirm / validate_cmd），
#   这里只负责"发出去、把回包收回来"。判据一个字都没有重写。
# ---------------------------------------------------------------------------

def run_plan(plan: Dict[str, Any], host: str, port: int, timeout: float,
             report=None) -> Dict[str, Any]:
    """
    真执行。report(progress, note) 是可选进度回调（长任务用）。

    返回 {"ok": bool, "sent": [...], "reply": "...", "error": "..."}
    """
    action = plan.get("action")
    arg = plan.get("arg")
    out: Dict[str, Any] = {"ok": False, "sent": [], "reply": "", "error": ""}

    # 这两类在阶段一就只有占位，阶段二也不假装能执行 —— 明确说"还没接"。
    if action in ("render", "knowledge"):
        out["error"] = ("action=%s 的执行器还没接（见 AGENTS.md §11 待办）"
                        % action)
        return out
    if action is None:
        out["error"] = "没有可执行的动作"
        return out

    if action == "led_blink":
        return _run_led_blink(arg or {}, host, port, timeout, out, report)

    # anim/draw 的执行方式是"渲染一帧发一帧"，只有一个合法入口：/play。
    # ⚠ 这里**绝不能**自己调 _play_plan 播一遍：前端拿到 done 之后还会再调
    #   /play（index.html 的 playAnim），两边都播就是同一句话播两遍。
    #   "动画播两遍"不会报错，只会让用户觉得慢半拍，最难查。
    # ⚠ 但也**不能**让它们落进下面的兜底分支 —— 原来那里只回一句
    #   "anim 的执行器还没接"，既没说是哪条路能走，也让人以为功能没做。
    if action in ("anim", "draw"):
        out["error"] = ("%s 是画面动作，不在这里执行：请发 POST /play"
                        % action)
        return out

    cmd = arg if action in ("cmd", "query") else None
    if not cmd:
        # 走到这里说明 action 是 ACTIONS 里有、但本函数没接的（将来新增的动作）。
        # 错误信息要说明"哪条路能走"，否则用户只知道失败了、不知道下一步。
        out["error"] = ("action=%s 不能直接执行：写命令走 /confirm，"
                        "画面走 /play" % action)
        return out

    # 板子之前再验一次命令白名单：HTTP 层是外部输入进来的，不信票。
    bad = dispatcher.validate_cmd(cmd)
    if bad:
        out["error"] = "拒绝执行：%s" % bad
        return out

    with Board(host, port, timeout=timeout) as b:
        try:
            out["reply"] = b.send_text(cmd).strip()
        except BoardError as e:
            out["error"] = "板子没回包：%s" % e
            return out
    out["sent"] = [cmd]
    out["ok"] = True
    return out


def _run_led_blink(arg: Dict[str, Any], host: str, port: int, timeout: float,
                   out: Dict[str, Any], report) -> Dict[str, Any]:
    idx = int(arg.get("index", 0))
    times = int(arg.get("times", 5))
    period = float(arg.get("period", 0.2))
    on_cmd, off_cmd = "LED %d 1" % idx, "LED %d 0" % idx

    last = ""
    with Board(host, port, timeout=timeout) as b:
        try:
            for i in range(times):
                try:
                    last = b.send_text(on_cmd).strip()
                    out["sent"].append(on_cmd)
                    if report:
                        report(i * 0.5, "第 %d/%d 次：开" % (i + 1, times))
                    time.sleep(period)
                    b.send_text(off_cmd)
                    out["sent"].append(off_cmd)
                    time.sleep(period)
                except BoardError as e:
                    out["error"] = "第 %d 次闪烁时板子没回包：%s" % (i + 1, e)
                    return out
                if report:
                    report((i + 1) * 0.5, "第 %d/%d 次：关" % (i + 1, times))
        finally:
            # 无论如何别把灯留在亮着 —— 和 dispatcher._exec_led_blink 同一约定
            try:
                b.send_text(off_cmd)
            except Exception:
                pass
    out["reply"] = last or "OK"
    out["ok"] = True
    return out


# ---------------------------------------------------------------------------
# Job 表（长任务）
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, raw: str, plan: Dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.raw = raw
        self.plan = plan
        self.state = "running"      # running | done | error
        self.progress = 0.0
        self.notes: List[str] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error = ""
        self.created = time.time()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job": self.id,
            "raw": self.raw,
            "action": self.plan.get("action"),
            "arg": self.plan.get("arg"),
            "state": self.state,
            "progress": round(self.progress, 3),
            "notes": self.notes[-10:],
            "result": self.result,
            "error": self.error,
        }


class JobTable:
    def __init__(self, cap: int = MAX_JOBS) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._order: queue.Queue = queue.Queue()
        self._cap = cap

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._order.put(job.id)
            while self._order.qsize() > self._cap:
                old = self._order.get()
                self._jobs.pop(old, None)

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)


JOBS = JobTable()


def _start_job(raw: str, plan: Dict[str, Any], cfg: Dict[str, Any]) -> Job:
    job = Job(raw, plan)
    JOBS.add(job)

    def report(p: float, note: str) -> None:
        job.progress = max(job.progress, min(1.0, p))
        if note:
            job.notes.append(note)

    def work() -> None:
        try:
            res = run_plan(plan, cfg["host"], cfg["port"], cfg["timeout"], report)
            job.result = res
            job.progress = 1.0
            job.state = "done" if res.get("ok") else "error"
            job.error = res.get("error", "")
        except Exception as e:  # noqa: BLE001
            job.state = "error"
            job.error = "%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
        finally:
            try:
                dispatcher.log_plan(plan, executed=True)
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()
    return job


# ---------------------------------------------------------------------------
# 动画：翻译成"真的画一帧发出去"
#
# ⚠ 阶段二 run_plan() 对 anim/draw/render 只说"执行器还没接"。阶段三前端要
#   真的看到屏幕动，所以在这里补上。但判据仍然全部来自 dispatcher ——
#   这里只多了"怎么发给板子"这件事。
#
# ⚠ 为什么用**短时长**而不是一直播到用户点停：
#   HTTP 请求必须有尽头。前端点"播放"发一次请求，播 3 秒后回包；
#   想继续就再点一次。这样不存在"看不见的后台线程一直发 UDP"——
#   页面上什么都看不见却在占板子，是最难排查的一类状态。
# ---------------------------------------------------------------------------

ANIM_MAX_SECONDS = 30.0        # 单次播放上限：别让一条请求占住板子半小时
ANIM_DEFAULT_SECONDS = 3.0     # 没说时长时播多久（用户定的默认值）
ANIM_DEFAULT_FPS = 20.0


def _plan_seconds(plan: Dict[str, Any], fallback: float) -> float:
    """
    取"这条指令要播多久"。

    规则层已经把"播 5 秒"认成 arg 之外的 seconds 了（dispatcher.py 的
    `_plan(..., **extra)`），阶段二之前没人读它 —— 等于用户说了白说。
    这里补上：说了就用他说的，没说才用默认值。
    """
    return _num_or(plan.get("seconds"), fallback)


def _num_or(v: Any, fallback: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(fallback)
    return f if f > 0 else float(fallback)


def _make_renderer(plan: Dict[str, Any]) -> Tuple[Any, str]:
    """
    按 action 造出 render(t, params) -> 1024 字节。

    三个来源，优先级写在调用处：
      * anim   → anim.ANIMS 里的内置函数（offline，不花钱）
      * draw   → 让 LLM 现写代码（花钱、要网络，但能画任意画面）
      * render → 同 anim，只是不发板子

    ⚠ draw 走 agent.code_for()，它自带磁盘缓存（code_cache/），
      同一个描述第二次是 0 延迟 0 花费。
    """
    action, arg = plan.get("action"), plan.get("arg")

    if action == "anim":
        fn = anim.get(str(arg))
        return (lambda t, p: agent._render_named(fn, t, p)), "内置动画 %s" % arg

    if action == "draw":
        code = agent.code_for(str(arg), use_cache=True, verbose=False)
        rend = agent.Renderer(code, timeout=3.0)
        return (lambda t, p: rend.render(t, p)), "LLM 现写代码"

    raise ValueError("action=%s 造不出渲染器" % action)


def _play_plan(plan: Dict[str, Any], cfg: Dict[str, Any],
               seconds: float = ANIM_DEFAULT_SECONDS,
               fps: float = ANIM_DEFAULT_FPS, report=None) -> Dict[str, Any]:
    """
    把一帧帧真的发到板子上。返回 {"ok", "sent", "reply", "error", "frames", "fps_real"}。

    ⚠ 全程复用**一个** Board 会话：每帧新建 socket 会 bind 一个临时端口，
      20fps 播 3 秒就是 60 个 socket，端口很快不够用。
    """
    out: Dict[str, Any] = {"ok": False, "sent": [], "reply": "", "error": "",
                           "frames": 0, "fps_real": 0.0}
    action = plan.get("action")
    if action not in ("anim", "draw"):
        out["error"] = "action=%s 不能用 /play 执行（用 /confirm）" % action
        return out

    seconds = max(0.1, min(ANIM_MAX_SECONDS, float(seconds)))
    fps = max(1.0, min(60.0, float(fps)))
    total = int(seconds * fps)

    # "2 倍速"：动画自身的时间轴走得更快，我们发的帧数不变。
    # ⚠ 不能靠提高 fps 来实现倍速 —— I2C 100kHz 下整屏约 92ms（硬上限 ≈11fps），
    #   多发帧只会被板子覆盖，看起来一样快但丢的包更多。
    speed = max(0.1, min(10.0, _num_or(plan.get("speed"), 1.0)))

    try:
        render, what = _make_renderer(plan)
    except Exception as e:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(e).__name__, e)
        return out

    out["sent"] = [what]
    start = time.time()
    n = 0
    with Board(cfg["host"], cfg["port"], timeout=cfg["timeout"]) as b:
        try:
            b.ping()                       # 先探活，"板子不在"要立刻报，不要等几秒后报
        except BoardError as e:
            out["error"] = "板子没回 PING：%s" % e
            return out

        try:
            while n < total:
                t = (n / fps) * speed          # 倍速只改动画自己的时间轴
                frame = render(t, {})
                b.send_frame(frame, seq=(n & 0xFFFF))
                n += 1
                if report and n % 5 == 0:
                    report(n / total, "第 %d/%d 帧" % (n, total))
                # 按绝对时间轴对齐（与 agent.play() 同一个理由：渲染耗时会累积）
                gap = (start + n / fps) - time.time()
                if gap > 0:
                    time.sleep(gap)
        except (BoardError, SandboxError) as e:
            out["error"] = "第 %d 帧失败：%s" % (n, e)
            out["frames"] = n
            return out
        except Exception as e:  # noqa: BLE001
            out["error"] = "第 %d 帧失败：%s: %s" % (n, type(e).__name__, e)
            out["frames"] = n
            return out

        elapsed = time.time() - start
        out["frames"] = n
        out["fps_real"] = round(n / elapsed, 1) if elapsed > 0 else 0.0
        try:
            out["reply"] = b.fb_stat().strip()      # FB: good=.. bad=.. ooo=.. 让前端能显示丢包
        except BoardError:
            out["reply"] = ""
    out["ok"] = True
    return out


def _render_png(plan: Dict[str, Any], t: float) -> bytes:
    """
    只渲染一帧成 PNG（4 倍放大），**不发板子**。

    ⚠ 复用 agent._save_png 写文件而不是在这里另写一套 PNG 编码：
      两套渲染器迟早会画出不一样的东西。先落临时文件读回来，完事删掉。
    """
    import tempfile

    render, _ = _make_renderer(plan)
    frame = render(max(0.0, float(t)), {})
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        agent._save_png(frame, path)
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

CFG: Dict[str, Any] = {
    "host": DEFAULT_HOST,       # 板子 IP（不是监听地址）
    "port": DEFAULT_PORT,
    "timeout": 1.5,
    "use_llm": True,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "OLED-api/1.0"

    # ---- 小工具 ----

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _text(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host_ok(self) -> bool:
        """
        挡 DNS rebinding：浏览器里的恶意网页可以往 127.0.0.1 发请求，
        但它的 Host 头会是攻击者的域名。只放行 localhost/127.0.0.1。
        """
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in ("localhost", "127.0.0.1", "[::1]", "::1")

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "Content-Length 不是数字"})
            return None
        if n <= 0:
            self._json(400, {"error": "空请求体"})
            return None
        if n > MAX_TEXT_BYTES:
            self._json(413, {"error": "请求体太大（上限 %d 字节）" % MAX_TEXT_BYTES})
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "请求体不是合法 JSON"})
            return None

    def log_message(self, fmt: str, *a) -> None:  # 别把每个请求刷到终端
        pass

    # ---- 路由 ----

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path == "/healthz":
            return self._json(200, {"ok": True, "board": CFG["host"],
                                    "llm": CFG["use_llm"]})
        if not self._host_ok():
            return self._json(403, {"error": "Host 头不合法（防 DNS rebinding）"})

        if path in ("/", "/index.html"):
            page = os.path.join(_HERE, "index.html")
            if not os.path.exists(page):
                return self._text(404, "前端还没做（阶段三）。\n"
                                       "接口已可用，见 GET /commands\n".encode(),
                                  "text/plain; charset=utf-8")
            with open(page, "rb") as f:
                return self._text(200, f.read(), "text/html; charset=utf-8")

        if path == "/commands":
            return self._json(200, {
                "actions": list(dispatcher.ACTIONS),
                "firmware_cmds": list(dispatcher.FIRMWARE_CMDS),
                "readonly": sorted(dispatcher.READONLY_CMDS),
                "query_only": sorted(dispatcher.QUERY_ONLY),
                "token_ttl": TOKEN_TTL,
            })

        if path.startswith("/job/"):
            job = JOBS.get(path[len("/job/"):])
            if job is None:
                return self._json(404, {"error": "没有这个 job"})
            return self._json(200, job.snapshot())

        return self._json(404, {"error": "没有这个路径"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if not self._host_ok():
            return self._json(403, {"error": "Host 头不合法（防 DNS rebinding）"})

        if path == "/dispatch":
            return self._post_dispatch()
        if path == "/confirm":
            return self._post_confirm()
        if path == "/play":
            return self._post_play()
        if path == "/render":
            return self._post_render()
        return self._json(404, {"error": "没有这个路径"})

    # ---- /dispatch：只翻译 ----

    def _post_dispatch(self) -> None:
        data = self._read_json()
        if data is None:
            return
        text = (data.get("text") or "").strip()
        if not text:
            return self._json(400, {"error": "text 不能为空"})
        if len(text) > 500:
            return self._json(400, {"error": "话太长了（上限 500 字）"})

        explain: List[str] = []
        try:
            plan = dispatcher.dispatch(text, use_llm=CFG["use_llm"],
                                       explain=explain)
        except agent.LLMError as e:
            return self._json(502, {"error": "LLM 不可用：%s" % e,
                                    "raw": text, "explain": explain})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})

        # 日志：凡是分派了（不论执行与否）都记一笔，才有回放价值
        dispatcher.log_plan(plan, executed=False)

        out: Dict[str, Any] = {
            "raw": text,
            "action": plan.get("action"),
            "arg": plan.get("arg"),
            "by": plan.get("by"),
            "needs_confirm": bool(plan.get("needs_confirm")),
            "why": plan.get("why", ""),
        }
        if data.get("explain"):
            out["explain"] = explain

        if plan.get("action") is None:
            out["status"] = "refused"
            return self._json(200, out)

        if plan.get("needs_confirm"):
            # ⚠ 写操作：只发票，不执行。这是整个阶段二的核心约束。
            out["status"] = "needs_confirm"
            out["token"] = issue_token(plan)
            out["expires_in"] = TOKEN_TTL
            out["risk"] = ("reg_write" if _is_reg_write(plan) else "write")
            out["preview"] = _preview(plan)
            return self._json(200, out)

        # ⚠ 画面请求只翻译、不执行：真正的发送入口是 /play（见下方 _post_play）。
        #   放进 done 但带上 play=true，前端一眼知道"翻译好了、下一步该播"，
        #   而不是看到 error 去猜；也保证同一句话只播一遍。
        if plan.get("action") in ("anim", "draw"):
            out["status"] = "done"
            out["play"] = True
            out["seconds"] = _plan_seconds(plan, ANIM_DEFAULT_SECONDS)
            out["result"] = {"ok": True, "sent": [], "reply": "",
                             "error": "", "frames": 0, "fps_real": 0.0}
            dispatcher.log_plan(plan, executed=False)
            return self._json(200, out)

        # 只读：直接执行，但仍然走 run_plan（它自己再验一次命令白名单）
        res = run_plan(plan, CFG["host"], CFG["port"], CFG["timeout"])
        out["status"] = "done" if res.get("ok") else "error"
        out["result"] = res
        if res.get("ok"):
            dispatcher.log_plan(plan, executed=True)
        return self._json(200, out)

    # ---- /confirm：验票 + 执行 ----

    def _post_confirm(self) -> None:
        data = self._read_json()
        if data is None:
            return
        payload, err = verify_token(data.get("token") or "")
        if payload is None:
            return self._json(403, {"error": err, "status": "invalid_token"})

        if not NONCES.claim(payload["nonce"]):
            return self._json(409, {"error": "这张票已经用过了",
                                    "status": "token_reused"})

        action = payload.get("action")
        arg = payload.get("arg")

        # ⚠ 重算 needs_confirm，**不信票里说什么**。
        #   票里没有 needs_confirm 字段，这行才是唯一判据。
        if action in ("cmd", "query"):
            must = dispatcher.needs_confirm(arg or "")
        elif action == "led_blink":
            must = True
        else:
            must = False
        if not must:
            return self._json(400, {"error": "这条指令不需要确认（票可能不是写操作）"})

        # by 保留 token 里带的原始来源（rule#led / llm / ...），
        # 但在前面加个 confirm 标记 —— 这样日志既看得出"是规则还是 LLM 翻译的"，
        # 也看得出"这条真的被确认执行过"。
        origin = payload.get("by") or "unknown"
        plan = dispatcher._plan(action, arg, by="confirm<%s>" % origin,
                                needs_confirm_=True,
                                why=payload.get("why", ""),
                                raw=payload.get("raw", ""))
        plan["sub"] = payload.get("sub")

        # 让前端选择同步还是异步：led_blink 一定是长任务
        want_async = bool(data.get("async")) or action == "led_blink"

        if want_async:
            job = _start_job(plan["raw"], plan, CFG)
            return self._json(202, {"status": "running", "job": job.id,
                                    "snapshot": job.snapshot()})

        res = run_plan(plan, CFG["host"], CFG["port"], CFG["timeout"])
        dispatcher.log_plan(plan, executed=True)
        return self._json(200 if res.get("ok") else 502,
                          {"status": "done" if res.get("ok") else "error",
                           "result": res})

    # ---- /play：动画走这条路（比 /confirm + run_plan 多一步"真的渲染"） ----

    def _post_play(self) -> None:
        """
        {"text": "...", "seconds": 3, "fps": 20} → 播一段动画。

        ⚠ 这里**不需要 token**，因为它不碰写命令 —— 动画走的是 FB 帧通道，
          和 LED 寄存器是两条完全不同的路（见 AGENTS.md §3.11）。
          但为了日志可追溯，仍然记一行 executed:true。
        """
        data = self._read_json()
        if data is None:
            return
        text = (data.get("text") or "").strip()
        if not text:
            return self._json(400, {"error": "text 不能为空"})

        try:
            seconds = _num_or(data.get("seconds"), 0.0)
            fps = _num_or(data.get("fps"), ANIM_DEFAULT_FPS)
        except (TypeError, ValueError):
            return self._json(400, {"error": "seconds/fps 必须是数字"})

        explain: List[str] = []
        try:
            plan = dispatcher.dispatch(text, use_llm=CFG["use_llm"],
                                       explain=explain)
        except agent.LLMError as e:
            return self._json(502, {"error": "LLM 不可用：%s" % e})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})

        out: Dict[str, Any] = {"raw": text, "action": plan.get("action"),
                               "arg": plan.get("arg"), "by": plan.get("by"),
                               "why": plan.get("why", "")}

        if plan.get("action") not in ("anim", "draw"):
            # 不是动画请求。明确告诉前端该走哪条路，别让它自己猜。
            out["status"] = "refused"
            out["error"] = ("这条是 %s，不是动画。%s"
                            % (plan.get("action") or "无法分派",
                               "写操作请先 /dispatch 再 /confirm"
                               if plan.get("action") else plan.get("why", "")))
            return self._json(200, out)

        # ⚠ 时长的三个来源有优先级：话里说的（"播 5 秒"）> 请求体给的 > 默认 3 秒。
        #   话里说的排第一，因为规则层已经把它认出来了，丢掉等于让用户白说一遍。
        said = _num_or(plan.get("seconds"), 0.0)
        if said > 0:
            seconds = said
        elif seconds <= 0:
            seconds = ANIM_DEFAULT_SECONDS
        out["seconds"] = round(min(ANIM_MAX_SECONDS, seconds), 1)

        res = _play_plan(plan, CFG, seconds, fps)
        dispatcher.log_plan(plan, executed=True)
        out["status"] = "done" if res.get("ok") else "error"
        out["result"] = res
        return self._json(200 if res.get("ok") else 502, out)

    # ---- /render：只画一帧成 PNG，不发板子 ----

    def _post_render(self) -> None:
        """
        {"text": "...", "t": 0.0} → image/png。

        ⚠ 返回的是二进制图片而不是 JSON，前端直接 <img src=...> 用不了
          （POST 不能当 src），所以前端拿到 blob 再换 objectURL。
          好处：预览和真发板子用的是**同一段渲染代码**，不会出现
          "预览好看、板上不一样"。
        """
        data = self._read_json()
        if data is None:
            return
        text = (data.get("text") or "").strip()
        if not text:
            return self._json(400, {"error": "text 不能为空"})
        try:
            t = float(data.get("t") or 0.0)
        except (TypeError, ValueError):
            return self._json(400, {"error": "t 必须是数字"})

        try:
            plan = dispatcher.dispatch(text, use_llm=CFG["use_llm"])
        except agent.LLMError as e:
            return self._json(502, {"error": "LLM 不可用：%s" % e})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})

        if plan.get("action") not in ("anim", "draw"):
            return self._json(200, {"error": "这条不是画面请求（%s）"
                                             % (plan.get("action") or "无法分派"),
                                    "why": plan.get("why", "")})
        try:
            png = _render_png(plan, t)
        except (SandboxError, agent.LLMError) as e:
            return self._json(200, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})
        return self._text(200, png, "image/png")


def _is_reg_write(plan: Dict[str, Any]) -> bool:
    return dispatcher._is_reg_write(plan)

def _preview(plan: Dict[str, Any]) -> List[str]:
    """给前端一行一行地预览"接下来真要发什么"，别让用户凭空点头。"""
    action, arg = plan.get("action"), plan.get("arg")
    if action == "led_blink" and isinstance(arg, dict):
        idx = int(arg.get("index", 0))
        times = int(arg.get("times", 5))
        period = float(arg.get("period", 0.2))
        return ["LED %d 1 / LED %d 0  ×%d" % (idx, idx, times),
                "间隔 %dms，约 %.1f 秒，结束时恢复成灭"
                % (int(period * 1000), times * period * 2)]
    if action in ("cmd", "query") and isinstance(arg, str):
        lines = [arg]
        if _is_reg_write(plan):
            lines.append("⚠ 这是直接写寄存器，写错会让板子掉时钟/变砖")
        return lines
    if action == "anim":
        return ["播放内置动画 %s" % arg,
                "板子会被占住这段时间，期间别的命令照常回包"]
    if action == "draw":
        return ["让 LLM 现写代码画：%s" % arg,
                "代码先在沙箱里试渲染，通过了才发板子"]
    if action == "render":
        return ["只渲染一帧看效果，不发板子"]
    return [str(arg)]


# ---------------------------------------------------------------------------
# 自测：不起浏览器，直接打自己
# ---------------------------------------------------------------------------

def selftest() -> int:
    import urllib.error
    import urllib.request

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    fails: List[str] = []
    n = 0

    def call(method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers=headers or {})
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def check(name, cond, detail=""):
        nonlocal n
        n += 1
        if not cond:
            fails.append("%s  %s" % (name, detail))

    # ---- token 本身 ----
    p = dispatcher._plan("cmd", "W 40020014 1", needs_confirm_=True,
                         raw="写寄存器")
    tok = issue_token(p)
    good, err = verify_token(tok)
    check("token 验签通过", good is not None, err)
    bad_tok = tok[:-3] + ("aaa" if tok[-3:] != "aaa" else "bbb")
    check("改过的 token 被拒", verify_token(bad_tok)[0] is None)
    check("乱码 token 被拒", verify_token("x.y")[0] is None)
    check("空 token 被拒", verify_token("")[0] is None)

    # 过期：伪造一个 exp 在过去的（用同一把钥匙签名，模拟"票放了很久"）
    stale = {"raw": "写", "action": "cmd", "arg": "W 40020014 1",
             "nonce": "n1", "exp": time.time() - 1}
    body = _b64e(json.dumps(stale, sort_keys=True).encode())
    check("过期 token 被拒",
          verify_token(body + "." + _sign(body))[0] is None)

    # ---- Host 头 ----
    try:
        req = urllib.request.Request(base + "/commands", method="GET",
                                     headers={"Host": "evil.example.com"})
        with urllib.request.urlopen(req, timeout=5) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    check("非本机 Host 被拒", code == 403, "得到 %s" % code)

    # ---- /dispatch 各种分支 ----
    code, r = call("POST", "/dispatch", {"text": "在吗"})
    check("只读：直接执行", r.get("status") == "done", json.dumps(r, ensure_ascii=False))
    check("只读：不需要确认", r.get("needs_confirm") is False)

    code, r = call("POST", "/dispatch", {"text": "把灯打开"})
    check("写：只发票不执行", r.get("status") == "needs_confirm",
          json.dumps(r, ensure_ascii=False))
    check("写：没有 result 字段（说明没执行）", "result" not in r)
    check("写：给了 token", bool(r.get("token")))
    check("写：预览里有 LED 命令",
          any("LED" in s for s in (r.get("preview") or [])),
          str(r.get("preview")))
    tok = r.get("token")

    code, r = call("POST", "/dispatch", {"text": "W 40023800 0"})
    check("写 RCC：分派器自己拦住", r.get("status") == "refused",
          json.dumps(r, ensure_ascii=False))

    code, r = call("POST", "/dispatch", {"text": "今天天气怎么样"})
    check("闲聊：拒绝", r.get("status") == "refused",
          json.dumps(r, ensure_ascii=False))

    # ---- token 复用 ----
    code, r1 = call("POST", "/confirm", {"token": tok})
    check("确认：第一次执行成功", r1.get("status") == "done",
          json.dumps(r1, ensure_ascii=False))
    code, r2 = call("POST", "/confirm", {"token": tok})
    check("确认：第二次被拒（一次性）", code == 409, "得到 %s" % code)

    # ---- 长任务 ----
    code, r = call("POST", "/dispatch", {"text": "闪灯 2 次 间隔 60 毫秒"})
    check("闪灯：要确认", r.get("status") == "needs_confirm")
    code, r = call("POST", "/confirm", {"token": r.get("token")})
    check("闪灯：返回 job 在跑", r.get("status") == "running", str(r))
    job_id = r.get("job")
    deadline = time.time() + 15
    snap = {}
    while time.time() < deadline:
        code, snap = call("GET", "/job/" + str(job_id))
        if snap.get("state") != "running":
            break
        time.sleep(0.1)
    check("闪灯：跑完了", snap.get("state") == "done",
          json.dumps(snap, ensure_ascii=False))
    check("闪灯：进度到 1", snap.get("progress") == 1.0)
    sent = (snap.get("result") or {}).get("sent") or []
    # ⚠ 正常跑完是 2×times 条：最后一次循环的关灯就是"恢复成灭"，
    #   finally 里那条兜底不会重复记进 sent。只有中途异常才会多出来。
    check("闪灯：发了开关各 2 条", sent == ["LED 0 1", "LED 0 0"] * 2, str(sent))

    # ---- 并发：两个只读请求同时打 ----
    results: List[Any] = []
    lock = threading.Lock()

    def hit():
        try:
            c, rr = call("POST", "/dispatch", {"text": "在吗"})
            with lock:
                results.append(rr.get("status"))
        except Exception as e:  # noqa: BLE001
            with lock:
                results.append("EXC %s" % e)

    ths = [threading.Thread(target=hit) for _ in range(4)]
    [t.start() for t in ths]
    [t.join(30) for t in ths]
    check("并发 4 个只读请求都成功",
          results.count("done") == 4, str(results))

    # ---- 动画：/dispatch 只说"要播什么"，真播必须走 /play ----
    # ⚠ 这条用例是补的回归：阶段三第一次提交后，页面上说"播放个烟花"
    #   落到 run_plan 的兜底分支，回一句 "anim 的执行器还没接"。
    #   当时的 24 项自测一条都没覆盖动画 —— 因为全都只走文本命令。
    #   现在把"翻译"和"执行"两段分开测，谁少接一步都会红。
    code, r = call("POST", "/dispatch", {"text": "播个烟花"})
    check("动画：分派成 anim", r.get("action") == "anim",
          json.dumps(r, ensure_ascii=False))
    check("动画：只读不要确认", r.get("needs_confirm") is False)
    check("动画：/dispatch 不报错", r.get("status") == "done",
          json.dumps(r, ensure_ascii=False))
    check("动画：/dispatch 标记要播", r.get("play") is True)
    check("动画：/dispatch 不发动画",
          (r.get("result") or {}).get("frames", 0) == 0,
          "翻译不该顺手播一屏，否则前端再发 /play 就播两遍")

    # ---- 时长/倍速参数必须被认出来（规则层认了、执行层不能吞） ----
    plan = dispatcher.dispatch("播 5 秒 烟花", use_llm=False)
    check("动画：plan 里有 seconds=5", plan.get("seconds") == 5.0,
          str(plan.get("seconds")))
    check("动画：没说时长用默认 3 秒",
          _plan_seconds(dispatcher.dispatch("播个烟花", use_llm=False),
                        ANIM_DEFAULT_SECONDS) == ANIM_DEFAULT_SECONDS)
    check("动画：2 倍速被识别",
          dispatcher.dispatch("播个烟花的动画 2 倍速",
                              use_llm=False).get("speed") == 2.0)
    check("_num_or 兜住脏输入", _num_or("abc", 3.0) == 3.0)

    # ---- 坏输入 ----
    code, _ = call("POST", "/dispatch", {"text": ""})
    check("空 text → 400", code == 400, "得到 %s" % code)
    code, _ = call("GET", "/nope")
    check("未知路径 → 404", code == 404, "得到 %s" % code)

    srv.shutdown()

    print("\n[api] 自测：%d 项，失败 %d 项" % (n, len(fails)))
    for f in fails:
        print("  [FAIL] %s" % f)
    if not fails:
        print("  [PASS] 全过")
    return 0 if not fails else 1


# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="api",
        description="把 dispatcher 包成 HTTP 接口（写操作两段式确认）")
    ap.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认只听本机；0.0.0.0 = 局域网可访问）")
    ap.add_argument("--listen-port", type=int, default=8765)
    ap.add_argument("--board", default=DEFAULT_HOST, help="板子 IP")
    ap.add_argument("--board-port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--no-llm", action="store_true", help="只跑规则层")
    ap.add_argument("--open", action="store_true", help="起服务后自动开浏览器")
    ap.add_argument("--selftest", action="store_true", help="跑接口自测后退出")
    args = ap.parse_args(argv)

    CFG["host"] = args.board
    CFG["port"] = args.board_port
    CFG["timeout"] = args.timeout
    CFG["use_llm"] = not args.no_llm

    if args.selftest:
        return selftest()

    srv = ThreadingHTTPServer((args.host, args.listen_port), Handler)
    port = srv.server_address[1]
    url = "http://127.0.0.1:%d/" % port

    print("[api] 监听 %s:%d  （板子 %s:%d，LLM %s）"
          % (args.host, port, CFG["host"], CFG["port"],
             "开" if CFG["use_llm"] else "关"))
    if args.host not in ("127.0.0.1", "localhost"):
        print("[api] ⚠ 监听在非本机地址：同一网段的人都能操作你的板子")
    print("[api] 打开 %s" % url)
    print("[api] Ctrl+C 停止")

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[api] 停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SandboxError, agent.LLMError) as e:
        print("\n[api] 出错：%s" % e, file=sys.stderr)
        sys.exit(2)
