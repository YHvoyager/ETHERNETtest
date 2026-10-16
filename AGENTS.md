# AGENTS.md — ETHERNETtest 工程工作手册

> **本文件给未来的 AI 助手（和我自己）看。每次改动代码后必须更新本文件。**
> 最后更新：2026-02-13 | 上一次提交：`a9f2452`（本次提交写入时尚未生成哈希）

---

## 0. 工作流约定（用户明确要求）

用户要求（本次会话）：

1. **每次改动代码，必须更新 AGENTS.md。**
2. **先写 AGENTS.md，再 commit。**（顺序很重要，见下）

所以标准流程是：

```
改代码 → 编译验证 → 写/更新 AGENTS.md（变更日志 + 受影响章节）→ git commit
```

**代码改动和 AGENTS.md 的更新放在同一个提交里。** 为什么这样更好：

- 文档与代码**原子落地**，不会出现"代码已提交、文档还没写"的中间状态。
- 变更日志里写的就是这次提交实际达到的状态，不会描述一个尚不存在的状态。
- 回滚提交时，文档和代码一起回滚，不会脱节。

> ⚠ 不要只改代码就结束，也不要先 commit 再补文档。
> **AGENTS.md 和代码是同一个交付物。**

### 0.1 commit message 规范

提交信息用中文，说明**做了什么 + 为什么**；若该次提交同时更新了 AGENTS.md，在正文里点明。
示例见 §9.3。

---

## 1. 工程速览

| 项 | 值 |
|---|---|
| 工程根 | `C:\Users\86185\Desktop\CubeMX\ETHERNETtest` |
| 远程 | `git@github.com:YHvoyager/ETHERNETtest.git` |
| 分支 | `master` |
| 目标板 | 正点原子阿波罗V2（STM32F429IGT6 + YT8512C PHY） |
| 生成器 | STM32CubeMX 6.18.1 → CMake + Ninja + arm-none-eabi-gcc |
| 中间件 | lwIP 2.1.2（`NO_SYS=1` 裸机，无 RTOS） |
| 板子 IP | `192.168.1.30` / 掩码 `255.255.255.0` |
| 串口 | USART1，115200-8-N-1 |
| UDP 回环端口 | `8080` |
| 验收标准 | PC 直连能 ping 通，且网络调试助手能收到回包 |

**当前资源占用**（2026-02-13 编译）：

```
RAM    35680 B / 192 KB   18.15%
CCMRAM     0 B /  64 KB    0.00%
FLASH  81100 B /   1 MB    7.73%
```

---

## 2. 构建与烧录（照抄即可）

### 2.1 工具链绝对路径

```
gcc     C:/Users/86185/AppData/Local/stm32cube/bundles/gnu-tools-for-stm32/14.3.1+st.2/bin/arm-none-eabi-gcc.exe
cmake   C:/Users/86185/AppData/Local/stm32cube/bundles/cmake/4.3.1+st.1/bin/cmake.exe
ninja   C:/Users/86185/AppData/Local/stm32cube/bundles/ninja/1.13.2+st.1/bin/ninja.exe
objcopy 同 gcc 目录
```

### 2.2 编译

```bash
cd C:/Users/86185/Desktop/CubeMX/ETHERNETtest

# 配置（首次，或 CMakeLists.txt 改动后）
cmake.exe -S . -B build/Debug -G Ninja -DCMAKE_BUILD_TYPE=Debug

# 编译
cmake.exe --build build/Debug
```

> 不要再传 `-DCMAKE_TOOLCHAIN_FILE`，build 目录已有缓存，会报 warning。

### 2.3 ⚠ 生成 hex（必做，容易忘）

**ninja 没有 hex target**，必须手工 objcopy：

```bash
arm-none-eabi-objcopy.exe -O ihex build/Debug/ETHERNETtest.elf build/Debug/ETHERNETtest.hex
```

> **踩过的坑**：只跑 `cmake --build` 只更新 `.elf`，`.hex` 留在旧时间戳。
> 直接烧 hex 会烧进旧固件。**每次编译后必须重新 objcopy + 检查时间戳。**

### 2.4 新增源文件必须登记

新 `.c` 文件要加到根 `CMakeLists.txt` 的 `target_sources()`，否则不参与编译：

```cmake
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/debug_uart.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/eth_phy.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/board_io.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/reg_shell.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/oled.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/font.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/echo_service.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/udp_echo.c
)
```

> **不要手改 `cmake/stm32cubemx/CMakeLists.txt`** —— 那是 CubeMX 生成的主清单，
> 重新生成会被覆盖。用户源文件统一加在**根 `CMakeLists.txt`**。

---

## 3. 代码结构与职责

```
ETHERNETtest/
├── AGENTS.md                  ← 本文件（每次改动必更新）
├── CMakeLists.txt             ← 用户源文件登记处（唯一需要手改的 CMake 文件）
├── CMakePresets.json          ← Debug / Release 预设
├── ETHERNETtest.ioc           ← CubeMX 工程文件
├── core/  (Core/)
│   ├── Inc/
│   │   ├── eth_phy.h          板级补丁接口（3 函数）
│   │   ├── debug_uart.h       printf 重定向接口
│   │   ├── board_io.h         板级 IO 注册表接口（DS0/DS1）
│   │   ├── reg_shell.h        ★ 以太网命令接口（LED / R / W / OLED）
│   │   ├── oled.h             ★ 波特律动 SSD1306 驱动接口（第三方）
│   │   ├── font.h             ★ 字库接口：afont16x8 / font16x16（第三方）
│   │   ├── echo_service.h     带话术的回声服务接口（**当前启用**）
│   │   ├── udp_echo.h         UDP 原样回环接口（保留，未启用）
│   │   ├── main.h / i2c.h / usart.h / gpio.h / stm32f4xx_it.h / stm32f4xx_hal_conf.h
│   └── Src/
│       ├── eth_phy.c          ★ 板级补丁（MspInit + PHY 复位 + PHY 准备 + 诊断）
│       ├── board_io.c         ★ 板级 IO 注册表（扩展点：加一行就多一个可控 IO）
│       ├── oled.c             ★ 波特律动 SSD1306 驱动（第三方，用 I2C2）
│       ├── font.c             ★ 波特律动字库：ASCII 8x6/12x6/16x8/24x12 + 中文 16x16
│       ├── reg_shell.c        ★ 命令解析 + 寄存器读写地址白名单 + OLED 命令
│       ├── echo_service.c     ★ 带话术的 UDP 回声 + 命令分发（当前启用的应用）
│       ├── udp_echo.c         UDP 原样回环（保留，未启用，端口与上面冲突）
│       ├── debug_uart.c       printf → USART1
│       ├── main.c             初始化顺序 + 主循环
│       ├── i2c.c / usart.c / gpio.c / stm32f4xx_hal_msp.c / stm32f4xx_it.c
│       └── syscalls.c / sysmem.c / system_stm32f4xx.c
├── LWIP/
│   ├── App/lwip.c             MX_LWIP_Init() / MX_LWIP_Process()，gnetif 定义处
│   └── Target/
│       ├── ethernetif.c       lwIP 网卡驱动（有 5 处手工改动）
│       ├── lwipopts.h         lwIP 配置
│       ├── eth_custom_phy_interface.c  ST 通用 PHY 驱动（**未使用**）
│       └── eth_custom_phy_interface.h
├── Drivers/                   STM32F4 HAL + CMSIS（CubeMX 生成）
├── Middlewares/               lwIP 源码 + FreeRTOS（239 文件）
├── docs/lwip-f429-apollo-v2.md  ★ 详细技术文档（597 行，含 4 个故障的完整排查）
└── build/                     编译输出（已 gitignore）
```

### 3.1 关键文件职责

| 文件 | 职责 | 备注 |
|---|---|---|
| `Core/Src/eth_phy.c` | 把 CubeMX 漏掉的三件事集中于此 | **本工程最重要的文件** |
| `Core/Src/main.c` | 初始化顺序（**不能改**） | 见 3.3 |
| `Core/Src/board_io.c` | 板级 IO 注册表（DS0/DS1） | **扩展点**，见 3.6 |
| `Core/Src/reg_shell.c` | 命令解析 + 寄存器读写白名单 | 见 3.7 |
| `Core/Src/oled.c` | 波特律动 SSD1306 驱动（第三方） | 用 `hi2c2`，见 3.9 |
| `Core/Src/font.c` | 波特律动字库（ASCII + 中文 16x16） | 第三方，见 3.9 |
| `Core/Src/echo_service.c` | **当前启用的应用**：UDP 8080 回声 + 心跳 + 命令分发 | 见 3.5 |
| `Core/Src/udp_echo.c` | UDP 8080 原样回环 + 每秒心跳 | **未启用**，端口与上面冲突 |
| `LWIP/App/lwip.c` | `gnetif` 定义（`:45`）、IP 配置（`:63-66`） | |
| `LWIP/Target/ethernetif.c` | 网卡驱动，5 处手工改动 | 见 3.4 |

> ⚠ **`echo_service.c` 与 `udp_echo.c` 不能同时启用**：两者功能重叠且默认都用
> **8080** 端口，一个 UDP 端口只能被一个 pcb 绑定（第二个 `udp_bind` 返回 `ERR_USE`）。
> `main.c` 里二选一，当前用 `Echo_Service_Init()`。要换回原样回环，把
> `Echo_Service_Init()`/`Echo_Service_Poll()` 注释掉、启用 `UDP_Echo_Init()`/`UDP_Echo_Poll()`。

### 3.2 `eth_phy.c` 四个函数

| 函数 | 职责 | 调用时机 |
|---|---|---|
| `ETH_PHY_ReleaseReset()` | I²C2 写 PCF8574，释放 PHY 复位 | `main()` 里，**`MX_LWIP_Init()` 之前** |
| `HAL_ETH_MspInit()` | 补 9 根 RMII 引脚 AF11 + ETH 时钟 | HAL 内部自动调 |
| `ETH_PHY_Prepare()` | MDC 分频 + 保证自协商开 + 调诊断 | `low_level_init()` 里，`HAL_ETH_Init()` 之后 |
| `ETH_PHY_Dump()` | 扫 MDIO，打印 PHY ID/BCR/BSR | 由 `Prepare()` 调；`ETH_PHY_DIAG 0` 可关 |

### 3.3 `main.c` 初始化顺序（**不能改**）

```c
MX_GPIO_Init();
MX_USART1_UART_Init();
MX_I2C2_Init();                    /* PCF8574 挂在 I2C2 上，必须先初始化 */

ETH_PHY_ReleaseReset();            /* ← 必须在 MX_LWIP_Init() 之前！ */

MX_LWIP_Init();                    /* 内部：ethernetif_init → low_level_init
                                    *   → HAL_ETH_Init → HAL_ETH_MspInit
                                    *   → ETH_PHY_Prepare → HAL_ETH_Start */

Echo_Service_Init();               /* 当前启用。netif 得先 add/up，udp_bind 才有意义 */

while (1)
{
  MX_LWIP_Process();               /* ethernetif_input + sys_check_timeouts + 链路检查 */
  Echo_Service_Poll();             /* 非阻塞，内部 1 秒节流 */
}
```

> **要换回 `udp_echo.c` 的原样回环**：把 `Echo_Service_Init()`/`Echo_Service_Poll()`
> 换成 `UDP_Echo_Init()`/`UDP_Echo_Poll()`。**两者端口都是 8080，绝不能同时开。**

