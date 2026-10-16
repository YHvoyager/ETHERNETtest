/**
  ******************************************************************************
  * @file    eth_phy.c
  * @brief   阿波罗V2（STM32F429 + YT8512C）以太网板级补丁
  *
  * 三件事：补 HAL_ETH_MspInit、释放 PHY 复位、准备 PHY。
  * 原理与故障排查过程见 docs/lwip-f429-apollo-v2.md。
  *
  * 【硬件事实（原理图 DNF429P_F767P_H743P V2.5.pdf）】
  *   PHY      : YT8512C (U2)，地址 0（PHYADD0/1 都去驱动 LED，没拉地址）
  *   ETH_RESET: PCF8574T (U11) 的 P7，经 Q1 反相
  *   PCF8574  : A2/A1/A0 全接地 -> 7 位地址 0x20 -> HAL 8 位格式 0x40
  *   IIC      : PH4 = SCL, PH5 = SDA (I2C2, AF4)
  *   RMII     : PA1 REF_CLK, PA2 MDIO, PA7 CRS_DV, PC1 MDC,
  *              PC4 RXD0, PC5 RXD1, PB11 TX_EN, PG13 TXD0, PG14 TXD1
  ******************************************************************************
  */

#include "eth_phy.h"
#include "i2c.h"
#include "lwip/netif.h"     /* ETH_PHY_CheckLink() 要调 netif_set_link_up/down() */
#include <stdio.h>

/* ===========================================================================
 * 一、PCF8574：PHY 复位的唯一控制通路
 * ========================================================================= */

#define PCF8574_ADDR_8BIT   (0x20 << 1)   /* 7 位 0x20 左移 -> HAL 的 8 位格式 0x40 */
#define PCF8574_I2C_TIMEOUT 100U

/* P7 = ETH_RESET，经 Q1 反相：P7=1 -> 复位，P7=0 -> 正常工作 */
#define PCF_PIN_ETH_RESET   (1U << 7)

/* ⚠ PCF8574 初值必须是 0xFF。
 *
 * 它是准双向口，**没有方向寄存器**：写一个字节就是驱动全部 8 个引脚，
 * "我只想改 P7" 是不成立的。上电默认 0xFF（全高）时：P0(BEEP)=1 -> Q4 是
 * PNP，基极高则截止 -> 蜂鸣器不响；P3(USB_PWR)=1 -> CH340 串口不掉线。
 * 若写 0x00 或 0x80：P0=0 -> 蜂鸣器狂响，P3=0 -> 串口直接掉线。
 * 结论：先写 0xFF，之后**只清 P7 那一位**。 */
#define PCF_POWER_ON_DEFAULT 0xFFU

/* PCF8574 读回的是引脚电平而非输出锁存，必须自己存影子 */
static uint8_t s_pcf_shadow = PCF_POWER_ON_DEFAULT;

extern I2C_HandleTypeDef hi2c2;

static HAL_StatusTypeDef pcf_write(uint8_t v)
{
  HAL_StatusTypeDef st = HAL_I2C_Master_Transmit(&hi2c2, PCF8574_ADDR_8BIT,
                                                 &v, 1, PCF8574_I2C_TIMEOUT);
  if (st == HAL_OK)
  {
    s_pcf_shadow = v;
  }
  return st;
}

