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
| `FB?` | 文本 | 回 `FB: good=N bad=N ooo=N resync=N` |

**帧格式（与 SSD1306 页寻址完全一致，板子收到后一个字节都不用改）**：

```
byte = gfx[(y >> 3) * 128 + x]
bit  = y & 7          // bit0 在最上面
```

**判据只看长度**（`FB_Dispatch()`）：`len == 1032` 校验 `"FBSEQ "` 头后
按序号处理；`len == 1024` 直接当整帧。其它长度一律 `return 0` 交回文本
路径 —— 文本命令上限 191 字节，**永远不会撞上**。

**序号判据（踩过两次坑，别再改回去）**：

判重**只在"同一个会话"内生效**，会话之间靠**时间间隔**切分，不靠序号差值。
`FB_SESSION_GAP_MS = 500`：距上一帧超过 500ms 就认为 PC 那边换了新进程，
把 `s_have_seq` 清零、`s_resync++`，新序号直接接受并重建基线。

会话内才用 `int16_t` 差值判迟到：`d = (int16_t)(seq - s_next_seq)`，
`d <= 0` 一律丢（`s_ooo++`）。u16 回绕靠 `int16_t` 差值处理
（0xFFFF → 0x0000 不会误判成倒退）。

> ⚠ **不要改回"靠序号差值判新会话"**（曾经的 `FB_SEQ_WINDOW = 128` 版本）。
> 那种做法只能拦住"回退超过 128 帧"，而 PC 每次重跑都从 `seq=0` 开始：
> 只要板子停在上次会话的期望值 48，`0 - 48 = -48` 落在窗口内 →
> **新会话的前 48 帧全被当迟到包丢掉**，表现为"第一个动画能动、第二个不动"。
> 根本错误是**用序号去猜时间**："回退 48"既可能是 1ms 内的真乱序，
> 也可能是 3 秒前那个进程留下的旧基线，光看序号分不出来。

> ⚠ **500ms 这个阈值不能调太小**：`--fps 1` 的帧间隔是 1000ms，
> 阈值小于 1000 会让每一帧都被当成"新会话"，判重彻底失效。

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
| `anim.py` | 内置示例动画：`eyes` / `eyes_fast` / `horse` / `rain` / `boing` / `text` / `car` / `fireworks` |
| `sandbox.py` | 沙箱：import 白名单 + 名字白名单 + 超时；注入 `draw_text()` 供 LLM 写中文 |
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
| **绘图原语入口强制 `int()` 坐标** | 见下面的"float 坐标死循环"，这是 LLM 生成代码的高频写法，必须在原语层兜住而不是逐个修缓存 |
| **沙箱注入辅助函数，不放行 `import bitmap`** | 放行会把 gdi32/ctypes 暴露进沙箱，且 GDI 句柄有进程级上限，子线程反复进出不安全。注入一个绑好的 `draw_text()` 既给了能力又没开新面 |
| **辅助函数起名 `draw_text` 而不是 `text`** | LLM 会把 `text` 当普通名词当变量名（缓存里真出现过 `text = "NI HAO"`），一旦局部变量遮蔽了注入的全局函数，调用时报 `'str' object is not callable`。动词开头不会被这么用 |

### 3.12.1 `pc_agent/dispatcher.py` —— 一句话 → 结构化指令（阶段一）

用户输入**自然语言**（"把灯打开"、"播个烟花"、"屏幕上一个字都没了"），
dispatcher 负责翻译成一条**结构化指令**，然后（可选）执行。

**它只翻译 + 执行，不画图。** 画图/动画交给 `agent.py`，二者边界清晰。

```
dispatcher.py "把灯打开"
   ↓
{"action":"cmd", "arg":"LED 0 1", "by":"rule#led", "needs_confirm":true}
   ↓  没有 --yes → 停下，exit 3
```

**6 个闭合 action**（`ACTIONS`，不许多）：

| action | 含义 | `arg` 是什么 |
|---|---|---|
| `cmd` | 给板子发一条固件命令 | 命令字符串，如 `LED 0 1` |
| `query` | 只读探测（PING/INFO/FB?/HELP/OLED STAT） | 命令字符串 |
| `anim` | 播内置动画 | 动画名（`anim.ANIMS` 里的） |
| `draw` | 让 LLM 现写代码画新动画 | 画面描述 |
| `render` | 只渲染发 PNG，**不发板子** | `None` |
| `knowledge` | 输出知识类内容 | 文本 |

**三层决策，越靠前越确定**：

```
① 规则层 match_rules()   正则命中 → 直接出结果（确定性，自测集必须 100% 过）
② LLM 层 ask_llm_for_plan()  未命中才问，temperature=0，只要严格 JSON
③ 拒绝                    两边都没把握 → action=None + why，**绝不瞎猜**
```

**自测集 `pc_agent/dispatch_cases.jsonl`**（53 条，一行一例）：

```jsonl
{"raw": "把灯打开", "action": "cmd", "arg": "LED 0 1"}
{"raw": "下雨", "action": null}            # 裸名词该拒绝，不是播雨动画
```

`python dispatcher.py --test` 跑它。规则层必须 **100%** 通过（确定性代码，
过不了就是规则写错了），另有若干条"规则层未命中"是**故意**留给 LLM 的。
**加新说法 → 加一行 → 跑 --test**，这是本文档最短的改动闭环。

**安全模型（三层，缺一不可）**：

| 层 | 函数 | 作用 |
|---|---|---|
| ① 命令白名单 | `validate_cmd()` | 命令必须在 `FIRMWARE_CMDS` 里（对应 `reg_shell.c` 的 `s_help_text`），寄存器地址必须在 GPIO 区间且**不能落在 RCC 只读区** |
| ② 写操作确认 | `needs_confirm()` | 写操作不加 `--yes` 一律不执行，exit 3 |
| ③ 板子端 | `reg_shell.c` | 固件自己还有一道白名单（§3.7） |

> ⚠ **`needs_confirm()` 的判据故意反过来**：只证明是只读的才免确认，其余全要。
> 写成 `if cmd in WRITE_CMDS: return True` 的话，将来固件加一条新命令，
> 它不在 `WRITE_CMDS` 里 → 被当只读 → 悄悄打到板子。反过来判，
> 新命令默认要确认，宁可多点一次。

> ⚠ **命令头只读 ≠ 这条命令只读**。`IO`（不带参数）是列状态，`IO 1 1` 是写引脚；
> `OLED` 是屏幕示意，`OLED CLR` 是写。所以 LED/IO/OLED 三个分支必须**看参数**。
> 早先写成 `if head in READONLY_CMDS: return False`，"IO 1 1" 因为头是 IO
> 被判只读，**不加 --yes 直接写进了板子**。

**为什么规则层要覆盖常见说法**：每条规则命中的请求都是 0 延迟、0 花费、
结果确定。只有规则接不住的才值得掉到 LLM 那层（有网络、有延迟、结果不保证）。

**几条踩过的语言陷阱**（写新规则前先看这个）：

| 陷阱 | 例子 | 处理 |
|---|---|---|
| 中文名词夹在别的词里 | "我在**汽车**站"、"我**马上**回来" | 动画词必须配**排除词**：`车(?!站)`、`马(?!上)`；且**裸名词不认**，要带"播/放/来个"这类动词 |
| 述宾方向搞反 | `没.{0,4}字` 对 "屏幕上一个字都**没了**" 永远不命中 | 两个方向都写：`没.{0,4}字\|字.{0,4}没` |
| 动词正则吞掉别的领域 | `(开\|亮)(屏幕\|屏)?` 里的 `(屏幕\|屏)?` 是**可选**的，等于裸"打开"也算开屏 → "把灯打开"被判成 OLED ON | 判"屏"必须要求"屏"字真的出现，且和动词紧挨 |
| 参数被丢掉 | "播眼睛 5 秒" → 只认出 anim=eyes，5 秒没了 | 规则层顺便抽 `([\d.]+)\s*秒` / `([\d.]+)\s*倍速` 塞进 extra |
| 规则太靠前会把后面的说法抢走 | 排障规则放在屏幕命令**之前**，于是"刷屏**卡**不卡"（卡→不动了）和"屏幕**没亮**，帮我开屏"（没亮）都被判成排障 → OLED INIT | 排障放**屏幕命令之后**。**用户说"开屏"就照开屏，别替他决定要不要重置** |
| 询问被当成命令 | "刷屏卡不卡""屏还在吗" 命中排障词后变成一次写操作 | `_ASK_INFO_RE`（不卡/卡不/不卡/亮不/还在/吗/哪/多少/状态/stat）挡一道。宁可漏判掉到 LLM，也不要"用户问一句就把屏重置了" |
| 命名组与取值对不上 | `_REG_READ_RE` 加了个 `reg` 组后，代码里还取 `m.group("word")` → `IndexError: no such group`（`py_compile` 抓不到，只有真跑一遍才炸） | 规则代码取值和正则分组**一一核对**；可选组的结果可能是 `None`，取前先判 |
| 可选分支让后续永远匹配不到 | `gpio\s*([a-k])\b(?:\s*(?P<reg>idr\|odr…))?` —— "GPIOB 的 IDR" 在 "GPIOB" 处就匹配成功，reg 恒为 None，于是**问哪个寄存器都回 ODR 的地址** | 端口名和寄存器名**分开匹配**（`_REG_READ_RE` + `_REG_NAMES_RE`） |
| 读规则截走写操作 | "W 40023800 0" 里的 `40023800` 命中 8 位地址规则 → 变成只读的 `R 40023800 1`，api 自测里"写 RCC 被拦"直接失败 | 寄存器规则开头排除 `\bw\b\|wb\|写\|改\|设\|清`，让写命令走到 `validate_cmd` |

**排障规则给的是"可执行的下一步"**（2026-10-18 改）：命中排障说法时返回
`action=cmd, arg="OLED INIT"`（`needs_confirm=true`），**不是** `action=None` + 一句建议。
理由：建议本身就是一条命令，前端只显示"没听懂"是浪费 —— 让用户点确认，
而不是把我们刚说过的话自己再打一遍。选 INIT 不选清屏：屏可能被别的帧画满了，
INIT 重走初始化并清屏，两种情况都覆盖。

**寄存器读取**（`rule#reg` / `rule#reg_any`）：

| 说法 | 结果 |
|---|---|
| `GPIOB 的 IDR 是多少` | `R 40020410 1`（基址 `0x40020000 + 1×0x400`，IDR 偏移 `0x10`） |
| `GPIOB 的 ODR 是多少` | `R 40020414 1` |
| `读 40020014` | `R 40020014 1`（8 位十六进制地址直接读） |
| `读一下 GPIOB` / `读一下寄存器` | `HELP`（`rule#reg_any`）—— 没说读哪个，回清单，别让 LLM 猜地址 |
| `GPIOB 的 PUPDR 是多少` | `R 40020400 4`（端口基址起 4 个字，**不猜**偏移） |
| `GPIOA 是什么` | 拒绝 —— 纯名词不是读取请求 |

