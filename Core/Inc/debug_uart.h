/**
 ******************************************************************************
 * @file    debug_uart.h
 * @brief   把 printf 重定向到 USART1（PA9=TX, PA10=RX, 115200-8-N-1）
 *
 * 【用法】在 main.c 里 #include "debug_uart.h" 之后，直接 printf 即可。
 *        前提：MX_USART1_UART_Init() 已经调用过。
 *
 * 【为什么不用 __io_putchar 的弱符号】
 *   CubeMX 生成的 Core/Src/syscalls.c 里 __io_putchar / _write 都是 weak，
 *   只要在本工程里定义一个同名的强符号，链接器就会优先用我们的。
 *   这样 CubeMX 重新生成代码也不会把重定向冲掉。
 ******************************************************************************
 */

#ifndef __DEBUG_UART_H
#define __DEBUG_UART_H

#include "main.h"
#include <stdio.h>

/* 低层字符输出（供 syscalls.c 的弱 _write 调用） */
int __io_putchar(int ch);

/* 批量输出（覆盖 syscalls.c 里逐字符的弱 _write，效率更高） */
int _write(int file, char *ptr, int len);

/* 打印一行分隔线，方便在串口助手里区分每次上电 */
void Debug_UART_Banner(const char *tag);

#endif /* __DEBUG_UART_H */
