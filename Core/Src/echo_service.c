/**
 ******************************************************************************
 * @file    echo_service.c
 * @brief   带话术的 UDP 回声服务 —— 板子回答"我收到你的信息了，是 xxx 吗？"
 *
 * 【输出格式】
 *   我收到你的信息了，是"hello"吗？
 *
 *   引号用的是 ASCII 的 0x22（"），不是全角引号 —— 全角引号在 UTF-8 里是 3 字节，
 *   网络调试助手的编码设置稍有不对就会显示成乱码，ASCII 引号没有这个风险。
 *   句末用中文全角问号？(EF BC 9F) 并在后面补 \r\n。
 *
 * 【和 udp_echo.c 的关系】
 *   udp_echo.c 是哑回环（原样吐回），本文件是带话术的应答，二者功能重叠。
 *   默认只启用本模块（见 main.c），udp_echo.c 的 Init 保留但不再调用。
 *
 * 【收包上下文】
 *   NO_SYS=1 的裸机 lwIP 里，回调是在主循环上下文被调用的：
 *       MX_LWIP_Process() -> ethernetif_input() -> netif->input(=ethernet_input)
 *         -> ip4_input() -> udp_input() -> 本文件的 recv 回调
 *   所以回调里直接 udp_sendto() 是安全的，不需要线程/消息队列。
 *
 * 【校验和】
 *   lwipopts.h 里 CHECKSUM_BY_HARDWARE=1、CHECKSUM_GEN_UDP=0，UDP 校验和由 ETH
 *   外设硬件插入，lwIP 不填这个字段是预期行为。不要顺手打开 CHECKSUM_GEN_UDP。
 ******************************************************************************
 */

#include "echo_service.h"

#include "lwip/udp.h"
#include "lwip/pbuf.h"
#include "lwip/ip_addr.h"
#include "lwip/netif.h"

#include "main.h"       /* HAL_GetTick() */

#include <stdio.h>
#include <string.h>

/* gnetif 定义在 LWIP/App/lwip.c（`struct netif gnetif;`），lwip.h 没导出它，
 * 这里自己声明，类型必须和定义处完全一致。 */
extern struct netif gnetif;

/* ------------------------------------------------------------------------- */
/* 可调参数                                                                    */
/* ------------------------------------------------------------------------- */

/** 单条应答最多回显多少字节原文。整个应答缓冲是 512 字节，中文话术占约 50 字节，
 *  剩下的都留给原文，260 是个对中文（UTF-8 一个汉字 3 字节）也比较宽松的值。
 *
 *  注意：绝对不能把收到的原始字节"硬截断"到这个长度 —— 中文一个字 3 字节，
 *  从中间砍断会产生非法的 UTF-8 序列，显示出来就是乱码或替换符。正确做法是先
 *  按字节收下来（见 s_rx_raw），再回退到最后一个**完整字符**的边界。 */
#define ECHO_MAX_PAYLOAD    260U

/** 应答缓冲总大小（静态分配，不占栈）。512 在 RAM 里很便宜，留足余量。 */
#define ECHO_TX_BUF_SIZE    512U

/** 心跳间隔 */
#define ECHO_BEAT_INTERVAL  1000U

/* ------------------------------------------------------------------------- */
/* 内部状态                                                                    */
/* ------------------------------------------------------------------------- */

/** 监听用的 UDP 控制块 */
static struct udp_pcb *s_pcb = NULL;

/** 最近一次给板子发过包的 PC 地址和端口 —— 心跳往这里发 */
static ip_addr_t s_peer_ip;
static u16_t     s_peer_port = 0U;
static uint8_t   s_have_peer = 0U;

/** 心跳节流 */
static uint32_t  s_last_beat_tick = 0U;

/** 收包计数，方便肉眼确认"到底收到没有" */
static uint32_t  s_rx_count = 0U;

/**
 * 组包用的缓冲。
 *
 * 【为什么是 static 而不是栈上的局部数组】
 *   默认 512 字节，STM32F429 的栈是 0x400 = 1024 字节（见 startup_stm32f429xx.s），
 *   在回调里放一个 512 字节的局部数组等于用掉半个栈 —— 加上 printf 的调用深度就
 *   危险了。这个缓冲只在主循环上下文被使用，不存在重入，做成 static 是安全的。
 */
static char s_tx_buf[ECHO_TX_BUF_SIZE];