> ⚠ **`while(1)` 里绝对不能加阻塞式轮询。** 曾经一个用未初始化句柄的轮询函数
> 导致 CPU 被卡死、`MX_LWIP_Process()` 被饿死，表现为"每 64 秒报一次错"、ping 不通。

### 3.4 `ethernetif.c` 的 5 处手工改动（**CubeMX 重新生成会丢，需重做**）

| 位置 | 改动 | 原因 |
|---|---|---|
| `:149-154` | MAC 改为 `02:00:00:12:34:56` | 原占位值 `00:80:E1:00:00:00` 尾段全零，某些网卡会把帧当异常丢弃 |
| `:206` | 加 `ETH_PHY_Prepare();` | MDC 分频 + 自协商 |
| `:213` | 调 `ethernet_link_check_state(netif)` | CubeMX 生成的是空函数 |
| `:220` | 加 `HAL_ETH_Start(&heth)` | **ping 不通的直接原因** |
| `:475` | 实现 `ethernet_link_check_state()` | 读 BSR bit2 判链路 |

### 3.5 `echo_service.c` —— 带话术的回声服务（当前启用的应用）

**功能**：收到任何 UDP 报文后，用中文话术回答，便于人肉核对内容：

```
我收到你的信息了，是"hello"吗？
```

**接口**（`Core/Inc/echo_service.h`）：

| 函数 | 职责 |
|---|---|
| `Echo_Service_Init(void)` | `udp_new()` + `udp_bind(0.0.0.0, ECHO_SERVICE_PORT)` + `udp_recv()` |
| `Echo_Service_Poll(void)` | 每秒向"最近一次来包的 PC"推中文心跳，非阻塞 |
| `Echo_Service_Reply(msg,len)` | 把文本回给最后来包的 PC —— **命令实现用它回包** |
| `Echo_Service_ReplyRaw(data,len)` | 同上，但语义是二进制 |
| `Echo_Service_ReplyBoth(data,len)` | 大帧：同时发给命令来源和 `BROADCAST` 订阅端口 |
| `Echo_Service_ReplyChunked(data,len,mtu)` | 按 mtu 切片逐片发（给"必须完整送达"的场景） |
| `Echo_Service_SetBroadcast(ip,port)` | 设置/关闭大帧的第二发送目标；`ip=NULL,port≠0` = 用当前 peer |

**分层发送**（新加的能力，见 §5 决策表）：

```
命令处理（reg_shell.c）
    └─ Echo_Service_Reply()          短应答：走 s_tx_buf → send_to_peer()
    └─ Echo_Service_ReplyBoth()      大帧：两路都发
            ├─ send_to_peer()        普通回包（最后来包的 PC）
            └─ send_raw()            直发 s_bcast_ip:s_bcast_port
                      ▲
       send_to_addr() ─┘ 拷进 s_tx_buf 再走 send_raw
                      ▲
            send_raw()  ← 最底层：不拷贝、不截断，len 上限 u16_t
```

> **为什么 `send_to_peer()` 挡在 512 字节**：它复用 `s_tx_buf`，
> 而 `ECHO_TX_BUF_SIZE` 就是 512。要发更大的东西必须走 `send_raw()`。

**关键常量**（`Core/Src/echo_service.c`）：

| 宏 | 值 | 说明 |
|---|---|---|
| `ECHO_SERVICE_PORT` | `8080U` | 在 `.h` 里，可用 `#ifndef` 覆盖 |
| `ECHO_MAX_PAYLOAD` | `260U` | 单条应答最多回显多少字节原文（**按字节，截断后会对齐到字符边界**） |
| `ECHO_TX_BUF_SIZE` | `512U` | 组包缓冲；**static 而非栈上**，因为栈只有 1024 字节 |
| `ECHO_BEAT_INTERVAL` | `1000U` | 心跳间隔 ms |

**四个值得记住的实现细节**：

1. **中文用 `\xNN` 转义写**（`"\xE6\x88\x91..."`），不直接把 UTF-8 汉字写进字符串
   字面量。原因：源码文件编码、`-fexec-charset`、编译器对 BOM 的处理都会影响
   直接写汉字的字节序列，而 `\x` 转义是 UTF-8 码元的精确表达，编出来的字节
   与编译环境无关。
2. **引号用 ASCII `"` (0x22)，不用全角 `"`**。全角引号是 3 字节，网络调试助手
   编码设置稍有偏差就显示成乱码；ASCII 引号无此风险。句末的全角问号 `？`
   (`\xEF\xBC\x9F`) 保留。
3. **`sanitize_inplace()` 只过滤 `< 0x20` 的控制字符**，`0x7F` 及以上**原样保留**。
   这是中文能回显的前提 —— UTF-8 汉字 3 个字节每个都 ≥ 0x80，早先写成
   "`c < 0x20 || c > 0x7E` 就换成 `.`" 会把中文整个打成点（见 §8 排查表）。
4. **截断必须先回退到字符边界**：`utf8_trim_incomplete()` 从开头按首字节推出每个
   字符的长度（0x00~0x7F→1、0xC0~0xDF→2、0xE0~0xEF→3、0xF0~0xF7→4），只能输出
   最后一个**完整**字符为止。直接把 260 字节硬砍，会把 3 字节的汉字砍成 1~2 字节，
   那不是合法 UTF-8，助手只会显示成替换符。裸续字节（0x80~0xBF）和非法首字节
   （0xF8~0xFF）按 1 字节透传，不悄悄改写别人的编码问题。
   原始字节先收进 `static char s_rx_raw[ECHO_MAX_PAYLOAD + 4]`（多留 3 字节用于判断
   末字符是否被砍断），再截断 + 过滤，**原始数据不被就地破坏**。

> **为什么组包缓冲用 `static char s_tx_buf[512]`**：STM32F429 的栈是
> `0x400` = 1024 字节（见 `startup_stm32f429xx.s`），回调里放 512 字节局部数组
> 等于半个栈，加上 `printf` 的调用深度就危险了。该缓冲只在主循环上下文使用，
> 不存在重入，static 是安全的。`s_rx_raw` 同理（原先它是个 261 字节的栈数组
> `char text[ECHO_MAX_PAYLOAD + 1U]`，一并挪到了 static）。

### 3.6 `board_io.c` —— 板级 IO 注册表（扩展点）

**这是个表，不是逻辑。** 目的是把"板上有哪些可控 IO"和"怎么解析命令"彻底分开：
将来加一个 LED / 继电器 / 蜂鸣器，**只在这张表里加一行**，命令解析、帮助文本、
大小写处理全都不用动。

**接口**（`Core/Inc/board_io.h`）：

| 函数 | 职责 |
|---|---|
| `Board_IO_Init(void)` | 初始化表里所有 IO 的硬件（时钟 + 输出电平） |
| `Board_IO_Count(void)` | 表项数量 |
| `Board_IO_Get(size_t idx, ...)` | 按下标取名字 + 当前电平 |
| `Board_IO_Find(const char *name)` | 按名字查下标（**大小写不敏感，`-`/`_` 等价**），找不到返回 `-1` |
| `Board_IO_Write(size_t idx, int level)` | 写电平，**同时更新影子变量** |
| `Board_IO_Toggle(size_t idx)` | 翻转 |
| `Board_IO_ReadRaw(size_t idx)` | 读**实际引脚**电平（与影子对照可验证写入是否真的生效） |

**表项结构**（`Core/Src/board_io.c`）：

```c
typedef struct {
    const char *name;       /* "DS0" */
    GPIO_TypeDef *port;     /* GPIOB */
    uint16_t pin;           /* GPIO_PIN_0 */
    uint8_t active_low;     /* 1 = 低电平点亮 */
    uint8_t cur_level;      /* 影子：当前"点亮/熄灭"逻辑电平 */
} board_io_t;
```

**当前表内容**：

| 名字 | 引脚 | 有效电平 | 说明 |
|---|---|---|---|
| `DS0` | `PB0` | 低电平点亮（`active_low=1`） | 正点原子阿波罗V2 板载 LED0 |
| `DS1` | `PB1` | 低电平点亮（`active_low=1`） | 正点原子阿波罗V2 板载 LED1 |

**两个关键设计**：

1. **`active_low` 抽象**：命令层说"点亮/熄灭"，表里翻译成引脚电平。扩展时
   遇到高电平有效的器件（如继电器）只需填 `active_low=0`，命令语义不变。
2. **影子变量 `cur_level`**：`Board_IO_Write()` 既写引脚也记下逻辑电平，于是
   `LED` 查询、`TOGGLE` 翻转都不需要回读引脚。`Board_IO_ReadRaw()` 保留下来
   专门用于对照验证（影子说亮、引脚却是灭 → 说明配置错了）。

> ⚠ **PB0/PB1 在 CubeMX 里原本是 ETH 的备用引脚还是普通 GPIO，以 `.ioc` 为准。**
> 若 CubeMX 重新生成后 `MX_GPIO_Init()` 不再初始化 PB0/PB1，`Board_IO_Init()`
> 会自己配一次（内部调用 `__HAL_RCC_GPIOB_CLK_ENABLE()` + `HAL_GPIO_Init()`），
> 不依赖 CubeMX 生成代码 —— 这样重新生成也不会失效。

### 3.7 `reg_shell.c` —— 以太网命令接口

**功能**：把 UDP 收到的**文本**当作命令行解析，执行后把结果组包回给发信人。
这是"AI 通过以太网操作单片机"的入口。

**命令表**：

| 命令 | 语法 | 作用 |
|---|---|---|
| `HELP` / `?` | `HELP` | 打印命令表与当前 IO 状态 |
| `LED` | `LED` | 列出所有可控 IO 及其状态 |
| | `LED DS0 1` / `LED DS0 0` | 点亮 / 熄灭 DS0（`ON`/`OFF`/`HIGH`/`LOW` 也接受） |
| | `LED DS0 TOGGLE` | 翻转 DS0 |
| `R` | `R <addr> <count>` | 读寄存器，addr/count 都是**十六进制**，count 上限 16 |
| `W` | `W <addr> <value>` | 写 32 位寄存器，addr/value 都是**十六进制** |
| `RB`/`WB` | `RB <addr>` / `WB <addr> <value>` | 8 位读写（`tok[0][1]=='B'` 判据） |
| `OLED` | `OLED` | 把帧缓冲渲染成 4×16 格 `#`/`.` ASCII 示意发回来（**不反查字库**） |
| | `OLED SCAN` | 扫 I2C2 总线，列所有应答的 7 位地址（OLED 应为 `0x3C`） |
| | `OLED CLR` / `OLED FILL` | 清屏 / 全亮 |
| | `OLED TXT <行 0..3> <文本...>` | 在指定行写字（先擦该行再画，见 §3.9 的字库分派） |
| | `OLED PIX <x> <y> [0\|1]` | 画/擦一个像素 |
| | `OLED RD <寄存器>` | **直接读 SSD1306 寄存器**（波特律动 `OLED_ReadCmd`），排障用 |
| | `OLED REFRESH` | 按 `s_oled_lines[]` 重画整屏 |
| | `OLED BAR <x> <y> <w> <h> [0\|1]` | 实心矩形（给"动眼睛"打底） |
| | `OLED STAT` | 后台刷屏状态：`busy=` / `dropped=`（调优用） |
| | `OLED RAW <ctrl> <hex...>` | 把原始字节直发 `0x78`，**完全绕开驱动**的逃生口 |
| `BROADCAST` | `BROADCAST [port]` | 大帧回包另发一份到这个端口（`0` = 关） |
| `PING` | `PING` | 回 `PONG tick=...`，最便宜的"活着吗"探测 |

