/**
  ******************************************************************************
  * @file    framebuf.h
  * @brief   二进制整屏帧缓冲：PC 一次 UDP 发 1024 字节，屏整屏更新
  *
  * 【为什么必须有这个模块 —— 这是"让屏幕动起来"的唯一可行路径】
  *
  *   已有的 OLED 文本命令（OLED TXT / OLED PIX）一条命令只能写 16px 高的一行
  *   或一个像素。要显示一幅 128x64 的完整画面需要 1024 个像素，用 OLED PIX
  *   就是 1024 条命令 —— 就算每秒能发 1000 条，也到不了任何像样的帧率，
  *   更别说"会动的眼睛"。
  *
  *   本模块走的是**原始二进制**：一个 UDP 报文直接携带 1024 字节的整屏位图，
  *   板子收到后原样刷进 SSD1306 显存。一个包一帧，30fps 也只需要 30 个包/秒。
  *
  * 【帧格式】1024 字节 = 8 页 x 128 列，每字节表示**一列里的 8 个像素**
  *
  *     byte = gfx[(y >> 3) * 128 + x]
  *     bit  = y & 7
  *     像素亮 <=> (byte >> bit) & 1 == 1
  *
  *   注意 bit0 在最上面 —— 这是 SSD1306 页寻址的天然格式，板子收到后**一个
  *   字节都不用改**，直接 memcpy 进 OLED_GRAM 就能显示。PC 端打包时按这个
  *   规则转换（见 pc_agent/canvas.py 的 pack()）。
  *
  * 【两条命令】
  *
  *   FB    <1024 字节>              —— 整个报文长度必须**正好** 1024，不带头
  *   FBSEQ <2 字节序号> <1024 字节> —— 报文长度 1026，序号小端 u16
  *
  *   FBSEQ 存在的理由：UDP 不保证顺序。动画连发 30 包/秒时，偶尔会出现
  *   "第 5 帧比第 4 帧先到"或"同一个包被重传两次"。没有序号的话，画面会
  *   闪回上一帧（看着像卡顿/抖动）；有序号就能直接丢掉迟到的帧，
  *   代价只是少显示一帧，而不是画面倒退。
  *
  *   ⚠ 判重只拦"差几帧"的迟到包（FB_SEQ_WINDOW = 128 以内），
  *   序号大幅回退（PC 重跑 agent.py，从 0 重新开始）会被认成新会话并
  *   重建基线。早期写成"必须严格递增"时，PC 每重跑一次，前 N 帧就被
  *   全部拒收，屏幕一直不动（实测 good 恒定、ooo 暴涨）。
  *
  *   两条命令都是**只认二进制**：FB 后面跟的是裸字节，不是文本。它们必须在
  *   文本命令分发（Reg_Shell_Exec）**之前**被识别，见 fb_dispatch() 的说明。
  *
  * ⚠ 为什么帧缓冲要放 static 而不是栈上：
  *   STM32F429 的栈只有 0x400 = 1024 字节（见 startup_stm32f429xx.s），
  *   而一帧正好是 1024 字节。放栈上会瞬间爆栈。这里用一块 static 暂存区
  *   接收，校验通过后再拷进 OLED_GRAM。
  ******************************************************************************
  */
#ifndef __FRAMEBUF_H
#define __FRAMEBUF_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/** 一帧的字节数：128 x 64 / 8 */
#define FB_BYTES            (1024U)

/** 带序号时的报文总长：6 字节魔数 "FBSEQ " + 2 字节序号 + 1024 数据 */
#define FB_SEQ_MAGIC        "FBSEQ "
#define FB_SEQ_MAGIC_BYTES  (6U)   /* 只比魔数这 6 个字节 */
#define FB_SEQ_HEADER_BYTES (8U)   /* 魔数 + 序号，共 8 字节 */
#define FB_SEQ_PACKET_BYTES (FB_SEQ_HEADER_BYTES + FB_BYTES)   /* 1032 */

/* ⚠ 校验魔数时必须用 FB_SEQ_MAGIC_BYTES（6），不能用 FB_SEQ_HEADER_BYTES（8）。
 * 头一共 8 字节 = 6 字节魔数 + 2 字节序号，拿 8 去 memcmp 会把序号也比进去，
 * 只有 seq 的低字节恰好为 0（即第一帧）时才碰巧通过 —— 曾因此出现
 * "good=1 bad=21" 的症状（120 帧里只有第 0 帧被认下）。 */

/**
  * @brief  尝试把一包数据当成二进制帧处理
  * @param  data  收到的原始字节
  * @param  len   字节数
  * @retval  1 = 认出来了并且已经处理（好帧已显示，或坏帧已丢弃并计数）
  *          0 = 不是帧数据，请调用者按文本命令处理
  *
  * @note   判据只看**数组长度**，不看内容，所以这一层永远不会把一条文本
  *         命令误吞掉 —— 文本命令不可能正好是 1024 或 1026 字节（命令上限
  *         是 191 字节，见 reg_shell.c 的 SHELL_MAX_LINE）。
  */
int FB_Dispatch(const uint8_t *data, uint16_t len);

/**
  * @brief  把当前帧缓冲标记为需要显示（异步，由主循环推进）
  *
  * @note   只为将来"脏矩形/局部刷新"预留。当前 FB_Dispatch() 收帧后直接
  *         拷贝并调 OLED_ShowFrame()，不经过这里。
  */
void FB_RequestFlush(void);

/**
  * @brief  收帧统计，给文本命令 FB? 用（实现里直接 snprintf 成一行）
  * @retval  写进 out 的字节数（不含结尾 '\0'）
  */
uint32_t FB_Stats(char *out, uint32_t out_size);

#ifdef __cplusplus
}
#endif

#endif /* __FRAMEBUF_H */