```python
_REG_READ_RE  = re.compile(r"gpio\s*(?P<port>[a-k])\b|\b(?P<addr>[0-9a-f]{8})\b", re.I)
_REG_NAMES_RE = re.compile(r"(?P<reg>moder|otyper|ospeedr|pupdr|idr|odr|bsrr|lckr|afrl|afrh)\b", re.I)
_REG_OFFSETS  = {"MODER":0x00, "OTYPER":0x04, "OSPEEDR":0x08, "PUPDR":0x0C,
                 "IDR":0x10, "ODR":0x14, "BSRR":0x18, "LCKR":0x1C, "AFRL":0x20, "AFRH":0x24}
```


**实测踩到的固件不匹配**：`LED DS0 1` 会让板子回
`ERR: bad LED index 'DS0'` —— 实际固件只认**数字索引**，要发 `LED 0 1`
（源码 `Core/Src/reg_shell.c` 里 LED 走 `parse_dec`）。
`DS0` 只有紧凑写法 `DS0`（命令头）才认。dispatcher 里发的是 `LED 0 1`。

**日志**：`pc_agent/dispatch_log.jsonl`，一行一次分派，含 `by`（命中哪条规则，
或 `llm`）、`needs_confirm`、`executed`、`why`。分析"哪些说法总掉到 LLM"
就从这里 grep。

**CLI**：

```bash
python pc_agent/dispatcher.py "把灯打开"        # 写操作 → 提示加 --yes，exit 3
python pc_agent/dispatcher.py "把灯打开" -y     # 真发
python pc_agent/dispatcher.py "在吗"            # 只读 → 直接执行
python pc_agent/dispatcher.py "播烟花" --json   # 只要结构化结果，不执行
python pc_agent/dispatcher.py "采样率" -x       # 解释为什么这样理解
python pc_agent/dispatcher.py --test            # 跑自测集
```

退出码：`0` 成功 / `1` 板子没回包或自测失败 / `2` 无法分派 / `3` 写操作待确认。

> ⚠ `dispatcher.py` 与 `agent.py` **共用** `_llm_config()` / `_chat_url()`，
> 所以 API key 的读取逻辑只有一份。改 LLM 配置只需要改 `agent.py`。


### 3.12.2 `pc_agent/api.py` —— HTTP 外壳 + 两段式确认（阶段二）

**它要解决的问题**：`dispatcher.py` 在命令行里每次都是新进程，`--yes` 一个标志
就把"翻译"和"执行"一次说完了。前端要的是**两次独立请求**中间的确认，以及
"闪 50 次灯"这种 20 秒任务不把服务卡死。

**接口**（`python pc_agent/api.py` 默认 `http://127.0.0.1:8765`）：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/healthz` | 探活，**不做 Host 校验**（给监控用） |
| GET | `/commands` | 列出 action / 固件命令表 / 只读白名单 |
| POST | `/dispatch` | `{"text": "..."}` → 只翻译。只读的**直接执行**；写操作返回 `status=needs_confirm` + `token` + `preview`，**不执行** |
| POST | `/confirm` | `{"token": "..."}` → 验票后执行。`led_blink` 或带 `async:true` 返回 `202` + `job` |
| GET | `/job/<id>` | 轮询长任务：`state` / `progress` / `notes` / `result` |

**status 取值只有四个**：`done` / `needs_confirm` / `refused` / `error`
（`/job` 的是 `running` / `done` / `error`）。前端按这个分派 UI 分支。

**一次性 token 怎么做的（核心设计）**：

```
payload = {raw, action, arg, sub, by, why, nonce, exp}
token   = base64url(JSON(payload)) + "." + base64url(HMAC-SHA256(KEY, body))
```

- **服务端不存待确认队列**。验签 + 验过期 + 验 nonce 没用过，三条全过才执行。
  好处：重启不丢、多进程不会状态不一致、不存在"忘了清队列导致旧指令被点火"。
- `KEY` 在 `pc_agent/.api_key`（首次运行自动生成 32 字节随机，**已 gitignore**）。
  刻意不走环境变量/命令行 —— 那会出现在进程列表里。
- `TOKEN_TTL = 120` 秒。
- `NonceStore` 只防"同一个 token 点两次"（防手滑），不是防攻击者。

> ⚠ **token 里刻意没有 `needs_confirm` 字段**。验票时用
> `dispatcher.needs_confirm()` **重新算**。安全判据不能由票自己声明 ——
> 否则改一下 payload 就能把写操作说成只读。同理 `run_plan()` 在发给板子之前
> 还会再调一次 `dispatcher.validate_cmd()`：HTTP 是外部输入，不信票。

**为什么 `api.py` 不直接调 `dispatcher.execute()`**：它用 `print()` 输出、
只返回退出码，拿不到回包正文。所以另写 `run_plan()` 负责"发出去、收回来"，
但**判据全部来自 dispatcher**，一行策略都没有复制。自测集测的仍是同一份逻辑。

**为什么长任务异步**：`led_blink` 闪 50 次要 20 秒。同步 HTTP 的话这 20 秒
服务不响应。所以 `202` + `job_id`，前端轮询。实测：闪灯 10 次（约 2 秒）
运行期间发"在吗"，**12ms 返回 PONG**。

**两道网络防护**：

1. **默认只听 `127.0.0.1`**。板子在 192.168.1.30，PC 在 192.168.1.100；
   监听 `0.0.0.0` 等于同一网段任何人打开浏览器就能点你的灯。要用局域网就显式
   `--host 0.0.0.0`（启动时会打印警告）。
2. **Host 头校验**。只看 127.0.0.1 挡不住恶意网页 —— 你浏览器里的网页可以往
   127.0.0.1 发请求（DNS rebinding）。所以除 `/healthz` 外，Host 不是
   `localhost`/`127.0.0.1` 一律 403。实测 `Host: evil.example.com` → 403。

> ⚠ **这两个都是"够用"级别的防护，不是认证**。真要暴露公网，前面必须加
> 反向代理 + 密码。见 §11 待办。

**自测**（`python pc_agent/api.py --selftest`，33 项，不需要浏览器）：

覆盖 token 验签/改签/过期/复用、Host 头拒绝、只读直执行、写操作只发票、
RCC 写被拒、闲聊被拒、长任务进度与 `sent` 序列、多路并发、坏输入。
**自测会真的操作板子**（点灯、闪灯），前提是板子在线。

> ⚠ 该自测在 **GBK 控制台**下曾崩溃：`UnicodeEncodeError: 'gbk' codec can't
> encode character '\u2717'`。已把输出里的符号换成 ASCII 的
> `[FAIL]`/`[PASS]`。**给 CLI 加符号前先想清楚控制台编码。**

**日志**：`/dispatch` 每翻译一次记一行（`executed:false`），
`/confirm` 执行后再记一行（`executed:true`）。执行那行的 `by` 是
`confirm<rule#led>` 这种形式 —— 前缀表示"确实确认执行过"，尖括号里保留
**原始来源**，这样查日志仍然看得出这条是规则翻译的还是 LLM 猜的。

> ⚠ 曾经执行时把 `by` 直接写成 `"confirm"`，把来源覆盖掉了 ——
> 而"能追到是谁翻译的"正是这份日志存在的唯一理由。已修。

**两个 HTTP 层才暴露的规则层 bug（都已修，用例已进自测集）**：

| 说法 | 错在哪 | 修法 |
|---|---|---|
| `闪灯 10 次` | 灯号正则 `灯\s*([01])` 贪婪只吃下 `1`、丢下 `0` → 误判 DS1，用户没说灯号却闪了另一盏 | 裸"灯"后的数字后面**不能跟数字或量词**（次/下/遍/秒/毫秒） |
| `闪灯 1 次` | 同一个歧义的另一面：那个 `1` 是**次数**不是灯号 | 同上一条修好后自然正确 |

> ⚠ 修第一条时我第一版把排除规则**两个分支共用**，结果 `闪 DS1 3 次`
> 因为 `1` 后面跟着 `3` 被整条否掉、退回 DS0。**`DS1`/`LED1` 是明确的灯号
> 声明，不该受裸"灯"那套歧义判断约束。** 两个分支必须分开写。

**为什么这两个 bug 拖到 HTTP 层才发现**：自测集原来没有 led_blink 的用例，
而命令行手工验证时恰好没试过"灯+个位数"。**手工验证覆盖不到的组合会一直在。**


### 3.12.3 `pc_agent/index.html` —— 浏览器前端（阶段三）

**它要解决的问题**：前两个阶段都只能在命令行里说一句话。用户要的是
"打开一个页面，在输入框里说要求，AI 翻译后执行"（m00167）。

**它是单文件、零依赖、零 CDN。** 400 行原生 JS + 内联 CSS，`api.py` 直接
从磁盘读它发给浏览器（`GET /`）。理由：

- 这个页面只服务本机一个人。引 React/Vue 会把"打开就能用"变成"先跑 npm install"。
- CDN 更糟：断网就白屏，而它的使用场景恰恰是"板子在 192.168.1.30、PC 直连"。
- 你改一行就能看到效果，不用等打包。

**页面结构**：

```
┌──────────────────────────────┬──────────────┐
│ 输入框 + [发送]               │ 画面预览      │
│ 常用说法 chips                │ (POST /render)│
├──────────────────────────────┤ [预览] 秒数   │
│ 对话区（每轮一张卡片）         ├──────────────┤
│  ├ 说的话                     │ 板子状态      │
│  ├ 状态标签（已执行/需要确认/…）│ (GET /healthz)│
│  ├ 键值表（动作/参数/来源/为什么）├──────────────┤
│  ├ 写操作预警 + 逐行预览       │ 可用命令表    │
│  └ [确认执行] [取消] 倒计时     │ (/commands)   │
└──────────────────────────────┴──────────────┘
```

**四种结局怎么显示**（前端只按 `status` 分派，不自己判断安全性）：

| `status` | 前端行为 |
|---|---|
| `done` | 直接显示回包正文。只读查询服务端已经执行过了 |
| `done` + `play:true` | **画面请求**：服务端只翻译、没发帧，前端接着调 `/play` 真播。判据是 `d.play`，不是"是不是 anim" |
| `needs_confirm` | 显示"将会发什么" + `[确认执行]`，**倒计时到 0 自动禁用** |
| `refused` | 显示 `why`，提示换个说法。**不提供"硬执行"按钮** |
| `error` | 显示原始 JSON，方便排查 |

> ⚠ **`done` 不等于"动画已经播了"。** 翻译和执行是两段：`/dispatch` 只回
> `{action:"anim", play:true, seconds:3}`，帧要前端再发一次 `/play` 才出去。
> 这条分叉漏过两次（前端没接上、后端顺手也播一遍），详见 §3.12.4。

