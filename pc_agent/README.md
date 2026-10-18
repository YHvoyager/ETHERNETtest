# pc_agent —— 用自然语言控制 STM32 板子上的 OLED

把一句话变成 128x64 OLED 上的动画。

```
你说："一双慢慢眨的眼睛"
         ↓
   LLM 写出一段 draw(c, t, p) 的画图代码
         ↓
   沙箱里逐帧执行，每帧 1024 字节
         ↓
   UDP 发给板子 → 板子转发到 I2C2 上的 SSD1306
```

---

## 一分钟上手

```bash
cd <工程根>

# 1. 确认板子在
python pc_agent/agent.py check

# 2. 先在终端里看效果，不用连板子
python pc_agent/agent.py --anim eyes --ascii

# 3. 发到板子上
python pc_agent/agent.py --anim eyes

# 4. 让它现场想一个
set DEEPSEEK_API_KEY=sk-xxxx
python pc_agent/agent.py "一双慢慢眨的眼睛，瞳孔跟着左右看"
```

---

## 命令一览

| 命令 | 作用 |
|---|---|
| `agent.py check` | 检查板子连通性（PING / INFO / FB? / OLED STAT） |
| `agent.py --list` | 列出内置动画 |
| `agent.py --anim eyes [--fps 15] [-s 10]` | 播内置动画 |
| `agent.py "描述"` | 让 LLM 写代码再播 |
| `agent.py --code my.py` | 播你自己写的 draw() |
| `agent.py --anim eyes --ascii` | 只在终端画字符画 |
| `agent.py --anim eyes --render -t 1.5 -o f.png` | 存一帧成 PNG |
| `agent.py --test` | 只跑沙箱自检 |
| `agent.py --anim eyes --stats 2` | 每 2 秒打印板子收帧统计 |

常用参数：`--host`（板子 IP，默认 `192.168.1.30`）、`--fps`（默认 20）、
`-s/--seconds`（0 = 一直播）、`--no-seq`（发帧不带序号）。

---

## 这里为什么是这样设计的

### 为什么让 LLM 写代码，而不是预置动作

最初的设计是预置 `eyes()`、`horse()` 这些函数，LLM 只做意图分类。
问题是**能力被写代码的人锁死了** —— 想要「一只打哈欠的猫」，
库里没有就没办法。

现在 LLM 现场写 `draw(c, t, p)`，预置的 eyes/horse 降级成**示例**。
能力上限从「我预置了多少个动作」变成「模型有多会写画图代码 + 画布
原语有多强」。两个都在持续变好，而动作库不会。

### 为什么帧是 1024 字节的位图

另一条路是用文本命令逐像素控制（板子已经有 `OLED PIX`）。
算一下就知道不可行：15fps × 1024 字节，一条 `W` 命令才改 4 字节，
需要几十万条命令每秒。

一个 UDP 包 1024 字节就是一帧，20fps 也才 20KB/s。
**以太网侧根本不是瓶颈 —— 瓶颈是 I2C。**

### 为什么发帧率高于屏幕刷新率

I2C 100kHz 下，整屏 1024 字节大约要 92ms，也就是**约 11fps 的硬上限**。
但 PC 端默认发 20fps，多出的帧会被板子直接覆盖掉。

这是故意的：PC 不知道哪个包丢了，多发几个能让板子**总是拿到最新画面**。
如果 PC 限速到 11fps，丢一个包就会看到一帧旧的。

想要更流畅，看下面的「还能怎么提速」。

### 为什么要沙箱

`agent.py` 会执行**模型生成的、没人看过的代码**。不加限制的话那段
代码能删你的文件、能连外网、能死循环。

三道闸门（见 `sandbox.py`）：

1. **import 白名单** —— 只能 `math` / `random`
2. **名字白名单** —— 没有 `open` / `eval` / `exec` / `__import__`
3. **超时** —— 单帧超 1 秒就放弃

最要紧的一条：**画布传进去，板子对象绝不传进去**。LLM 的代码碰得到
`Canvas`，碰不到 `Board` —— 改不了 I2C、发不了包、读不到文件。

自带 10 个攻击用例自检（`agent.py --test`），应该永远 10/10 拦住。

> ⚠ 说清楚定位：它防的是**模型写错代码**和**提示注入**，不是防有备而来
> 的攻击者。纯 Python 沙箱绕得过去。它的价值是把手滑的代价从「删掉文件」
> 降到「报个错」。

### 为什么代码有缓存

`code_cache/` 里存着 LLM 写成功过的代码，按描述文本哈希索引。

这就是「skill accumulation」的落地 —— 知识存在**文件**里，不在模型权重里。
第一次问「画眼睛」要等 3 秒，第二次是 0 秒。想强制重新生成用 `--no-cache`。