int ETH_PHY_ReleaseReset(void)
{
  /* 1) 探测 PCF8574 在不在总线上 */
  if (HAL_I2C_IsDeviceReady(&hi2c2, PCF8574_ADDR_8BIT, 3, PCF8574_I2C_TIMEOUT) != HAL_OK)
  {
    printf("[PCF] FAIL: device not ready (addr=0x%02X) -> check PH4/PH5 pull-ups\r\n",
           PCF8574_ADDR_8BIT);
    return -1;
  }

  /* 2) 先归位到安全默认值，避免总线上的状态未知时误动作 */
  s_pcf_shadow = PCF_POWER_ON_DEFAULT;
  if (pcf_write(s_pcf_shadow) != HAL_OK) { printf("[PCF] FAIL: safe-default write\r\n"); return -2; }
  HAL_Delay(2);

  /* 3) 断言复位（P7=1），保证后面释放的是一个确定的"复位 -> 工作"边沿 */
  s_pcf_shadow |= PCF_PIN_ETH_RESET;
  if (pcf_write(s_pcf_shadow) != HAL_OK) { printf("[PCF] FAIL: assert write\r\n"); return -3; }
  HAL_Delay(10);                       /* 复位脉宽，datasheet 最小 100us，给 10ms */

  /* 4) 只清 P7，其余七位保持 1 */
  s_pcf_shadow &= (uint8_t)~PCF_PIN_ETH_RESET;
  if (pcf_write(s_pcf_shadow) != HAL_OK) { printf("[PCF] FAIL: release write\r\n"); return -4; }

  printf("[PCF] eth_reset released, shadow=0x%02X (BEEP=%u USB_PWR=%u RS485_RE=%u, must all be 1)\r\n",
         s_pcf_shadow,
         (unsigned)((s_pcf_shadow >> 0) & 1U),
         (unsigned)((s_pcf_shadow >> 3) & 1U),
         (unsigned)((s_pcf_shadow >> 6) & 1U));

  HAL_Delay(120);   /* PHY 自举时间，省了会读不到 PHY ID */
  return 0;
}

/* ===========================================================================
 * 二、HAL_ETH_MspInit：补上 CubeMX 漏掉的那一块
 *
 * CubeMX 生成的 stm32f4xx_hal_msp.c 里没有 HAL_ETH_MspInit，HAL 库里它是
 * __weak 空函数。缺了它，9 根 RMII 引脚不会被配成 AF11、ETH 时钟不会开，
 * MAC 和 PHY 之间的数据通路是断的。这里补上（强符号覆盖）。
 * ========================================================================= */

void HAL_ETH_MspInit(ETH_HandleTypeDef *heth)
{
  GPIO_InitTypeDef gpio = {0};

  if (heth->Instance != ETH) { return; }

  __HAL_RCC_ETH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();

  gpio.Mode      = GPIO_MODE_AF_PP;
  gpio.Pull      = GPIO_NOPULL;
  gpio.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio.Alternate = GPIO_AF11_ETH;

  gpio.Pin = GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_7;      /* PA1 REF_CLK, PA2 MDIO, PA7 CRS_DV */
  HAL_GPIO_Init(GPIOA, &gpio);

  gpio.Pin = GPIO_PIN_11;                                /* PB11 TX_EN */
  HAL_GPIO_Init(GPIOB, &gpio);

  gpio.Pin = GPIO_PIN_1 | GPIO_PIN_4 | GPIO_PIN_5;       /* PC1 MDC, PC4 RXD0, PC5 RXD1 */
  HAL_GPIO_Init(GPIOC, &gpio);

  gpio.Pin = GPIO_PIN_13 | GPIO_PIN_14;                  /* PG13 TXD0, PG14 TXD1 */
  HAL_GPIO_Init(GPIOG, &gpio);

  printf("[MSP] HAL_ETH_MspInit: RMII GPIO (AF11) + ETH clock OK\r\n");
}

/* ===========================================================================
 * 三、PHY 准备：MDC 分频 + 自协商
 *
 * 必须在 HAL_ETH_Init() 之后、任何 MDIO 访问之前调用。
 * ========================================================================= */

extern ETH_HandleTypeDef heth;   /* 定义在 LWIP/Target/ethernetif.c */

#if ETH_PHY_DIAG
static void eth_phy_dump_impl(void);
#endif

