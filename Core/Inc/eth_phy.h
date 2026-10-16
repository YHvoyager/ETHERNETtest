/**
  ******************************************************************************
  * @file    eth_phy.h
  * @brief   阿波罗V2（STM32F429 + YT8512C）以太网的板级补丁
  *
  * CubeMX 生成的 lwIP 工程在正点原子阿波罗V2 上跑不起来，缺三块东西，
  * 全部集中在这里：
  *   1) HAL_ETH_MspInit()  —— HAL 库是 __weak 空函数，没人配 RMII 引脚和 ETH 时钟
  *   2) ETH_PHY_ReleaseReset() —— ETH_RESET 挂在 PCF8574 的 P7 上，不释放 PHY 不工作
  *   3) ETH_PHY_Prepare()  —— MDC 时钟分频 + 强制自协商，必须在任何 MDIO 访问前做
  *
  * 详细原理见 docs/lwip-f429-apollo-v2.md。
  ******************************************************************************
  */

#ifndef __ETH_PHY_H
#define __ETH_PHY_H

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"

/* PHY 复位控制（PCF8574 P7）。返回 0 成功，负数为失败阶段。
 * 必须在 MX_LWIP_Init() 之前调用。 */
int ETH_PHY_ReleaseReset(void);

/* MDC 时钟分频 + 保证自协商打开。必须在 HAL_ETH_Init() 之后、
 * 任何 HAL_ETH_ReadPHYRegister() 之前调用（ethernetif.c 的 low_level_init 里）。 */
void ETH_PHY_Prepare(void);

/* 链路检测：读 BSR 判链路，据此调 netif_set_link_up/down()。
 *
 * 【为什么这个函数在这里而不是在 ethernetif.c 里】
 * CubeMX 生成的 ethernetif.c 里有个空的 ethernet_link_check_state()，函数体
 * 不在 USER CODE 区内，每次重新生成都被清空 —— 已经丢过两次。丢了以后
 * netif_set_link_up() 永远不会被调用，netif 的 NETIF_FLAG_LINK_UP 恒为 0
 * （netif_init() 里是 netif->flags = 0），于是 ip4_route() 找不到出口网卡，
 * udp_sendto() 一律返回 ERR_RTE(-4)：表现为"能收不能发"（PC 的命令能到达
 * 并执行，但板子的回包和心跳全发不出去）。
 *
 * 所以实现放在本文件（CubeMX 不生成、永不覆盖），ethernetif.c 里只留一行
 * ETH_PHY_CheckLink(netif); —— 就算再被清掉，丢的也只是一行，一眼能看出。
 *
 * 由 ethernetif.c 的 ethernet_link_check_state() 每 100ms 调一次
 * （LWIP/App/lwip.c 的 Ethernet_Link_Periodic_Handle）。 */
struct netif;
void ETH_PHY_CheckLink(struct netif *netif);

/* 一次性打印 PHY 的 ID / BCR / BSR，用于确认物理层是否真的活着。
 * 不需要时把 ETH_PHY_DIAG 定义为 0 即可。 */
#define ETH_PHY_DIAG 1
#if ETH_PHY_DIAG
void ETH_PHY_Dump(void);
#endif

#ifdef __cplusplus
}
#endif

#endif /* __ETH_PHY_H */
