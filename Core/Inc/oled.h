#ifndef __OLED_H__
#define __OLED_H__

#include "font.h"
#include "main.h"
#include "string.h"

typedef enum {
  OLED_COLOR_NORMAL = 0, // 正常模式 黑底白字
  OLED_COLOR_REVERSED    // 反色模式 白底黑字
} OLED_ColorMode;

void OLED_Init();
void OLED_DisPlay_On();
void OLED_DisPlay_Off();

void OLED_NewFrame();
void OLED_ShowFrame();
void OLED_SetPixel(uint8_t x, uint8_t y, OLED_ColorMode color);

/* ---------------------------------------------------------------------------
 * 【本工程新增】非阻塞刷屏
 *
 * 原版 OLED_ShowFrame() 一次同步发 8 页 = 1024 字节 @100kHz ≈ 92ms，
 * 期间主循环里的 MX_LWIP_Process() 完全停摆（ping 丢包、心跳间隔抖动）。
 *
 * 现在 OLED_ShowFrame() 只把第一页启动起来就返回，后续由主循环里的
 * OLED_FlushPoll() 一页一步推进，每步最长约 2.8ms（129 字节 @100kHz）。
 *
 *   while (1) {
 *     MX_LWIP_Process();
 *     Echo_Service_Poll();
 *     OLED_FlushPoll();       <-- 加这一句
 *   }
 *
 * OLED_ShowFrameBlocking() 保留原版阻塞语义，只在开机画面、OLED INIT
 * 这种"必须发完再往下走"的场合用。
 * ------------------------------------------------------------------------- */
uint8_t  OLED_FlushPoll(void);
uint8_t  OLED_FlushBusy(void);
uint32_t OLED_FlushDropped(void);
void     OLED_ShowFrameBlocking(void);

/* ---------------------------------------------------------------------------
 * 【本工程新增】I2C 总线死锁恢复
 *
 * I2C2 上挂着 SSD1306（0x78）和 PCF8574（0x20，管 ETH_RESET）两个从机。
 * 任一从机在"发 ACK"途中被复位/掉电打断，就会把 SDA 钳在低电平不放，
 * 主板再发起始条件也永远等不到总线空闲 —— 用 HAL_MAX_DELAY 的话主循环
 * 会永久卡死（屏幕定格、ping 不应）。
 *
 * 本函数走标准解锁流程：反初始化 -> 9 个 SCL 脉冲 -> STOP -> 重新 Init。
 * 由 OLED_Send() 发送失败时、以及 OLED_FlushPoll() 看门狗超时时自动调用，
 * 也可以用 OLED RECOVER 命令手动触发（见 reg_shell.c）。
 * ------------------------------------------------------------------------- */
void OLED_I2C_Recover(void);

void OLED_DrawLine(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2, OLED_ColorMode color);
void OLED_DrawRectangle(uint8_t x, uint8_t y, uint8_t w, uint8_t h, OLED_ColorMode color);
void OLED_DrawFilledRectangle(uint8_t x, uint8_t y, uint8_t w, uint8_t h, OLED_ColorMode color);
void OLED_DrawTriangle(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2, uint8_t x3, uint8_t y3, OLED_ColorMode color);
void OLED_DrawFilledTriangle(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2, uint8_t x3, uint8_t y3, OLED_ColorMode color);
void OLED_DrawCircle(uint8_t x, uint8_t y, uint8_t r, OLED_ColorMode color);
void OLED_DrawFilledCircle(uint8_t x, uint8_t y, uint8_t r, OLED_ColorMode color);
void OLED_DrawEllipse(uint8_t x, uint8_t y, uint8_t a, uint8_t b, OLED_ColorMode color);
void OLED_DrawImage(uint8_t x, uint8_t y, const Image *img, OLED_ColorMode color);

void OLED_PrintASCIIChar(uint8_t x, uint8_t y, char ch, const ASCIIFont *font, OLED_ColorMode color);
void OLED_PrintASCIIString(uint8_t x, uint8_t y, char *str, const ASCIIFont *font, OLED_ColorMode color);
void OLED_PrintString(uint8_t x, uint8_t y, char *str, const Font *font, OLED_ColorMode color);

#endif // __OLED_H__