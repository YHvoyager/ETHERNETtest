/**
 ******************************************************************************
 * @file    debug_uart.c
 * @brief   printf 重定向到 USART1
 *
 * 【依赖】usart.c 里的 huart1（MX_USART1_UART_Init 已配置 115200-8-N-1）
 *
 * 【为什么阻塞发送是安全的】
 *   本工程是裸机 + NO_SYS=1，没有 RTOS，不会因为阻塞发送被别人抢占。
 *   但要注意：**不要在 LwIP 主循环里长时间阻塞**，一次 printf 几十字节
 *   在 115200 下大约 1~2 ms，可以接受；打印几百字节就要留意了。
 ******************************************************************************
 */

#include "debug_uart.h"
#include "usart.h"

/* 单字符输出：覆盖 syscalls.c 里的弱符号 __io_putchar */
int __io_putchar(int ch)
{
  uint8_t c = (uint8_t)ch;
  HAL_UART_Transmit(&huart1, &c, 1U, 100U);
  return ch;
}

/* 批量输出：覆盖 syscalls.c 里的弱符号 _write。
 * GCC 的 printf 最终会走到这里，一次把整个缓冲区发出去，
 * 比逐字符调用 HAL_UART_Transmit 快很多。 */
int _write(int file, char *ptr, int len)
{
  (void)file;
  HAL_UART_Transmit(&huart1, (uint8_t *)ptr, (uint16_t)len, 1000U);
  return len;
}

void Debug_UART_Banner(const char *tag)
{
  printf("\r\n");
  printf("========================================\r\n");
  printf(" %s\r\n", tag);
  printf(" sysclk=%lu Hz, tick=%lu ms\r\n",
         (unsigned long)HAL_RCC_GetHCLKFreq(),
         (unsigned long)HAL_GetTick());
  printf("========================================\r\n");
}