---

## 写自己的动画

```python
# my_anim.py
def draw(c, t, p):
    y = 50 - abs(math.sin(t * 3.0)) * 35
    c.circle(int(64 + math.sin(t * 1.1) * 40), int(y), 8, True, True)
    c.hline(0, 58, 128, True)
```

```bash
python pc_agent/agent.py --code my_anim.py
```

规则只有三条：必须有 `draw(c, t, p)`；只能 import `math`/`random`；
**同一个 t 必须画出同一帧**（不要用函数外的状态）。

第三条最重要 —— 纯函数才能随机跳到 `t=5.0` 去渲染预览图。

### 画布 API

坐标 `(0,0)` 左上，`(127,63)` 右下。

```python
c.clear(on=False)                        # 清屏
c.set(x, y, on=True)                     # 点
c.get(x, y) -> bool                      # 读点
c.xor(x, y)                              # 翻转（闪烁）

c.hline(x, y, w)      c.vline(x, y, h)
c.line(x0, y0, x1, y1)
c.rect(x, y, w, h)    c.fill_rect(x, y, w, h)

c.circle(cx, cy, r, fill=False)
c.ellipse(cx, cy, rx, ry, fill=False)
c.polygon([(x,y), ...], fill=False)

c.text(x, y, "ASCII")                    # 6x8 字体
c.blit(x, y, w, h, bits)                 # 贴位图
c.invert_rect(x, y, w, h)                # 反色
```

### 显示任意中文

板子的第三方字库只有 4 个汉字（「波特律动」），**不要指望它**。

正确做法是 PC 端渲染成点阵再传过去（`bitmap.py`，用 Windows GDI，
不需要装任何东西）：

```python
def draw(c, t, p):
    c.text(0, 0, "ASCII 用内置字体")
    # 中文：PC 渲染好再贴
    w, h, bits = bitmap.render_text("你好", size=16)
    c.blit(0, 20, w, h, bits)
```

现成的滚动效果：

```bash
python pc_agent/agent.py --code ... # 或直接用内置的 text 动画
# 参数在 anim.scrolling_text 里：text / face / size / speed
```

---

## 文件说明

| 文件 | 干什么 |
|---|---|
| `proto.py` | UDP 通道：文本命令 + 二进制帧（**会过滤板子每秒的心跳**） |
| `canvas.py` | 128x64 画布 + 全套画图原语 + 内置 ASCII 字体 |
| `anim.py` | 内置示例动画（eyes / eyes_fast / horse / car / rain / boing / text / fireworks） |
| `bitmap.py` | 中文点阵渲染（Windows GDI） |
| `sandbox.py` | 沙箱：import 白名单、名字白名单、超时 |
| `agent.py` | 主程序：CLI、LLM 调用、播放循环、代码缓存 |
| `dispatcher.py` | **说一句话 → 结构化指令**（规则层 + LLM 层 + 安全白名单），见下 |
| `api.py` | 给前端用的 HTTP 外壳：两段式确认、一次性 token、长任务异步 |
| `dispatch_cases.jsonl` | dispatcher 的验收标准（自测集，进版本库） |
| `index.html` | 浏览器前端：说一句话、看预览、点确认（单文件零依赖） |
| `code_cache/` | LLM 写成功过的代码（自动生成） |

---

## 说一句话就能动：dispatcher

`agent.py "描述"` 只负责**画**。要"把灯打开""闪灯三下""报一下板子状态"，
用 `dispatcher.py` —— 它把自然语言翻译成**一条结构化指令**，然后（可选）执行。

```bash
python pc_agent/dispatcher.py "把灯打开"          # 写操作 → 停下要你确认，exit 3
python pc_agent/dispatcher.py "把灯打开" -y       # 真发
python pc_agent/dispatcher.py "在吗"              # 只读 → 直接执行
python pc_agent/dispatcher.py "播烟花" --json     # 只要结构化结果，不执行
python pc_agent/dispatcher.py "采样率" -x         # 解释为什么这样理解
python pc_agent/dispatcher.py --test              # 跑自测集
```

分三层，越靠前越确定：

```
① 规则层   正则命中 → 结果确定、0 延迟、0 花费
② LLM 层   规则未命中才问模型，temperature=0，只收严格 JSON
③ 拒绝     两边都没把握 → 明确说不知道，绝不瞎猜
```

7 个 action：`cmd` / `query` / `anim` / `draw` / `render` / `knowledge` / `led_blink`。

**安全靠三道闸**（缺一不可）：

1. 命令必须在固件命令表里，寄存器地址必须在 GPIO 区间、**不能写 RCC**
2. 写操作不加 `-y` 一律不执行
3. 板子端 `reg_shell.c` 自己还有一道白名单

