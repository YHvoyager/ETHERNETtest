# STM32F429 阿波罗V2 lwIP 以太网移植技术文档

> 目标板：正点原子阿波罗V2（STM32F429IGT6 + YT8512C PHY）
> 工程：`C:\Users\86185\Desktop\CubeMX\ETHERNETtest`（STM32CubeMX 6.18.1 生成，CMake + Ninja + arm-none-eabi-gcc）
> 验收标准：PC 直连能 ping 通 192.168.1.30，且网络调试助手能收到单片机回发的数据

---

## 目录

1. [硬件接线](#1-硬件接线)
2. [四个串行故障](#2-四个串行故障必须全部修完才通)
3. [代码结构与职责](#3-代码结构与职责)
4. [构建与烧录](#4-构建与烧录)
5. [验证步骤](#5-验证步骤)
6. [故障排查速查表](#6-故障排查速查表)
7. [工程教训](#7-工程教训)

---

## 1. 硬件接线

### 1.1 RMII 引脚（原理图 DNF429P_F767P_H743P V2.5.pdf 第 1 页确认）

STM32F429 的 ETH 外设固定复用这 9 根引脚，全部是 **AF11**：

| STM32 引脚 | 信号 | 方向 | 对端（YT8512C U2） |
|---|---|---|---|
| PA1 | RMII_REF_CLK | 输入 | XTAL_IN（25MHz 晶振另供，见下） |
| PA2 | RMII_MDIO | 双向 | MDIO (pin 23) |
| PA7 | RMII_CRS_DV | 输入 | CRS/CRS_DV (pin 26) |
| PC1 | RMII_MDC | 输出 | MDC (pin 22) |
| PC4 | RMII_RXD0 | 输入 | RXD0 (pin 9) |
| PC5 | RMII_RXD1 | 输入 | RXD1 (pin 10) |
| PB11 | RMII_TX_EN | 输出 | TX_EN (pin 20) |
| PG13 | RMII_TXD0 | 输出 | TXD0 (pin 16) |
| PG14 | RMII_TXD1 | 输出 | TXD1 (pin 17) |

REF_CLK 线上有串阻 R6 = 22Ω；PHY 的 25MHz 晶振是独立的 Y1 + C21/C25 (22pF)。

### 1.2 PHY 地址 = 0

YT8512C 的地址由 **pin 24 (LED0/PHYADD0)** 和 **pin 25 (LED1/PHYADD1)** 决定。
本板上这两脚都接去驱动 LED，**没有上拉成其他地址**，所以 PHY 地址固定为 **0**。

> 代码里因此硬编码 `DevAddr = 0`，不走地址扫描。理由见 [2.2](#22-故障二hal_eth_mspinit-是空的)。

### 1.3 ETH_RESET 走 PCF8574，不接 MCU GPIO

这是阿波罗V2 最容易踩的一个坑：

```
PCF8574T (U11) P7  ──>  Q1（三极管反相）  ──>  YT8512C RESET (pin 21)
```

- **PCF8574 的 P7 = 1** → Q1 导通 → RESET 被拉低 → **PHY 处于复位**
- **PCF8574 的 P7 = 0** → Q1 截止 → RESET 上拉为高 → **PHY 正常工作**

也就是说 MCU **没有任何一根 GPIO 直接控制 PHY 复位**，必须通过 I²C 写 PCF8574 才能让 PHY 上电。CubeMX 不知道这件事，生成的代码里完全没有这段。

### 1.4 PCF8574 与 I²C

| 项 | 值 |
|---|---|
| 芯片 | PCF8574T (U11)，16 脚 |
| A2/A1/A0 | 全部接地 |
| 7 位地址 | `0x20` |
| HAL 用的 8 位左对齐地址 | **`0x40`** |
| SCL | PH4（I2C2，AF4） |
| SDA | PH5（I2C2，AF4） |
| 上拉 | R24/R25 = 4.7K |
| INT | 经 R42 4.7K 上拉到 PB12（本工程未使用） |

同一组 PH4/PH5 上还挂着 AP3216C、ST480MC 磁力计、SH3001 六轴。

### 1.5 PCF8574 引脚分配（全板）

| 位 | 信号 | 有效电平 | 备注 |
|---|---|---|---|
| P0 | BEEP | **低有效** | Q4 是 **PNP (8550)**，基极拉低就导通 → 蜂鸣器响 |
| P1 | AP_INT | | |
| P2 | DCMI_PWDN | | |
| P3 | USB_PWR | **高有效** | 拉低会**切断 USB 供电，CH340 串口掉线** |
| P5 | 6D_INT | | |
| P6 | RS485_RE | | |
| P7 | ETH_RESET | **高 = 复位** | 见 1.3 |

> ⚠ **PCF8574 是准双向口，没有方向寄存器。** 写一个字节就是驱动全部 8 个引脚。
> 上电默认 0xFF（全高）是安全的：BEEP=1 蜂鸣器不响、USB_PWR=1 串口不掉。
> 如果初始值写成 `0x00` 或 `0x80`，会**蜂鸣器狂响 + 串口直接掉线**。
> 这段血泪写在 `Core/Src/eth_phy.c` 的 `PCF_POWER_ON_DEFAULT` 注释里。

### 1.6 时钟

当前 `SystemClock_Config()` 用的是 **HSI**（内部 RC）：

```
OscillatorType = RCC_OSCILLATORTYPE_HSI
PLLSource      = RCC_PLLSOURCE_HSI
PLLM = 8, PLLN = 180, PLLP = DIV2, PLLQ = 4
→ SYSCLK = 16MHz/8*180/2 = 180MHz
→ HCLK = 180MHz, APB1 = 45MHz, APB2 = 90MHz
```

`.ioc` 里定义了 `RCC.HSE_VALUE = 25000000`（板上有 25MHz 晶振，PH0/PH1 也已占用为 OSC_IN/OSC_OUT），但当前没启用。

> **建议改 HSE**：HSI 精度 ±1%，而 RMII 需要稳定的 50MHz 参考时钟。现在能用是因为 REF_CLK 由 PHY 自己的 25MHz 晶振提供，但 HSI 会让 UART 波特率有偏差。不影响以太网功能，属可选优化。

---

## 2. 四个串行故障（必须全部修完才通）

这四个故障是**串行**关系：任何一个没修，网口都不通，而且现象各不相同。
排查顺序就是发现顺序。

### 2.1 故障一：PHY 复位从未释放

| 项 | 内容 |
|---|---|
| **现象** | 网线插着，RJ45 的双灯（绿 LINK_LED / 黄 SPEED_LED）**全灭**。 |
| **根因** | ETH_RESET 挂在 PCF8574 P7 上（见 [1.3](#13-eth_reset-走-pcf8574不接-mcu-gpio)），CubeMX 生成的代码里没有任何 PCF8574 初始化。PHY 一直处于复位态，根本没上电。 |
| **为什么隐蔽** | `HAL_ETH_Init()` 返回 `HAL_OK`。因为 F4 HAL 的 `HAL_ETH_Init()` 是**纯 MAC/DMA 初始化**，只做 MAC 软复位、写配置寄存器、搭 DMA 描述符链，**完全不碰 PHY**。所以软件层面一切"正常"，硬件层面网口是死的。 |
| **修法** | I²C2 写 PCF8574：先把 P7 置 1 断言复位，延时 10ms，再把 **P7 清 0**（其余 7 位保持 1），延时 **120ms** 等 PHY 自举。 |
| **代码** | `Core/Src/eth_phy.c` → `ETH_PHY_ReleaseReset()`，在 `main.c` 里 `MX_LWIP_Init()` **之前**调用 |

那个 120ms 延时不能省。省掉后 `HAL_ETH_Init()` 之后的第一次 MDIO 读会失败（PHY 还没自举完）。

**验证方法**：读 PHY ID 寄存器。能读到 `PHYID1=0x0007 PHYID2=0xC0F1`，OUI = `0x001C03` = **Motorcomm（裕太微）**，就证明 MDIO 通了、PHY 活了。灯亮是硬件在替我们回答。

---

### 2.2 故障二：`HAL_ETH_MspInit()` 是空的

| 项 | 内容 |
|---|---|
| **现象** | 即使 PHY 上电了，MDIO 也读不到东西 / 读回垃圾。 |
| **根因** | CubeMX 生成的 `Core/Src/stm32f4xx_hal_msp.c` 里**没有 `HAL_ETH_MspInit`**，而 HAL 库里它是 `__weak` 空函数（`stm32f4xx_hal_eth.c:454`）。缺了它：<br>① 9 根 RMII 引脚的 GPIO 时钟没开、没配成 AF11<br>② ETH 外设时钟没开 |
| **验证** | 全工程 grep `AF11_ETH` 和 `__HAL_RCC_ETH` → 零结果，就是没实现。 |
| **修法** | 自己写一个强符号 `HAL_ETH_MspInit()` 覆盖弱符号。 |

实现要点（`Core/Src/eth_phy.c`）：

```c
__HAL_RCC_ETH_CLK_ENABLE();
__HAL_RCC_GPIOA_CLK_ENABLE();  __HAL_RCC_GPIOB_CLK_ENABLE();
__HAL_RCC_GPIOC_CLK_ENABLE();  __HAL_RCC_GPIOG_CLK_ENABLE();

gpio.Mode      = GPIO_MODE_AF_PP;
gpio.Pull      = GPIO_NOPULL;
gpio.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
gpio.Alternate = GPIO_AF11_ETH;

HAL_GPIO_Init(GPIOA, &gpio);   // PA1 | PA2 | PA7
HAL_GPIO_Init(GPIOB, &gpio);   // PB11
HAL_GPIO_Init(GPIOC, &gpio);   // PC1 | PC4 | PC5
HAL_GPIO_Init(GPIOG, &gpio);   // PG13 | PG14
```

`Core/Src/gpio.c` 的 `MX_GPIO_Init()` 只开了 GPIOH/C/A/B/G 的时钟但**没有配置任何引脚**，所以不会冲突。

**顺带一个坑：MDIO 地址扫描的假阳性。** 总线上没有器件应答时，MDIO 读到的是悬空电平，常见 `0xFFFF` **和 `0x7FFF`** 两种值。如果用 `regvalue != 0xFFFF` 当判据（ST 的 `USER_PHY_Init()` 和正点原子官方例程都这么写），会把一堆空地址误报成器件 —— 实测 addr = 1/6/8/11/12/13/17/18/20/29/30/31 全报 `0x7FFF`。

**正确判据**：要求厂商 OUI 合法，即 ID1/ID2 既不全 0 也不全 1，且 `OUI != 0`（`ETH_PHY_Dump()` 就是这么做的）。

---

### 2.3 故障三：MDC 时钟超频（4.29MHz > 2.5MHz）

| 项 | 内容 |
|---|---|
| **现象** | 能读到 PHY，但寄存器值**脏**。实测 BSR 读出 `0x7809`（link=0），而真实值是 `0x782D`（link=1）。 |
| **根因** | `HAL_ETH_Init()` **不会**配置 `MACMIIAR` 的 `CR[2:0]`。复位默认值 `000` = **HCLK/42**，这个分频只在 HCLK 60~100MHz 下合法。<br>本板 HCLK = **180MHz** → MDC = 180/42 ≈ **4.29MHz**，超出 IEEE 802.3 规定的 **2.5MHz** 上限。MDC 超频时 PHY 对寄存器访问的应答变得不确定。 |
| **关键证据** | 全库 grep `HAL_ETH_SetMDIOClockRange` → **只有定义（`stm32f4xx_hal_eth.c:2394`），零调用点**。CubeMX 生成的 lwIP 模板里也没有这一句。 |
| **修法** | 自己在 `HAL_ETH_Init()` 之后调 `HAL_ETH_SetMDIOClockRange(&heth);` |

该函数按 HCLK 自动选 CR（`stm32f4xx_hal_eth.c:2431`）：

| HCLK | CR | 分频 | MDC @180MHz |
|---|---|---|---|
| < 35 MHz | `Div16` (0x8) | /16 | — |
| < 60 MHz | `Div26` (0xC) | /26 | — |
| < 100 MHz | `Div42` (0x0) | /42 | — |
| < 150 MHz | `Div62` (0x4) | /62 | — |
| **else** | **`Div102` (0x10)** | **/102** | **≈ 1.76MHz** ✓ |

**对照实验（这是定位真因的关键）**：故障二阶段写的隔离测试固件里手动调过这一句，读到干净的 `BSR=0x782D`；换成 CubeMX 生成的 lwIP 模板（没有这一句），立刻读出脏的 `BSR=0x7809`。同一块板、同一根线，唯一变量就是这一句。

> ⚠ **当时的错误推断（记录下来避免重蹈）**：一开始把读到的 `BCR=0x2100` 当真值，解读为"PHY 被强制 100M 全双工、关闭自协商"，并推理"强制端 ↔ 自协商端不兼容 → 链路起不来"。
> 加了 MDC 分频后再读，`BCR = 0x3000`（`autoneg_en=1`）—— **自协商从来就是开着的**，`0x2100` 纯粹是超频读出来的幻影。整套推理建立在脏值上，不成立。
> **教训：读到的寄存器值是脏的时候，所有基于它的推理都是沙上建塔。先保证通信参数正确，再看数据。**

---

### 2.4 故障四：`HAL_ETH_Start()` 从未调用（ping 不通的直接原因）

| 项 | 内容 |
|---|---|
| **现象** | PHY 上电、MDC 分频已修、自协商完成、`[LINK] UP` 稳定、lwIP 把 ARP 应答都组装好了 —— 但 PC 上 `ping 192.168.1.30` 报 **`来自 192.168.1.100 的回复: 无法访问目标主机。`** |
| **根因** | `HAL_ETH_Init()` 只做三件事：MAC 软复位 + `ETH_MACDMAConfig()` 写配置寄存器 + 搭 DMA 描述符链。它**不打开 MAC 收发使能**，也**不启动 DMA 引擎**：<br>• `MACCR.TE` (bit3) / `MACCR.RE` (bit2) = 0 → MAC 收发单元关闭<br>• `DMAOMR.ST` (bit13) / `DMAOMR.SR` (bit1) = 0 → DMA 引擎停止 |
| **真正置位的地方** | `HAL_ETH_Start()`（`stm32f4xx_hal_eth.c:714`）：`ETH_UpdateDescriptor()` → `SET_BIT(MACCR, TE)` → `SET_BIT(MACCR, RE)` → `ETH_FlushTransmitFIFO()` → `SET_BIT(DMAOMR, ST)` → `SET_BIT(DMAOMR, SR)`，末尾 `gState = HAL_ETH_STATE_STARTED`。 |
| **验证** | 全工程 grep `HAL_ETH_Start` → 只有 HAL 库自己的定义、`HAL_ETH_Start_IT` 和头文件声明，**零调用点**。 |
| **修法** | 在 `low_level_init()` 里补上，位置在 `HAL_ETH_Init()` 之后、自协商处理之后。 |

```c
if (HAL_ETH_Start(&heth) != HAL_OK)
{
  printf("[ETH] ERR: HAL_ETH_Start() failed\r\n");
  Error_Handler();
}
```

前置校验是 `if (heth->gState == HAL_ETH_STATE_READY)`，而 `HAL_ETH_Init()` 正好留下 `READY`，所以调用会生效。

**为什么现象这么有欺骗性**：这条链路上除了收发使能，其他一切都是好的。PHY 正常、链路 UP、lwIP 正常工作、ARP 应答包完整组装 —— 然后丢进一个收发被关掉的 MAC，一个字节都发不出去。PC 侧收不到 ARP 应答，Windows 只能报"无法访问目标主机"。

**修完立刻 ping 通**：`来自 192.168.1.30 的回复: 字节=32 时间<1ms TTL=255` × 4，0% 丢失。

---

### 2.5 故障总表

| # | 故障 | 现象 | 验证方法 |
|---|---|---|---|
| 1 | PHY 复位未释放 | RJ45 双灯全灭 | 读 PHY ID，`0xFFFF`/`0x7FFF` = 没通 |
| 2 | `HAL_ETH_MspInit` 空 | MDIO 读不到 / 读垃圾 | grep `AF11_ETH` |
| 3 | MDC 超频 4.29MHz | 寄存器值脏（link 位读错） | 对照有无 `SetMDIOClockRange` |
| 4 | `HAL_ETH_Start` 未调用 | 链路 UP 但 ping「无法访问目标主机」 | grep `HAL_ETH_Start` |

**每一个都足以让网口完全不通。** 排查时必须按这个顺序，因为后面的故障会掩盖前面的。

---

## 3. 代码结构与职责

### 3.1 文件清单

```
Core/
  Inc/
    eth_phy.h              板级补丁接口（3 个函数）
    debug_uart.h           printf 重定向接口
    udp_echo.h             UDP 回环接口
  Src/
    eth_phy.c              ★ 板级补丁实现（MspInit + PHY 复位 + PHY 准备 + 诊断）
    debug_uart.c           printf → USART1
    udp_echo.c             ★ UDP 回环服务
    main.c                 初始化顺序 + 主循环
    i2c.c                  I2C2（PH4/PH5）
    usart.c                USART1（PA9/PA10，115200-8-N-1）
LWIP/
  App/lwip.c               MX_LWIP_Init() / MX_LWIP_Process()
  Target/ethernetif.c      lwIP 网卡驱动（low_level_init/output/input）
  Target/lwipopts.h        lwIP 配置
  Target/eth_custom_phy_interface.c   ST 生成的通用 PHY 驱动（未使用，见 3.4）
```

### 3.2 `eth_phy.c` — 板级补丁模块

把 CubeMX 漏掉的东西全部集中在这一个文件里，接口只 3 个函数：

| 函数 | 职责 | 调用时机 |
|---|---|---|
| `ETH_PHY_ReleaseReset()` | I²C 写 PCF8574，释放 PHY 复位 | `main()` 里，`MX_LWIP_Init()` **之前** |
| `HAL_ETH_MspInit()` | 补 9 根 RMII 引脚 AF11 + ETH 时钟 | HAL 内部自动调（`HAL_ETH_Init` 里） |
| `ETH_PHY_Prepare()` | MDC 分频 + 保证自协商打开 + 调诊断 | `low_level_init()` 里，`HAL_ETH_Init()` 之后 |
| `ETH_PHY_Dump()` | 扫 MDIO、打印 PHY ID/BCR/BSR | 由 `ETH_PHY_Prepare()` 调用；`ETH_PHY_DIAG 0` 可整体关掉 |

> **为什么自协商修复只做一次**：放在 100ms 的 `ethernet_link_check_state()` 里会导致每次轮询都触发 `RESTART_AUTONEG`，协商永远完不成。这是个很容易犯的设计错误。

### 3.3 `ethernetif.c` — 我们改动的地方

CubeMX 生成的原版基础上改了 5 处：

| 位置 | 改动 | 原因 |
|---|---|---|
| `:149-154` | MAC 改 `02:00:00:12:34:56` | 原占位值 `00:80:E1:00:00:00` 尾段全零，某些网卡驱动会把帧当异常丢弃 → 链路通但 ping 不通 |
| `:206` | 加 `ETH_PHY_Prepare();` | 故障三 + 自协商 |
| `:213` | `ethernet_link_check_state(netif)` | CubeMX 生成的空函数，已实现（原来里面是空的） |
| `:220` | 加 `HAL_ETH_Start(&heth)` | **故障四，ping 不通的直接原因** |
| `:475` | 实现 `ethernet_link_check_state()` | 读 BSR bit2 判链路 |

**`ethernet_link_check_state()` 的实现要点**：

```c
/* 第一次读清锁存器，第二次取真值 */
(void)HAL_ETH_ReadPHYRegister(&heth, 0U, 0x01U, &bsr);
if (HAL_ETH_ReadPHYRegister(&heth, 0U, 0x01U, &bsr) != HAL_OK) return;
/* 读失败保持状态不动，不要误判成 link down */

if ((bsr & 0x0004U) != 0U)   /* BSR bit2 = Link Status */
{
  ...
  netif_set_link_up(netif);
}
```

两个关键点：

1. **IEEE 802.3 规定 BSR 的 link/autoneg 位是锁存低的** —— 读到 0 表示"曾经断过"。必须连读两次取第二次。
2. **⚠ 不要从 BSR 的 bit11~15 反推协商结果。** 那几个位表示 PHY 的**能力**（支持哪些模式），不是本次协商实际选中的模式。
   `BSR = 0x782D` 的 bit11~14 全 1，含义只是"100FD/100HD/10FD/10HD 四种我都支持"。
   实际协商结果在厂商专用寄存器里（YT8512C 是 `0x11`），BSR 读不出来。
   > 我在调试时把 bit13/bit15 当 speed/duplex 打印，得出"100M half duplex"的假结论 —— 这是**解码错误**，代码里已改成只报原始值 + 链路/协商状态位。

**为什么不调用 ST 生成的 `USER_PHY_GetLinkState()`**：
读它的实现（`eth_custom_phy_interface.c:223-324`）发现一个会直接害死 ping 的缺陷 —— 自协商完成后读 ANAR/ANLPAR 算 `common_adv`，如果匹配不上任何已知模式分支，就走到最后的 `else`，**返回 `USER_PHY_STATUS_LINK_DOWN`（`:323`）**。它把"自协商完成但模式未识别"误报成"链路断开"。
YT8512C 实测 `BSR=0x782D`（link=1, autoneg_done=1）走的正是这条路 → lwIP 被告知链路断开 → 不发 ARP → ping 不通。
直接读 BSR 位语义明确，还少 6 次 MDIO 读。

### 3.4 关于 `eth_custom_phy_interface.c`

这是 CubeMX 在 `LWIP0.BSP.component = USER_PHY` 配置下生成的通用 IEEE 802.3 PHY 驱动（445 行），本身没有 bug，但当前实现**不使用**它：

- `USER_PHY_Init()` 的地址扫描判据有假阳性缺陷（见 [2.2](#22-故障二hal_eth_mspinit-是空的)）
- `USER_PHY_GetLinkState()` 会把"模式未识别"误报成"链路断开"（见 [3.3](#33-ethernetifc--我们改动的地方)）

保留它是因为 CubeMX 重新生成代码时还会带上；`ethernetif.c` 里的 3 个 `user_phy_*` 回调也只为了满足链接需要。

### 3.5 `udp_echo.c` — UDP 回环服务

| 项 | 内容 |
|---|---|
| 端口 | `8080`（`UDP_ECHO_PORT`） |
| 绑定 | `0.0.0.0:8080` |
| 行为 | 收到什么原样回发；另外**每秒主动推**一条心跳 `STM32F429 alive, tick=... ms, rx=...` |
| 接口 | `UDP_Echo_Init()`（`MX_LWIP_Init()` 之后调）、`UDP_Echo_Poll()`（`while(1)` 里调，非阻塞） |

**四个设计决策与理由**：

1. **回调里可以直接 `udp_sendto()`**
   `NO_SYS=1` 的裸机 lwIP 收包链是：
   `MX_LWIP_Process()` → `ethernetif_input()` → `netif->input`(= `ethernet_input`) → `ip4_input()` → `udp_input()` → 回调
   **全程主循环上下文，不是中断**。所以在回调里直接发包是安全的，不需要消息队列或线程。

2. **拷贝而非复用收到的 pbuf**
   收到的 pbuf 来自 `RX_POOL`（`ethernetif.c:611 HAL_ETH_RxAllocateCallback` 分配），归 DMA 接收环所有。直接改地址发回去等于把接收缓冲借给发送路径 —— 如果 TX DMA 还没搬完而 RX 侧回收了内存，就是一次**静默的数据损坏**。用 `pbuf_alloc` + `pbuf_take` 拷一份，慢一点点但没坑。

3. **不要动校验和**
   `lwipopts.h` 里 `CHECKSUM_BY_HARDWARE=1`、`CHECKSUM_GEN_UDP=0`，UDP 校验和由 ETH 外设硬件插入（`TxConfig.Attributes` 里的 `ETH_TX_PACKETS_FEATURES_CSUM`）。lwIP 不填这个字段是**预期行为**，别"顺手"打开 `CHECKSUM_GEN_UDP`，否则和硬件重复计算。

4. **加主动心跳**
   纯被动回环有诊断盲区：目标端口填错、或 Windows 防火墙拦入站包时，界面一片空白，用户无法区分"板子没收到"还是"回包被拦"。让板子先出声，**一开机就能确认方向**。

### 3.6 `main.c` 初始化顺序

这个顺序**不能改**：

```c
MX_GPIO_Init();
MX_USART1_UART_Init();
MX_I2C2_Init();                    /* PCF8574 挂在 I2C2 上，必须先初始化 */

ETH_PHY_ReleaseReset();            /* ← 必须在 MX_LWIP_Init() 之前！ */

MX_LWIP_Init();                    /* 内部会调 ethernetif_init → low_level_init
                                    *   → HAL_ETH_Init → HAL_ETH_MspInit
                                    *   → ETH_PHY_Prepare → HAL_ETH_Start */

UDP_Echo_Init();                   /* netif 得先 add/up，udp_bind 才有意义 */

while (1)
{
  MX_LWIP_Process();               /* ethernetif_input + sys_check_timeouts + 链路检查 */
  UDP_Echo_Poll();                 /* 非阻塞，内部 1 秒节流 */
}
```

**为什么 PHY 复位必须在 `MX_LWIP_Init()` 之前**：否则 `HAL_ETH_Init()` 会对着一个没上电的 PHY 返回"成功"，然后得到一个永远 ping 不通的 lwIP。

**⚠ 不要在 `while(1)` 里加阻塞式轮询。** 曾经的 `ETH_LinkTest_Poll()` 用了一个只在 `ETH_LinkTest_Run()` 里赋值的 `static ETH_HandleTypeDef`，而 `main()` 从没调用 `Run()` → `Instance == NULL` → 每次调用都是拿空指针读写 ETH 寄存器。实测结果是**每 64 秒才吐一次错误**，CPU 被卡在里面，`MX_LWIP_Process()` 得不到执行 → lwIP 定时器/ARP 全停 → ping 必然不通。
链路状态改由 `ethernet_link_check_state()` 每 100ms 上报（`lwip.c:125`），足够了。

### 3.7 lwIP 配置（`lwipopts.h`）

| 配置 | 值 | 含义 |
|---|---|---|
| `NO_SYS` | 1 | 裸机模式，无 RTOS |
| `LWIP_NETCONN` | 0 | 不用 netconn API |
| `LWIP_SOCKET` | 0 | 不用 socket API |
| `LWIP_NETIF_LINK_CALLBACK` | 1 | 链路状态回调 |
| `CHECKSUM_BY_HARDWARE` | 1 | 校验和交给 ETH 外设 |
| `CHECKSUM_GEN_UDP` | 0 | lwIP 不填 UDP 校验和（硬件填） |
| `LWIP_UDP` | 1 | （在 `opt.h` 里）UDP 可用 |
| `LWIP_TCP` | 1 | （在 `opt.h` 里）TCP 可用但工程未写应用 |

用的是 **lwIP 2.1.2**（`LWIP.Version=v2.1.2_Cube`）。

---

## 4. 构建与烧录

### 4.1 工具链路径

```
编译器  C:/Users/86185/AppData/Local/stm32cube/bundles/gnu-tools-for-stm32/14.3.1+st.2/bin/arm-none-eabi-gcc.exe
cmake   C:/Users/86185/AppData/Local/stm32cube/bundles/cmake/4.3.1+st.1/bin/cmake.exe
ninja   C:/Users/86185/AppData/Local/stm32cube/bundles/ninja/1.13.2+st.1/bin/ninja.exe
```

版本：`arm-none-eabi-gcc 14.3.1`（GNU Tools for STM32 14.3.rel1）

### 4.2 构建

```bash
cd C:/Users/86185/Desktop/CubeMX/ETHERNETtest

# 配置（首次或 CMakeLists.txt 改动后自动触发）
cmake.exe -S . -B build/Debug -G Ninja -DCMAKE_BUILD_TYPE=Debug

# 编译
cmake.exe --build build/Debug
```

> **注意**：不要再传 `-DCMAKE_TOOLCHAIN_FILE`，build 目录已有缓存，会报 warning 说该参数未被使用。

### 4.3 ⚠ 生成 hex

**ninja 没有 hex target**（`--target ETHERNETtest.hex` 会报 unknown target），必须手工：

```bash
arm-none-eabi-objcopy.exe -O ihex build/Debug/ETHERNETtest.elf build/Debug/ETHERNETtest.hex
```

> **踩过的坑**：只跑 `cmake --build` 只更新 `.elf`，`.hex` 会**留在旧时间戳**。如果直接烧 hex，烧进去的是旧固件。**每次编译后必须重新 objcopy**，并检查 hex 的时间戳。

### 4.4 当前占用

```
RAM    35680 B / 192 KB   18.15%
CCMRAM     0 B /  64 KB    0.00%
FLASH  81100 B /   1 MB    7.73%
```

### 4.5 新增源文件必须登记

新增 `.c` 文件要加到 **`CMakeLists.txt` 的 `target_sources()`** 里，否则不会被编译：

```cmake
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/debug_uart.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/eth_phy.c
    ${CMAKE_CURRENT_SOURCE_DIR}/Core/Src/udp_echo.c
)
```

（`cmake/stm32cubemx/CMakeLists.txt` 是 CubeMX 生成的主清单，手改它会被重新生成覆盖，所以用户源文件统一加在根 `CMakeLists.txt`。）

---

## 5. 验证步骤

### 5.1 PC 侧网络配置

| 项 | 值 |
|---|---|
| IP 分配 | 手动 |
| IPv4 地址 | `192.168.1.100` |
| 子网掩码 | `255.255.255.0` |
| 网关 | **留空**（网线直连，无网关） |

必须与板子 `192.168.1.30` **同网段、同掩码**。

### 5.2 串口（115200-8-N-1）

正常启动的完整日志：

```
========================================
 ETHERNETtest boot (step 3: lwip)
 sysclk=180000000 Hz, tick=...
========================================
[OK] printf redirect works
[PCF] eth_reset released, shadow=0x7F (BEEP=1 USB_PWR=1 RS485_RE=1, must all be 1)
[MSP] HAL_ETH_MspInit: RMII GPIO (AF11) + ETH clock OK
[PHY] addr=0 ID1=0x0007 ID2=0xC0F1 OUI=0x001C03          ← PHY 活着，OUI=Motorcomm
[PHY] BCR=0x3000 (autoneg_en=1)  BSR=0x7809 (link=0 autoneg_done=0)
[OK] MX_LWIP_Init() returned
[ETH] HAL_ETH_Start() OK -- MAC TE/RE + DMA ST/SR enabled
[IP ] board = 192.168.1.30  mask = 255.255.255.0  gw = 192.168.1.1
[MAC] 02:00:00:12:34:56
[IP ] ping 192.168.1.30 from the PC now
[UDP] echo server listening on 0.0.0.0:8080 (board 192.168.1.30)
[LINK] DOWN  BSR=0x7809 BCR=0x3000                       ← 刚开机，还没协商完
[LINK] UP  BSR=0x782D autoneg_done=1 (cap: 100FD=1 100HD=1 10FD=1 10HD=1)   ← 约 1 秒后
```

**关键判据**：
- `OUI=0x001C03` = Motorcomm，确认 PHY 是 YT8512C
- `[PCF] ... must all be 1` 三个都是 1（否则蜂鸣器响或串口掉线）
- `[LINK] UP` 且 `autoneg_done=1`
- RJ45 双灯亮

### 5.3 ping

```cmd
ping 192.168.1.30
```

期望：
```
来自 192.168.1.30 的回复: 字节=32 时间<1ms TTL=255
数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)
```

### 5.4 UDP 回环（网络调试助手）

配置：**UDP**，本地端口任意，**目标 `192.168.1.30:8080`**

| 操作 | 期望结果 |
|---|---|
| 发送 `hello` | 立刻收到 `hello`（回显） |
| 不发任何东西 | 依然每秒收到 `STM32F429 alive, tick=119582 ms, rx=1` |

串口同时打印：
```
[UDP] #1 recv 5 byte(s) from 192.168.1.100:xxxxx
[UDP]     payload: "hello"
[UDP]     hex: 68 65 6C 6C 6F
[UDP]     echoed 5 byte(s) back to 192.168.1.100:xxxxx
```

> **心跳 tick 间隔必须稳定在 1000ms。** 如果变成 64 秒一次，说明主循环被什么东西卡住了（见 [3.6](#36-mainc-初始化顺序)）。

---

## 6. 故障排查速查表

| 现象 | 最可能的原因 | 检查 |
|---|---|---|
| RJ45 双灯全灭 | PHY 复位没释放 | 串口有没有 `[PCF] eth_reset released`；`ETH_PHY_ReleaseReset()` 是否在 `MX_LWIP_Init()` 之前 |
| 蜂鸣器狂响 / 串口掉线 | PCF8574 初值写错了 | `PCF_POWER_ON_DEFAULT` 必须是 `0xFF`，只清 P7 |
| `[PCF] FAIL: device not ready` | I²C2 没通 | PH4/PH5 上拉、`MX_I2C2_Init()` 是否在前 |
| `[PHY] no valid PHY found` | MspInit 没生效 / MDC 超频 | grep `AF11_ETH`；有没有 `ETH_PHY_Prepare()` |
| `[PHY] addr=1 ... =0x7FFF` | MDIO 悬空电平被误判 | 等 PHY 自举（120ms）；OUI 判据 |
| PHY 读到了但值脏 | MDC 分频没设 | `HAL_ETH_SetMDIOClockRange()` |
| 链路 UP 但 ping「无法访问目标主机」 | `HAL_ETH_Start()` 没调 | grep `HAL_ETH_Start`；串口有没有 `[ETH] HAL_ETH_Start() OK` |
| ping 通但 UDP 收不到 | 目标端口/协议错 | 助手选 **UDP**，目标 `192.168.1.30:8080` |
| UDP 完全没反应 | Windows 防火墙 | 暂时关闭防火墙测试 |
| 心跳 tick 间隔异常（如 64 秒） | 主循环被阻塞 | `while(1)` 里不能有阻塞轮询 |
| 编译报 `undefined reference` | 新 .c 没登记 | 加到 `CMakeLists.txt` 的 `target_sources()` |
| 烧进去没变化 | hex 是旧的 | 重新 `objcopy`，检查时间戳 |

---

## 7. 工程教训

### 7.1 `HAL_ETH_Init()` 不代表网口"开起来了"

它返回 `HAL_OK` 只说明 MAC 配置寄存器写进去了、DMA 描述符链搭好了。它**不碰 PHY、不使能收发、不启动 DMA**。看到 `HAL_OK` 就去 ping，会浪费大量时间。

### 7.2 不要盲信库的默认值

`HAL_ETH_Init()` 从不调用 `HAL_ETH_SetMDIOClockRange()` —— 整个 HAL 库只有定义、零调用点。而 `MACMIIAR.CR` 的复位默认值（`HCLK/42`）只在 HCLK 60~100MHz 下合法。这类"库以为你知道"的坑，只能靠读源码 + 算数字发现。

### 7.3 读到的值是脏的，基于它的推理全是沙上建塔

`BCR=0x2100` 让我推导出"PHY 被强制、自协商关闭、与 PC 不兼容"一整套理论。加了 MDC 分频后真实值是 `0x3000`（自协商一直是开的）。**先保证通信参数正确，再看数据。**

### 7.4 寄存器解码别想当然

IEEE 802.3 的 BSR 高 5 位是**能力位**不是**协商结果**。我从 bit13/bit15 导出"100M half duplex"的结论是错的 —— 真实协商结果在厂商专用寄存器里。**查手册，别猜位含义。**

### 7.5 官方例程也会互相矛盾

原理图说 PHY 是 YT8512C，开发指南第 1013 页说 LAN8720A（那是更老的阿波罗V1 板）。官方例程里 ETH_RESET 的极性两支写法**完全相反**（LAN8720A 用 1→0，YT8512C 用 0→1），说明连官方也不确定，是靠运行时探测板卡版本猜的。
**结论：多个来源冲突时，以原理图 + 实测为准。**

### 7.6 共享 I/O 扩展器：先写全默认值，再逐位改

PCF8574 没有方向寄存器，写一个字节就是驱动全部 8 个脚。第一次写 `0x80` 导致**蜂鸣器狂响 + USB 串口掉线**。
**规矩：碰共享 I/O 扩展器一律先写全默认值（这里是 `0xFF`），再逐位改，其余位永不触碰。**

### 7.7 主循环里不能有阻塞式轮询

一个用未初始化句柄的轮询函数，表现为"每 64 秒报一次错"，实际是 CPU 被卡死、`MX_LWIP_Process()` 被饿死。**裸机 lwIP 的主循环必须每圈都跑到。**

### 7.8 先隔离，再集成

调试顺序是：① 串口 printf 通 → ② 物理层（PCF8574 + MspInit + MDIO 读 PHY ID）通 → ③ 链路 UP → ④ 完整 lwIP + ping → ⑤ UDP 应用。
每步只加一件事，每步都用串口验证。**这套顺序让四个故障能被逐个发现，而不是混在一起猜。**

---

## 附：关键代码位置索引

| 内容 | 位置 |
|---|---|
| PCF8574 释放 PHY 复位 | `Core/Src/eth_phy.c` → `ETH_PHY_ReleaseReset()` |
| RMII 引脚 AF11 配置 | `Core/Src/eth_phy.c` → `HAL_ETH_MspInit()` |
| MDC 分频 + 自协商 | `Core/Src/eth_phy.c` → `ETH_PHY_Prepare()` |
| PHY 诊断打印 | `Core/Src/eth_phy.c` → `ETH_PHY_Dump()` |
| MAC 地址 | `LWIP/Target/ethernetif.c:149-154` |
| `HAL_ETH_Start()` | `LWIP/Target/ethernetif.c:220` |
| 链路状态检测 | `LWIP/Target/ethernetif.c:475` |
| UDP 回环 | `Core/Src/udp_echo.c` |
| 初始化顺序 | `Core/Src/main.c` → `main()` |
| IP 配置 | `LWIP/App/lwip.c:63-74` |