/**
 * 存放收到的原始字节的缓冲（static，理由同上）。
 *
 * 为什么需要它：收到的包可能比 ECHO_MAX_PAYLOAD 长，而我们要在截断之后仍然能
 * 判断"截断点是不是落在了一个 UTF-8 字符的中间"。先把原始字节完整收进来（到
 * 这个缓冲的上限为止），再对**副本**做截断和过滤，就不会破坏原始数据。
 * 比 ECHO_MAX_PAYLOAD 多留 3 字节，刚好够判断最后一个字符是否需要整段回退。
 */
static char s_rx_raw[ECHO_MAX_PAYLOAD + 4U];

/**
 * 找出 [0, len) 范围内最后一个完整 UTF-8 字符的结束位置。
 *
 * @param  s   字节流
 * @param  len 已有字节数
 * @retval 可以安全输出的字节数（不含任何被截断的半个字符）
 *
 * 判据：从开头扫描，按首字节决定该字符的长度
 *   0x00~0x7F -> 1 字节，0xC0~0xDF -> 2 字节，0xE0~0xEF -> 3 字节，0xF0~0xF7 -> 4 字节。
 * 一旦某个字符的长度超出 len，就丢掉这个不完整的字符（以及它之后的所有内容）。
 * 遇到非法首字节（0x80~0xBF 的裸续字节、0xF8~0xFF）按 1 字节跳过，让它们原样
 * 透传 —— 那是发送端的编码问题，不该由我们悄悄改写。
 */
static size_t utf8_trim_incomplete(const char *s, size_t len)
{
  size_t i = 0U;

  while (i < len)
  {
    unsigned char c = (unsigned char)s[i];
    size_t need;

    if (c < 0x80U)        { need = 1U; }
    else if (c < 0xC0U)   { need = 1U; }   /* 裸续字节，当 1 字节放过 */
    else if (c < 0xE0U)   { need = 2U; }
    else if (c < 0xF0U)   { need = 3U; }
    else if (c < 0xF8U)   { need = 4U; }
    else                  { need = 1U; }   /* 非法首字节，当 1 字节放过 */

    if ((i + need) > len)
    {
      break;                              /* 这个字符被截断了，整个丢掉 */
    }
    i += need;
  }

  return i;
}

/* ------------------------------------------------------------------------- */
/* 工具函数                                                                    */
/* ------------------------------------------------------------------------- */

/**
  * @brief  把 payload 里的控制字符替换成 '.'
  * @param  s   要就地处理的字符串
  * @param  len 字符数
  * @note   只过滤 < 0x20 的控制字符（\n \r \t 以及各种转义序列），它们会把网络
  *         调试助手的显示搞乱。
  *
  *         **0x7F 及以上的字节原样保留** —— UTF-8 汉字是 3 个字节、每个都 >= 0x80，
  *         按 "> 0x7E 就换成 '.'" 的老写法会把中文整个打成点，这正是之前"回显不出
  *         中文"的原因。非 UTF-8 的编码（如 GBK）通过这里时不会被改，仍会显示成
  *         乱码 —— 那是发送端编码的问题，见 udp_echo.c 里的原始字节十六进制转储。
  */
static void sanitize_inplace(char *s, size_t len)
{
  size_t i;

  for (i = 0U; i < len; i++)
  {
    unsigned char c = (unsigned char)s[i];

    if (c < 0x20U)
    {
      s[i] = '.';
    }
  }
}

/**
  * @brief  把一条消息发到指定 peer
  * @retval 0 = 成功，-1 = 组包或发送失败
  */
static int send_to_peer(const char *msg, size_t len)
{
  struct pbuf *p;
  err_t err;

  if (s_pcb == NULL || s_have_peer == 0U || len == 0U)
  {
    return -1;
  }

  /* 截断保护：一条 UDP 报文超过底层能承载的长度会直接发失败 */
  if (len > (size_t)ECHO_TX_BUF_SIZE)
  {
    len = (size_t)ECHO_TX_BUF_SIZE;
  }

  p = pbuf_alloc(PBUF_TRANSPORT, (u16_t)len, PBUF_POOL);
  if (p == NULL)
  {
    printf("[ECHO] WARN: pbuf_alloc(%u) failed\r\n", (unsigned int)len);
    return -1;
  }

  if (pbuf_take(p, msg, (u16_t)len) != ERR_OK)
  {
    printf("[ECHO] WARN: pbuf_take failed\r\n");
    pbuf_free(p);
    return -1;
  }

  err = udp_sendto(s_pcb, p, &s_peer_ip, s_peer_port);
  pbuf_free(p);   /* 本工程用拷贝语义，交给下层之后这里可以释放 */

  if (err != ERR_OK)
  {
    printf("[ECHO] WARN: udp_sendto failed (err=%d)\r\n", (int)err);
    return -1;
  }

  return 0;
}