**`R`/`W` 的地址白名单（安全边界，极其重要）**：

`R`/`W` 能读写任意 32 位地址，等于把整颗芯片的控制权交出去。若不加限制，
一句 `W 40023800 0`（RCC 时钟寄存器）就能把板子写砖，或写坏 Flash/外设配置。
所以 `reg_shell.c` 开头有一张**显式白名单**，只有落在白名单里的地址才允许访问，
其实现方式是**地址范围表 + 逐项比对**，命中范围外的地址一律回
`[ERR] address 0x........ is not in the allow-list`。

**当前白名单**：

| 范围 | 含义 |
|---|---|
| `0x40020000` ~ `0x40023FFF` | GPIOA~GPIOK 外设寄存器 |
| `0x40023800` ~ `0x40023BFF` | RCC —— ⚠ **只读，禁止写**（写 RCC 会掉时钟/变砖） |

> **要加新的可访问外设，就在白名单表里加一行范围**，不要放开整片 `0x40000000`。
> 宁可"加一次改一次"，也不要一个能写坏板子的万能后门。

**其他实现要点**：

- **解析大小写不敏感**，`led ds0 on` == `LED DS0 ON`。
- **回包缓冲与回声服务一样是 static**（`s_reply[REG_SHELL_REPLY_MAX]`，栈只有 1024 字节）。
- **超长的 `W` 值会被拒**（`parse_hex32()` 溢出检测），不静默截断。
- **越界地址在真正读写前就拦住**，不是先读了再判断。
- 命令处理是**纯函数式**的：`Reg_Shell_Execute(const char *cmd, char *out, size_t out_size)`
  返回 `0` 成功、非 0 失败，不直接调 `udp_sendto()`。这样将来换传输方式
  （TCP / 串口 / 甚至 MQTT）都不用改 `reg_shell.c`。

### 3.8 命令分发是怎么接进回声服务的

`Core/Src/echo_service.c` 的回调里**先看内容再决定怎么答**：

```
收到 UDP 包
   │
   ├─ 以 "ECHO " 或 "echo " 开头 ──→ 走原来的中文话术回显
   │
   └─ 否则 ──→ 交给 Reg_Shell_Execute() 当命令解析
                 │
                 ├─ 返回 0 ──→ 回显执行结果
                 └─ 返回非0 ──→ 回显 "[ERR] unknown command ..." + HELP 提示
```

**为什么要一个 `ECHO ` 前缀**：不加前缀的话，"hello" 这种普通测试文本会被
当成未知命令回错误，原来的回声测试就没法用了。加前缀让两种用法共存：

| 你发的内容 | 板子的回答 |
|---|---|
| `ECHO hello` | `我收到你的信息了，是"hello"吗？` |
| `LED DS0 1` | `[OK] DS0 (PB0) = ON` |
| `LED` | 列出 DS0/DS1 状态 |
| `R 40020014 2` | 读 GPIOB 的 ODR/... 十六进制值 |
| `hello` | `[ERR] unknown command: hello` + HELP 提示 |

> **触发心跳的行为不变**：任何来包都会更新"最近一次来包的 PC"，所以命令
> 发过一次之后，心跳仍会每秒推给那台 PC。

### 3.9 `oled.c` / `font.c` —— OLED 驱动（波特律动，第三方）

**驱动来源**：波特律动（BaudDance）`oled.c` / `oled.h` / `font.c` / `font.h`，
用户提供的第三方代码，**不是自己写的**。此前自己写过一版 `ssd1306.c`，
已废弃删除（见 §10 变更日志）。

**接线**：SSD1306 128×64 挂在**已有的 I2C2**（`PH4`=SCL / `PH5`=SDA），
7 位地址 `0x3C`（写到驱动的 8 位形式是 `0x78`）。I2C2 上同时挂着 PCF8574
（`0x20`，管 ETH_RESET）—— **地址不冲突可共存**，但两个上拉并联会让等效
阻值偏低。

**接口**（`Core/Inc/oled.h`，第三方原本的 API —— 以代码为准，别凭记忆）：

| 函数 | 职责 |
|---|---|
| `OLED_Init(void)` | 初始化序列（含电荷泵 `0x8D 0x14`），**返回 void，不做 ACK 探测** |
| `OLED_DisPlay_On(void)` / `OLED_DisPlay_Off(void)` | 开/关显示 |
| `OLED_NewFrame(void)` | 清显存（`memset(OLED_GRAM, 0, ...)`，**0 = 全亮**） |
| `OLED_ShowFrame(void)` | 把显存推到屏上（**异步版**，见 §3.10） |
| `OLED_ShowFrameBlocking(void)` | 同上的阻塞版（自己加的，初始化时用） |
| `OLED_SetPixel(x, y, OLED_ColorMode)` | 一个像素（**bit=1 表示灭，bit=0 表示亮**） |
| `OLED_DrawLine` / `OLED_DrawRectangle` / `OLED_DrawFilledRectangle` / `OLED_DrawTriangle` / `OLED_DrawFilledTriangle` / `OLED_DrawCircle` / `OLED_DrawFilledCircle` / `OLED_DrawEllipse` | 图形 |
| `OLED_DrawImage(x, y, const Image *img, OLED_ColorMode)` | 贴位图 |
| `OLED_PrintASCIIChar` / `OLED_PrintASCIIString` | ASCII（`afont8x6` / `afont12x6` / `afont16x8` / `afont24x12`） |
| `OLED_PrintString(x, y, str, const Font *, OLED_ColorMode)` | 中英混排，查 `font16x16`，**查不到且是 ASCII 就退化成 `font->ascii`，否则画空格** |

**几何宏不在头文件里**：`OLED_ADDRESS 0x78` / `OLED_PAGE 8` / `OLED_COLUMN 128`
都定义在 `Core/Src/oled.c` **内部**。`reg_shell.c` 因此**自写了一份本地常量**
（`OLED_COLS_V` / `OLED_PAGES_V` / `OLED_ADDR_8BIT`）+ `extern uint8_t OLED_GRAM[8][128];`
—— 这样将来升级第三方驱动不会把本文件一起弄坏。

**字库分派（重要坑）**：`font.c` 里 `afont8x6`/`afont12x6`/`afont16x8`/`afont24x12`
是 ASCII，`font16x16` 是中文 —— 但**中文只有 4 个字：「波特律动」**
（UTF-8 `e6 b3 a2` / `e7 89 b9` / `e5 be 8b` / `e5 8a a8`），另有 `bilibiliImg`。

> ⚠ `OLED_PrintString()` 查的是**字模数据**不是汉字码，查不到就画空格。
> 所以**板子上显示不了任意中文**。要在 OLED 上显示中文，走 PC 端渲染点阵
> + `FB` 帧通道（见 §3.11）。`OLED TXT` 命令只对 ASCII 有效。

**与 CubeMX 的关系**：驱动用的是全局 `hi2c2`（`Core/Src/i2c.c` 里定义），
所以 `MX_I2C2_Init()` 必须已经跑过 —— `main.c` 里 `OLED_Init()` 的调用点
在 `ETH_PHY_ReleaseReset()` **之后**，理由见 §3.3。

> ⚠ **OLED 初始化放在 PHY 复位之后，是为了隔离风险**：OLED 若把 I2C2 总线
> 拉死，`ETH_PHY_ReleaseReset()` 会失败并让 `main()` 停在 `while(1) HAL_Delay(1000)`，
> 板子永远起不来。放后面最坏只是屏不亮，网络不受影响。

> ⚠ **不要用"探测 ACK"来决定是否继续初始化**。自己写的那版 `ssd1306.c`
> 就是在最前面先发一条 `0xAE` 探测，一次短传输没成功就 `return -1` 放弃整条
> 初始化路径，报 `[OLED] FAIL: no ACK from 0x78` —— 而实测 `0x3C` 是**真的有
> 器件在应答**。波特律动驱动完全不探测、一口气写完 30 多条命令，反而成功。
> **探测失败只代表这一次传输没成功，不代表设备不在。**

> ⚠ **`OLED_Send()` 返回 void，吞掉所有 HAL 错误**。串口不报错 ≠ 写成功。
> 屏不亮时发 `OLED INIT` 重试，而不是去串口找错误信息。

### 3.10 OLED 刷屏是异步状态机（性能关键）

`OLED_ShowFrame()` **不是**阻塞发完 8 页，而是启动一个状态机，由主循环
里的 `OLED_FlushPoll()` 一步一步推进：

```
OLED_ShowFrame()   → 置 s_flush_active=1, s_flush_page=0，发第 0 页的换页命令
MX_LWIP_Process()  → 主循环继续跑，lwIP 不受影响
OLED_FlushPoll()   → 发第 0 页的 129 字节数据，stage 0→1
OLED_FlushPoll()   → 发第 1 页的换页命令，stage 1→0，page++
...                → 8 页走完，s_flush_active=0
```

**为什么**：整屏 1024 字节 @100kHz ≈ **92ms**。阻塞发完的话
`MX_LWIP_Process()` 有 92ms 完全停摆 —— ping 会超时、心跳间隔从 1000ms
变成 1090ms 以上。拆成 8 步后每步约 2.8ms，lwIP 每 2.8ms 就能跑一次。

| 接口 | 语义 |
|---|---|
| `OLED_ShowFrame(void)` | 异步启动。**上一帧还没发完就调用 → 直接丢弃（`s_flush_dropped++`）** |
| `OLED_FlushPoll(void)` | 推进一步。返回 1 = 还在发，0 = 发完了。**主循环必须每轮调它** |
| `OLED_FlushBusy(void)` | 查询是否在发 |
| `OLED_FlushDropped(void)` | 读走并清零丢弃计数（对应 `OLED STAT` 的 `dropped=`） |
| `OLED_ShowFrameBlocking(void)` | 老的阻塞版。**`OLED_Init()` 里必须用它** |

> ⚠ **`OLED_Init()` 内部的清屏必须用阻塞版**。`oled.c:153` 原本是
> `OLED_NewFrame(); OLED_ShowFrame();` —— 异步版只发第一页就返回，而且
> 它是在 `main()` 进主循环**之前**跑的，`s_flush_active` 会一直挂着，
> 导致主循环第一次刷屏被当成"上一帧没发完"丢弃，屏上只有第一页。
> **已修为 `OLED_ShowFrameBlocking()`。**

> ⚠ **`main.c` 的 `while(1)` 里必须有 `OLED_FlushPoll();`**，少了它整屏只
> 会送出第一页。

> ⚠ **本轮仍是阻塞的 `OLED_Send()` ⟶ `HAL_I2C_Master_Transmit(..., HAL_MAX_DELAY)`，
> 并没有真正用 DMA。** `Core/Src/dma.c` 里 CubeMX 生成的 `hdma_i2c2_tx`
> （DMA1_Stream7 / CH7 / MEMORY_TO_PERIPH）与 `I2C2_EV_IRQHandler` 目前
> **没有被 `oled.c` 使用**。见 §11 待办。

**中断为什么必须补**：`Core/Src/dma.c` 的 `MX_DMA_Init()` 里补了
`I2C2_EV_IRQn` / `I2C2_ER_IRQn` 的 NVIC（`.ioc` 只勾了 DMA1_Stream2/7，
I2C2 的 NVIC 没勾），`Core/Src/stm32f4xx_it.c` 里补了对应的两个 Handler。
**少了 Handler 的后果很隐蔽**：第一次刷屏正常，之后所有 I2C（**包括
PCF8574 上的 ETH_RESET**）都会 `HAL_BUSY` —— 因为 DMA 传完只说明"数据
塞进 TXDR 了"，要 TC 中断才能把 `hi2c2.State` 从 `BUSY_TX` 放回 `READY`。