void ETH_PHY_Prepare(void)
{
  uint32_t bcr = 0;

  /* MDC 时钟分频 —— STM32F4 上必须自己补的坑。
   * HAL_ETH_Init() **不会**配置 MACMIIAR 的 CR[2:0]，复位默认 000 = HCLK/42，
   * 只在 HCLK 60~100MHz 下合法。本板 HCLK=180MHz -> MDC = 180/42 ≈ 4.29MHz，
   * 超出 IEEE 802.3 的 2.5MHz 上限，PHY 对寄存器访问的应答变得不确定。
   * HAL_ETH_SetMDIOClockRange() 按 HCLK 选 CR（180MHz -> Div102 ≈ 1.76MHz）。 */
  HAL_ETH_SetMDIOClockRange(&heth);

  /* 保证自协商是开着的。读 BCR，若 bit12 AUTONEG_EN=0 则清强制速率/双工位、
   * 置 AUTONEG_EN 并触发 RESTART_AUTONEG。PC 侧网卡是自协商模式，一端强制
   * 一端自协商按 IEEE 802.3 无法达成一致。
   * 只在这里做一次 —— 放进 100ms 的 ethernet_link_check_state() 会导致每次
   * 轮询都重启协商，链路永远协商不完。 */
  if (HAL_ETH_ReadPHYRegister(&heth, 0U, 0x00U, &bcr) == HAL_OK)
  {
    if ((bcr & 0x1000U) == 0U)
    {
      bcr &= ~(uint32_t)(0x2000U | 0x0100U);   /* 清 SPEED_SELECT、DUPLEX_MODE */
      bcr |= 0x1000U;                          /* AUTONEG_EN                   */
      bcr |= 0x0200U;                          /* RESTART_AUTONEG              */

      if (HAL_ETH_WritePHYRegister(&heth, 0U, 0x00U, bcr) == HAL_OK)
      {
        printf("[ETH] PHY autoneg was off, re-enabled (BCR=0x%04lX)\r\n", (unsigned long)bcr);
      }
      else
      {
        printf("[ETH] WARN: BCR write failed\r\n");
      }
    }
  }

#if ETH_PHY_DIAG
  eth_phy_dump_impl();
#endif
}

/* ---------------------------------------------------------------------------
 * 链路检测
 *
 * 【这个函数为什么住在 eth_phy.c 而不是 ethernetif.c】
 * CubeMX 生成的 ethernetif.c 里有个空的 ethernet_link_check_state()，它的
 * 函数体不在 USER CODE 区内，每次 CubeMX 重新生成都会被清空 —— 已经丢过
 * 两次，最近一次导致板子"能收不能发"（见下面 ERR_RTE 的说明）。
 *
 * 把实现放在本文件，CubeMX 不生成这里、永不覆盖；ethernetif.c 里只留一行
 * ETH_PHY_CheckLink(netif); —— 就算再被清掉，丢的也只是一行，git diff 一眼
 * 能看出来。
 *
 * 【丢了会怎样 —— 值得完整记一遍】
 * netif_set_link_up() 永远不会被调用 → netif 的 NETIF_FLAG_LINK_UP 恒为 0
 * （netif_init() 里 netif->flags = 0，见 lwip/src/core/netif.c:328）
 * → ip4_route() 的判据 netif_is_up() && netif_is_link_up() && IP非零
 * 三条里第二条不成立，找不到出口网卡并返回 NULL
 * → udp_sendto() 一律返回 ERR_RTE(-4)
 * → 现象是"能收不能发"：PC 发来的命令能到达、能执行（ethernetif_input()
 * 不看链接标志），但所有回包和每秒心跳全部发不出去。
 * ------------------------------------------------------------------------- */

/* 只在链路状态变化时打印，避免每 100ms 刷一行。初值 0xFF 表示"还没有过状态"，
 * 保证开机第一次一定会打印。 */
#define ETH_PHY_LINK_UNKNOWN 0xFFU