/* ------------------------------------------------------------------------- */
/* 收包回调                                                                    */
/* ------------------------------------------------------------------------- */

/**
  * @brief  UDP 收到数据时被 lwIP 调用（主循环上下文）
  * @param  arg  udp_recv 注册时传进来的用户参数（这里没用）
  * @param  pcb  收到数据的那个控制块
  * @param  p    收到的数据（回调返回前必须由我们释放）
  * @param  addr 发送方 IP
  * @param  port 发送方端口
  */
static void echo_recv(void *arg, struct udp_pcb *pcb, struct pbuf *p,
                      const ip_addr_t *addr, u16_t port)
{
  char   *text;
  u16_t  copy_len;
  u16_t  full_len;
  int    n;

  (void)arg;

  /* lwIP 约定：p == NULL 表示这个 pcb 出错了，什么都不用做 */
  if (p == NULL)
  {
    return;
  }

  /* 没有源地址就没法回，直接丢掉（正常路径不会走到这里） */
  if (addr == NULL)
  {
    pbuf_free(p);
    return;
  }

  /* 记住发信人，心跳和应答都往这里回 */
  ip_addr_copy(s_peer_ip, *addr);
  s_peer_port = port;
  s_have_peer = 1U;
  s_rx_count++;

  /* ---- 1. 取出原文 ----
   * 先把原始字节完整收到 s_rx_raw（static，不占栈）。这里按 ECHO_MAX_PAYLOAD + 3
   * 收，多出来的 3 字节是用来判断"最后一个字符有没有被砍断"的。
   * 注意：这一步**不做任何截断判断**，原样收下来。 */
  copy_len = pbuf_copy_partial(p, s_rx_raw, (u16_t)(ECHO_MAX_PAYLOAD + 3U), 0);
  s_rx_raw[copy_len] = '\0';

  /* ---- 2. 决定能安全输出多少字节 ---- */
  if (copy_len <= (u16_t)ECHO_MAX_PAYLOAD)
  {
    /* 整包都在限长之内，不会截断任何字符 */
    full_len = copy_len;
  }
  else
  {
    /* 超长了：截到 ECHO_MAX_PAYLOAD，再回退掉可能被砍断的半个字符。
     * 这一步就是"中文不变成乱码"的关键 —— 硬截断会把 3 字节的汉字砍成 1~2 字节，
     * 那不是合法 UTF-8，助手只能显示成替换符。 */
    full_len = (u16_t)utf8_trim_incomplete(s_rx_raw, (size_t)ECHO_MAX_PAYLOAD);
  }
  s_rx_raw[full_len] = '\0';

  /* ---- 3. 过滤控制字符（0x7F 及以上原样保留，中文才出得来） ---- */
  {
    u16_t i;
    for (i = 0U; i < full_len; i++)
    {
      if (s_rx_raw[i] == '\0')
      {
        s_rx_raw[i] = '.';   /* 内嵌 \0 会让 strlen 提前结束，先替掉 */
      }
    }
  }
  sanitize_inplace(s_rx_raw, (size_t)full_len);

  text = s_rx_raw;

  /* ---- 4. 组装中文应答 ---- */
  n = snprintf(s_tx_buf, sizeof(s_tx_buf),
               "\xE6\x88\x91\xE6\x94\xB6\xE5\x88\xB0\xE4\xBD\xA0\xE7\x9A\x84"
               "\xE4\xBF\xA1\xE6\x81\xAF\xE4\xBA\x86\xEF\xBC\x8C\xE6\x98\xAF"
               "\"%s\"\xE5\x90\x97\xEF\xBC\x9F\r\n",
               text);
  if (n <= 0)
  {
    pbuf_free(p);
    return;
  }
  if ((size_t)n >= sizeof(s_tx_buf))
  {
    n = (int)sizeof(s_tx_buf) - 1;   /* snprintf 被截断时返回的是"本该写多少" */
  }

  /* ---- 4. 串口打印，方便对照 ---- */
  printf("[ECHO] #%lu recv %u byte(s) from %u.%u.%u.%u:%u\r\n",
         (unsigned long)s_rx_count,
         (unsigned int)p->tot_len,
         (unsigned int)ip4_addr1(ip_2_ip4(addr)),
         (unsigned int)ip4_addr2(ip_2_ip4(addr)),
         (unsigned int)ip4_addr3(ip_2_ip4(addr)),
         (unsigned int)ip4_addr4(ip_2_ip4(addr)),
         (unsigned int)port);
  printf("[ECHO]     payload: \"%s\"\r\n", text);
  printf("[ECHO]     reply  : %s", s_tx_buf);
  if (p->tot_len > full_len)
  {
    printf("[ECHO]     note: payload %u bytes, echoed first %u byte(s)%s\r\n",
           (unsigned int)p->tot_len, (unsigned int)full_len,
           (full_len < copy_len) ? " (trimmed back to a character boundary)" : "");
  }

  /* ---- 5. 发回去 ---- */
  (void)send_to_peer(s_tx_buf, (size_t)n);

  /* 收包必须由回调释放 */
  pbuf_free(p);
}