> ⚠ **改动 `.ioc` 后 `MX_DMA_Init()` 会被重新生成**，补进去的 NVIC 四行会丢。
> 补在**函数体内**（不是文件末尾的 `USER CODE BEGIN 2` —— 那个块在
> `dma.c` 里位于函数闭合花括号之后，是文件作用域，写代码会编译错）。

### 3.11 二进制帧通道 —— `FB` / `FBSEQ`（PC 端动画的入口）

板子端 `Core/Src/framebuf.c`，PC 端 `pc_agent/`。

**为什么需要它**：`OLED PIX` / `W` 这类命令一次才改几个像素，而全屏一帧
是 1024 字节。15fps × 1024 字节用 4 字节一条的 `W` 要几十万条命令/秒 ——
物理上做不到。**正确抽象是一次 UDP 包 = 一帧。**

| 命令 | 长度 | 说明 |
|---|---|---|
| `FB <1024 字节>` | 1024 | 不带序号，板子只按长度识别 |
| `FBSEQ <u16 LE 序号> <1024 字节>` | **1032** | 带序号，抗 UDP 乱序/重复 |
| `FB?` | 文本 | 回 `FB: good=N bad=N ooo=N` |

**帧格式（与 SSD1306 页寻址完全一致，板子收到后一个字节都不用改）**：

```
byte = gfx[(y >> 3) * 128 + x]
bit  = y & 7          // bit0 在最上面
```

**判据只看长度**（`FB_Dispatch()`）：`len == 1032` 校验 `"FBSEQ "` 头后
按序号处理；`len == 1024` 直接当整帧。其它长度一律 `return 0` 交回文本
路径 —— 文本命令上限 191 字节，**永远不会撞上**。

**序号比较用 `int16_t` 差值**：`if ((int16_t)(seq - s_next_seq) <= 0) { s_ooo++; }`
—— 这样 u16 回绕是正确的（0xFFFF → 0x0000 不会误判成倒退）。

**分发点必须在 `echo_recv()` 的最前面**（记住发信人之后、"取出原文"之前）：
后面的「对齐字符边界 + 过滤控制字符」会把二进制数据毁掉（`0x00` 被替成 `.`）。

**故意不回包**。20~30fps 等往返会被时延卡死；要看统计就发文本命令 `FB?`。

**发帧率高于屏幕刷新率是故意的**：I2C 100kHz 下整屏约 92ms ≈ **11fps 硬上限**，
而 PC 默认发 20fps，多出的帧被板子直接覆盖。这样即使丢包，板子也总是
拿到最新画面。**以太网侧根本不是瓶颈 —— 瓶颈是 I2C。**

> ⚠ `s_stage[FB_BYTES]`（1024 字节）**必须是 static**。本工程栈只有
> 1024 字节（见 `startup_stm32f429xx.s`），放栈上直接溢出。

### 3.12 `pc_agent/` —— PC 端 agent（自然语言 → OLED）

用户描述画面 → LLM 写 `draw(c, t, p)` → 沙箱执行 → 每帧 1024 字节 UDP 发出。

| 文件 | 职责 |
|---|---|
| `proto.py` | UDP 通道：`send_text()` 文本命令 + `send_frame()` 二进制帧 |
| `canvas.py` | 128×64 画布 + 全套画图原语 + 6x8 ASCII 字体 |
| `bitmap.py` | 中文点阵渲染（Windows GDI，无需第三方库） |
| `anim.py` | 内置示例动画：`eyes` / `horse` / `rain` / `boing` / `text` |
| `sandbox.py` | 沙箱：import 白名单 + 名字白名单 + 超时 |
| `agent.py` | CLI、LLM 调用、播放循环、代码缓存 |
| `code_cache/` | LLM 写成功过的代码（自动生成，按描述哈希索引） |

**设计决策（重要，改动前先想清楚）**：

| 决策 | 理由 |
|---|---|
| **让 LLM 写代码，不做"动作库"** | 预置 `eyes()`/`horse()` 的能力被写代码的人锁死；想要"打哈欠的猫"库里没有就卡住。现写代码后，能力上限 = 模型写码能力 × 画布原语表达力，两者都在持续变好 |
| **只给画布，绝不把 Board 传进沙箱** | LLM 代码碰不到网络/I2C/文件系统 |
| **沙箱只挡手滑，不挡攻击者** | 纯 Python 沙箱绕得过去。定位是把手滑代价从"删文件"降到"报错" |
| **每帧从空白开始，禁用函数外状态** | 纯函数才能随机跳到 `t=5.0` 渲染预览图 |
| **按绝对时间轴对齐，不 `sleep(1/fps)`** | 渲染耗时会累积成系统性帧率偏低 |
| **代码落盘缓存** | 这就是 skill accumulation：知识在文件里不在权重里。第一次 3 秒，第二次 0 秒 |
| **中文走 PC 点阵，不给板子加字库** | 板子侧只需"收 1024 字节画一屏"这一件事；内容的复杂度留在 PC 端，改动画不用重新烧固件 |

> ⚠ `pc_agent/` 是**纯 PC 端代码，不参与固件编译**，`CMakeLists.txt` 里
> 也不需要登记。

---

## 4. 四个串行故障（历史记录，避免重蹈）

这四个故障是**串行**的，任何一个没修网口都不通，且现象各不相同。
**排查必须按此顺序，后面的会掩盖前面的。**

| # | 故障 | 现象 | 根因 | 修法 |
|---|---|---|---|---|
| 1 | PHY 复位未释放 | RJ45 双灯全灭 | ETH_RESET 挂 PCF8574 P7，CubeMX 不知道 | `ETH_PHY_ReleaseReset()` |
| 2 | `HAL_ETH_MspInit` 是空 | MDIO 读不到/读垃圾 | HAL 库里是 `__weak` 空函数 | 自己写强符号覆盖 |
| 3 | MDC 超频 4.29MHz | 寄存器值脏（link 位读错） | `HAL_ETH_Init()` 不配 `MACMIIAR.CR`，默认 HCLK/42 只在 60~100MHz 合法；本板 180MHz | `HAL_ETH_SetMDIOClockRange()` |
| 4 | `HAL_ETH_Start` 未调用 | 链路 UP 但 ping「无法访问目标主机」 | `HAL_ETH_Init()` 不开 MAC TE/RE、不启 DMA ST/SR | `low_level_init()` 里补 |

### 4.1 硬件事实（原理图确认，不要凭记忆改）

```
PHY      : YT8512C (U2)，地址 0（PHYADD0/1 都去驱动 LED，没拉地址）
ETH_RESET: PCF8574T (U11) 的 P7，经 Q1 反相
            P7=1 → 复位    P7=0 → 正常工作
PCF8574  : A2/A1/A0 全接地 → 7 位地址 0x20 → HAL 8 位格式 0x40
IIC      : PH4 = SCL, PH5 = SDA (I2C2, AF4)
RMII     : PA1 REF_CLK, PA2 MDIO, PA7 CRS_DV, PC1 MDC,
           PC4 RXD0, PC5 RXD1, PB11 TX_EN, PG13 TXD0, PG14 TXD1  (全部 AF11)
时钟     : HSI，PLLM=8 PLLN=180 PLLP=DIV2 → SYSCLK=HCLK=180MHz
```

### 4.2 ⚠ PCF8574 血泪教训

**PCF8574 是准双向口，没有方向寄存器。写一个字节就是驱动全部 8 个引脚。**

| 位 | 信号 | 有效电平 |
|---|---|---|
| P0 | BEEP | **低有效**（Q4 是 PNP） |
| P3 | USB_PWR | **高有效**（拉低 → CH340 串口掉线） |
| P6 | RS485_RE | |
| P7 | ETH_RESET | **高 = 复位** |

> **规矩**：初值必须 `0xFF`（`PCF_POWER_ON_DEFAULT`），之后**只改目标那一位**，
> 其余位永不触碰。曾写 `0x80` 导致**蜂鸣器狂响 + USB 串口掉线**。

---

## 5. 设计决策与「不要动」清单

以下是踩坑后确定的，**改动前先想清楚**：

| 决策 | 理由 |
|---|---|
| **自协商修复只做一次** | 放进 100ms 的 `ethernet_link_check_state()` 会导致每次轮询都 `RESTART_AUTONEG`，协商永远完不成 |
| **不调 ST 的 `USER_PHY_GetLinkState()`** | `eth_custom_phy_interface.c:323` 把"自协商完成但模式未识别"误报成 `LINK_DOWN`，YT8512C 实测正走这条路 → lwIP 被告知断链 → 不发 ARP |
| **直接读 BSR bit2 判链路** | 位语义明确，且少 6 次 MDIO 读 |
| **BSR 必须连读两次取第二次** | IEEE 802.3 规定 link/autoneg 位**锁存低**，读到 0 表示"曾经断过" |
| **不从 BSR bit11~15 反推协商结果** | 那是 PHY 的**能力位**，不是本次协商选中的模式。真实结果在厂商专用寄存器（YT8512C 是 `0x11`） |
| **UDP 回环用 `pbuf_alloc`+`pbuf_take` 拷贝** | 收到的 pbuf 归 DMA 接收环所有，借给发送路径会造成**静默数据损坏** |
| **不动校验和配置** | `CHECKSUM_BY_HARDWARE=1`/`CHECKSUM_GEN_UDP=0`，UDP 校验和由 ETH 外设硬件插入。打开 `CHECKSUM_GEN_UDP` 会与硬件重复计算 |
| **保留 `eth_custom_phy_interface.c` 但不用它** | CubeMX 重新生成还会带上，删了白删 |
| **MAC 地址尾段不能全零** | 某些网卡驱动会丢弃，导致链路通但 ping 不通 |
| **PHY 地址硬编码 0，不扫描** | 板上 PHYADD0/1 都接了 LED；且 MDIO 悬空电平 `0x7FFF` 会造成假阳性 |
| **`sanitize_inplace()` 只滤 `< 0x20`，不滤 `> 0x7E`** | UTF-8 汉字每字节都 ≥ 0x80，按 `> 0x7E` 过滤会把中文整句打死。控制字符才需要清 |
| **截断回退到字符边界（`utf8_trim_incomplete()`）** | 3 字节的汉字被硬砍成 1~2 字节就不是合法 UTF-8，助手显示成替换符 |
| **原始字节先收进 `s_rx_raw` 再在副本上加工** | 先截断+过滤会破坏原始数据，事后无法再判断"PC 到底发的什么编码" |
| **`UDP_ECHO_HEXDUMP` 默认 0** | 115200 下打 32 字节的十六进制要 99 字符≈8.6ms，收包频繁时拖慢主循环 |
| **发送分三层（`send_raw` / `send_to_addr` / `send_to_peer`）** | 上层短应答要的是"安全截断"，底层大帧要的是"一个字节都不能少"。混成一个函数必然二选一 |
| **大帧同时发两路（`ReplyBoth`），不切片** | 一条 UDP 最大 1472 字节，1472 字节在 100M 链路上只要约 0.1ms。**切片没有收益**，真正的瓶颈是 I2C（1024 字节 @100kHz ≈ 100ms） |
| **`send_raw()` 不做任何拷贝** | 960 字节的帧拷一遍就要 `PBUF_POOL_SIZE × PBUF_POOL_BUFSIZE` = 4×1524 = 6096 字节的池里再占一块，多一次 `memcpy` 没有意义 |
| **`BROADCAST` 只改"第二路目标"，不动 peer** | 保持心跳和普通回包仍指向"最后来包的 PC"，不因为设了广播就改变主链路 |
| **OLED 用第三方波特律动驱动，不自写** | 自写 `ssd1306.c` 一版能编译、I2C 也通，但屏不亮，反复排查成本高于换驱动。第三方驱动带完整初始化和 `OLED_ReadCmd` 回读能力 |
| **`ssd1306.c` 废弃删除，不保留** | 两套驱动都定义 `0x3C` 的读写路径，同时存在会重复占用 I2C2 且符号冲突；波特律动那套已被 `OLED RD 1` 实测验证能点亮，保留旧的没有收益 |
| **OLED 初始化放在 `ETH_PHY_ReleaseReset()` 之后** | OLED 把 I2C2 拉死时，PHY 复位会失败 → `main()` 停在 `while(1) HAL_Delay(1000)`，板子彻底起不来。放后面最坏只是屏不亮 |
| **`OLED TXT` 只走 ASCII 路径** | 波特律动的 `OLED_ShowChinese()` 用数组下标而非汉字码，命令层无从表达；中文留给第 3 步 `OLED BLIT` 由 PC 下发点阵，更通用 |
| **保留 `OLED RAW` 逃生口** | 驱动封装再全也可能漏掉某个寄存器；`RAW` 直发原始字节给 `0x78`，是排障和试探的最后一招 |