void ETH_PHY_CheckLink(struct netif *netif)
{
  static uint8_t s_last_link = ETH_PHY_LINK_UNKNOWN;

  uint32_t bsr = 0;
  uint32_t bcr = 0;
  uint8_t  link;

  if (netif == NULL)
  {
    return;
  }

  /* BSR（reg 0x01）必须连读两次取第二次。
   * IEEE 802.3 规定 bit2 Link Status 和 bit5 Auto-Negotiation Complete 是
   * **锁存低**（latching low）：链路曾经断过就一直读 0，直到被读走一次才刷新。
   * 只读一次会拿到"历史值"而不是当前值。 */
  if (HAL_ETH_ReadPHYRegister(&heth, 0U, 0x01U, &bsr) != HAL_OK)
  {
    return;                                 /* 读失败就保持原状态，不乱改 */
  }

  if (HAL_ETH_ReadPHYRegister(&heth, 0U, 0x01U, &bsr) != HAL_OK)
  {
    return;
  }

  link = ((bsr & 0x0004U) != 0U) ? 1U : 0U;  /* bit2 = Link Status */

  if (link == s_last_link)
  {
    return;                                  /* 无变化，不打印也不动 netif */
  }

  s_last_link = link;

  if (link != 0U)
  {
    netif_set_link_up(netif);
    printf("[LINK] UP  BSR=0x%04lX autoneg_done=%lu (cap: 100FD=%lu 100HD=%lu 10FD=%lu 10HD=%lu)\r\n",
           (unsigned long)bsr,
           (unsigned long)((bsr >> 5) & 1U),
           (unsigned long)((bsr >> 14) & 1U),
           (unsigned long)((bsr >> 13) & 1U),
           (unsigned long)((bsr >> 12) & 1U),
           (unsigned long)((bsr >> 11) & 1U));
  }
  else
  {
    netif_set_link_down(netif);

    /* 顺手读一次 BCR 一起打印，方便判断"是协商没开还是线没插" */
    (void)HAL_ETH_ReadPHYRegister(&heth, 0U, 0x00U, &bcr);
    printf("[LINK] DOWN  BSR=0x%04lX BCR=0x%04lX\r\n",
           (unsigned long)bsr, (unsigned long)bcr);
  }
}

#if ETH_PHY_DIAG
/* ===========================================================================
 * 四、诊断：扫 MDIO 总线，打印 PHY 的 ID / BCR / BSR
 *
 * 地址扫描的判据必须排除 MDIO 悬空电平：没有器件应答时读回 0xFFFF 或 0x7FFF，
 * 只判断 "!= 0xFFFF" 会把一堆空地址误报成器件（实测 addr=1/6/8/11..31 全报
 * 0x7FFF）。要求厂商 OUI 合法才认。
 * ========================================================================= */
static void eth_phy_dump_impl(void)
{
  uint32_t id1 = 0, id2 = 0, bcr = 0, bsr = 0;
  uint32_t oui;
  int n;

  for (n = 0; n <= 31; n++)
  {
    if (HAL_ETH_ReadPHYRegister(&heth, (uint32_t)n, 0x02U, &id1) != HAL_OK) continue;
    if (HAL_ETH_ReadPHYRegister(&heth, (uint32_t)n, 0x03U, &id2) != HAL_OK) continue;
    if (id1 == 0xFFFFU || id1 == 0x7FFFU || id1 == 0U) continue;
    if (id2 == 0xFFFFU || id2 == 0x7FFFU || id2 == 0U) continue;

    oui = ((id1 & 0x3FFFU) << 6) | ((id2 >> 10) & 0x3FU);
    if (oui == 0U || oui == 0x3FFFFU) continue;

    printf("[PHY] addr=%d ID1=0x%04lX ID2=0x%04lX OUI=0x%06lX\r\n",
           n, (unsigned long)id1, (unsigned long)id2, (unsigned long)oui);

    (void)HAL_ETH_ReadPHYRegister(&heth, (uint32_t)n, 0x00U, &bcr);
    (void)HAL_ETH_ReadPHYRegister(&heth, (uint32_t)n, 0x01U, &bsr);
    printf("[PHY] BCR=0x%04lX (autoneg_en=%lu)  BSR=0x%04lX (link=%lu autoneg_done=%lu)\r\n",
           (unsigned long)bcr, (unsigned long)((bcr >> 12) & 1U),
           (unsigned long)bsr, (unsigned long)((bsr >> 2) & 1U), (unsigned long)((bsr >> 5) & 1U));
    return;
  }
  printf("[PHY] no valid PHY found on MDIO bus (all 0xFFFF/0x7FFF)\r\n");
}

void ETH_PHY_Dump(void)
{
  eth_phy_dump_impl();
}
#endif /* ETH_PHY_DIAG */
