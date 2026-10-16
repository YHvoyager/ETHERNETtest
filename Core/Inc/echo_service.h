/**
 ******************************************************************************
 * @file    echo_service.h
 * @brief   带话术的 UDP 回声服务 —— 板子用中文回答"我收到你的信息了，是 xxx 吗？"
 *
 * 【和 udp_echo.c 的区别】
 *   udp_echo.c  是"哑回环"：把收到的字节原样吐回去，用来验证链路。
 *   本文件是"会说话的回环"：按固定话术组装一条中文应答，便于人肉核对内容。
 *   两者是独立的 UDP 服务，只是**不能同时占用同一个端口**（见下面 PORT 说明），
 *   所以调用上二选一，默认用本模块。
 *
 * 用法：
 *   1) MX_LWIP_Init() 之后调用 Echo_Service_Init();
 *   2) while(1) 里调用 Echo_Service_Poll()（和 MX_LWIP_Process() 并排）
 *   3) PC 网络调试助手：UDP，目标 192.168.1.30:8080，
 *      发 "hello" 收到 → 我收到你的信息了，是"hello"吗？
 ******************************************************************************
 */
#ifndef __ECHO_SERVICE_H
#define __ECHO_SERVICE_H

#include <stdint.h>

/**
 * 板子监听的 UDP 端口。
 *
 * 注意：如果同时启用 udp_echo.c 和本模块，**必须让两者用不同端口**，
 * 因为一个 UDP 端口只能被一个 pcb 绑定（第二个 udp_bind 返回 ERR_USE）。
 * 默认沿用原来的 8080，让网络调试助手的配置不用改。
 */
#ifndef ECHO_SERVICE_PORT
#define ECHO_SERVICE_PORT   8080U
#endif

/**
  * @brief  创建并绑定回声服务的 UDP socket
  * @note   必须在 MX_LWIP_Init() 之后调用（netif 要先 add/up，udp_bind 才有意义）
  * @retval 0 = 成功，-1 = 失败
  */
int Echo_Service_Init(void);

/**
  * @brief  周期性任务：向"最近一次给板子发过包的 PC"推送心跳
  * @note   放 while(1) 里，非阻塞，内部自己做 1 秒节流
  */
void Echo_Service_Poll(void);

#endif /* __ECHO_SERVICE_H */