### 5.1 MDIO 地址扫描的假阳性（重要）

总线上没器件应答时，MDIO 读到悬空电平，常见 `0xFFFF` **和 `0x7FFF`** 两种。
用 `!= 0xFFFF` 当判据（ST 和正点原子官方例程都这么写）会把空地址误报成器件 ——
实测 addr = 1/6/8/11/12/13/17/18/20/29/30/31 全报 `0x7FFF`。

**正确判据**：要求厂商 OUI 合法（ID1/ID2 既不全 0 也不全 1，且 `OUI != 0`）。

---

## 6. lwIP 配置要点（`LWIP/Target/lwipopts.h`）

| 配置 | 值 | 含义 |
|---|---|---|
| `NO_SYS` | 1 | 裸机，无 RTOS |
| `LWIP_NETCONN` | 0 | 不用 netconn API |
| `LWIP_SOCKET` | 0 | 不用 socket API |
| `LWIP_NETIF_LINK_CALLBACK` | 1 | 链路状态回调 |
| `CHECKSUM_BY_HARDWARE` | 1 | 校验和交给 ETH 外设 |
| `CHECKSUM_GEN_UDP` | 0 | lwIP 不填 UDP 校验和（硬件填） |

> **`NO_SYS=1` 收包链全程在主循环上下文**，不是中断：
> `MX_LWIP_Process()` → `ethernetif_input()` → `netif->input` → `ip4_input()`
> → `udp_input()` → 回调。所以回调里直接 `udp_sendto()` 是安全的。

---

## 7. 验证步骤

### 7.1 PC 侧网络

| 项 | 值 |
|---|---|
| IPv4 | `192.168.1.100` |
| 掩码 | `255.255.255.0` |
| 网关 | **留空**（网线直连） |

### 7.2 正常启动日志（115200-8-N-1）

```
========================================
 ETHERNETtest boot (step 3: lwip)
 sysclk=180000000 Hz, tick=...
========================================
[OK] printf redirect works
[PCF] eth_reset released, shadow=0x7F (BEEP=1 USB_PWR=1 RS485_RE=1, must all be 1)
[MSP] HAL_ETH_MspInit: RMII GPIO (AF11) + ETH clock OK
[PHY] addr=0 ID1=0x0007 ID2=0xC0F1 OUI=0x001C03          ← OUI=Motorcomm，PHY 活着
[PHY] BCR=0x3000 (autoneg_en=1)  BSR=0x7809 (link=0 autoneg_done=0)
[OK] MX_LWIP_Init() returned
[ETH] HAL_ETH_Start() OK -- MAC TE/RE + DMA ST/SR enabled
[IP ] board = 192.168.1.30  mask = 255.255.255.0  gw = 192.168.1.1
[MAC] 02:00:00:12:34:56
[UDP] echo server listening on 0.0.0.0:8080 (board 192.168.1.30)
[LINK] DOWN  BSR=0x7809 BCR=0x3000                       ← 刚开机
[LINK] UP  BSR=0x782D autoneg_done=1 (cap: 100FD=1 100HD=1 10FD=1 10HD=1)   ← 约 1 秒后
```

**关键判据**：`OUI=0x001C03`（Motorcomm）、`[PCF]` 三个位都是 1、`[LINK] UP` + `autoneg_done=1`、RJ45 双灯亮。

### 7.3 ping

```cmd
ping 192.168.1.30
```

期望：`来自 192.168.1.30 的回复: 字节=32 时间<1ms TTL=255`，0% 丢失。

### 7.4 UDP 回环（网络调试助手）

配置：**UDP**，本地端口任意，目标 `192.168.1.30:8080`

| 操作 | 期望 |
|---|---|
| 发送 `ECHO hello` | 立刻收到 `我收到你的信息了，是"hello"吗？` |
| 发送 `hello`（无前缀） | `[ERR] unknown command: hello` + HELP 提示 |
| 不发任何东西 | 仍每秒收到中文心跳 |

> **心跳间隔必须稳定 1000ms。** 变成 64 秒说明主循环被卡住。

> ⚠ **`ECHO ` 前缀不能省**（见 §3.8）。不带前缀的普通文本现在会被当命令，
> 得到 `[ERR] unknown command`。这是改用命令接口后的**行为变更**。

### 7.5 OLED 实测

| 发这条 | 期望 | 现象 |
|---|---|---|
| （上电即测） | 串口打印 `[OLED] boot screen drawn (BaudDance driver, I2C2 PH4/PH5)` | **屏上出现 4 行字**：`ETHERNETtest` / `192.168.1.30` / `UDP :8080` / `type HELP` |
| `OLED INIT` | `OK OLED re-init` | 屏重新初始化（屏全黑时第一招） |
| `OLED TXT 0 HELLO` | `OK` | 第 1 行变成 `HELLO` |
| `OLED PIX 64 32 1` | `OK` | 屏幕正中央一个亮点 |
| `OLED BAR 0 0 64 16 1` | `OK` | 左上角一个 64×16 实心块 |
| `OLED` | ASCII 屏幕示意（`#`/`.`） | 能远程「看到」屏上内容 |
| `OLED CLR` / `OLED FILL` | `OK` | 清屏 / 全亮 |
| `OLED OFF` / `OLED ON` | `OK` | 屏灭 / 屏亮（**不丢显存**） |
| `OLED RAW 00 AF` | `OK` | 直发原始字节（绕开驱动，最后逃生口） |

> **OLED 全黑时的排查顺序**：① 发 `OLED INIT`（上电时序错了就这一招救回）；
> ② 发 `OLED RAW 00 AF` 看有没有 `OK`（判 I2C2 握手）；③ 摸模块 VCC 的 3.3V；
> ④ 换 `0x3D` 地址的屏试。波特律动驱动**吞掉 HAL 错误**（`OLED_Send()` 返回 void），
> 所以串口不报错**不代表**写入成功。

### 7.6 命令接口实测（当前主功能）

配置同上，发 **文本命令**，逐条核对：

| 发这条 | 期望回包 | 现象 |
|---|---|---|
| `LED` | 列出 `DS0`/`DS1` 及状态 | — |
| `LED DS0 1` | `[OK] DS0 (PB0) = ON` | **板载 LED0 亮** |
| `LED DS0 0` | `[OK] DS0 (PB0) = OFF` | **板载 LED0 灭** |
| `LED DS1 1` | `[OK] DS1 (PB1) = ON` | **板载 LED1 亮** |
| `LED DS0 TOGGLE` | `[OK] DS0 (PB0) = ...` | LED0 翻转 |
| `R 40020014 1` | `0x........` 十六进制 | 读 GPIOB ODR |
| `PING` | `PONG tick=...` | 最便宜的"活着吗"探测 |
| `BROADCAST 8081` | 设成功提示 | 之后的大帧另发一份到 `192.168.1.100:8081` |
| `W 40020014 1` 后再 `R` | 值变了 | 直接写寄存器 |
| `W 40023800 0` | `[ERR] ... not writable` | **白名单拦住写 RCC** |
| `HELP` | 命令表 | — |

**验收标准**：发 `LED DS0 1` 后**板载 LED0 真的亮**，发 `LED DS0 0` 后真的灭，
且串口日志同步打印 `[CMD] ...`。

> **影子与实测对照**：若回包说 `ON` 但灯不亮，用 `R 40020014 1` 读 GPIOB 的 ODR
> 看 bit0 是不是 0。bit0=0 而灯不亮 → 引脚/硬件问题；bit0=1 → `Board_IO_Write()`
> 没真的写进去。这比盯着灯猜快得多。

---

## 8. 故障排查速查表

| 现象 | 最可能原因 | 检查 |
|---|---|---|
| RJ45 双灯全灭 | PHY 复位没释放 | 串口有 `[PCF] eth_reset released`？在 `MX_LWIP_Init()` 之前？ |
| 蜂鸣器狂响 / 串口掉线 | PCF8574 初值写错 | `PCF_POWER_ON_DEFAULT` 必须 `0xFF`，只清 P7 |
| `[PCF] FAIL: device not ready` | I²C2 没通 | PH4/PH5 上拉、`MX_I2C2_Init()` 在前？ |
| `[PHY] no valid PHY found` | MspInit 没生效 / MDC 超频 | grep `AF11_ETH`；有 `ETH_PHY_Prepare()`？ |
| `[PHY] addr=1 ... =0x7FFF` | MDIO 悬空误判 | 等 PHY 自举 120ms；用 OUI 判据 |
| PHY 读到了但值脏 | MDC 分频没设 | `HAL_ETH_SetMDIOClockRange()` |
| 链路 UP 但 ping「无法访问目标主机」 | `HAL_ETH_Start()` 没调 | grep `HAL_ETH_Start` |
| ping 通但 UDP 收不到 | 目标端口/协议错 | 助手选 **UDP**，目标 `192.168.1.30:8080` |
| UDP 完全没反应 | Windows 防火墙 | 暂时关闭防火墙测试 |
| 心跳间隔异常（如 64 秒） | 主循环被阻塞 | `while(1)` 里不能有阻塞轮询 |
| 编译报 `undefined reference` | 新 .c 没登记 | 加到根 `CMakeLists.txt` 的 `target_sources()` |
| 烧进去没变化 | hex 是旧的 | 重新 objcopy，检查时间戳 |
| **回显的原文全变成 `.`** | `sanitize_inplace()` 把 ≥0x80 的字节也滤了 | 判据必须只有 `c < 0x20`；UTF-8 汉字每字节都 ≥0x80 |
| **中文回显成乱码/替换符** | 截断砍断了多字节字符 | 用 `utf8_trim_incomplete()` 回退到字符边界 |
| **想知道 PC 到底发的什么编码** | 缺原始字节观察手段 | 把 `udp_echo.c` 的 `UDP_ECHO_HEXDUMP` 置 1，看 `[UDP] raw` 行 |
| **命令回 `[ERR] unknown command`** | 忘了 `ECHO ` 前缀 / 命令拼错 | 普通文本要写 `ECHO xxx`；命令看 `HELP`（见 §3.8） |
| **`LED DS0 1` 回了 OK 但灯不亮** | 引脚配置错 / 影子与硬件不符 | 用 `R 40020014 1` 读 GPIOB ODR，看 bit0 是否为 0 |
| **命令回了 `not in the allow-list`** | 地址不在白名单 | 只有 GPIOA~K 和 RCC 允许；加外设要改 §3.7 的白名单表 |
| **`W 40023800 ...` 被拒** | RCC 是只读项 | **这是设计如此**，写 RCC 会掉时钟/变砖 |
| **串口没有 `[CMD]` 日志** | `echo_service.c` 分发没接上 | 检查回调里的前缀判断（见 §3.8） |
| **OLED 全黑，串口却无任何报错** | 波特律动驱动吞掉 HAL 错误 | `OLED_Send()` 返回 void。先发 `OLED INIT`，再发 `OLED RAW 00 AF` 判握手（见 §7.5） |
| **`OLED SCAN` 报 `not found` 但屏其实能点亮** | 扫描用 `HAL_I2C_IsDeviceReady` 探测，**该函数不可靠** | 别信扫描结果，直接发 `OLED TXT 0 TEST` 看屏。实测扫描曾漏报 0x3C 而屏是可点亮的 |
| **串口日志停在 `[PCF] eth_reset released` 就没了** | CubeMX 重新生成把 `USER CODE` 区外的代码删了 | `git diff` 看 `main.c`；手写代码必须放进 `USER CODE BEGIN/END` 配对里（见 §3.4 注） |
| **CubeMX 重新生成后网口又不通** | `ethernetif.c` 的 5 处手工改动被还原 | 按 §3.4 逐条重做；MAC 变回 `00:80:E1:00:00:00` 或丢了 `HAL_ETH_Start()` 都是它 |

