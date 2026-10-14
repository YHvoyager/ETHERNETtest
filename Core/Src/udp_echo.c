/**
 ******************************************************************************
 * @file    udp_echo.c
 * @brief   UDP 回环服务 —— 让网络调试助手看到 STM32 发回的信息
 *
 * 【工作原理】
 *   NO_SYS=1 的裸机 lwIP 里，收包的调用链是：
 *       MX_LWIP_Process() -> ethernetif_input() -> netif->input(=ethernet_input)
 *         -> ip4_input() -> udp_input() -> 我们注册的 recv 回调
 *   也就是说回调是在**主循环上下文**里被调用的，不是中断里。所以在回调里直接
 *   调用 udp_sendto() 是安全的（裸机 lwIP 的标准做法），不需要额外开线程或
 *   消息队列。这也是为什么这个文件只需要两个函数：Init 建 socket，回调干活。
 *
 * 【为什么用 udp_sendto 而不是复用收到的 pbuf】
 *   收到的 pbuf 是 RX_POOL 里的自定义 pbuf（HAL_ETH_RxAllocateCallback 分配的，
 *   见 ethernetif.c:611）。它归 DMA 接收环所有，生命周期由 pbuf_free 管理。虽然
 *   理论上能直接改个地址再发回去，但那样等于把接收缓冲借给发送路径，一旦 TX
 *   DMA 还没搬完而 RX 侧又把这块内存回收了，就是一次静默的数据损坏。这里选择
 *   老实用 pbuf_alloc + pbuf_take 拷一份出来发，慢一点点，但不会有内存别名的坑。
 *
 * 【校验和】
 *   lwipopts.h 里 CHECKSUM_BY_HARDWARE=1、CHECKSUM_GEN_UDP=0，所以 UDP 校验和
 *   由 STM32 的 ETH 外设硬件插入（TxConfig.Attributes 里的
 *   ETH_TX_PACKETS_FEATURES_CSUM，见 ethernetif.c:167）。lwIP 不填这个字段是
 *   预期行为，不要"顺手"把 CHECKSUM_GEN_UDP 打开，否则会和硬件重复计算。
 ******************************************************************************
 */

#include "udp_echo.h"

#include "lwip/udp.h"
#include "lwip/pbuf.h"
#include "lwip/ip_addr.h"
#include "lwip/netif.h"

#include "main.h"       /* HAL_GetTick() */

#include <stdio.h>
#include <string.h>

/* gnetif 定义在 LWIP/App/lwip.c（第 45 行 `struct netif gnetif;`），
 * 但 lwip.h 只 extern 了 heth，没有导出 gnetif —— 这里自己声明。
 * 注意必须和定义处完全一致（非 static 的全局 struct netif）。 */
extern struct netif gnetif;

/* ------------------------------------------------------------------------- */
/* 内部状态                                                                    */
/* ------------------------------------------------------------------------- */

/** 监听用的 UDP 控制块 */
static struct udp_pcb *s_echo_pcb = NULL;

/** 最近一次给板子发过包的 PC 的地址和端口 —— 心跳往这里发 */
static ip_addr_t s_last_peer_ip;
static u16_t     s_last_peer_port = 0U;

/** 是否已经有过至少一个来包（没有的话心跳不发，避免往 0.0.0.0 乱发） */
static uint8_t   s_have_peer = 0U;

/** 心跳节流 */
static uint32_t  s_last_beat_tick = 0U;

/** 收包计数，方便肉眼确认"到底收到没有" */
static uint32_t  s_rx_count = 0U;

/* ------------------------------------------------------------------------- */
/* 收包回调                                                                    */
/* ------------------------------------------------------------------------- */

/**
  * @brief  UDP 收到数据时被 lwIP 调用（主循环上下文）
  * @param  arg  udp_recv 注册时传进来的用户参数（这里没用）
  * @param  pcb  收到数据的那个控制块
  * @param  p    收到的数据（回调返回后必须由我们释放）
  * @param  addr 发送方 IP
  * @param  port 发送方端口
  */
