/**
  ******************************************************************************
  * @file    ssd1306.h
  * @brief   SSD1306 128x64 OLED 驱动（I2C2，PH4=SCL / PH5=SDA）
  *
  * 【这块屏和它挂在哪】
  *   SSD1306 128x64，四针 I2C 模块（VCC/GND/SCL/SDA），地址 0x3C（7 位）
  *   → HAL 的 8 位格式 0x78。
  *
  *   挂在 **I2C2** 上，和板载 PCF8574T（U11，地址 0x20）**共用一条总线**。
  *   I2C 本来就是总线，地址不冲突就能共存，实际也确认能共存。
  *   ⚠ PCF8574 管着 ETH_RESET（P7），所以 I2C2 上任何操作都不能把总线拉死，
  *     否则 ETH_PHY_ReleaseReset() 失败 → main() 直接 while(1) 停住 → 板子起不来。
  *
  * 【三级 buffer 的职责划分 —— 这是本驱动的核心设计】
  *
  *     上层（命令 / 未来的 AI）
  *         │  DrawPixel / DrawText / Blit / Clear
  *         ▼
  *     g_oled_gfx[1024]   ← 图形缓冲：SSD1306 的显存镜像，纯软件，随便改
  *         │  SSD1306_Flush()
  *         ▼
  *     g_oled_dirty[8]    ← 脏页位图：8 个 bit 对应 8 页，标出哪几页变了
  *         │  只把脏页拼出来
  *         ▼
  *     g_oled_tx[129]     ← 发送缓冲：0x40 + 一页 128 字节，一次 I2C 传一页
  *         │  HAL_I2C_Master_Transmit()（第 1 步用阻塞版）
  *         ▼
  *     SSD1306 面板
  *
  *   为什么要脏页位图：128x64 全屏是 1024 字节，100kHz 下要传约 100ms，
  *   一整帧阻塞下来主循环里的 MX_LWIP_Process() 就被饿死了（ping 会超时）。
  *   只传变了的页，改一行字通常只脏 1~2 页（约 12~25ms），代价可接受。
  *   这一步还不需要 DMA，等下一步加了帧缓冲上传再开。
  *
  * 【坐标与像素格式】
  *   坐标系原点在**左上角**，x 向右 0~127，y 向下 0~63。
  *   SSD1306 本身是**页寻址**的：显存分 8 页，每页 8 行像素，
  *   每页里一个字节的 bit0 是这一页的**最上面**那行。转换在 DrawPixel 里做。
  *
  * 【当前实现状态】
  *   第 1 步：阻塞 I2C + 脏页刷新。目标是先把屏点亮、证明硬件通路没问题。
  *   第 2 步才会加 DMA 和 OLED 命令。
  ******************************************************************************
  */
#ifndef __SSD1306_H
#define __SSD1306_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* --- 屏幕几何 --- */
#define SSD1306_WIDTH        128U
#define SSD1306_HEIGHT       64U
#define SSD1306_PAGES        (SSD1306_HEIGHT / 8U)          /* 8 页 */
#define SSD1306_GFX_SIZE     (SSD1306_WIDTH * SSD1306_PAGES) /* 1024 字节 */

/* --- I2C 地址与超时 ---
 * 7 位地址 0x3C 左移一位 → HAL 要的 8 位格式 0x78。
 * 注意 HAL_I2C_Master_Transmit 的 DevAddress 参数就是"8 位格式"，
 * 和 eth_phy.c 里 PCF8574 用 (0x20 << 1) 是同一个道理。 */
#define SSD1306_I2C_ADDR     (0x3C << 1)

/** 单页传输（1 控制字节 + 128 数据字节）在 100kHz 下约 12ms，给足余量 */
#define SSD1306_I2C_TIMEOUT  100U

/**
  * @brief  初始化 OLED 并清屏
  * @retval  0 = 成功
  *         -1 = 总线上找不到 0x3C（屏没插 / 接线反了 / 上拉不够）
  *         -2 = 初始化命令序列写失败
  *         -3 = 清屏失败
  *
  * @note   必须在 MX_I2C2_Init() 之后调用。
  *         **不要**放在 ETH_PHY_ReleaseReset() 之前 —— 先保证网口那条路活着。
  */
int SSD1306_Init(void);

/**
  * @brief  把图形缓冲里"变脏的页"刷到屏上，然后清掉脏标记
  * @retval  0 = 成功（含"没有脏页，什么都没做"）
  *         <0 = I2C 出错（返回 HAL 状态码的负值）
  *
  * @note   非阻塞的替代品在下一步（DMA）。当前这一版会阻塞约
  *         (脏页数 × 12)ms，所以**不要在 while(1) 里无条件每圈都调**。
  */
int SSD1306_Flush(void);

/**
  * @brief  标记全部 8 页为脏，让下一次 Flush 推整个屏
  */
void SSD1306_MarkAllDirty(void);

/**
  * @brief  清空图形缓冲（**只是缓冲，屏上要等 Flush 才变**）
  * @param  on  0 = 全黑，非 0 = 全亮
  */
void SSD1306_Clear(uint8_t on);

/**
  * @brief  画/擦一个像素
  * @param  x,y  坐标，原点左上
  * @param  on   0 = 灭，非 0 = 亮
  * @note   越界坐标会被静默丢弃，不会写坏缓冲 —— 上层画图时不必自己夹紧。
  */
void SSD1306_DrawPixel(uint8_t x, uint8_t y, uint8_t on);

/**
  * @brief  得到图形缓冲（1024 字节，页优先：buf[page*128 + x]）
  * @note   直接改这个缓冲后，必须自己调 SSD1306_MarkAllDirty()
  *         （或者知道改了哪页就只标记那页）。
  */
uint8_t *SSD1306_GetBuffer(void);

/**
  * @brief  用 8x16 的 ASCII 字模画一个字符
  * @param  x,y  左上角坐标；y 建议取 8 的倍数（一个字横跨 2 页）
  * @param  c    可打印 ASCII（0x20~0x7E），其余当成空格
  * @param  on   0 = 擦成黑，非 0 = 点亮
  */
void SSD1306_DrawChar(uint8_t x, uint8_t y, char c, uint8_t on);

/**
  * @brief  用 8x16 字模画一行字符串
  * @param  x,y  左上角坐标
  * @param  s    以 '\0' 结尾的字符串；**非 ASCII 字节会画成方块占位**
  * @param  on   0 = 擦成黑，非 0 = 点亮
  * @retval 画完之后的 x 坐标（可用于接着画）
  *
  * @note   本驱动**不做中文字库**：一个 16x16 汉字点阵要 32 字节，
  *         常用 3000 字就是 96KB，F429 有 1MB Flash 但没必要为此占。
  *         要显示中文就等第 3 步的 Blit 命令，由 PC 侧把点阵发下来。
  */
uint8_t SSD1306_DrawString(uint8_t x, uint8_t y, const char *s, uint8_t on);

/**
  * @brief  诊断：扫 I2C2 总线，把每个有应答的地址填进 out
  * @param  out      输出文本缓冲
  * @param  out_size 缓冲大小
  * @retval 找到的器件数
  *
  * 用来回答一个很常见的问题："OLED 不亮，到底是屏没接上还是驱动没写对？"
  * 扫到 0x3C 就说明总线通、屏活着，问题在驱动；扫不到就是接线/供电问题。
  */
uint32_t SSD1306_I2CScan(char *out, uint32_t out_size);

#ifdef __cplusplus
}
#endif

#endif /* __SSD1306_H */