---

## 9. Git 工作流

### 9.1 当前 `.gitignore` 覆盖范围

已忽略：`build*/`、CMake 生成物（`CMakeCache.txt`/`CMakeFiles/`/`compile_commands.json`/
`.ninja_log`/`build.ninja` 等）、编译产物（`*.o`/`*.d`/`*.su`/`*.elf`/`*.bin`/`*.hex`/`*.map`/`*.a`）、
CubeMX/IDE 临时文件（`mx.scratch`/`*.ioc.bak`/`.cproject`/`.project`）、
clangd `.cache/`、`__pycache__/`、OS 垃圾文件。

**白名单（`!` 强制保留，不会被误伤）**：`.settings/*.json`、`.vscode/settings.json`、
`.vscode/c_cpp_properties.json`、`CMakePresets.json`、`CMakeLists.txt`、`cmake/*.cmake`、
`cmake/stm32cubemx/CMakeLists.txt`、`*.ioc`、`*.ld`、`*.s`、`.clangd`。

### 9.2 已验证的规则

- `git ls-files -i -c --exclude-standard` → 空（无已追踪文件被误排除）
- 用 13 个诱饵文件实测（`Core/Src/main.o`、`__pycache__/x.pyc`、`CMakeUserPresets.json` 等）→ 全部命中忽略

### 9.3 提交规范

提交信息用中文，说明**做了什么 + 为什么**；若该次提交同时更新了 AGENTS.md，在正文里点明。示例：

```
添加 STM32CubeMX 项目 .gitignore

忽略 build/、CMake 生成物、编译产物、CubeMX/IDE 临时文件，
同时用 ! 白名单确保 .ioc/.ld/startup_*.s/.clangd/CMakePresets.json
等必需源文件不被误伤。

同步更新 AGENTS.md §9.1/§9.2 与变更日志。
```

### 9.4 乱序提交的补救（历史遗留）

仓库早期有两次提交是"**先 commit 后写文档**"的顺序（违反 §0 约定）：

| 提交 | 问题 |
|---|---|
| `f037cb2` | 只含 `.gitignore`，AGENTS.md 在下一个提交才补 |
| `872e524` | 只含 AGENTS.md，其内容描述的 `.gitignore` 已在上一提交 |

**后果**：`f037cb2` 处没有任何文档说明，`872e524` 的变更日志条目属于事后补记。
**不打算重写历史**（已推送的提交改写会影响协作者）。此处仅作记录。

> **未决事项**：`.mxproject` 目前**仍被追踪**。它是 CubeMX 自动生成的元数据，
> 每次打开项目都可能变，容易产生无意义 diff。若要移除：
> `git rm --cached .mxproject` 并加入 `.gitignore`。（用户尚未决定）

---

## 10. 变更日志

> **每次改动代码后在此追加一条，最新的在最上面。**

### 2026-02-13 — 二进制帧通道 `FB`/`FBSEQ` + PC 端 agent（本轮）

**目标**（用户原话）：要一个 agent，「能够理解我的意思使之完成对应的操作在单片机上……
比如我要显示一个会动的眼睛，一个会奔跑的马，以以太网的速率」。并追问过
「我如何训练一个 agent」。

**先说清楚一个判断**：这不需要"训练"。Agent = **系统提示词 + 工具 + 循环 + 状态**，
骨架不到 100 行。而且早先设想的"动作库"模式（预置 `eyes()`/`horse()`，LLM 只做意图
分类）有个致命问题：**能力被写代码的人锁死** —— 想要"打哈欠的猫"库里没有就卡住。
所以改成**让 LLM 现场写渲染代码**，预置动画降级成示例。能力上限
= 模型写码能力 × 画布原语表达力，两者都在持续变好。

**性能事实（决定了整个设计）**：以太网侧 **30fps × 1032 字节 = 30KB/s，绰绰有余**；
真正的瓶颈是 I2C —— 1024 字节 @100kHz ≈ 92ms，即**整屏约 11fps 的硬上限**。
所以"逐寄存器写"是不可行的抽象（15fps × 1024 字节用 4 字节一条的 `W` 要几十万条
命令/秒），正确抽象是**一个 UDP 包 = 一帧**。

**板子端新增**：

- `Core/Inc/framebuf.h` + `Core/Src/framebuf.c` —— 二进制帧通道。
  - `FB <1024 字节>`（不带序号）与 `FBSEQ <u16 LE 序号> <1024 字节>`（**1032 字节**）。
    FBSEQ 的存在理由：UDP 不保证顺序，20~30 包/秒会出现乱序/重复，没有序号
    会画面倒退。
  - 帧格式与 SSD1306 页寻址**完全一致**：`byte = gfx[(y>>3)*128 + x]`，`bit = y & 7`
    （bit0 在最上面）—— 板子收到后一个字节都不用改就能 `memcpy` 进 `OLED_GRAM`。
  - **判据只看长度**：1032 走 FBSEQ 分支（校验 `"FBSEQ "` 头），1024 直接当整帧，
    其它长度 `return 0` 交回文本路径（文本上限 191 字节，永不撞上）。
  - 序号比较用 **`int16_t` 差值** `(int16_t)(seq - s_next_seq) <= 0`，u16 回绕才正确。
  - `fb_show()` 调**异步**的 `OLED_ShowFrame()`；`s_stage[1024]` **必须 static**
    （栈只有 1024 字节）。
  - `FB_Stats()` 回 `FB: good=N bad=N ooo=N`。
- `Core/Src/echo_service.c` —— 在 `echo_recv()` 回调的**最前面**（记住发信人之后、
  "取出原文"之前）加第 0 步分发。**必须在最前面**：后面的「对齐字符边界 + 过滤控制
  字符」会把二进制毁掉（0x00 被替成 `.`）。**故意不回包**（30fps 等往返会被时延卡死），
  要统计就发文本 `FB?`。
- `Core/Src/reg_shell.c` —— 新增 `FB?` 命令 + 帮助文本一行。
- `CMakeLists.txt` —— `target_sources()` 登记 `framebuf.c`（现共 9 个用户源文件）。

**PC 端新增 `pc_agent/`**（纯 PC 代码，**不参与固件编译**）：

| 文件 | 职责 |
|---|---|
| `proto.py` | UDP 通道：`send_text()` 文本命令 + `send_frame()` 二进制帧 |
| `canvas.py` | 128×64 画布 + 全套画图原语（点/线/矩形/圆/椭圆/多边形/位图/反色）+ 内置 6x8 ASCII 字体 |
| `bitmap.py` | 中文点阵渲染（**Windows GDI**，`ctypes` 调 `gdi32`，不需要装任何库）+ 字符画预览 |
| `anim.py` | 内置示例动画：`eyes` / `horse` / `rain` / `boing` / `text` |
| `sandbox.py` | 沙箱：import 白名单 + 名字白名单 + 超时 + **10 个攻击用例自检** |
| `agent.py` | CLI、LLM 调用、播放循环、代码落盘缓存 |
| `README.md` | 用法与设计说明 |

**沙箱（最关键的安全设计）**：三道闸门 —— ① import 只允许 `math`/`random`；
② `__builtins__` 换成白名单（没有 `open`/`eval`/`exec`/`__import__`）；
③ 单帧渲染超时 1 秒。**最要紧的一条：画布传进去，`Board` 对象绝不传进去** ——
LLM 代码碰得到 `Canvas`，但碰不到网络/I2C/文件系统。
> ⚠ 定位要说清楚：**它防的是"模型写错代码"和"提示注入"，不是防有备而来的攻击者**。
> 纯 Python 沙箱绕得过去。它的价值是把"手滑"的代价从"删掉文件"降到"报个错"。
> `python pc_agent/agent.py --test` 跑自检，应永远 10/10 拦住。

**中文显示**：板子的第三方字库只有 4 个汉字（「波特律动」），**指望不上**。
改为 PC 端用 Windows GDI 渲染成点阵，随帧下发 —— 板子侧只需要"收 1024 字节画一屏"
这一件事，**内容的复杂度留在 PC 端，改动画不用重新烧固件**。

**验证**：

- 固件：`arm-none-eabi-gcc -fsyntax-only -Wall -Wextra -std=gnu11` 检查
  `framebuf.c` / `echo_service.c` / `reg_shell.c` / `main.c` / `oled.c` / `dma.c` /
  `stm32f4xx_it.c` → **7 个全 OK，零警告**。
- PC：`sandbox.py` 自检 **10/10 拦住**；5 个内置动画在 t=0/0.5/2.5 全部渲染出
  1024 字节；`eyes` 与 `horse` 用字符画核对过形状；中文"春天来了"字符画清晰可读；
  `--render -o x.png` 手写 PNG 输出正常。

> ⚠ 实测（`python pc_agent/agent.py check` + 播放）**尚未做**，需要先烧写新固件。

同步更新 AGENTS.md 新增 §3.11 / §3.12，以及 §2.4 / §3 结构树 / §3.7 / §7 / §8 / §10 / §11。

### 2026-02-13 — OLED 异步刷屏：把 92ms 阻塞拆成 8 步

**问题**：波特律动的 `OLED_ShowFrame()` 一次同步发 8 页 = 1024 字节 @100kHz
≈ **92ms**，期间主循环里的 `MX_LWIP_Process()` 完全停摆 —— ping 丢包、心跳
间隔抖动，违反 §3.3 的"`while(1)` 里不能有阻塞式轮询"。

**做法**：把原来"一口气发完"改成由主循环推进的状态机。

