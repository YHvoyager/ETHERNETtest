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
#include <stddef.h>
#include "lwip/ip_addr.h"

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

/**
  * @brief  以某个端口为订阅目标：开启后，大帧会同时发到这里
  * @param  ip    订阅方 IP（一般是发命令那台 PC）
  * @param  port  订阅方端口
  * @retval 0 = 成功，-1 = 参数非法
  *
  * @note   让 PC 可以用**两个 socket**：一个命令 socket（发命令、
  *         收短应答），一个数据 socket（只收光栅帧）。抓包和编码
  *         调试都会清楚很多。发 `BROADCAST <port>` 即可开启。
  *         传 port = 0 关闭。
  */
int Echo_Service_SetBroadcast(const ip_addr_t *ip, uint16_t port);

/**
  * @brief  把一条文本应答发回给"最后来包的那台 PC"
  * @retval 0 = 成功，-1 = 失败
  *
  * 给命令处理函数用（如 `PING` → `PONG`），这样命令实现不需要知道 peer 是谁。
  * len 上限 ECHO_TX_BUF_SIZE（512）。
  */
int Echo_Service_Reply(const char *msg, size_t len);

/**
  * @brief  回一段二进制数据（不做字符串假设）
  * @note   和 Echo_Service_Reply 一样走 send_to_peer，只是语义更明确。
  */
int Echo_Service_ReplyRaw(const void *data, size_t len);

/**
  * @brief  大帧回包：同时发给"命令来源"和 BROADCAST 订阅端口
  * @note   给 OLED 全屏位图这类 1KB 级数据用，见 .c 里的说明。
  *         **不受 ECHO_TX_BUF_SIZE（512）限制** —— 直接走 send_raw()，
  *         上限是单个 UDP 报文（65535 字节，实际还受 PBUF_POOL 约束）。
  */
int Echo_Service_ReplyBoth(const void *data, size_t len);

/**
  * @brief  把数据切成 mtu 大小的片，逐片发回给最后来包的那台 PC
  * @param  mtu  每片最大字节数（建议 ≤ 1000，留出头空间）
  * @retval 0 = 全部发完，-1 = 中途失败
  *
  * @note   只给"必须完整送达"的场景用。UDP 本身不保证顺序和到达，
  *         分片只是把"整条丢"变成"丢一片"，并没有解决可靠性。
  */
int Echo_Service_ReplyChunked(const uint8_t *data, size_t len, uint16_t mtu);

#endif /* __ECHO_SERVICE_H */