/* ------------------------------------------------------------------------- */
/* 对外接口                                                                    */
/* ------------------------------------------------------------------------- */

int Echo_Service_Init(void)
{
  ip_addr_t bind_addr;

  s_rx_count = 0U;
  s_have_peer = 0U;
  s_peer_port = 0U;
  s_last_beat_tick = HAL_GetTick();

  s_pcb = udp_new();
  if (s_pcb == NULL)
  {
    printf("[ECHO] ERR: udp_new() failed (MEMP_NUM_UDP_PCB exhausted?)\r\n");
    return -1;
  }

  /* 绑定到 "任意本地地址"（0.0.0.0）。用 ip_addr_set_zero 而不是 ip_addr_set_any()：
   * 后者在 IPv6 编译开关不同时展开成不同原型，zero 在两种配置下都等价于
   * IP_ADDR_ANY，语义一样但没有条件编译的坑。 */
  ip_addr_set_zero(&bind_addr);

  if (udp_bind(s_pcb, &bind_addr, (u16_t)ECHO_SERVICE_PORT) != ERR_OK)
  {
    printf("[ECHO] ERR: udp_bind(port %u) failed -- port already in use?\r\n",
           (unsigned int)ECHO_SERVICE_PORT);
    udp_remove(s_pcb);
    s_pcb = NULL;
    return -1;
  }

  udp_recv(s_pcb, echo_recv, NULL);

  printf("[ECHO] service listening on 0.0.0.0:%u (board %u.%u.%u.%u)\r\n",
         (unsigned int)ECHO_SERVICE_PORT,
         (unsigned int)ip4_addr1(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr2(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr3(ip_2_ip4(&gnetif.ip_addr)),
         (unsigned int)ip4_addr4(ip_2_ip4(&gnetif.ip_addr)));
  printf("[ECHO] send anything, board replies: \"...\" is what I got\r\n");

  return 0;
}

void Echo_Service_Poll(void)
{
  int n;

  /* 和 udp_echo.c 里一样：没有 peer 就不发，避免往 0.0.0.0 乱发。
   * 主动推心跳的理由见 udp_echo.c 的注释 —— 助手界面先出声，用户才好判断
   * 到底是"板子没收到"还是"回包被防火墙拦了"。 */
  if (s_have_peer == 0U || s_pcb == NULL)
  {
    return;
  }

  if ((HAL_GetTick() - s_last_beat_tick) >= ECHO_BEAT_INTERVAL)
  {
    s_last_beat_tick = HAL_GetTick();

    /* 心跳也用中文，保持界面风格一致 */
    n = snprintf(s_tx_buf, sizeof(s_tx_buf),
                 "STM32F429 \xE5\x9C\xA8\xE7\xBA\xBF\xEF\xBC\x8C"      /* 在线， */
                 "\xE5\xB7\xB2\xE6\x94\xB6 %lu \xE6\x9D\xA1\r\n",       /* 已收 N 条 */
                 (unsigned long)s_rx_count);
    if (n > 0)
    {
      if ((size_t)n >= sizeof(s_tx_buf))
      {
        n = (int)sizeof(s_tx_buf) - 1;
      }
      (void)send_to_peer(s_tx_buf, (size_t)n);
    }
  }
}
