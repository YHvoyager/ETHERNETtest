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
| `proto.py` | UDP 通道：文本命令 + 二进制帧 |
| `canvas.py` | 128x64 画布 + 全套画图原语 + 内置 ASCII 字体 |
| `anim.py` | 内置示例动画（eyes / horse / rain / boing / text） |
| `bitmap.py` | 中文点阵渲染（Windows GDI） |
| `sandbox.py` | 沙箱：import 白名单、名字白名单、超时 |
| `agent.py` | 主程序：CLI、LLM 调用、播放循环、代码缓存 |
| `code_cache/` | LLM 写成功过的代码（自动生成） |

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
| LLM 报错 | 看提示，通常是没设 `DEEPSEEK_API_KEY` |
