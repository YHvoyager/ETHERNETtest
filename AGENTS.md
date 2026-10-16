# AGENTS.md — ETHERNETtest 工程工作手册

> **本文件给未来的 AI 助手（和我自己）看。每次改动代码后必须更新本文件。**
> 最后更新：2026-02-13 | 当前提交：`f037cb2`

---

## 0. 工作流约定（用户明确要求）

用户要求（本次会话）：

1. **每次改动代码，先 commit 一遍**，然后再写文档。
2. **每次改动后必须更新 AGENTS.md**，方便后续查阅。

所以标准流程是：

```
改代码 → 编译验证 → git commit → 更新 AGENTS.md 的「变更日志」+ 受影响章节
```

> ⚠ 不要只改代码就结束。**文档和提交是交付物的一部分。**

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
│   │   ├── udp_echo.h         UDP 回环接口
│   │   ├── main.h / i2c.h / usart.h / gpio.h / stm32f4xx_it.h / stm32f4xx_hal_conf.h
│   └── Src/
│       ├── eth_phy.c          ★ 板级补丁（MspInit + PHY 复位 + PHY 准备 + 诊断）
│       ├── udp_echo.c         ★ UDP 回环服务
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
| `Core/Src/udp_echo.c` | UDP 8080 回环 + 每秒心跳 | 非阻塞 |
| `LWIP/App/lwip.c` | `gnetif` 定义（`:45`）、IP 配置（`:63-66`） | |
| `LWIP/Target/ethernetif.c` | 网卡驱动，5 处手工改动 | 见 3.4 |

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

UDP_Echo_Init();                   /* netif 得先 add/up，udp_bind 才有意义 */

while (1)
{
  MX_LWIP_Process();               /* ethernetif_input + sys_check_timeouts + 链路检查 */
  UDP_Echo_Poll();                 /* 非阻塞，内部 1 秒节流 */
}
```

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
| 发送 `hello` | 立刻收到 `hello` |
| 不发任何东西 | 仍每秒收到 `STM32F429 alive, tick=..., rx=...` |

> **心跳间隔必须稳定 1000ms。** 变成 64 秒说明主循环被卡住。

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

提交信息用中文，说明**做了什么 + 为什么**。示例：

```
添加 STM32CubeMX 项目 .gitignore

忽略 build/、CMake 生成物、编译产物、CubeMX/IDE 临时文件，
同时用 ! 白名单确保 .ioc/.ld/startup_*.s/.clangd/CMakePresets.json
等必需源文件不被误伤。
```

> **未决事项**：`.mxproject` 目前**仍被追踪**。它是 CubeMX 自动生成的元数据，
> 每次打开项目都可能变，容易产生无意义 diff。若要移除：
> `git rm --cached .mxproject` 并加入 `.gitignore`。（用户尚未决定）

---

## 10. 变更日志

> **每次改动代码后在此追加一条，最新的在最上面。**

### 2026-02-13 — `f037cb2`

- **新增** `.gitignore`（147 行）：完整覆盖 CubeMX/CMake/ARM GCC 的编译产物与 IDE 临时文件，
  并用 `!` 白名单保护 `.ioc`/`.ld`/`startup_*.s`/`.clangd`/`CMakePresets.json`/`.settings` 等必需文件。
  已用 `git ls-files -i` + 13 个诱饵文件实测验证。
- **新增** `AGENTS.md`（本文件）：工程工作手册，含构建设置、架构、四个串行故障、
  设计决策、验证步骤、排查速查表。

### 2026-02-13 — `707a834`（初始提交，"第一次上传"）

- 工程初始状态：完成 STM32F429 阿波罗V2 的 lwIP 以太网移植（4 个故障全部修复），
  实现 UDP 8080 回环 + 每秒心跳，能 ping 通 `192.168.1.30`。
- 技术文档 `docs/lwip-f429-apollo-v2.md`（597 行）。

---

## 11. 待办 / 已知问题

| 项 | 说明 | 优先级 |
|---|---|---|
| `.mxproject` 追踪 | 见 9.3，尚未决定是否移除追踪 | 低 |
| 改用 HSE 25MHz | 当前用 HSI ±1%，UART 波特率有偏差；RMII 参考时钟由 PHY 自己的晶振提供，不影响以太网。属可选优化 | 低 |
| TCP 应用 | `LWIP_TCP=1` 但工程未写 TCP 应用 | — |
| `eth_custom_phy_interface.c` | 保留未用（见 5） | — |

---

## 12. 铁律速记

1. **改代码 → 编译 → commit → 更新 AGENTS.md**（用户要求）
2. **`ETH_PHY_ReleaseReset()` 必须在 `MX_LWIP_Init()` 之前**
3. **`while(1)` 里不能有阻塞式轮询**
4. **PCF8574 初值 `0xFF`，只改目标位**
5. **编译后必须手工 objcopy 生成 hex，否则烧的是旧固件**
6. **新 `.c` 必须登记到根 `CMakeLists.txt`**
7. **改 `ethernetif.c` 时记住 CubeMX 重新生成会覆盖那 5 处改动**
8. **不要动校验和配置**
9. **读到的寄存器值脏时，先修通信参数再看数据**
10. **多个来源冲突时，以原理图 + 实测为准**