- `Core/Src/oled.c` + `Core/Inc/oled.h`：
  - 新增 static 状态 `s_flush_buf[129]` / `s_flush_active` / `s_flush_stage` /
    `s_flush_page` / `s_flush_dropped`。
  - **`OLED_ShowFrame()` 改为异步**：若上一帧还没发完就 `s_flush_dropped++; return;`
    （**丢帧**），否则记下页号并立刻启动第一页再返回。
  - **新增 `OLED_FlushPoll(void)`**：每次调用只推进一小步（发一页的换页命令，
    或发一页的 129 字节数据），最长阻塞约 **2.8ms**。返回 1 = 传输中、0 = 空闲。
  - **新增 `OLED_ShowFrameBlocking(void)`**：保留原版阻塞语义，原函数体整体改名而来。
  - 新增 `OLED_FlushBusy()` / `OLED_FlushDropped()`（后者读后清零）供 `OLED STAT` 用。
  - `s_flush_buf` 只有 129 字节、**是每页现从 `OLED_GRAM` 拷一份**，不是 8 页共用
    整屏缓冲 —— 这样显存可以在传输途中被安全改写。
  - ⚠ **`OLED_Init()` 里的 `OLED_ShowFrame()` 必须改成 `OLED_ShowFrameBlocking()`**：
    初始化在 `main()` 进主循环之前跑，用异步版则屏上只有第一页有内容，且
    `s_flush_active` 会一直挂着，导致主循环第一次刷屏被当成"上一帧没发完"丢掉。
- `Core/Src/main.c`：开机画面改用 `OLED_ShowFrameBlocking()`（那一刻还没有网络
  要伺候）；`while(1)` 里 `Echo_Service_Poll()` 之后新增 **`OLED_FlushPoll();`**。
- `Core/Src/dma.c`：`MX_DMA_Init()` 内新增 `I2C2_EV_IRQn` / `I2C2_ER_IRQn` 的
  `HAL_NVIC_SetPriority(..., 0, 0)` + `HAL_NVIC_EnableIRQ(...)`。**`.ioc` 里 I2C2
  的 NVIC 没勾**（只勾了 DMA1_Stream2/7），这两句必须手写。
- `Core/Src/stm32f4xx_it.c`：新增 `I2C2_EV_IRQHandler()` / `I2C2_ER_IRQHandler()`
  调 `HAL_I2C_EV_IRQHandler(&hi2c2)` / `HAL_I2C_ER_IRQHandler(&hi2c2)`。
  少了它们，`hi2c2.State` 永远回不到 `READY`（DMA 传完只说明数据进了 TXDR，
  不等于已经从 SCL/SDA 移出去），第一次刷屏看起来正常，之后所有 I2C
  （含 PCF8574 的 ETH_RESET）全部 `HAL_BUSY`。
- `Core/Src/reg_shell.c`：
  - 新增 **`OLED STAT`** 子命令，回 `OLED flush: busy=%u  dropped=%lu`。
  - `OLED INIT` 与 `OLED CLR` 现在**同时清空 `s_oled_lines[]` 影子** ——
    只清显存的话，下一次整屏重绘会把旧文字又带回来。
  - **`OLED PIX` 与 `OLED BAR` 由裸 `OLED_ShowFrame()` 改为 `oled_redraw_lines()`** ——
    否则整屏会被"空显存 + 一个矩形"覆盖掉。

**验证**：`arm-none-eabi-gcc -fsyntax-only -Wall -Wextra -std=gnu11` 逐个检查
`oled.c` / `reg_shell.c` / `main.c` / `dma.c` / `stm32f4xx_it.c` / `i2c.c` / `font.c`
全部通过，无警告。（本会话不跑 cmake，编译由用户在 STM32CubeIDE 里做。）

> ⚠ **本轮实际的刷屏机制要说清楚**：`OLED_FlushPoll()` 内部调的仍是**阻塞**的
> `OLED_Send()`（`HAL_I2C_Master_Transmit(..., HAL_MAX_DELAY)`），**并没有真正
> 用上 DMA**。它的效果是把"一次阻塞 92ms"拆成"每次阻塞约 2.8ms × 8 次"，
> 由主循环分 8 遍喂完 —— 主循环的响应性大幅改善，但它不是 DMA。
> `Core/Src/dma.c` / `Core/Src/i2c.c` 里的 `hdma_i2c2_tx`（DMA1_Stream7 / CH7 /
> MEMORY_TO_PERIPH）与新增的两个中断目前**没有被 `oled.c` 使用**。
> **第 2 步真正的 DMA 化仍待做**（见 §11）。

同步更新 AGENTS.md §3.9 / §5 / §7.5 / §8 / §10 / §11。

### 2026-02-13 — 切换到波特律动 OLED 驱动

**背景**：自写的 `ssd1306.c` 能编译、I2C 扫描也能扫到 `0x3C`，但屏始终不亮，
串口报 `[OLED] FAIL: no ACK from 0x78`。换用用户提供的第三方波特律动驱动后，
`OLED RD 1` 一次点亮 —— **根因是自写驱动的探测逻辑过于激进**：它在初始化最前面
先发一条 `0xAE` 探测，一次短传输没成功就 `return -1` 放弃整条初始化路径
（`Core/Src/ssd1306.c:95`）。**探测失败不代表设备不在，只代表这一次传输没成功。**

**新增（用户提供的第三方代码，本工程只做了 I2C 端口移植）**：

- `Core/Inc/oled.h` + `Core/Src/oled.c` —— 波特律动 SSD1306 驱动（MIT，2023-08）。
  唯一的本工程改动：`extern I2C_HandleTypeDef hi2c1;` → **`hi2c2`**，
  调用处 `HAL_I2C_Master_Transmit(&hi2c1, ...)` → `&hi2c2`（本工程 OLED 挂 I2C2，
  且没有 I2C1，不改会 undefined reference）。原注释里驱动作者自己也提示了这一点。
- `Core/Inc/font.h` + `Core/Src/font.c` —— 波特律动字库。ASCII 四档
  （`afont8x6`/`afont12x6`/`afont16x8`/`afont24x12`）+ 中文 `font16x16`
  （**只有 4 个字：「波特律动」**）+ `bilibiliImg`。

**删除**：`Core/Inc/ssd1306.h` + `Core/Src/ssd1306.c`（自写驱动，见 §5 决策表）。
`CMakeLists.txt` 的 `target_sources()` 里对应换成 `oled.c` / `font.c`。

**改动 `Core/Src/reg_shell.c`（OLED 命令整块重写）**：

- 由于几何宏（`OLED_COLUMN`/`OLED_PAGE`/`OLED_ADDRESS`）都定义在 `oled.c`
  **内部**而不在头文件里，本文件**自写一份常量**（`OLED_COLS_V 128`、`OLED_PAGES_V 8`、
  `OLED_ADDR_8BIT 0x78` 等）并 `extern uint8_t OLED_GRAM[8][128];`。
  这样做的好处是：日后升级第三方驱动不会因为宏改名而破坏本文件。
- 新增 `static char s_oled_lines[4][64]` 四行文本影子 + `oled_redraw_lines()`。
  **必须这样的原因**：波特律动是全屏重绘模型，`OLED_NewFrame()` 会 `memset`
  整个显存，只画一行会把其它三行抹掉。
- 子命令改为 `INIT` / `ON` / `OFF` / `CLR` / `FILL` / `TXT <行> <文本>` /
  `REFRESH` / `PIX <x> <y> [0|1]` / `BAR <x> <y> <w> <h> [0|1]` / `RAW <ctrl> <hex...>`。
- `OLED` / `OLED SHOW` 的 ASCII 示意判据**反了**：波特律动 `OLED_SetPixel()` 里
  **bit=1 表示灭、bit=0 表示亮**（`OLED_NewFrame()` 是 `memset(0)` = 全亮），
  所以 `(masked) == 0U` 才算亮点。

**改动 `Core/Src/main.c`（开机屏显）**：

- `HAL_Delay(100)` 等模块上电稳定（`oled.c` 原注释提示 STM32 启动比 OLED 快），
  然后 `OLED_Init()` → `OLED_NewFrame()` → 4 行 `OLED_PrintASCIIString()` →
  `OLED_ShowFrame()`，串口打 `[OLED] boot screen drawn (BaudDance driver, I2C2 PH4/PH5)`。
- **不检查返回值**：波特律动的 `OLED_Init()` 返回 void，`OLED_Send()` 把 HAL 错误
  静默吞掉。屏不亮就发 `OLED INIT` 重试。
- 调用点仍在 `ETH_PHY_ReleaseReset()` **之后**（理由见 §5 决策表）。

**实测结论**：`OLED RD 1` 后屏幕点亮，中文回显与命令通道均正常。

同步更新 AGENTS.md §2.4 / §3 结构树 / §3.1 / §3.9 / §5 / §7.5 / §8 / §10。

### 2026-02-13 — 分层发送层 + `BROADCAST` / `PING` 命令

**为什么做这个**：OLED 全屏位图一帧 1032 字节（4 字节头 + 1024 字节帧缓冲），
而原来的 `send_to_peer()` 复用的 `s_tx_buf` 只有 512 字节，**发不出去**；
再加上 1032 字节大于"网络调试助手"的接收习惯区，需要一条能同时发给两个目标的通道。
所以先把发送能力分层抽出来，再用命令把它接出来。

**改动 `Core/Src/echo_service.c` / `Core/Inc/echo_service.h`**：

- **新增最底层 `static err_t send_raw(const ip_addr_t *ip, u16_t port, const void *data, u16_t len)`**：
  不做拷贝、不截断，`len` 上限就是 `u16_t`。用 `MEM_SIZE` 允许的最短路径组包。
- **新增 `static err_t send_to_addr(const ip_addr_t *ip, u16_t port, const void *data, u16_t len)`**：
  拷进 `s_tx_buf` 再调 `send_raw()`，`len > ECHO_TX_BUF_SIZE` 时回 `ERR_MEM`。
- **`send_to_peer()` 保持不变**（挡在 512 字节，复用 `s_tx_buf`）。
- **新增对外 API**（`.h` 里声明，供 `reg_shell.c` 使用）：
  - `int Echo_Service_Reply(const char *msg, u16_t len)` —— 文本答复，走 `send_to_peer()`。
  - `int Echo_Service_ReplyRaw(const void *data, u16_t len)` —— 二进制答复，等价路径。
  - `int Echo_Service_ReplyBoth(const void *data, u16_t len)` —— **大帧**：同时发
    `send_to_peer()` 和 `send_raw(s_bcast_ip, s_bcast_port)` 两路。
  - `int Echo_Service_ReplyChunked(const void *data, u16_t len, u16_t mtu)` —— 按 mtu
    切片逐片发（当前无人使用，留作"必须完整送达"的备选）。
  - `int Echo_Service_SetBroadcast(const ip_addr_t *ip, u16_t port)` —— 设第二路目标；
    `ip == NULL` 且 `port != 0` 表示"就用当前 peer 的 IP"；`port == 0` 表示关闭。
- 新增 `static ip_addr_t s_bcast_ip;` + `static u16_t s_bcast_port;` 记录第二路目标。

> **为什么大帧不切片**：1472 字节在 100M 链路上只要约 0.1ms，**切片没有收益**。
> 真正的瓶颈是 I2C（1024 字节 @100kHz ≈ 100ms）。需要的是"分两路回包"，不是"分多次发"。

**改动 `Core/Src/reg_shell.c`**：

