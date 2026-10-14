/**
 ******************************************************************************
 * @file    udp_echo.h
 * @brief   UDP 回环服务 —— 让网络调试助手看到 STM32 发回的信息
 *
 * 用法：
 *   1) MX_LWIP_Init() 之后调用 UDP_Echo_Init();
 *   2) while(1) 里调用 UDP_Echo_Poll()（和 MX_LWIP_Process() 并排）
 *   3) PC 上网络调试助手：UDP，本地端口随意，目标 IP 192.168.1.30，目标端口 8080
 *      发什么都原样收回来；另外板子每秒主动推一条心跳（发给最近一次来包的 PC）。
 ******************************************************************************
 */
#ifndef __UDP_ECHO_H
#define __UDP_ECHO_H

#include "lwip/err.h"

/* 板子监听的 UDP 端口 */
#define UDP_ECHO_PORT   8080U

/**
  * @brief  创建并绑定 UDP 回环 socket
  * @note   必须在 MX_LWIP_Init() 之后调用（netif 要先起来）
  * @retval 0 = 成功，-1 = 失败
  */
int UDP_Echo_Init(void);

/**
  * @brief  周期性任务：向"最近一次给板子发过包的 PC"推送心跳
  * @note   放 while(1) 里，非阻塞，内部自己做 1 秒节流
  */
void UDP_Echo_Poll(void);

#endif /* __UDP_ECHO_H */