> ⚠ **前端不拼固件命令、不判断哪些是写操作。** 所有安全判据都在服务端
> （`dispatcher.needs_confirm()` + `api.py` 的 token 验签）。改这个页面的 JS
> 一点也提升不了权限 —— 这是刻意的：**如果安全性由前端代码决定，那它就不是安全性。**
> 同理，`refused` 时故意**不给**"我就要执行"的逃生按钮。

**两个新增路由**（`api.py`）：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/play` | `{text, seconds, fps}` → 真的把动画一帧帧发到板子。**不需要 token**（走 FB 帧通道，不是写命令） |
| POST | `/render` | `{text, t}` → 直接返回 `image/png`（4 倍放大），**不发板子** |

**为什么 `/play` 要短时长（默认 3 秒）而不是"一直播到点停"**：
HTTP 请求必须有尽头。点"播放"发一次请求、播 3 秒回包；想继续再点。
反过来的设计（前端发"开始"再发"停止"）会有个致命状态：**页面上什么都看不见，
后台线程还在发 UDP、还在占板子** —— 那是所有故障里最难排查的一类。

**为什么 `/render` 返回二进制而不是 JSON**：
预览必须和真发板子用**同一段渲染代码**，否则会出现"预览好看、板上不一样"。
所以复用 `agent._save_png()`（写临时文件→读回来→删掉），不在这里另写一套
PNG 编码。两套渲染器迟早会画出不同的东西。

**为什么 `/play` 用 `agent._render_named()` 而不是 `agent.play()`**：
`play()` 是 CLI 播放循环，绑着 `print()` 和 `KeyboardInterrupt`。
HTTP 里要的是"渲染 N 帧 + 进度回调"，所以只借用渲染这一半。

**踩过的坑**：

| 现象 | 根因 | 修法 |
|---|---|---|
| 预览图看着像"一个大圆圈" | **不是 bug**。`fireworks` 在 t=0.7 时 age 已经 0.44，24 个粒子散成一个环，`age<0.25` 的中心余亮早就没了 | 用 `car` 对照验证渲染管线本身是好的（车+轮子+地面都画对了） |
| `/play` 对非动画请求返回 200 而不是 400 | 故意的：业务拒绝用 `status:"refused"` 表达，前端只需认 `status` 一个字段 | 保持 |

**自测**（离线，不需要浏览器）：

```bash
python pc_agent/api.py --selftest      # 33 项，含动画"只翻译不播"与 /play /render 的拒绝路径
```

**手工验收清单**（真机，`python pc_agent/api.py --open`）：

| 在页面上说 | 期望 |
|---|---|
| `在吗` | 立刻显示 `PONG tick=...`，绿色「已执行」 |
| `把灯打开` | 黄色「需要确认」+ `LED 0 1` 预览 + 倒计时。**此时灯不亮** |
| 点「确认执行」 | 灯亮，显示 `IO 0 (DS0) = ON` |
| 再点同一张票（刷新页面重放） | 409 `token_reused` |
| `闪灯 3 次` → 确认 | 灯闪 3 次，进度条走到头，结束时灯是灭的 |
| `播个烟花` → 确认 | 板子上屏动起来，回包里有 `FB: good=.. bad=..` |
| 右侧「预览」 | 出现 128×64 的像素图 |
| `今天天气怎么样` | 灰色「没听懂」+ 建议 |


### 3.12.4 ⚠ 画面请求是"翻译"和"执行"两段（踩过两次）

**问题**：用户说"播放个烟花"，结果返回 `出错 … "error":"anim 的执行器还没接"`。

**根因**：`/dispatch` 只负责**翻译**。`dispatcher` 判 `anim` 是只读动作 →
`needs_confirm=false` → `_post_dispatch` 直接落进 `run_plan()`，而 `run_plan()`
只会处理 `cmd/query/led_blink`，画面动作落到兜底的
`"%s 的执行器还没接"`。真正能发帧的 `POST /play` **只有确认按钮那一支会调**，
而画面动作永远不弹确认 —— 于是这条路是死的。

**现在的分工**（两边都不能碰对方的活）：

```
POST /dispatch  {"text":"播放个烟花"}
     ↓  只翻译，绝不发帧
{"action":"anim","arg":"fireworks","status":"done","play":true,"seconds":3.0,
 "result":{"frames":0,"sent":[],"reply":""}}
     ↓  前端看到 play:true
POST /play      {"text":"播放个烟花","seconds":3.0}
     ↓  才真的把 60 帧发出去
{"ok":true,"frames":60,"fps_real":20.0,
 "reply":"FB: good=152 bad=0 ooo=168 resync=5"}
```

| 约束 | 理由 |
|---|---|
| `run_plan()` 遇到 `anim`/`draw` **只报错不执行**（`"%s 是画面动作，不在这里执行：请发 POST /play"`） | 曾一度改成转发 `_play_plan()`，结果 `/dispatch` 自己播了 3 秒、前端再播一遍 —— **播两遍**。同一个动作只有一条执行路径 |
| `_post_dispatch` 的判据是 `plan["action"] in ("anim","draw")`，返回值带 `play:true` + `seconds` | 前端靠 `d.play` 分派，不靠"是不是 anim"猜 |
| 前端 `say()` 里写 `if (d.play)`，**不写 `if (isAnim)`** | `isAnim` 这个词曾经用来判"要不要弹确认"，含义已经变过两次，是过期判据 |
| 时长优先级：话里说的（`plan["seconds"]`）> 请求体 `seconds` > 默认 3 秒 | "播 5 秒烟花"必须尊重用户；没说的用默认 |
| 倍速走 `speed`，`t = (n/fps) * speed` | **不能靠提 fps 加速**：I2C 100kHz 下整屏约 92ms ≈ 11fps 硬上限，fps 提到 20 只是丢帧 |

> ⚠ **`status:"done"` 不等于"动画已经播了"。** 对画面请求，它只表示
> "翻译成功，请接着去 `/play`"。`result.frames == 0` 是这个阶段的正常值，
> 别拿它当失败判据。

**连带修掉的两个前端 bug**：

| 现象 | 根因 | 修法 |
|---|---|---|
| `led_blink` 确认后显示"失败"，其实灯在闪 | `/confirm` 对长任务返回 **202 + `status:"running"`**，前端把非 200 或非 `done` 当失败 | 判 `r.job` 走 `await pollJob(r.job, ...)` 轮询到底 |
| 确认按钮文案两张卡不一致 | 一支写"确认发送"、一支写"确认执行" | 统一 `确认执行` |

**自测**（`python pc_agent/api.py --selftest`，33 项）新增 9 项专盯这条分叉：

```
分派成 anim / 不要确认 / status=="done" / play is True / frames==0 /
plan["seconds"]==5.0 / 默认 3 秒 / speed==2.0 / _num_or("abc",3.0)==3.0
```

> **为什么会漏**：我一开始只验证了「`/play` 单独发能不能播」，
> 没走页面真正的路径 `/dispatch → /play`。**接口逐个都对，串起来是断的。**
> 验收必须走用户实际会走的整条链路，而不是逐段测完就宣布成功。

### 3.13 ⚠ float 坐标会让 Bresenham 死循环（PC 端，踩过一次）

**现象**：`python pc_agent\\agent.py "..."` 报
`渲染第 1 帧失败：渲染超时（>1.0 秒）`，且**与 `t` 无关**（第 0 帧就卡）。
`--fps` 调多低都一样，因为根本没渲染出第一帧。

**根因**：`pc_agent/canvas.py` 的 `line()` 是 Bresenham，终止判据是
`if x0 == x1 and y0 == y1: break` 的**精确相等**。LLM 生成的代码常写
`c.line(int(x), y - 12, int(x) - 3 + swing, y, True)`（`swing` 是 float）：
- `x1` 是 float（如 `14.736`），`x0` 是 int
- `sx = -1`，每次 `x0 += sx` 保持整数步进
- **`x0` 永远不可能 `== 14.736`** → `while True` 永不退出

**修法**：`pc_agent/canvas.py` 新增模块级 `_iv(v)`，`line` / `hline` /
`vline` / `rect` / `fill_rect` 入口全部先 `_iv()` 强转。
`int()` 是截断不是四舍五入，坐标差 1 像素看不出来，换来"任何数字进来都不会死循环"。

> **为什么在原语层修而不是改那段缓存代码**：LLM 会持续生成这种写法，
> 改一个缓存文件治不了本。

**排查教训（重要）**：这个 bug 拖了很久才定位，因为症状像"性能问题"。
走过的弯路：
1. 先怀疑帧率/网络/板子 —— 全错，`timeout=5` 的**离线**测试也卡死
2. 加 `threading.settrace()` 逐行记录卡在哪 —— **trace 一次没触发**（报 `?:0`）。
   这个信号当时没被读懂：**不是 Python 层循环**（否则每行都会回调）
3. 差点去改 `threading`/`timeout` 机制 —— 都不是原因
4. ✅ 最后是**直接读那份缓存代码**，看到 `int(x) - 3 + swing` 才确认

> ⚠ 那个 `settrace` 诊断代码**本身成了 bug**：它的回调要跟着被测代码逐行走，
> 被测代码死循环时回调也跟着无限跑。已撤掉，现在超时只打一次
> `faulthandler` 栈（不参与正常路径）。**诊断脚手架不该改变被测系统的行为。**

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
| **串口助手一个字都收不到，波特率设置却是对的** | ① 串口被别的进程独占（UE4/编辑器插件/第二个助手实例）② 烧的是旧 hex ③ 串口线/地线 | 先按 §13.1 三连测：关独占进程 → 重新 objcopy 比时间戳 → 换 COM 号裸开一次（见 §13） |
| **串口日志停在 `[PCF] eth_reset released` 就没了** | CubeMX 重新生成把 `USER CODE` 区外的代码删了 | `git diff` 看 `main.c`；手写代码必须放进 `USER CODE BEGIN/END` 配对里（见 §3.4 注） |
| **CubeMX 重新生成后网口又不通** | `ethernetif.c` 的 5 处手工改动被还原 | 按 §3.4 逐条重做；MAC 变回 `00:80:E1:00:00:00` 或丢了 `HAL_ETH_Start()` 都是它 |

---

## 9. Git 工作流

### 9.1 当前 `.gitignore` 覆盖范围

已忽略：`build*/`、CMake 生成物（`CMakeCache.txt`/`CMakeFiles/`/`compile_commands.json`/
`.ninja_log`/`build.ninja` 等）、编译产物（`*.o`/`*.d`/`*.su`/`*.elf`/`*.bin`/`*.hex`/`*.map`/`*.a`）、
CubeMX/IDE 临时文件（`mx.scratch`/`*.ioc.bak`/`.cproject`/`.project`）、
clangd `.cache/`、`__pycache__/`、OS 垃圾文件，以及 **`pc_agent/dispatch_log.jsonl`**
（dispatcher 的运行日志，随调试无限增长；对应的自测集 `pc_agent/dispatch_cases.jsonl`
是验收标准，**必须保留**）和 **`pc_agent/.api_key`**（`api.py` 给一次性确认票
签名的密钥，首次运行自动生成；进版本库等于公开私钥）。

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

### 2026-10-18 — 页面报"没听懂"的两条说法：补排障与寄存器规则

**现象**（用户实点页面）：`屏幕上一个字都没了` 和 `读一下 GPIOB` 都显示
「没听懂」。前者 `by=rule#trouble` 但 `action=null`，后者 `by=llm` 也没给出动作。

