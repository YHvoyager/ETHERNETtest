/**
  ******************************************************************************
  * @file    framebuf.c
  * @brief   二进制整屏帧缓冲的实现（协议细节见 framebuf.h）
  ******************************************************************************
  */

#include "framebuf.h"
#include "main.h"
#include "oled.h"

#include <string.h>
#include <stdio.h>

/* ------------------------------------------------------------------------- */
/* 与第三方驱动的接口                                                          */
/* ------------------------------------------------------------------------- */

/* OLED_GRAM 是波特律动驱动 oled.c 里的全局显存，8 页 x 128 列。
 * 它的尺寸宏（OLED_PAGE / OLED_COLUMN）定义在 oled.c **内部**、不在头文件里，
 * 所以这里自己写一份常量，顺便在编译期交叉验证：
 * 万一哪天换了驱动、显存尺寸变了，下面的 #error 会立刻拦下来，
 * 而不是让帧数据悄悄错位。 */
extern uint8_t OLED_GRAM[8][128];

#define FB_PAGES   (8U)
#define FB_COLS    (128U)

#if (FB_BYTES != (FB_PAGES * FB_COLS))
#error "FB_BYTES 与 8x128 的显存尺寸不一致"
#endif

/* ------------------------------------------------------------------------- */
/* 状态                                                                        */
/* ------------------------------------------------------------------------- */

/* 接收暂存区。⚠ 必须 static：栈只有 1024 字节，而一帧就是 1024 字节。 */
static uint8_t s_stage[FB_BYTES];

/* 统计量，用 FB? 查询。分三类有助于定位问题：
 *   good  正常显示的帧
 *   bad   长度不对的包（PC 端打包错了，或者被 MTU 截断）
 *   ooo   乱序/重复、被丢弃的帧（网络抖动，属于正常现象） */
static uint32_t s_good;
static uint32_t s_bad;
static uint32_t s_ooo;

/* FBSEQ 的期望序号：每收一帧 +1。收到不等于它的序号就丢弃。 */
static uint16_t s_next_seq;
static uint8_t  s_have_seq;

/* ------------------------------------------------------------------------- */
/* 内部                                                                        */
/* ------------------------------------------------------------------------- */

/**
  * @brief  把暂存区的一帧拷进显存并启动（异步）显示
  *
  * 【为什么用异步的 OLED_ShowFrame() 而不是阻塞版】
  *   全屏 1024 字节 @100kHz I2C 约 90ms。如果每收一帧都阻塞 90ms，主循环
  *   会被彻底堵死：ping 丢包、心跳从 1000ms 变成 1090ms 以上。异步版把
  *   90ms 拆成 8 次每次约 2.8ms 的推进，由主循环的 OLED_FlushPoll() 分 8 遍
  *   喂完；中途来新帧会被自动丢弃（丢帧策略，见 oled.c 的 s_flush_dropped）。
  *
  *   ⚠ 这也是本工程帧率的真实上限所在：I2C 100kHz 下整屏约 11fps。
  *   想更快必须把 I2C 提到 400kHz（Fast Mode，约 4 倍）或只传变化区域。
  */
static void fb_show(void)
{
  /* 一次 memcpy 直接覆盖 8 页 x 128 列 —— 帧格式和显存格式本来就一致，
   * 不需要任何逐像素转换，这正是选这个帧格式的原因。 */
  memcpy((void *)OLED_GRAM, (const void *)s_stage, (size_t)FB_BYTES);
  OLED_ShowFrame();
}

/* ------------------------------------------------------------------------- */
/* 对外接口                                                                    */
/* ------------------------------------------------------------------------- */

int FB_Dispatch(const uint8_t *data, uint16_t len)
{
  uint16_t seq;

  if ((data == NULL) || (len == 0U))
  {
    return 0;
  }

  /* ---- 带序号：FBSEQ <u16 LE> <1024 字节> ---- */
  if (len == (uint16_t)FB_SEQ_PACKET_BYTES)
  {
    /* 必须确认真的是我们的头，否则一个恰好 1032 字节的文本命令会被误吞。
     * （虽然 1032 > SHELL_MAX_LINE 的 192，按理到不了这里，但判据写明确
     * 一点不花什么代价。） */
    if (memcmp(data, "FBSEQ ", FB_SEQ_HEADER_BYTES) != 0)
    {
      s_bad++;
      return 1;                    /* 长度是我们的，内容不是 —— 当坏帧丢掉 */
    }

    seq = (uint16_t)data[6] | (uint16_t)((uint16_t)data[7] << 8);

    if (s_have_seq != 0U)
    {
      /* 序号相等 = 重复包，序号更旧 = 迟到的包。两种都丢。
       * 用 int16 差值比较而不是直接 != ，是为了让 u16 回绕（65535 → 0）
       * 也能正确判断成"更新"。 */
      if ((int16_t)(seq - s_next_seq) <= 0)
      {
        s_ooo++;
        return 1;
      }
    }

    s_next_seq = (uint16_t)(seq + 1U);
    s_have_seq = 1U;

    memcpy(s_stage, data + FB_SEQ_HEADER_BYTES, (size_t)FB_BYTES);
    s_good++;
    fb_show();
    return 1;
  }

  /* ---- 不带序号：整个报文就是 1024 字节 ---- */
  if (len == (uint16_t)FB_BYTES)
  {
    memcpy(s_stage, data, (size_t)FB_BYTES);
    s_good++;
    fb_show();
    return 1;
  }

  /* 长度既不是 1024 也不是 1032：不是帧，交回调用者当文本命令处理。 */
  return 0;
}

void FB_RequestFlush(void)
{
  OLED_ShowFrame();
}

/**
  * @brief  统计信息，供 Reg_Shell_Exec() 的 FB? 命令使用
  *
  * 【为什么要有这个】发帧是"发了就不管"的（没有应答，否则 30fps 会被
  * 往返时延卡住）。没有统计的话，PC 端根本不知道帧到底有没有被收下 ——
  * 屏幕黑着还是板子没收到，完全无法区分。有了 good/bad/ooo 三个数，
  * 一眼就能看出是"打包错了"（bad 涨）还是"网络抖动"（ooo 涨）。
  *
  * @param  out       输出缓冲
  * @param  out_size  缓冲字节数
  * @retval  写进 out 的字节数（不含结尾 '\0'）
  */
uint32_t FB_Stats(char *out, uint32_t out_size)
{
  int n;

  if ((out == NULL) || (out_size == 0U))
  {
    return 0U;
  }

  n = snprintf(out, (size_t)out_size,
               "FB: good=%lu bad=%lu ooo=%lu  (%u bytes/frame, %u bytes with seq)\r\n",
               (unsigned long)s_good,
               (unsigned long)s_bad,
               (unsigned long)s_ooo,
               (unsigned int)FB_BYTES,
               (unsigned int)FB_SEQ_PACKET_BYTES);

  if (n < 0)
  {
    out[0] = '\0';
    return 0U;
  }

  return ((uint32_t)n < out_size) ? (uint32_t)n : (out_size - 1U);
}