> ⚠ 固件只认**数字**索引：`LED 0 1` 而不是 `LED DS0 1`（后者板子回
> `ERR: bad LED index 'DS0'`）。

**规则层认识的几类说法**（命中即 0 延迟、0 花费、结果确定）：

| 你说 | 分派结果 |
|---|---|
| `把灯打开` / `关灯` | `LED 0 1` / `LED 0 0`（写操作，要确认） |
| `闪灯 3 次 间隔 100 毫秒` | `led_blink {index:0, times:3, period:0.1}` |
| `在吗` / `刷屏卡不卡` | `PING` / `OLED STAT`（只读，直接执行） |
| `GPIOB 的 IDR 是多少` | `R 40020410 1`（读寄存器，只读） |
| `读一下 GPIOB` | `HELP` —— 没说读哪个寄存器就回清单，不猜地址 |
| `屏幕上一个字都没了` / `屏幕没亮` | **`OLED INIT` + 要你确认**（不是"没听懂"） |
| `画一只打哈欠的猫` / `画个笑脸` | `draw`，**直接播 3 秒**（不用确认，画面只在 PC 渲染） |

> 排障说法给的是**可执行的下一步**，不是一句建议文本。早期版本回
> `action=null` + "先发 OLED INIT…"，页面只显示「没听懂」，用户还得自己再打一遍。

> **"画个 X"不用配 API key 也能听懂。** 规则层直接把它变成 `draw`，只有画室**从没画过的那个画面**才需要 LLM 写代码（此时才读 key）。
> 内置列表里有的就别用"画"（"把眼睛画出来"仍落回 `anim/eyes`）。

> ⚠ 规则太靠前会**抢走**后面的说法：排障规则曾放在屏幕命令前面，于是
> "刷屏**卡**不卡"被当成"不动了"、"屏幕**没亮**，帮我开屏"被当成排障。
> 现在排障排在屏幕命令之后，并用一批询问词（`卡不卡`/`亮不亮`/`还在吗`/`多少`）
> 挡一道。**用户说"开屏"就照开屏，别替他决定要不要重置。**

每次分派记一行到 `dispatch_log.jsonl`（含 `by` 说明是规则命中的还是 LLM 猜的）。
想加说法：往 `dispatch_cases.jsonl` 加一行，跑 `--test`，规则层必须 100% 过。

---

## 浏览器里说：api.py

不想开终端时，`api.py` 把 dispatcher 包成一个本地 HTTP 服务：

```bash
python pc_agent/api.py              # http://127.0.0.1:8765
python pc_agent/api.py --selftest   # 33 项自测（会真的点灯，需要板子在线）
```

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/healthz` | 探活 |
| GET | `/commands` | 列出 action / 固件命令 / 只读白名单 |
| POST | `/dispatch` | 只翻译。**只读的直接执行**，写操作返回 `needs_confirm` + `token` |
| POST | `/confirm` | 凭 token 执行。长任务返回 `202` + job id |
| GET | `/job/<id>` | 轮询长任务进度 |

**两段式确认怎么保证的**：服务端**不存待确认队列**。`/dispatch` 把
`{原文, action, arg, 来源, 过期时间, nonce}` 用 HMAC-SHA256 签成一张票，
`/confirm` 验签 + 验过期 + 验 nonce 没用过，三条全过才执行。

> 票里**没有** `needs_confirm` 字段 —— 验票时用 dispatcher 的判据**重新算**。
> 安全结论不能由票自己声明，否则改一下 payload 就能把写操作说成只读。

密钥在 `pc_agent/.api_key`（首次运行生成，**已 gitignore**）。

> ⚠ 默认只听 `127.0.0.1`，并且除 `/healthz` 外校 Host 头 —— 挡住的是
> "你浏览器里某个网页偷偷往 localhost 发请求"。**这不是认证**，别拿它暴露公网。


---

## 打开一个网页就能说：index.html

```bash
python pc_agent/api.py --open      # 起服务并自动打开浏览器
```

`index.html` 是**单文件、零依赖、零 CDN** 的前端（原生 JS + 内联 CSS），
`api.py` 直接从磁盘读它。左边说一句话，右边看画面预览和板子状态。

每轮对话是一张卡片：**说的话 → 状态 → 动作/参数/来源/为什么 → 将要发什么 → [确认执行]**。
五种结局：`done` 直接显示回包；`done` + `play:true` 是画面请求，前端接着调
`/play` 真播（**服务端只翻译，不发帧**）；`needs_confirm` 才给确认按钮（带倒计时，
到点自动失效）；`refused` 只解释为什么没懂，**不给"硬执行"的按钮**；
`error` 打印原始 JSON。

> ⚠ **`done` 不等于"动画已经播了"。** 画面请求走两段：`/dispatch` 回
> `{action:"anim", play:true, seconds:3}`，前端看到 `play` 再发 `/play`。
> `result.frames == 0` 是翻译阶段的正常值。**一条执行路径只能有一个出口** ——
> 曾经让 `/dispatch` 顺手也播一遍，结果播了两遍。

**动画默认播 3 秒**，播完给「再播一次」按钮。想播更长就说"播 5 秒烟花"，
想快就加"2 倍速"（倍速是压缩动画时间轴，不是提 fps —— I2C 卡的 11fps 是硬上限）。

新增两个路由（只有前端用）：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/play` | `{text, seconds, fps}` → 真的逐帧发到板子，返回 `frames` / `fps_real` |
| POST | `/render` | `{text, t}` → 回 `image/png`，**不发板子** |