**根因**：① 排障规则命中后返回 `action=None` + 一句"先发 OLED INIT…"的
**建议文本** —— 前端只能显示"没听懂"，用户还得把建议自己再打一遍。
② 规则层完全没有寄存器读取的说法，`GPIOB` 这种"一半人话一半符号"的输入
必然掉到 LLM。详见 §3.12.1。

**改动**（全部在 `pc_agent/dispatcher.py` 的规则层，`api.py` 一行没动）：

1. **排障改给可执行动作**：返回 `action=cmd, arg="OLED INIT"`（`needs_confirm=true`）。
   选 INIT 不选清屏 —— 屏可能被别的帧画满了，INIT 重走初始化并清屏两种情况都覆盖。
2. **新增 `rule#reg`**（寄存器读取）：`GPIOB 的 IDR 是多少` → `R 40020410 1`；
   `读 40020014` → `R 40020014 1`。基址 `0x40020000 + (端口-'A')*0x400`，偏移表
   `_REG_OFFSETS`（MODER 0x00 … ODR 0x14 … AFRH 0x24）。点名的寄存器不在表里时
   **只读基址 4 个字**，不猜偏移。
3. **新增 `rule#reg_any`**：`读一下 GPIOB` / `读一下寄存器` → `HELP`。
   没说读哪个就回清单 —— LLM 面对"差一个参数"的请求只会猜一个地址，猜错比不猜更糟。
4. **`_TROUBLE_RE` 扩展** `(屏幕|显示屏|屏).{0,4}(没|不|黑|白)`，覆盖"屏幕没亮/屏幕黑了"。

**修的过程中又踩了四个坑**（都已写进 §3.12.1 的陷阱表，都是"跑一遍才炸"的）：

| 坑 | 症状 |
|---|---|
| 命名组和取值对不上 | `IndexError: no such group`（先缺 `reg`/`word`，补完 `reg` 还剩 `word`） |
| 可选组 `(?:...)?` 让后续永远匹配不到 | `GPIOB 的 IDR` 在 `GPIOB` 处就匹配成功 → **问哪个寄存器都回 ODR 的地址**。改成端口名与寄存器名分开匹配 |
| 排障规则放太靠前会抢走后面的说法 | `刷屏卡不卡`（卡→不动了）和 `屏幕没亮，帮我开屏`（没亮）全被判成排障 → OLED INIT。把排障**挪到屏幕命令之后**，并加 `_ASK_INFO_RE` 挡掉"卡不卡/亮不亮/还在吗"这类只读询问 |
| 读规则截走写操作 | `W 40023800 0` 里的 8 位地址命中读规则 → 变成 `R 40023800 1`，**api 自测里"写 RCC 被拦"当场失败** |

> ⚠ 最后一条是**自测集当场抓到的**，不是我想到的。这就是"改规则必须两套自测都跑"
> 的价值：`dispatcher --test` 只测规则层自己不矛盾，只有 `api --selftest` 会
> 端到端检查"写 RCC 必须被拒"。**只跑一套等于没跑。**

**验证**：

- `python pc_agent/dispatcher.py --test` → 自测集 58 → **67 条**，规则层 **101/101**，未命中 8 条。
  新增 10 条用例（3 条寄存器有名 + 读地址 + 2 条只报端口 → HELP + 纯名词拒 + 屏幕没亮 + 刷屏卡不卡）。
  其中 `"屏幕上一个字都没了"` 的期望从 `action: null` **改成 `cmd/OLED INIT`** —— 这是有意的行为变更。
- `python pc_agent/api.py --selftest` → **33/33 失败 0**。
- 真机端到端（重启服务后，模拟浏览器的 `/dispatch` 路径）：

```
[PASS] 读一下 GPIOB            -> done by=rule#reg_any arg=HELP
[PASS] GPIOB 的 IDR 是多少     -> done by=rule#reg arg=R 40020410 1  reply='OK R 0x40020410 = 0x0000101B'
[PASS] 读 40020014             -> done by=rule#reg arg=R 40020014 1    reply='OK R 0x40020014 = 0x00000000'
[PASS] 屏幕上一个字都没了       -> needs_confirm by=rule#trouble arg=OLED INIT preview=['OLED INIT']
[PASS] 屏幕没亮                -> needs_confirm by=rule#trouble arg=OLED INIT
[PASS] 刷屏卡不卡              -> done by=rule#query arg=OLED STAT
[PASS] 在吗                    -> done by=rule#query arg=PING  reply='PONG tick=394032'
失败 0 / 7
```

> ⚠ **第一次跑这 7 条时失败 2 条，原因不是代码**：8765 端口上有**两个** python
> 进程在 LISTENING（旧的 15:13 那个没退干净，新代码跑在 15:19 那个上），
> 请求随机落到旧进程，于是看到的是旧规则。`job_kill` 杀不掉 detached 的子进程，
> 得按 PID `Stop-Process`。**改完 `dispatcher.py` 一定要确认服务真的重启了** ——
> 判据是 `netstat -ano | Select-String ':8765'` 只剩一个 PID，而不是"我执行过重启"。

### 2026-02-13 — 修「播放个烟花」报 `anim 的执行器还没接` + proto 心跳错位

**现象**（用户实点页面）：说 `播放个烟花`，卡片上显示 `出错`，原始 JSON 里
`"status":"error"` 且 `"error":"anim 的执行器还没接"`。

**根因**：`/dispatch` 只翻译。`anim` 被判只读 → `needs_confirm=false` →
`_post_dispatch` 直接落进 `run_plan()`，而它只处理 `cmd/query/led_blink`，
画面动作撞上兜底报错。真正能发帧的 `POST /play` 只有"点确认"那一条分支会调，
画面动作永远不弹确认 —— **这条路是死的**。详见 §3.12.4。

> **我的责任**：上一轮只验证了 `POST /play` 单独发能不能播、`/dispatch` 单独发
> 返回什么，**没在页面里点过**。接口逐个都对，串起来是断的。

#### 画面请求改成"两段"（`pc_agent/api.py` + `pc_agent/index.html`）

1. **`/dispatch` 对 `anim`/`draw` 返回 `status:"done"` + `play:true` + `seconds`**，
   `result.frames` 为 0（翻译阶段本来就没发帧）。**绝不在这里发帧。**
2. **`run_plan()` 遇到 `anim`/`draw` 只报错**：`"%s 是画面动作，不在这里执行：请发 POST /play"`。
   曾一度改成直接转发 `_play_plan()`，结果 `/dispatch` 自己播了 3 秒、前端再播一遍
   —— **播两遍**。同一个动作只能有一条执行路径。
3. **前端 `say()` 用 `if (d.play)` 分派**去调 `playAnim()`，不再用 `isAnim`
   那种"猜是不是动画"的过期判据。
4. **动画默认播 3 秒**（`ANIM_DEFAULT_SECONDS`），播完给「再播一次」按钮。
   时长优先级：话里说的（`plan["seconds"]`）> 请求体 `seconds` > 默认 3 秒；
   上限 `ANIM_MAX_SECONDS = 30`。
5. **倍速走 `plan["speed"]`，`t = (n/fps) * speed`**。**不能靠提 fps 加速** ——
   I2C 100kHz 下整屏约 92ms ≈ 11fps 硬上限，fps 提到 20 只是丢帧。
6. 连带修掉两个前端 bug：`led_blink` 收到 `202 + status:"running"` 被当成失败
   （改判 `r.job` 走 `await pollJob(...)`）；确认按钮文案两支不一致（统一「确认执行」）。
7. `api.py` 的 `selftest()` **24 项 → 33 项**，新增 9 项专盯这条分叉：
   分派成 anim / 不要确认 / `status=="done"` / `play is True` / `frames==0` /
   `plan["seconds"]==5.0` / 默认 3 秒 / `speed==2.0` / `_num_or("abc",3.0)==3.0`。

#### `pc_agent/proto.py` 心跳错位（同一批里查出来的）

**现象**：经 `api.py` 跑端到端时，`FB?` 收到了 `STM32F429 在线，已收 115 条，命令 48 条`。

**根因两件事叠在一起**：

| # | 问题 | 真相 |
|---|---|---|
| 1 | 我把每秒心跳当成了 `INFO` 的回应 | 固件里 `INFO` 回的是 `board 192.168.1.30  tick=... ms  io_count=2`（`Core/Src/reg_shell.c:392` 的 `cmd_info()`）；`STM32F429 在线...` 是 `Echo_Service_Poll()` 每秒主动推的**心跳**（`Core/Src/echo_service.c:638`） |
| 2 | `send_text()` 只 `recvfrom` 一次 | 收到任何"在途旧包/心跳"就当成本条回应 —— **一次错位之后每条命令都拿到上一条的回应**，看起来像协议错位 |

**修法**：

```python
_HEARTBEAT_PREFIXES = ("STM32F429", "心跳")

def _is_heartbeat(text: str) -> bool:
    t = text.lstrip()
    for p in _HEARTBEAT_PREFIXES:
        if t.startswith(p):
            return True
    return False
```

`send_text()` 改为：① 发之前先用 `settimeout(0.02)` **排空积压**；② 发之后循环收，
`_is_heartbeat()` 为真的包**丢弃继续等**；③ 到 deadline 才抛
`BoardError("板子没有回包（超时）。检查：网线、板子是否在 %s、Windows 防火墙、以及是否用了正确的端口。")`。
判不准是不是心跳时**当成回应**（宁可错收一条，也不要空等超时）。

> ⚠ **诊断教训**：我一度给 `_is_heartbeat()` 写了反向特例
> （`if t.startswith("STM32F429") and "已收" in t: return False`）来"修正"一个
> 并不存在的错位，白折腾一轮。**"回包错位"和"我把协议记错了"看起来一模一样。
> 下结论前先去固件读回应格式**（`reg_shell.c` 的 `cmd_info()` / `echo_service.c` 的心跳），
> 别凭记忆写断言。

#### 验证