static void udp_echo_recv(void *arg, struct udp_pcb *pcb, struct pbuf *p,
                          const ip_addr_t *addr, u16_t port)
{
  struct pbuf *tx = NULL;
  err_t err;

  (void)arg;

  if (p == NULL)
  {
    return;   /* lwIP 约定：p == NULL 表示这个 pcb 出错了，什么都不用做 */
  }

  /* 记住发信人，心跳要往这个地址发 */
  if (addr != NULL)
  {
    ip_addr_copy(s_last_peer_ip, *addr);
    s_last_peer_port = port;
    s_have_peer = 1U;
  }

  s_rx_count++;

  /* ---- 串口打印：让用户亲眼看到"板子收到了什么" ---- */
  printf("[UDP] #%lu recv %u byte(s) from %u.%u.%u.%u:%u\r\n",
         (unsigned long)s_rx_count,
         (unsigned int)p->tot_len,
         (unsigned int)ip4_addr1(ip_2_ip4(addr)),
         (unsigned int)ip4_addr2(ip_2_ip4(addr)),
         (unsigned int)ip4_addr3(ip_2_ip4(addr)),
         (unsigned int)ip4_addr4(ip_2_ip4(addr)),
         (unsigned int)port);

  if (p->tot_len > 0U)
  {
    /* 把内容按文本和十六进制两种形式打出来，方便核对 */
    uint8_t buf[128];
    u16_t n = pbuf_copy_partial(p, buf, sizeof(buf) - 1U, 0);
    u16_t i;

    buf[n] = '\0';
    /* 非可打印字符换成 '.'，免得终端被控制字符搞乱 */
    for (i = 0U; i < n; i++)
    {
      if (buf[i] < 0x20U || buf[i] > 0x7EU)
      {
        buf[i] = '.';
      }
    }
    printf("[UDP]     payload: \"%s\"\r\n", (char *)buf);

    printf("[UDP]     hex:");
    for (i = 0U; i < n && i < 32U; i++)
    {
      printf(" %02X", (unsigned int)buf[i]);
    }
    printf("\r\n");
  }

  /* ---- 原样回发 ---- */
  tx = pbuf_alloc(PBUF_TRANSPORT, p->tot_len, PBUF_POOL);
  if (tx == NULL)
  {
    printf("[UDP] WARN: pbuf_alloc failed, echo dropped\r\n");
    pbuf_free(p);
    return;
  }

  if (pbuf_take(tx, p->payload, p->tot_len) != ERR_OK)
  {
    printf("[UDP] WARN: pbuf_take failed, echo dropped\r\n");
    pbuf_free(tx);
    pbuf_free(p);
    return;
  }

  err = udp_sendto(pcb, tx, addr, port);
  if (err != ERR_OK)
  {
    printf("[UDP] WARN: udp_sendto failed (err=%d)\r\n", (int)err);
  }
  else
  {
    printf("[UDP]     echoed %u byte(s) back to %u.%u.%u.%u:%u\r\n",
           (unsigned int)tx->tot_len,
           (unsigned int)ip4_addr1(ip_2_ip4(addr)),
           (unsigned int)ip4_addr2(ip_2_ip4(addr)),
           (unsigned int)ip4_addr3(ip_2_ip4(addr)),
           (unsigned int)ip4_addr4(ip_2_ip4(addr)),
           (unsigned int)port);
  }

  pbuf_free(tx);   /* udp_sendto 已经把数据交给下层，拷贝语义下这里可以释放 */
  pbuf_free(p);    /* 收包必须由回调释放 */
}

/* ------------------------------------------------------------------------- */
/* 对外接口                                                                    */
/* ------------------------------------------------------------------------- */

int UDP_Echo_Init(void)
{
  ip_addr_t bind_addr;

  s_rx_count = 0U;
  s_have_peer = 0U;
  s_last_peer_port = 0U;
  s_last_beat_tick = HAL_GetTick();

  s_echo_pcb = udp_new();
  if (s_echo_pcb == NULL)
  {
    printf("[UDP] ERR: udp_new() failed (MEMP_NUM_UDP_PCB exhausted?)\r\n");
    return -1;
  }

  /* 绑定到 "任意本地地址"（0.0.0.0）。用 ip_addr_set_zero 而不是 ip_addr_set_any()：
   * 后者在 IPv6 编译开关不同的情况下展开成不同原型，zero 在这两种配置下都等价于
   * IP_ADDR_ANY，语义一样但没有条件编译的坑。 */
  ip_addr_set_zero(&bind_addr);

  if (udp_bind(s_echo_pcb, &bind_addr, (u16_t)UDP_ECHO_PORT) != ERR_OK)
  {
    printf("[UDP] ERR: udp_bind(port %u) failed\r\n", (unsigned int)UDP_ECHO_PORT);
    udp_remove(s_echo_pcb);
    s_echo_pcb = NULL;
    return -1;
  }

  udp_recv(s_echo_pcb, udp_echo_recv, NULL);

  printf("[UDP] echo server listening on 0.0.0.0:%u (board %u.%u.%u.%u)\r\n",
         (unsigned int)UDP_ECHO_PORT,
         (unsigned int)ip4_addr1(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr2(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr3(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr4(ip_2_ip4(&gnetif.ip_addr)));
  printf("[UDP] open NetAssist: UDP, target %u.%u.%u.%u:%u\r\n",
         (unsigned int)ip4_addr1(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr2(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr3(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr4(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)UDP_ECHO_PORT);

  return 0;
}

void UDP_Echo_Poll(void)
{
  /* 每秒往"最近一次来包的 PC"推一条心跳。
   *
   * 为什么要主动推：网络调试助手是"客户端发、看回应"的模式。如果板子只做
   * 被动回环，用户必须先在助手界面里手动发一条才能看到东西 —— 而如果他的
   * 目标端口填错、或者 Windows 防火墙把入站包拦了，界面就会一片空白，用户
   * 完全无从判断是"板子没收到"还是"回包被拦了"。主动心跳让板子先出声，
   * 一开机就能在助手里看到数据，链路方向立刻确认。 */
  if (s_have_peer == 0U || s_echo_pcb == NULL)
  {
    return;
  }

  if ((HAL_GetTick() - s_last_beat_tick) >= 1000U)
  {
    struct pbuf *p;
    char msg[64];
    int len;

    s_last_beat_tick = HAL_GetTick();

    len = snprintf(msg, sizeof(msg),
                   "STM32F429 alive, tick=%lu ms, rx=%lu\r\n",
                   (unsigned long)HAL_GetTick(),
                   (unsigned long)s_rx_count);
    if (len <= 0)
    {
      return;
    }

    p = pbuf_alloc(PBUF_TRANSPORT, (u16_t)len, PBUF_POOL);
    if (p == NULL)
    {
      return;
    }

    if (pbuf_take(p, msg, (u16_t)len) != ERR_OK)
    {
      pbuf_free(p);
      return;
    }

    (void)udp_sendto(s_echo_pcb, p, &s_last_peer_ip, s_last_peer_port);
    pbuf_free(p);
  }
}