**板子每秒会主动推一条心跳** `STM32F429 在线，已收 N 条…`，它**不是**任何命令的
回应（固件 `Core/Src/echo_service.c` 的 `Echo_Service_Poll()`）。`proto.py` 的
`send_text()` 会把它丢掉继续等真正的回应，否则一次错位之后**每条命令都拿到上一条的回包**。
`INFO` 的回应是 `board 192.168.1.30  tick=… ms  io_count=2`，别和心跳混。

> **为什么 `/play` 是"播 3 秒"而不是"一直播到点停"**：HTTP 请求必须有尽头。
> 否则会出现"页面上什么都看不见、后台线程还在发 UDP 占着板子"这种最难查的状态。

> ⚠ **页面 JS 里没有一行安全判据。** 哪些是写操作、要不要确认，全部由服务端
> （`dispatcher.needs_confirm()` + token 验签）决定。改前端一点也提升不了权限 ——
> 如果安全性由前端代码决定，那它就不是安全性。


---

## 板子端对应什么

| PC 端 | 板子端 |
|---|---|
| `board.send_frame(buf)` 1024 字节 | `Core/Src/framebuf.c` 的 `FB_Dispatch()` |
| `board.send_frame(buf, seq=0)` 1032 字节 | `FBSEQ` 分支 |
| `board.fb_stat()` | `FB?` 命令（`Core/Src/reg_shell.c`） |
| `board.send_text("OLED INIT")` | `OLED` 命令组 |

帧格式：`byte = gfx[(y >> 3) * 128 + x]`，`bit = y & 7`，**bit0 在最上面**。
和 SSD1306 的页寻址一致，所以板子收到后一个字节都不用改就能显示。

看板子收帧的情况：

```bash
python pc_agent/agent.py check      # 里面有 FB? 一行
```

三个计数的含义：

| 计数 | 涨了说明 |
|---|---|
| `good` | 正常。板子收到了，画不出来就是 I2C/屏的问题 |
| `bad` | PC 打包长度错了 |
| `ooo` | 网络乱序丢弃 —— 正常现象，UDP 本来就不保证顺序 |
| 三个都不涨 | 包根本没到板子（IP/端口/防火墙） |

---

## 还能怎么提速

| 手段 | 效果 | 代价 |
|---|---|---|
| `hi2c2.Init.ClockSpeed = 400000` | **约 4 倍，到 ~40fps** | 一行改动，最划算 |
| 脏矩形局部刷新 | 只画变化的区域 | 板子端要改 `framebuf`，帧格式要带矩形信息 |
| 刷屏真正走 DMA | 主循环不再等 I2C | 板子端要改 `oled.c`（见 AGENTS.md §11） |

---

## 出问题时

| 现象 | 先查 |
|---|---|
| `check` 超时 | 网线、板子串口有没有 `[LINK] UP`、`ping 192.168.1.30`、Windows 防火墙 |
| 板子回 PING 但屏不动 | `FB?` 看 `good` 涨不涨；涨了就是 I2C/屏的问题 |
| 画面撕裂/倒退 | 正常丢包。默认已经带 `FBSEQ` 序号抗乱序 |
| 屏全黑 | 发 `OLED INIT` 重试；波特律动驱动会吞掉 I2C 错误，串口不报错 ≠ 写成功 |
| 终端里 `--ascii` 乱码 | Windows 控制台编码，用 `chcp 65001` |
| 页面上说"播个烟花"，回包是 `STM32F429 在线…` | 拿到的是**每秒心跳**不是 `FB?` 的回应（`FB: good=…`），说明 `proto.py` 的过滤或服务进程是旧的 —— **改完 `.py` 要重启 `api.py`** |
| 页面报 `xxx 的执行器还没接` | 画面动作不该走 `/dispatch`：服务端只回 `play:true`，帧由前端再发 `/play` |
| LLM 报错 | 看提示，通常是没设 `DEEPSEEK_API_KEY` |