| 项 | 结果 |
|---|---|
| `_probe_fb2.tmp.py`（5 条 `_is_heartbeat` + Board 直连 2 轮 × 5 条命令） | 全 PASS，`FB?`→`FB:`、`INFO`→`board `、`PING`→`PONG` 各归各位 |
| `_e2e_anim.tmp.py`（按页面真实路径 `/dispatch → /play`） | 全过。`播放个烟花`→`play=true seconds=3.0`；`/play`→`frames=60 fps_real=20.0 reply='FB: good=152 bad=0 ooo=168 resync=5'`；`播 2 秒 烟花`→`seconds=2.0`；`在吗`→done 无 play；`把灯打开`→needs_confirm 无 play |
| `dispatcher.py --test` | 58 条，规则层 **84/84**，未命中 7 条 |
| `api.py --selftest` | **33/33，0 失败** |
| `agent.py --test` | **10/10**（stderr 的 faulthandler 栈是"故意死循环"用例打的，exit 0） |
| `_check_js.tmp.py` | 括号配平 + 12 项前端契约全 PASS，3 项死代码已清除 |

> ⚠ **改 `.py` 模块后必须重启常驻服务再验证**。这一轮第一次经 `api.py` 复验仍然失败，
> 原因是服务进程是在 `proto.py` 修复**之前**启动的 —— 测的是旧模块。`job_kill` 重启后全过。

同步更新 AGENTS.md §3.12.3（「四种结局」表加 `done + play:true` 行）、
新增 §3.12.4（画面请求两段式）、§3.12.2/§3.12.3 自测行数 24 → 33、§10 本条目。

### 2026-02-13 — 阶段三：`index.html` 浏览器前端 + `/play` `/render`

阶段一到二都只能在命令行/curl 里说一句话。用户在 m00167 要的是"打开一个页面，
直接说要什么，AI 翻译后执行，写操作在页面上确认"。本批做出这个页面。

**新增 `pc_agent/index.html`**（单文件、零依赖、零 CDN，约 400 行原生 JS + 内联 CSS）：

1. **左侧对话区**：输入框 + 常用说法 chips + 每轮一张卡片。卡片上是
   `说的话 / 状态标签 / 键值表（动作、参数、来源、为什么）/ 写操作逐行预览 /
   [确认执行] [取消] + 倒计时`。
2. **右侧**：画面预览（`POST /render` 拿 PNG，4 倍放大）、板子状态
   （`GET /healthz` 轮询）、可用命令表（`GET /commands`）。
3. **按 `status` 四值分派 UI，前端不判断安全性**：`done` 直接显示回包；
   `needs_confirm` 才给确认按钮且倒计时到 0 自动禁用；`refused` 只显示
   `why` 和建议，**故意不给"我就要执行"的逃生按钮**；`error` 打印原始 JSON。
4. **前端不拼固件命令**。所有安全判据仍在服务端
   （`dispatcher.needs_confirm()` + `api.py` 的 token 验签）。改页面 JS 提升不了
   权限 —— 如果安全性由前端决定，那它就不是安全性。

**`api.py` 新增两条路由**：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/play` | `{text, seconds, fps}` → 真的逐帧发到板子，返回 `{sent, frames, fps_real, reply}` |
| POST | `/render` | `{text, t}` → 直接回 `image/png`，**不发板子** |

- **`/play` 不需要 token**：走的是 FB 帧通道（不是写命令，不碰寄存器/IO）。
- **`/play` 时长默认 3 秒而不是"一直播到点停"**：HTTP 请求必须有尽头。反过来的
  设计（前端"开始"/"停止"两次请求）会有个致命状态 —— 页面上什么都看不见、
  后台线程还在发 UDP 占着板子。那是最难排查的一类故障。
- **`/render` 复用 `agent._save_png()`**（写临时文件→读回→删），不另写一套 PNG
  编码：预览必须和真发板子用同一段渲染。两套渲染器迟早画出不同的东西。
- **`/play` 复用 `agent._render_named()` 而不是 `agent.play()`**：`play()` 是 CLI
  播放循环，绑着 `print()` 和 `KeyboardInterrupt`，HTTP 里只需要"渲染 N 帧 +
  进度回调"这一半。

**真机验证**（板子在线，`api.py` 跑在 8799）：

| 请求 | 结果 |
|---|---|
| `POST /play {"text":"播个烟花","seconds":1.0,"fps":10}` | `status=done`、`by=rule#anim`、`frames=10`、`fps_real=10.0`、`reply="STM32F429 在线，已收 6635 条，命令 181 条"` |
| `POST /render {"text":"播个烟花","t":0.7}` | 返回 613 字节 PNG（512×256） |

**排查记录（结论：不是 bug）**：`/render` 出来像"一个大圆圈"，一度怀疑渲染
管线坏了。逐层核对：`canvas.get()` 统计 24 个亮点、包围盒 x 27~52 / y 19~44、
`_save_png()` 输出正常、行分布 11 行每行 2~3 点 —— **都正常**。原因是
`anim.fireworks` 在 t=0.7 时 age 已经 0.44，24 个粒子散成一个环，而
`age < 0.25` 的中心余亮早就没了。用 `anim.car`（车+轮子+地面虚线）对照渲染
一次，整幅画正确 → 确认管线没问题，是这一帧本来就长这样。

> **教训**：视觉异常先算清楚"这个时刻应该长什么样"，再去怀疑管线。
> `fireworks` 是"随时间变化"的动画，静态看一张图永远像坏了。

**文档**：新增 AGENTS.md §3.12.3（页面结构、四种 status 的 UI 分派、
两条新路由的理由、上面这条排查记录、手工验收清单），并在本变更日志登记。

**未做**（刻意）：HTTPS/鉴权、多轮对话、把 `api.py` 做成开机自启服务、
`knowledge`/`draw`/`render` 三个 action 的板子侧执行器（仍走 `/play` `/render`）。

### 2026-02-13 — 阶段二：`api.py`（HTTP 外壳 + 两段式确认 + 一次性票）

阶段一的 dispatcher 只能在命令行跑，`--yes` 一个标志就把"翻译"和"执行"
一次说完了。用户要的是**前端上"我先看到它理解成什么，再点确认"**，
所以本批把 dispatcher 包成 HTTP，并把确认拆成两次独立请求。

**新增 `pc_agent/api.py`**（不新增第三方依赖，`http.server` + `hmac`）：

1. **五条路由**：`/healthz`、`/commands`、`/dispatch`、`/confirm`、`/job/<id>`。
   `/dispatch` **只翻译**：只读的顺手执行，写操作返回 `needs_confirm` +
   `preview` + `token`，**一个字节都不发给板子**。

2. **一次性 token 用 HMAC 签，服务端不存队列**：
   `base64url(payload) + "." + base64url(HMAC-SHA256(key, payload))`，
   payload 含 `raw/action/arg/sub/by/why/nonce/exp`。验签 + 验过期（`TOKEN_TTL=120`）
   + 验 nonce 未用过，三条全过才执行。

   > **为什么不存待确认队列**：存队列就有"重启丢一半""多进程状态不一致"
   > "忘了清理导致三天前的指令被点火"。无状态签名票把这些问题全部消掉。

   > ⚠ **票里刻意不放 `needs_confirm`**，验票时用 `dispatcher.needs_confirm()`
   > **重算**；`run_plan()` 在执行前还会再调一次 `dispatcher.validate_cmd()`。
   > **安全结论不能由被检查的对象自己声明。**

3. **判据全部复用 `dispatcher.py`，一行策略都没复制**。`api.py` 自己只写
   `run_plan()`（发出去、收回来，因为 `dispatcher.execute()` 只 print + 返回退出码，
   拿不到回包正文）。所以 `--test` 测的仍是同一份逻辑。

4. **长任务异步**：`led_blink` 闪 50 次要 20 秒，同步 HTTP 会把这 20 秒
   服务全占住。改为 `202` + `job_id` + 进度轮询。实测闪灯 10 次期间
   并发发"在吗"，**12ms 返回 PONG**。

5. **两道网络防护**：默认只听 `127.0.0.1`；除 `/healthz` 外校验 Host 头
   （挡 DNS rebinding —— 你浏览器里的网页能往 localhost 发请求）。
   实测 `Host: evil.example.com` → `403`。
   **这是"够用"级，不是认证。**

6. **`--selftest` 24 项**，覆盖：token 验签/改签/过期/复用、Host 拒绝、
   只读直执行、写操作只发票、RCC 写被拒、闲聊被拒、长任务进度与 `sent` 序列、
   并发、坏输入。**24/24 通过**（真板子在线）。

**同时修掉的三个真 bug**：

7. **规则层 `闪灯 10 次` 误判灯号**（HTTP 层第一次真实使用才暴露）。
   `灯\s*([01])` 贪婪只吃下 `1`，剩个 `0` → 判成 DS1，用户没说灯号却闪了
   另一盏灯；`闪灯 1 次` 里那个 `1` 是次数，被当成灯号。
   修法：裸"灯"后面的数字**后面不能跟数字或量词**（次/下/遍/秒/毫秒）。

   > ⚠ 第一版把排除规则**两个分支共用**，把 `闪 DS1 3 次` 也否掉了
   > （`1` 后面跟着 `3`），退回 DS0。**`DS1`/`LED1` 是明确的灯号声明，
   > 不能受裸"灯"的歧义判断约束** —— 两个分支必须分开写。

8. **`--selftest` 在 GBK 控制台崩溃**：`UnicodeEncodeError: 'gbk' codec can't
   encode character '\u2717'`。CLI 输出里的 `✗`/`✅` 全部换成 ASCII 的
   `[FAIL]`/`[PASS]`。**给 CLI 加符号前先想控制台编码。**

9. **执行那行日志把来源覆盖掉了**：`/confirm` 原本把 `by` 写成 `"confirm"`，
   于是"这条是规则翻译的还是 LLM 猜的"查不出来了 —— 而这正是日志存在的
   唯一理由。改为 `confirm<rule#led>`：前缀说明确认执行过，尖括号保留原始来源。

**其它**：

10. `.gitignore` 新增 `pc_agent/.api_key`（签名密钥，进库等于公开私钥）。
    验证：`git check-ignore -v` 命中 `.gitignore:148`，
    `git ls-files -i -c --exclude-standard` 仍为空。
11. `pc_agent/README.md` 补 dispatcher / api.py 两节（把 `文件说明` 表补全）。

**验证**：`dispatcher.py --test` → **79/79（53 条用例）**；
`api.py --selftest` → **24/24**；真机端到端跑通 `/dispatch` → 改票被拒 →
`/confirm` 执行 → `/job` 轮询完成。

**为什么不直接改 `dispatcher.py` 加 HTTP**：dispatcher 的价值是"纯翻译 +
确定性自测集"，掺进 socket 和 token 之后 `--test` 就不纯了。多一个薄壳
`api.py`，多一层可单独自测的东西。

### 2026-02-13 — `dispatcher.py` 新增 `led_blink`：真的会闪灯的动作

**问题**（用户现场，m00507）：

```
python pc_agent/dispatcher.py "在吗，在就闪灯"
  理解：anim eyes   来源：rule#led   只读
[dispatcher] anim 的执行器还没接
```