- `:10` 加 `#include "echo_service.h"`。
- 命令表新增 `BROADCAST [port]` 与 `PING`（见 §3.7 命令表）。
- `BROADCAST` 走 `Echo_Service_SetBroadcast(NULL, port)`，**只改第二路目标，不动 peer**。
- 帮助文本同步更新。

同步更新 AGENTS.md §3.5 / §3.7 / §5 / §10。

### 2026-02-13 — 以太网命令接口 + 板级 IO 注册表

> **本条写入时代码尚未编译验证**（§0 要求先写文档再 commit）。烧写后请按 §7.5 逐条核对。

**目标**（用户原话）：留一个可以通过以太网改单片机寄存器的接口，后期能靠 AI 传数据
改寄存器实现功能；**第一步先做"传数据点亮/熄灭 DS0、DS1"**。

**新增文件**：

- `Core/Inc/board_io.h` + `Core/Src/board_io.c` —— 板级 IO 注册表。
  表项 `{name, port, pin, active_low, cur_level}`，当前两项：`DS0`=PB0、`DS1`=PB1，
  都按正点原子阿波罗V2 的**低电平点亮**填 `active_low=1`。
  对外 7 个函数：`Board_IO_Init/Count/Get/Find/Write/Toggle/ReadRaw`。
  **扩展方式：表里加一行。** 命令解析、帮助文本都不需要动。
- `Core/Inc/reg_shell.h` + `Core/Src/reg_shell.c` —— 命令解析 + 地址白名单。
  `Reg_Shell_Execute(cmd, out, out_size)` 是**纯函数**，不碰网络，方便换传输方式。
  支持 `HELP` / `LED` / `R` / `W`，解析大小写不敏感。

**改动文件**：

- `Core/Src/echo_service.c` —— 回调里加**分发**：以 `ECHO ` 开头走原来的中文回显，
  否则交给 `Reg_Shell_Execute()`（见 §3.8）。
- `Core/Src/main.c` —— `MX_GPIO_Init()` 之后加 `Board_IO_Init()`（让它自己在
  `MX_LWIP_Init()` 之前把 PB0/PB1 配好，不依赖 CubeMX 生成代码）。
- `CMakeLists.txt` —— `target_sources()` 登记 `board_io.c`、`reg_shell.c`。

**为什么 `R`/`W` 一定要白名单**：这两个命令能读写任意 32 位地址，等于把整颗芯片
交出去。一句 `W 40023800 0` 就能掉时钟/变砖。当前只放行
GPIOA~GPIOK（`0x40020000`~`0x40023FFF`）与 RCC（`0x40023800`~`0x40023BFF`，**只读**）。
**要加外设就往白名单表里加一行，不要放开整片 `0x40000000`。**

**行为变更（重要）**：`ECHO ` 前缀现在是必需的。以前发什么回什么，现在不带前缀
的文本会被当命令，回 `[ERR] unknown command: xxx`。这是为了让"回声测试"和
"命令接口"共存所付的代价。

同步更新 AGENTS.md §2.4 / §3 结构树 / §3.1 / §3.6 / §3.7 / §3.8 / §5 / §7.4 /
§7.5 / §8 / §11 / §12。

### 2026-02-13 — `5f770d9` 回声服务支持中文

> **已实测验证**：烧写后用网络调试助手发中文，能正确回显，不再变成点。
> 本条的三项根因判断成立，其中 `sanitize_inplace()` 的 `> 0x7E` 判据是主因。

**问题**：网络调试助手能收到回包，但发中文时回显的原文全变成 `.`（点）。

**根因**（三个独立缺陷叠加）：

1. **`sanitize_inplace()` 误杀**：老判据是 `c < 0x20 || c > 0x7E` 就换成 `.`。
   本意是清理控制字符，但 UTF-8 汉字是 3 个字节、**每个都 ≥ 0x80**，于是整句中文
   被逐字节打死。
2. **硬截断砍断字符**：`pbuf_copy_partial(p, text, ECHO_MAX_PAYLOAD, 0)` 直接把
   原文切到 260 字节，不问切点落在哪。3 字节的汉字被砍成 1~2 字节后不是合法
   UTF-8 序列，助手只能显示成替换符。
3. **缺少原始字节的观察手段**：串口上能看到的只有过滤后的字符串，无法区分
   "PC 用 GBK 发的"和"板子改坏了"。

**改动**：

- `Core/Src/echo_service.c`：
  - `sanitize_inplace()` 判据收窄为**只过滤 `c < 0x20`**，`0x7F` 及以上原样保留。
  - 新增 `static size_t utf8_trim_incomplete(const char *s, size_t len)`：从开头按
    首字节推算每个字符的长度（`<0x80`→1、`<0xC0`→1/裸续字节透传、`<0xE0`→2、
    `<0xF0`→3、`<0xF8`→4、其余→1/非法首字节透传），只在字符完整时推进；遇到
    超出 `len` 的不完整字符即停止并丢弃它。
  - 新增 `static char s_rx_raw[ECHO_MAX_PAYLOAD + 4U]`：先把原始字节收到这里
    （多收 3 字节用于判断末字符是否被砍断），再在副本上做截断 + 过滤，
    **不再就地破坏原始数据**。
  - 回调里的 261 字节栈数组 `char text[ECHO_MAX_PAYLOAD + 1U]` 改为指针
    `char *text` 指向 `s_rx_raw` —— 栈只有 1024 字节，这个数组原本就占四分之一。
  - 步骤编号重排为 1 取原文 / 2 决定安全长度 / 3 过滤控制字符 / 4 组装应答 /
    5 发回，并修正了此前编号错乱（原有两个 `---- 2. ----`）。
  - 截断提示改为按 `full_len` 判断，被字符边界回退时补一句
    `(trimmed back to a character boundary)`。
- `Core/Src/udp_echo.c`：新增 `UDP_ECHO_HEXDUMP` 开关（默认 `0`）与
  `UDP_ECHO_RAW_SNIFF`（默认 `32U`），在**过滤之前**打印原始字节的十六进制：
  `[UDP] raw 6 byte(s): E4 BD A0 E5 A5 BD`。默认关闭是因为 115200 下 32 字节的
  十六进制要打 99 个字符≈8.6ms，收包频繁时会拖慢主循环。

**如何判断是哪种编码**（打开 `UDP_ECHO_HEXDUMP` 后看 `[UDP] raw` 那行）：

| 看到的字节 | 含义 |
|---|---|
| `E4 BD A0 E5 A5 BD` | 合法 UTF-8 中文（"你好"），发送端没问题 |
| `C4 E3 BA C3` | **GBK** 编码，是助手的编码设置问题，不是板子 |
| `3F 3F` | 发出前就已经是 `??` |
| `EF BF BD` | 已经是 U+FFFD 替换符，上游就已损坏 |

> ⚠ 非 UTF-8 编码（GBK）通过 `sanitize_inplace()` 时**不会被改动**，仍会显示成
> 乱码 —— 那是发送端的问题。要用 GBK 就必须在 `sanitize_inplace()` 里做转码，
> 但那要带码表（几千字节），当前不做。

同步更新 AGENTS.md §3.5 / §5 / §8 / 变更日志。

### 2026-02-13 — 工作流约定修正（本提交）

- **修正 §0 工作流顺序**：由"先 commit 后写文档"改为"**先写 AGENTS.md 再 commit**"，
  代码与文档放同一提交（用户指示）。补充了这样做的理由。
- **新增 §0.1** commit message 规范。
- **新增 §9.4** 记录早期两次乱序提交（`f037cb2`/`872e524`）作为历史遗留，不重写历史。
- **修正 §9.3** 示例，体现"同步更新 AGENTS.md"的写法。
- **修正 §12 铁律 #1**，与新顺序一致。
- ⚠ 本节起，**变更日志条目在提交之前写**，因此条目内引用的提交哈希在写入时尚未生成。

### 2026-02-13 — `f037cb2`

- **新增** `.gitignore`（147 行）：完整覆盖 CubeMX/CMake/ARM GCC 的编译产物与 IDE 临时文件，
  并用 `!` 白名单保护 `.ioc`/`.ld`/`startup_*.s`/`.clangd`/`CMakePresets.json`/`.settings` 等必需文件。
  已用 `git ls-files -i` + 13 个诱饵文件实测验证。

### 2026-02-13 — `872e524`

- **新增** `AGENTS.md`（本文件）：工程工作手册，含构建设置、架构、四个串行故障、
  设计决策、验证步骤、排查速查表。
- 注：本次提交只含 AGENTS.md，而它描述的 `.gitignore` 在上一个提交 `f037cb2` 里 ——
  属于先 commit 后写文档的乱序提交，见 §9.4。

### 2026-02-13 — `707a834`（初始提交，"第一次上传"）

- 工程初始状态：完成 STM32F429 阿波罗V2 的 lwIP 以太网移植（4 个故障全部修复），
  实现 UDP 8080 回环 + 每秒心跳，能 ping 通 `192.168.1.30`。
- 技术文档 `docs/lwip-f429-apollo-v2.md`（597 行）。

---

## 11. 待办 / 已知问题

| 项 | 说明 | 优先级 |
|---|---|---|
| **OLED 第 2 步：刷屏真正走 DMA** | 本轮已把 92ms 阻塞拆成 8×2.8ms（见 §10 与 §3.9），主循环响应性已解决，但**用的仍是阻塞 `HAL_I2C_Master_Transmit`，没上 DMA**。`hdma_i2c2_tx`=DMA1_Stream7 / CH7 / MEMORY_TO_PERIPH 已由 CubeMX 生成，`I2C2_EV_IRQHandler` 也已补上（在 `Core/Src/dma.c` / `Core/Src/stm32f4xx_it.c`），但**尚未被 `oled.c` 使用** | **高** |
| **OLED 第 3 步：`OLED BLIT` + 动眼睛动画** | 用户目标（原话）：「在 OLED 上显示一双会动的眼睛，AI 可以通过修改寄存器等操作直接控制」。**帧缓冲上传（约 1032 字节/帧）才是可行形态，不是逐寄存器写** —— 15~30 fps × 1024 字节用 `W` 一条 4 字节要几十万条命令/秒，物理上做不到。发送侧 `Echo_Service_ReplyBoth()` 已就绪 | **高** |
| `.mxproject` 追踪 | 见 9.3，尚未决定是否移除追踪 | 低 |
| 改用 HSE 25MHz | 当前用 HSI ±1%，UART 波特率有偏差；RMII 参考时钟由 PHY 自己的晶振提供，不影响以太网。属可选优化 | 低 |
| TCP 应用 | `LWIP_TCP=1` 但工程未写 TCP 应用 | — |
| `eth_custom_phy_interface.c` | 保留未用（见 5） | — |

---

## 12. 铁律速记

1. **改代码 → 编译 → 写 AGENTS.md → commit**（用户要求：文档和代码同一个提交）
2. **`ETH_PHY_ReleaseReset()` 必须在 `MX_LWIP_Init()` 之前**
3. **`while(1)` 里不能有阻塞式轮询**
4. **PCF8574 初值 `0xFF`，只改目标位**
5. **编译后必须手工 objcopy 生成 hex，否则烧的是旧固件**
6. **新 `.c` 必须登记到根 `CMakeLists.txt`**
7. **改 `ethernetif.c` 时记住 CubeMX 重新生成会覆盖那 5 处改动**
8. **不要动校验和配置**
9. **读到的寄存器值脏时，先修通信参数再看数据**
10. **多个来源冲突时，以原理图 + 实测为准**