两个毛病一起暴露：① "闪灯" 被规则层错认成 `anim eyes`（当时没有闪灯动作，
只好回退成播眼睛动画并加一条 warn）；② `anim` 的执行器根本没接，
所以哪怕认对了也只会打印一行"还没接"。

**修法**：新增第 7 个 action **`led_blink`**，`arg` 是对象
`{"index": 0|1, "times": 次数, "period": 半周期秒数}`。

> **为什么它是唯一的多条命令动作**：`ACTIONS` 里其余 6 个都是"**一条**指令"
> （cmd/query 一条固件命令，anim/draw/render 一次播放/渲染，knowledge 一个字段）。
> 而固件里**没有"闪灯"这条命令**，闪烁只能是 PC 端按时间反复发 `LED n 1` / `LED n 0`。
> 硬塞进 `cmd` 会让 `arg` 变成"命令列表"，整个执行层都要跟着改；
> 单开一个 action 反而是最小改动，而且语义清楚。

**执行器 `_exec_led_blink()` 的三个设计点**：

1. **在同一个 `Board` with 块里循环**。每次 `Board(...)` 都新建 socket + bind
   临时端口，5 次闪就是 10 个 socket。
2. **`finally` 里必须补一条 `LED n 0`**。中途 Ctrl+C 或板子掉线也要把灯恢复成灭。
3. **结束回到灭是"幂等"设计**：闪完停在亮，用户下次看灯分不清"这是闪完留下的
   状态"还是"本来就这样"。执行前后板子状态一样，才敢随便重放。

**参数上限**（防止一句话占住板子几十秒）：`LED_BLINK_MAX_TIMES = 50`、
`LED_BLINK_MIN_PERIOD = 0.05` 秒、`period` 上限 2 秒。默认 5 次 / 200ms。
"闪2秒"这种**只说时长不说次数**的，按 `次数 = 时长 / (2×半周期)` 折算。

**又抓到一个只在真实路径上炸的 bug**：`_is_reg_write()` 里
`(plan.get("arg") or "").strip()` 遇到 `led_blink` 的 **dict** 参数直接
`AttributeError: 'dict' object has no attribute 'strip'`。
`--json` 分支走不到它、自测集也不构造带 dict 的 plan，所以**两套测试全绿，
只有手工敲一次命令才炸**。教训：`--json` 能过不代表人类路径能过。

**真机验证**（`--yes`，板子在线）：

```
[dispatcher] → 闪 DS0 5 次，间隔 200ms（共 10 条命令，约 2.0 秒）
  1/5  OK IO 0 (DS0) = ON      ...  4/5  OK IO 0 (DS0) = OFF
[dispatcher] ✅ 闪完了，灯已恢复成灭
```

**回归**：自测集 53 条 → 规则层 **79/79**（新增 4 条闪灯用例 + 安全断言）；
`在吗` 仍判 `query PING` 只读直接执行；`W 40023800 0` 仍被分派器自己拒掉。

同步更新 AGENTS.md §3.12.1（action 表 + 闪灯小节）与本节。**固件侧无改动。**

**`.gitignore` 新增 `pc_agent/dispatch_log.jsonl`**（见 §9.1）。它是每次分派追加一行的
运行日志，随本机调试无限增长，属于运行产物；而自测集 `dispatch_cases.jsonl`
是手工维护的验收标准，**必须进版本库**。两者只差一个词，别一起忽略。


### 2026-02-13 — 新增 `pc_agent/dispatcher.py`：一句话 → 结构化指令（阶段一）

**做了什么**：用户要"代码简洁的同时功能强大"，于是把"自然语言 → 板子指令"
这一层从 `agent.py` 里拆出来，单独成 `pc_agent/dispatcher.py`（约 820 行 +
53 条自测集）。`agent.py` 只管画画，dispatcher 只管理解，两者边界清晰。

**新增文件**：

| 文件 | 说明 |
|---|---|
| `pc_agent/dispatcher.py` | 规则层 + LLM 层 + 执行层；6 个闭合 action |
| `pc_agent/dispatch_cases.jsonl` | 53 条自测集（验收标准），规则层必须 100% 过 |
| `pc_agent/dispatch_log.jsonl` | 运行日志（每次分派一行） |

**真机验证**（板子 `192.168.1.30:8080` 在线，全部实打实跑过）：
`PING` → `PONG tick=...`；`INFO` → `board 192.168.1.30  tick=... io_count=2`；
`LED 0 1` / `LED 0 0` → `OK IO 0 (DS0) = ON/OFF`；
`OLED ON` → `OK display on`；`OLED CLR` → `OK OLED cleared`；
`FB?` → `FB: good=... bad=0 ooo=... resync=...`；
`OLED STAT` → `OLED flush: busy=0 dropped=1`。

**开发中抓到的五个真 bug**（都是自测集或真机当场发现的，记录以防回退）：

1. **⚠ `needs_confirm` 被绕过（安全）**：规则层 `_plan("cmd", ...)` 默认
   `needs_confirm_=False`，而 `dispatch()` 只在某个分支里补算 → **"把灯打开"
   被判成只读，不加 `--yes` 就直接打到了板子**。修法：新增 `_finalize(hit, text)`，
   对**每一条** cmd/query 统一重算 `needs_confirm`，规则层和 LLM 层共用；
   `run_tests` 同时加入安全断言（每条 cmd 的 `needs_confirm` 必须等于独立重算的结果）。
   自测计数因此从 39/39 变 **69/69**。
2. **命令头只读 ≠ 命令只读**：`if head in READONLY_CMDS: return False` 让
   `IO 1 1`（真在写引脚）被判只读。拆成四段：OLED 看子命令 / LED·IO 看有没有"值" /
   其余查白名单。附带修掉一个隐藏崩溃：旧代码 `tok[2]` 在 `"IO 0"`（2 token）上
   会 `IndexError`，而 **`IndexError` 不是 `Exception` 的子类**，会让整个进程崩掉。
3. **`WB` 的字节上限校验是死代码**：它写在 `return ... GPIO 区间` 之后，
   只有落到 `return "不在白名单"` 才可能被执行 —— 等于对合法地址永不检查，
   `WB 40020014 1FF` 会原样打到板子。已移到读取 `val` 之后、区间判断之前。
4. **`_TROUBLE_RE` 正则方向搞反**：`没.{0,4}字` 对"屏幕上一个字都**没了**"
   永远不命中（中文述宾语序里"字"在前）。两个方向都写才覆盖。
5. **开屏正则吞掉所有"打开"**：先写成 `(开|亮|点亮|打开).{0,3}屏`，
   "板子上的灯亮一下"会被误判；改成 `(开|亮|…)(屏幕|屏)?` 更糟 ——
   `(屏幕|屏)?` 是**可选**的，等于裸"打开"也算开屏，**"把灯打开"全被判成 OLED ON**。
   最终要求"屏"字必须真的出现且和动词紧挨。这两次都是**自测集当场抓到的**。

**固件不匹配（实测）**：`LED DS0 1` 会让板子回 `ERR: bad LED index 'DS0'` ——
固件只认**数字索引**（`Core/Src/reg_shell.c` 里 LED 走 `parse_dec`），
dispatcher 发的是 `LED 0 1`。

**离线降级验证**：把 `OLED_AGENT_BASE_URL` 指向 `http://127.0.0.1:9`，
LLM 层报 `URLError: <urlopen error [WinError 10061] 由于目标计算机积极拒绝...>`，
程序不崩、正常给出拒绝原因。

同步更新 AGENTS.md 新增 §3.12.1 与本节变更日志。**固件侧无任何改动。**


### 2026-02-13 — 帧率修复 + FBSEQ 时间判据 + 链路检测搬迁 + 中文/float 坐标

**这是积累多轮的一批改动**（跨了链路修复、OLED 帧率、FBSEQ 判据、PC 端中文与
沙箱修复）。用户实测确认的部分逐条标注。

#### 固件侧

1. **`ETH_PHY_CheckLink()` 搬到自建文件 `Core/Src/eth_phy.c`**（§3.4 防御策略）。
   原来链路检测写在 `LWIP/Target/ethernetif.c`，被 CubeMX 重新生成清空后
   `netif_set_link_up()` 从未被调用 → `netif_is_link_up()` 恒假 → `ip4_route()`
   返回 NULL → `udp_sendto` 返回 `ERR_RTE(-4)` → **能收不能发**。
   现在 `ethernetif.c` 里只留一行调用 + 醒目注释，重生成只丢 1 行、一眼可见。
   同时改为**只在链路状态变化时打印**（`static uint8_t s_last_link`），
   不再每 100ms 刷屏。
   ✅ **用户实测验证**：`--check` 的 PING/INFO/FB?/OLED STAT 全部有回包，
   `[LINK] UP BSR=0x782D autoneg_done=1` 出现。

2. **`framebuf.c` 帧头 memcmp 比错字节数**：`memcmp(data, "FBSEQ ", FB_SEQ_HEADER_BYTES)`
   里 `FB_SEQ_HEADER_BYTES` 是 8，但字面量 `"FBSEQ "` 只有 6 字节 →
   把序号 2 字节也算进比较，**只有 seq=0 那一帧能过**。
   引入 `FB_SEQ_MAGIC_BYTES = 6` 做前缀比较。
   ✅ **用户实测验证**：`FB: good=80 bad=0 ooo=80` —— `bad` 从 21 变 0。

3. **FBSEQ 序号判据改为"时间切会话"**（详见 §3.11）。
   曾经用过 `FB_SEQ_WINDOW = 128` 的纯序号窗口版，被实测推翻：
   连播两个 4 秒动画后 `FB: good=24 bad=0 ooo=72 resync=0` —— 第二个动画
   序号从 0 开始、差值 -48 落在窗口内，**48 帧全被当迟到包丢掉**。
   现在用 `FB_SESSION_GAP_MS = 500` 按时间间隔切分会话。
   `FB_Stats` 输出新增 `resync=%lu`。

4. **`oled.c` 的 `OLED_FlushPoll()` 由二段式改为一次调用发一整页**。
   原来是"一次调用只走一步"（发换页命令**或**发一页数据），8 页 × 2 步 =
   **16 次调用**才刷完一屏；主循环约 10ms/圈 → 160ms/帧 ≈ **6.25fps**，
   与实测 6.7fps 完全吻合 —— **这就是"眼睛看起来不动"的根因**。
   改为 `OLED_Send(pageCmd,4)` 紧跟 `OLED_Send(s_flush_buf,129)`，
   删除 `s_flush_stage` 变量。
   ✅ **用户实测验证**："眼睛都能动了"。

5. **`oled.c` 的 `OLED_ShowFrame()` 忙时不再丢帧、改为从头重刷**。
   旧逻辑是 `s_flush_active` 为真就 `s_flush_dropped++` 然后 return ——
   被丢的其实不是新帧，而是**正在刷的那一帧的后半截**，屏上定格成
   "上帧前几页 + 下帧后几页"的撕裂画面且永远落后半帧。
   现在忙时也照常 `s_flush_page = 0`、`s_flush_active = 1` 并立刻发第 0 页命令；
   代价是一页可能重发（129 字节 @400kHz 约 3ms），保证屏幕永远是某帧的完整内容。
   `s_flush_dropped` 语义随之改为"被中途打断、改为从头重刷的帧数"。
   ✅ **用户实测验证**："眼睛一开始动了，复位之后就不会动了" → 后经
   `OLED_Send` 超时恢复修复（`HAL_I2C_Master_Transmit` 的 `HAL_MAX_DELAY`
   改为带超时）彻底解决，复位后也能动。

#### PC 端（`pc_agent/`）

6. **`agent.py` 的 `_chat_url()`**：用 `re.search(r"/v\d+$", base)` 判断 base 是否
   已带版本路径。DeepSeek/OpenAI 不带，通义千问
   `https://dashscope.aliyuncs.com/compatible-mode/v1`、智谱
   `https://open.bigmodel.cn/api/paas/v4`、本地 Ollama `http://localhost:11434/v1`
   都自带 —— 简单拼 `/v1/chat/completions` 会 **404**。
   另新增 `--envcheck` 与 `_KNOWN_ENDPOINTS`（五家常用端点）。

7. **`agent.py` 的 `play()` 调错对象**：`--anim` 传的是**裸函数** `fn(t, params)`，
   LLM 路径传的是 **`Renderer` 对象**（有 `.render()`）。原代码写死
   `renderer.render(t, params)` → `AttributeError: 'function' object has no attribute 'render'`。
   此 bug 一直未暴露是因为板子从未成功回过包。加 `_render_once()` 用
   `getattr(renderer, "render", None)` 分派。

8. **`anim.py` 新增 `eyes_fast` / `car` / `fireworks`**。
   - `eyes_fast`：方波式摆动让瞳孔在 ±0.95 之间以 1 秒周期扫动，
     摆幅是普通 `eyes` 的 4 倍以上 —— 专门用来验证"帧率够不够让画面动起来"
   - `car`：车身左移循环 + 地面滚动虚线 + 轮速按纯滚动条件
     `spin = -(t * speed) / max(1, r)`
   - `fireworks`：`random.seed(20241016)` 保证纯函数，粒子带重力 `age * age * 16`

9. **`bitmap.py` 二值化阈值 `128` → `_DOT_THRESHOLD = 96`**。
   16px 抗锯齿后二值化，阈值 128 偏高导致笔画断裂。

10. **沙箱注入 `draw_text()`**（详见 §3.12 的设计决策）。
    `_make_text_helper()` 返回闭包，**内部延迟 `import bitmap`** —— 顶层 import
    会在非 Windows 平台直接炸，且让 `--envcheck` 之类的诊断路径在缺 GDI 时
    仍能列出其它原因。

11. **`sandbox.py` 的 `timeout` 1.0 → 3.0 秒**。1 秒对 128×64 的纯画线代码
    看似极宽松（正常 1ms 内），但假阳性会让整个播放 `break` 退出，
    用户看到"动画完全没出来"，比多等 2 秒糟得多。

12. **⚠ `canvas.py` 的 float 坐标死循环修复**（详见 §3.13）。
    这是本批**最重要的 PC 端 bug**：`line()` 的 Bresenham 终止判据
    `x0 == x1` 要求整数，LLM 写 `int(x) - 3 + swing`（float）就死循环。
    新增 `_iv()` 在 `line`/`hline`/`vline`/`rect`/`fill_rect` 入口强转。
    ✅ **离线实测验证**：那份缓存代码从"第 1 帧超时"变成
    **48 帧 0.010 秒 → 4648 fps**；沙箱自检 10/10 全拦住。

13. **撤掉 `sandbox.py` 里 `threading.settrace()` 诊断**（曾用于定位超时卡在哪行）。
    它的回调要跟着被测代码逐行走，被测代码死循环时回调也跟着无限跑 ——
    **诊断脚手架改变了被测系统的行为**。现在超时只打一次 `faulthandler` 栈。

#### 其它

14. **`.gitignore` 新增 pc_agent 临时产物段**：`pc_agent/code_cache/`、
    `eyes_preview.png`、`*_preview.png`、`car*.txt`、`ascii_*.txt`。
    `code_cache/` 是随着本机环境变化的运行产物，不适合进版本库。

同步更新 AGENTS.md §3.11 / §3.12 / §3.13（新增）/ §11 待办 / §10 变更日志。

### 2026-02-13 — 修 `--check` / `--test` 被 API key 挡住

**现象**（用户实测，`pc_agent/agent.py` 第一次真正跑）：

```
C:\...\ETHERNETtest>python pc_agent\agent.py check
[agent] 出错：没有配置 API key。请设置环境变量 DEEPSEEK_API_KEY，例如：
    set DEEPSEEK_API_KEY=sk-xxxx
（没配也能用：--anim 播内置动画，--code 播你自己的代码）
```

`check` 只是 ping 板子看在线不在线，**跟 LLM 一点关系都没有**，却退出在 key 检查上。
`--list` / `--test` 同理。

**根因**：`main()` 的分派里 `--test` 被误接给了 `_cmd_play()`，而
`_cmd_play()` 第一行就是 `_make_renderer(args)` → `_resolve_code()` →
`code_for()` → `_llm_config()`，于是读 key 失败、抛 `LLMError`、被
`__main__` 的 `except (SandboxError, LLMError)` 打印退出。

`_cmd_check()` 和 `_cmd_list()` 本身**不碰 LLM**，它们的 return 在 `main()`
里也排在前面 —— 之所以还是被拦，是因为 `main()` 顺序里 `--check` / `--list`
的判断在 `--test` 之前，但它们各自 return 到的是**正确**的函数；
真正被 key 卡住的是原先 `if args.test: return _cmd_play(args)` 这一支。

**修法**：

- 新增 `_cmd_sandbox_test()` —— 只调 `self_test()`，不建 `Board`、不建
  `Renderer`、不读 key。
- `main()` 里 `--test` 改接 `_cmd_sandbox_test()`。
- 从 `_cmd_play()` 里删掉那段 `if args.test:` 分支（它已经进不去了）。

**规矩（写 CLI 时记住）**：**读取外部配置（API key、配置文件）必须发生在
真正需要它的那一刻，不能放在所有命令的公共入口。** 否则每加一个不需要
网络的子命令（`--list` / `--test` / `--check`），都要它陪绑一次 key 检查。
`--check` 的价值恰恰是"网络没配好时告诉我哪里不对"，它自己先因为没配 key
而死掉，就完全失去意义了。

**验证**（无 key、无板子的环境下）：

| 命令 | 期望 | 实测 |
|---|---|---|
| `python pc_agent/agent.py --list` | 列出 5 个内置动画 | ✅ |
| `python pc_agent/agent.py --test` | `沙箱自检：10/10 拦住` | ✅ |
| `python pc_agent/agent.py --check` | 不报 key，直接 ping，超时后给排查清单 | ✅ exit 1（板子未烧新固件） |

> ⚠ 中文在这三条输出里是乱码，**那是 PowerShell 控制台的 GBK 编码显示问题，
> 不是程序问题**（`chcp 65001` 可解决）。

### 2026-02-13 — 勾上 I2C2 NVIC 后修复重复定义 + 二次覆盖

**背景**：用户在 CubeMX 的 NVIC 页勾上了 I2C2 的中断并重新生成，导致又一次覆盖。
这次的**现象和上次不同**，暴露了一个更隐蔽的坑。

**新产生的编译错误（`-fsyntax-only` 抓到，cmake 也会报）**：

```
Core/Src/stm32f4xx_it.c:266:6: error: redefinition of 'I2C2_EV_IRQHandler'
Core/Src/stm32f4xx_it.c:220:6: note: previous definition of 'I2C2_EV_IRQHandler' with type 'void(void)'
```

**根因**：CubeMX 现在**自己会生成** `I2C2_EV_IRQHandler`（因为 `.ioc` 有了
`NVIC.I2C2_EV_IRQn=true\:0\:0\:...`），但我早先在 `USER CODE BEGIN 1` 区里手写的
那份还在 —— 同一符号两个定义。

> ⚠ **教训：`USER CODE` 区能保护代码不被删，但保护不了代码变得多余。**
> 一旦把某个配置从"手写补丁"变成"CubeMX 正式生成"，就必须**回去把补丁删掉**，
> 否则就是重定义。补丁的生命周期要跟着配置走。

**修法**：删掉 `USER CODE BEGIN 1` 里手写的 `I2C2_EV_IRQHandler`，**保留
`I2C2_ER_IRQHandler`**（ER 的 NVIC 仍然没勾，CubeMX 不会生成），并把那里的注释
从"两个 Handler 为什么都要手写"改写成"为什么只剩 ER 是手写的"。

**当前 I2C2 中断的真实分工（重要，别再搞混）**：

| 中断 | 谁生成 | 在哪使能 NVIC | 作用 |
|---|---|---|---|
| `I2C2_EV_IRQHandler` | **CubeMX**（`.ioc` 已勾 `NVIC.I2C2_EV_IRQn`） | `Core/Src/i2c.c:138-139` 的 `HAL_I2C_MspInit()` 里，由 CubeMX 生成 | TC 中断把 `hi2c2.State` 从 `BUSY_TX` 放回 `READY` |
| `I2C2_ER_IRQHandler` | **手写**（`.ioc` 里没勾 error interrupt） | `Core/Src/i2c.c` 的 `USER CODE BEGIN I2C2_MspInit 1` 区，手写补 | 总线错误时清标志、踢回 `READY` |

**`Core/Src/dma.c` 里不再需要任何 I2C2 代码**（上一轮补的 4 行已被 CubeMX 删掉，
现在也不需要补回去 —— NVIC 使能已经移到 `i2c.c` 的 `HAL_I2C_MspInit()` 里，
那才是它本来该在的位置）。

**`Core/Src/i2c.c` 手写补丁**（放在 `USER CODE BEGIN I2C2_MspInit 1` 区）：

```c
HAL_NVIC_SetPriority(I2C2_ER_IRQn, 0, 0);
HAL_NVIC_EnableIRQ(I2C2_ER_IRQn);
```

> **想一劳永逸**：在 CubeMX 的 NVIC 页把 "I2C2 error interrupt" 也勾上，
> 然后回来删掉这里的 2 行**和** `stm32f4xx_it.c` 里手写的 `I2C2_ER_IRQHandler`
> —— 两个都要删，不然又是重定义（`I2C2_EV_IRQHandler` 刚踩过）。

**`Core/Src/main.c` 的 `MX_LWIP_Init()` 位置问题（第二次被覆盖）**：

`.ioc:188` 的 `ProjectManager.functionlistsort` 把 `MX_LWIP_Init()` 排在
`MX_I2C2_Init()` **之前**（`5-MX_LWIP_Init-LWIP-false-HAL-false,6-MX_I2C2_Init-I2C2-false-HAL-true`），
所以**每次重新生成都会在 `MX_I2C2_Init()` 前面插一行 `MX_LWIP_Init();`**，
这违反 §3.3（`ETH_PHY_ReleaseReset()` 要靠 I2C2，必须排在 `MX_LWIP_Init()` 之前）。

这次的修法**换成了标记 + 注释**，因为单纯删掉它下次还会回来：

```c
  MX_USART1_UART_Init();
  /* USER CODE BEGIN MX_LWIP_Init_Disabled */
  /* 【本工程刻意删掉了 CubeMX 生成的 MX_LWIP_Init();】 ... 理由 ... */
  /* USER CODE END MX_LWIP_Init_Disabled */
  MX_I2C2_Init();
```

> **更彻底的办法**：去 CubeMX 的 Project Manager → Advanced Settings，把
> `MX_LWIP_Init` 的调用顺序拖到 `MX_I2C2_Init` 之后，那样 CubeMX 就不会再插错位置。
> **没做这一步之前，每次重新生成都要检查这一行。**

**验证**：`arm-none-eabi-gcc -fsyntax-only -Wall -Wextra -std=gnu11` 检查
`main.c` / `i2c.c` / `dma.c` / `stm32f4xx_it.c` / `framebuf.c` / `echo_service.c` /
`reg_shell.c` / `oled.c` / `ethernetif.c` / `eth_phy.c` / `board_io.c` / `font.c`
→ **12 个全 OK，零警告**。

### 2026-02-13 — I2C2 提到 400kHz + 修复 CubeMX 重新生成的覆盖

**背景**：用户把 I2C2 从 100kHz 改成 400kHz（`ETHERNETtest.ioc` 新增
`I2C2.I2C_Mode=I2C_Fast`，`Core/Src/i2c.c:43` 变为 `hi2c2.Init.ClockSpeed = 400000;`），
目的是把 OLED 刷屏的帧率上限从约 11fps 提到约 40fps。

**性能账（这是本轮最重要的数字）**：

| I2C 速率 | 整屏 1024 字节耗时 | 帧率上限 |
|---|---|---|
| 100kHz（原） | 约 92 ms | 约 11 fps |
| 400kHz（现） | 约 23 ms | 约 40 fps |

> ⚠ 注意这只是**理论上限**。`OLED_FlushPoll()` 当前每步仍是阻塞的
> `HAL_I2C_Master_Transmit`，一步 129 字节 @400kHz 约 2.9ms，8 步共 23ms ——
> 也就是说一帧仍会占用主循环 23ms。lwIP 在这 23ms 里被切成 8 段跑，
> **ping 和心跳不会断**，但 40fps 时主循环有 92% 的时间在做 I2C。
> 真要让主循环彻底解放，仍需 §11 的"刷屏真正走 DMA"。

**CubeMX 重新生成造成的覆盖（本轮全部修回）**：

用户在 CubeMX 里改 I2C 速率触发了重新生成，`git diff` 显示 4 处手写代码被冲掉。
**关键教训：`USER CODE` 区是有效的，但要放对位置。**

| 文件 | 丢失内容 | 修法 |
|---|---|---|
| `Core/Src/main.c` | `MX_I2C2_Init()` 之前被塞进一行 `MX_LWIP_Init()` —— 违反 §3.3 的初始化顺序 | 删掉那一行，恢复 `MX_I2C2_Init()` 紧跟 `MX_USART1_UART_Init()` |
| `Core/Src/dma.c` | `I2C2_EV_IRQn` / `I2C2_ER_IRQn` 的 NVIC 四行 | 补回 `MX_DMA_Init()` **函数体内**（不是文件末尾的 `USER CODE BEGIN 2`，那个块在函数闭合花括号之后，是文件作用域） |
| `Core/Src/stm32f4xx_it.c` | `extern I2C_HandleTypeDef hi2c2;` | 补回 `USER CODE BEGIN EV` 区（**两个 Handler 函数本身没丢**，因为它们在 `USER CODE BEGIN 1` 里） |

**没有丢的（`USER CODE` 区保护生效）**：`LWIP/Target/ethernetif.c` 的 5 处手工改动
**全部健在** —— MAC `02:00:00:12:34:56`（`:163-168`）、`ETH_PHY_Prepare()`（`:212`）、
`ethernet_link_check_state(netif)`（`:219`）、`HAL_ETH_Start()`（`:237`）、
三个 `user_phy_*` 回调（`:471-489`）。这说明**只要代码在 `USER CODE` 配对里，
CubeMX 就不会碰** —— 之前那次全丢是因为当时用自己编的 `USER CODE BEGIN 2b` 标记名，
CubeMX 不认识。

> **`.ioc` 里 I2C2 的 NVIC 依旧没勾**（只有 `NVIC.DMA1_Stream2_IRQn` /
> `NVIC.DMA1_Stream7_IRQn`）。所以 `dma.c` 里那 4 行**必须继续手写**，
> 每次 CubeMX 重新生成后都要检查。想一劳永逸就在 CubeMX 的 NVIC 页把
> I2C2 event / error interrupt 勾上。

**验证**：`arm-none-eabi-gcc -fsyntax-only -Wall -Wextra -std=gnu11` 检查
`main.c` / `dma.c` / `stm32f4xx_it.c` / `i2c.c` / `framebuf.c` / `echo_service.c` /
`reg_shell.c` / `oled.c` / `ethernetif.c` → **9 个全 OK，零警告**。

> ⚠ 实测仍未做：400kHz 下的画质（I2C 过快可能出现丢字节/花屏，SSD1306 数据手册
> 支持 400kHz 但模块的**上拉电阻**才是关键 —— 阿波罗板上 I2C2 同时挂了 PCF8574，
> 两个上拉并联后等效阻值偏低，理论上更稳；若出现花屏，先把 `ClockSpeed` 退回
> 100000 排除速率因素）。

### 2026-02-13 — 二进制帧通道 `FB`/`FBSEQ` + PC 端 agent

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
| ~~**OLED 第 3 步：`OLED BLIT` + 动眼睛动画**~~ | ✅ **已被 `FBSEQ` 通道取代**（见 §3.11 / §3.12）。帧缓冲上传（1032 字节/帧）已跑通，用户实测眼睛能动、LLM 生成的篮球动画也能显示 | 已完成 |
| **中文动画端到端验证** | `draw_text()` 已注入沙箱、提示词已写中文章节，但**用户尚未跑过一次带中文的 LLM 动画** | **高** |
| **`--ascii` 不指定 `-s` 时应有限时长** | `--seconds` 默认 0 表示无限播，用户在 VS Code 终端里画个不停要 Ctrl+C。应改为 `--ascii` 时默认有限时长 | 中 |
| **`.mxproject` 追踪** | 见 §9.3，尚未决定是否移除追踪 | 低 |
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
11. **PC 端绘图原语的坐标必须能是 float —— 入口一律 `_iv()` 强转**（见 §3.13）
12. **FBSEQ 判重只在同一会话内生效，会话由 500ms 时间间隔切分**（见 §3.11）
13. **诊断脚手架不该改变被测系统的行为**（`settrace` 的教训，见 §3.13）
14. **写操作确认的判据要反过来写**：只证明是只读的才免确认，其余全要（见 §3.12.1）
15. **规则层加说法 → 在 `dispatch_cases.jsonl` 加一行 → 跑 `--test`**（见 §3.12.1）

---

## 13. 串口助手收不到任何打印（现场诊断）

> 触发场景：串口助手一个字都收不到，但波特率 115200-8-N-1 设置是对的。
> **先确认这是不是板子的问题** —— 绝大多数情况不是。

### 13.1 三连测（按顺序做，前一步不过不要往下）

| # | 测什么 | 怎么做 | 判据 |
|---|---|---|---|
| 1 | **串口是否被独占** | 关掉所有可能占用 COM 口的东西（UE4、编辑器串口插件、第二个串口助手实例、Arduino IDE 等），然后单独开一次助手 | 端口能打开。若报 `Access to the path 'COM22' is denied.` / `打开串口失败`，就是被独占 |
| 2 | **烧的是不是旧 hex** | 比时间戳：源文件 `Core/Src/main.c` vs `build/Debug/ETHERNETtest.hex` | **hex 必须比所有源文件新**。不新就重新 `objcopy`（见 §2.3） |
| 3 | **换 COM 号裸开一次** | 设备管理器里看 CH340 的**真实** COM 号（USB-SERIAL CH340；曾出现注册表残留 COM22 而实际设备名是 `USB-SERIAL CH340 (COM11)`），用另一个助手或裸串口工具打开它 | 能看到乱码或正常文本。一个字节都看不到 → 查线和地 |

> **踩过的坑**：`HKLM\HARDWARE\DEVICEMAP\SERIALCOMM` 里可能残留
> `\Device\USBSER000=COM22`，而 CH340 的 `FriendlyName` 实际写的是 `COM11`。
> **以设备管理器的 FriendlyName 为准，不要信注册表里的旧映射。**

### 13.2 代码链路本身（基本可以排除）

已核对过，printf 重定向这条链**没有缺陷**：
`printf` → `iprintf` → `_vfiprintf_r` → `__sfvwrite_r` → `_write`
（`Core/Src/debug_uart.c:29`，强符号，链接器选中它，`syscalls.c` 里的弱版被丢弃）
→ `HAL_UART_Transmit(&huart1, ...)`。`HAL_UART_MspInit` 的反汇编里
AF7 / PA9 / PA10 / GPIOA 时钟 / USART1 时钟全部正确。

> 唯一的小瑕疵：`Core/Inc/debug_uart.h:23` 声明了 `__io_putchar` 但
> `debug_uart.c` 没有包含这个头文件（`-Wmissing-prototypes` 隐患）。
> nano printf 路径不经 `__io_putchar`，所以它**不会**导致无输出。

### 13.3 Windows 网络栈的干扰（顺带记录）

排查同期发现本机 `ping 192.168.1.30` 报
`PING: transmit failed. General failure.`，连 ping 自己 `192.168.1.100` 也一样，
`arp -a` 里对应网卡没有动态邻居条目 —— **这是 PC 侧网络栈坏了，不是板子**。
遇到这种"连自己都 ping 不通"，先 `netsh winsock reset` 再重启，不要动固件。

> ⚠ 沙箱/受限权限下 `Get-PnpDevice` / `Get-NetIPAddress` / `Get-NetAdapter` /
> `Get-NetRoute` / `Get-CimInstance` 会**静默返回空**。此时改用原生命令：
> `reg query`、`netstat -ano`、`ipconfig`、`route print`、`arp -a`、`tasklist`。
