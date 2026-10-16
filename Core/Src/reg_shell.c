/**
  ******************************************************************************
  * @file    reg_shell.c
  * @brief   以太网命令解析 —— 见 reg_shell.h
  ******************************************************************************
  */

#include "reg_shell.h"
#include "board_io.h"
#include "main.h"

#include <stdio.h>
#include <string.h>

/* gnetif 定义在 LWIP/App/lwip.c，lwip.h 没导出它 */
#include "lwip/netif.h"
#include "lwip/ip_addr.h"
extern struct netif gnetif;

/* ------------------------------------------------------------------------- */
/* 可调参数                                                                    */
/* ------------------------------------------------------------------------- */

/** 一行命令最多多少字符，超出直接拒绝（防止畸形输入被逐字节解析） */
#define SHELL_MAX_LINE      192U

/** 一行命令最多几个 token */
#define SHELL_MAX_TOKEN     8U

/* ------------------------------------------------------------------------- */
/* 地址白名单                                                                  */
/* ------------------------------------------------------------------------- */

#define REG_ADDR_PERIPH_LO   0x40000000UL
#define REG_ADDR_PERIPH_HI   0x5FFFFFFFUL
#define REG_ADDR_SRAM_LO     0x20000000UL
#define REG_ADDR_SRAM_HI     0x2002FFFFUL   /* F429IGT6: 192KB 主 SRAM */
#define REG_ADDR_CCM_LO      0x10000000UL
#define REG_ADDR_CCM_HI      0x1000FFFFUL   /* 64KB CCM */

/**
  * @brief  判断地址是否可以访问
  * @retval 0 = 拒绝，1 = 允许
  *
  * 明确**不放行** 0x00000000~0x1FFFFFFF：那是 Flash 和它的别名区，
  * 写进去要么没反应要么触发总线错误，是"手滑必死"的地址。
  */
static int addr_allowed(uint32_t addr)
{
  /* 4 字节对齐：非对齐访问在 Cortex-M4 上对某些外设寄存器会直接 BusFault */
  if ((addr & 0x3UL) != 0UL)
  {
    return 0;
  }

  if ((addr >= REG_ADDR_PERIPH_LO) && (addr <= REG_ADDR_PERIPH_HI)) { return 1; }
  if ((addr >= REG_ADDR_SRAM_LO)   && (addr <= REG_ADDR_SRAM_HI))   { return 1; }
  if ((addr >= REG_ADDR_CCM_LO)    && (addr <= REG_ADDR_CCM_HI))    { return 1; }

  return 0;
}

/** 8 位访问不要求 4 字节对齐，但仍然只允许落在白名单区内 */
static int addr_allowed_byte(uint32_t addr)
{
  if ((addr >= REG_ADDR_PERIPH_LO) && (addr <= REG_ADDR_PERIPH_HI)) { return 1; }
  if ((addr >= REG_ADDR_SRAM_LO)   && (addr <= REG_ADDR_SRAM_HI))   { return 1; }
  if ((addr >= REG_ADDR_CCM_LO)    && (addr <= REG_ADDR_CCM_HI))    { return 1; }

  return 0;
}

/* ------------------------------------------------------------------------- */
/* 解析工具                                                                    */
/* ------------------------------------------------------------------------- */

/**
  * @brief  十六进制字符串 → uint32（不依赖 strtoul，避免 newlib 的 locale 逻辑）
  * @retval 1 = 解析成功并至少有一个数字；0 = 失败
  */
static int parse_hex(const char *s, uint32_t *out)
{
  uint32_t v = 0UL;
  uint32_t digits = 0UL;

  if (s == NULL)
  {
    return 0;
  }

  if ((s[0] == '0') && ((s[1] == 'x') || (s[1] == 'X')))
  {
    s += 2;
  }

  while (*s != '\0')
  {
    char c = *s;
    uint32_t d;

    if      ((c >= '0') && (c <= '9')) { d = (uint32_t)(c - '0'); }
    else if ((c >= 'a') && (c <= 'f')) { d = (uint32_t)(c - 'a' + 10); }
    else if ((c >= 'A') && (c <= 'F')) { d = (uint32_t)(c - 'A' + 10); }
    else { return 0; }                    /* 混进非法字符就整体拒绝 */

    if (v > 0x0FFFFFFFUL)                 /* 再左移 4 位就溢出了 */
    {
      return 0;
    }

    v = (v << 4) | d;
    digits++;
    s++;
  }

  if (digits == 0UL)
  {
    return 0;
  }

  *out = v;
  return 1;
}

/**
  * @brief  十进制字符串 → uint32
  */
static int parse_dec(const char *s, uint32_t *out)
{
  uint32_t v = 0UL;
  uint32_t digits = 0UL;

  if (s == NULL)
  {
    return 0;
  }

  while (*s != '\0')
  {
    char c = *s;

    if ((c < '0') || (c > '9'))
    {
      return 0;
    }
    if (v > 429496729UL)
    {
      return 0;
    }

    v = (v * 10UL) + (uint32_t)(c - '0');
    digits++;
    s++;
  }

  if (digits == 0UL)
  {
    return 0;
  }

  *out = v;
  return 1;
}

/**
  * @brief  字符串转大写（就地），便于关键字不区分大小写
  */
static void upper_inplace(char *s)
{
  while (*s != '\0')
  {
    if ((*s >= 'a') && (*s <= 'z'))
    {
      *s = (char)(*s - 'a' + 'A');
    }
    s++;
  }
}

/**
  * @brief  把一行命令切成最多 SHELL_MAX_TOKEN 个 token
  * @note   分隔符：空格、\t、\r、\n。就地写 '\0'，所以入参必须可写。
  * @retval token 个数
  */
static uint32_t tokenize(char *line, char *tok[], uint32_t max_tok)
{
  uint32_t n = 0UL;
  char    *p = line;

  while ((*p != '\0') && (n < max_tok))
  {
    /* 跳过空白 */
    while ((*p == ' ') || (*p == '\t') || (*p == '\r') || (*p == '\n'))
    {
      p++;
    }
    if (*p == '\0')
    {
      break;
    }

    tok[n++] = p;

    /* 找到 token 结尾并截断 */
    while ((*p != '\0') && (*p != ' ') && (*p != '\t') &&
           (*p != '\r') && (*p != '\n'))
    {
      p++;
    }
    if (*p != '\0')
    {
      *p = '\0';
      p++;
    }
  }

  return n;
}

/* ------------------------------------------------------------------------- */
/* 命令实现                                                                    */
/* ------------------------------------------------------------------------- */

static const char *const s_help_text =
  "commands (case-insensitive, value optional = toggle):\r\n"
  "  HELP               this text\r\n"
  "  IO                 list registered board IO\r\n"
  "  INFO               board status\r\n"
  "  LED <n> [0|1|T]    LED n: 0=off 1=on T=toggle (default). LED 0=DS0/PB0, 1=DS1/PB1\r\n"
  "  IO <id> [0|1|T]    same, by board IO id\r\n"
  "  LED0 / DS1 [0|1|T] compact form, same thing\r\n"
  "  R <addr>           read 32-bit register, addr hex  (R 40020014 = GPIOB_ODR)\r\n"
  "  W <addr> <val>     write 32-bit register, hex\r\n"
  "  RB <addr>          read one byte\r\n"
  "  WB <addr> <val>    write one byte\r\n"
  "examples: LED0  |  LED 1 1  |  W 40020014 3  |  R 40020014\r\n";

const char *Reg_Shell_Help(void)
{
  return s_help_text;
}

/**
  * @brief  "IO <id> <0|1|T>" / "LED <n> <0|1|T>" 的公共实现
  */
static int cmd_io_op(uint32_t id, const char *op, char *out, uint32_t out_size)
{
  int n;

  if (Board_IO_Name(id) == NULL)
  {
    n = snprintf(out, (size_t)out_size,
                 "ERR: IO id %u out of range (0..%u)\r\n",
                 (unsigned int)id,
                 (unsigned int)(Board_IO_Count() - 1U));
    return (n < 0) ? -1 : -1;
  }

  if ((op[0] == '0') && (op[1] == '\0'))
  {
    (void)Board_IO_Set(id, 0U);
    n = snprintf(out, (size_t)out_size, "OK IO %u (%s) = OFF\r\n",
                 (unsigned int)id, Board_IO_Name(id));
  }
  else if ((op[0] == '1') && (op[1] == '\0'))
  {
    (void)Board_IO_Set(id, 1U);
    n = snprintf(out, (size_t)out_size, "OK IO %u (%s) = ON\r\n",
                 (unsigned int)id, Board_IO_Name(id));
  }
  else if (((op[0] == 'T') || (op[0] == 't')) && (op[1] == '\0'))
  {
    (void)Board_IO_Toggle(id);
    n = snprintf(out, (size_t)out_size, "OK IO %u (%s) = %s (toggled)\r\n",
                 (unsigned int)id, Board_IO_Name(id),
                 (Board_IO_Get((uint32_t)id) == 1) ? "ON" : "OFF");
  }
  else
  {
    n = snprintf(out, (size_t)out_size,
                 "ERR: bad value '%s', use 0 / 1 / T\r\n", op);
    return (n < 0) ? -1 : -1;
  }

  return (n < 0) ? -1 : 1;
}

static int cmd_io_list(char *out, uint32_t out_size)
{
  uint32_t i;
  uint32_t used = 0UL;
  int      n;

  for (i = 0UL; i < Board_IO_Count(); i++)
  {
    if (used >= (uint32_t)out_size)
    {
      break;
    }

    n = Board_IO_Describe(i, out + used, out_size - used);
    if (n <= 0)
    {
      break;
    }
    used += (uint32_t)n;
  }

  if (used < 2UL)
  {
    (void)snprintf(out, (size_t)out_size, "ERR: no IO registered\r\n");
    return -1;
  }

  return 1;
}

/**
  * @brief  把 "LED0" / "DS1" 这类紧凑写法拆成名字和数字
  * @param  tok   输入 token，**会被就地改写**（在字母和数字之间插 '\0'）
  * @param  name  输出：名字部分（指向 tok 内部）
  * @param  num   输出：数字部分（必须是纯数字，非空）
  * @retval 1 = 拆分成功，0 = 不是这种形式
  *
  * 为什么要做这个：网络调试助手上手敲 "LED0"、"DS1" 比 "LED 0 1" 自然得多，
  * 而严格按空格分词会把 "LED0" 判成"不认识的关键字"→ 走中文回声，
  * 用户看到的是"我收到你的信息了，是 LED0 吗？"，非常困惑（实测踩过）。
  */
static int split_name_num(char *tok, char **name, char **num)
{
  char *p = tok;

  /* 名字部分：至少一个字母 */
  while (((*p >= 'A') && (*p <= 'Z')) || ((*p >= 'a') && (*p <= 'z')))
  {
    p++;
  }
  if (p == tok)
  {
    return 0;
  }

  /* 数字部分：至少一位数字 */
  if ((*p < '0') || (*p > '9'))
  {
    return 0;
  }

  *name = tok;
  *num  = p;
  *p    = '\0';      /* 就地切开 */

  /* 数字部分必须全是数字 */
  {
    char *q = p + 1;
    while ((*q >= '0') && (*q <= '9'))
    {
      q++;
    }
    if (*q != '\0')
    {
      return 0;      /* 后面还有别的字符，不是紧凑写法 */
    }
  }

  return 1;
}

static int cmd_info(char *out, uint32_t out_size)
{
  int n;

  n = snprintf(out, (size_t)out_size,
               "board 192.168.1.30  tick=%lu ms  io_count=%u\r\n",
               (unsigned long)HAL_GetTick(),
               (unsigned int)Board_IO_Count());
  return (n < 0) ? -1 : 1;
}

static int cmd_read(uint32_t addr, int is_byte, char *out, uint32_t out_size)
{
  int n;

  if (is_byte != 0)
  {
    if (addr_allowed_byte(addr) == 0)
    {
      n = snprintf(out, (size_t)out_size,
                   "ERR: address 0x%08lX not allowed (byte)\r\n",
                   (unsigned long)addr);
      return -1;
    }

    {
      volatile uint8_t *p = (volatile uint8_t *)addr;
      n = snprintf(out, (size_t)out_size, "OK RB 0x%08lX = 0x%02X\r\n",
                   (unsigned long)addr, (unsigned int)(*p));
    }
    return (n < 0) ? -1 : 1;
  }

  if (addr_allowed(addr) == 0)
  {
    n = snprintf(out, (size_t)out_size,
                 "ERR: address 0x%08lX not allowed (need word-aligned, "
                 "periph 0x40000000-0x5FFFFFFF / SRAM / CCM)\r\n",
                 (unsigned long)addr);
    return -1;
  }

  {
    volatile uint32_t *p = (volatile uint32_t *)addr;
    n = snprintf(out, (size_t)out_size, "OK R 0x%08lX = 0x%08lX\r\n",
                 (unsigned long)addr, (unsigned long)(*p));
  }
  return (n < 0) ? -1 : 1;
}

static int cmd_write(uint32_t addr, uint32_t val, int is_byte,
                     char *out, uint32_t out_size)
{
  int n;

  if (is_byte != 0)
  {
    volatile uint8_t *p;
    uint8_t           old;

    if (addr_allowed_byte(addr) == 0)
    {
      n = snprintf(out, (size_t)out_size,
                   "ERR: address 0x%08lX not allowed (byte)\r\n",
                   (unsigned long)addr);
      return -1;
    }
    if (val > 0xFFUL)
    {
      n = snprintf(out, (size_t)out_size,
                   "ERR: byte value 0x%lX > 0xFF\r\n", (unsigned long)val);
      return -1;
    }

    p   = (volatile uint8_t *)addr;
    old = *p;
    *p  = (uint8_t)val;

    n = snprintf(out, (size_t)out_size,
                 "OK WB 0x%08lX <= 0x%02X (was 0x%02X)\r\n",
                 (unsigned long)addr, (unsigned int)val, (unsigned int)old);
    return (n < 0) ? -1 : 1;
  }

  if (addr_allowed(addr) == 0)
  {
    n = snprintf(out, (size_t)out_size,
                 "ERR: address 0x%08lX not allowed (need word-aligned, "
                 "periph 0x40000000-0x5FFFFFFF / SRAM / CCM)\r\n",
                 (unsigned long)addr);
    return -1;
  }

  {
    volatile uint32_t *p   = (volatile uint32_t *)addr;
    uint32_t           old = *p;
    *p = val;

    n = snprintf(out, (size_t)out_size,
                 "OK W 0x%08lX <= 0x%08lX (was 0x%08lX, readback 0x%08lX)\r\n",
                 (unsigned long)addr, (unsigned long)val,
                 (unsigned long)old, (unsigned long)(*p));
  }
  return (n < 0) ? -1 : 1;
}

/* ------------------------------------------------------------------------- */
/* 入口                                                                        */
/* ------------------------------------------------------------------------- */

int Reg_Shell_Exec(const char *cmd, uint32_t cmd_len,
                   char *out, uint32_t out_size)
{
  char     line[SHELL_MAX_LINE];
  char    *tok[SHELL_MAX_TOKEN];
  uint32_t ntok;
  uint32_t copy_len;

  if ((cmd == NULL) || (out == NULL) || (out_size == 0U))
  {
    return 0;
  }

  /* 一律回一个空串，调用者不用先清缓冲 */
  out[0] = '\0';

  if (cmd_len >= (uint32_t)SHELL_MAX_LINE)
  {
    (void)snprintf(out, (size_t)out_size,
                   "ERR: command too long (max %u)\r\n",
                   (unsigned int)(SHELL_MAX_LINE - 1U));
    return -1;
  }

  /* 拷进来再解析：tokenize 会就地写 '\0'，不能改调用者的缓冲区
   * （echo_service.c 还要拿原字节做中文回显）。 */
  copy_len = cmd_len;
  memcpy(line, cmd, (size_t)copy_len);
  line[copy_len] = '\0';

  ntok = tokenize(line, tok, (uint32_t)SHELL_MAX_TOKEN);
  if (ntok == 0UL)
  {
    return 0;                     /* 空行，当普通数据 */
  }

  upper_inplace(tok[0]);

  /* ---- HELP ---- */
  if (strcmp(tok[0], "HELP") == 0)
  {
    (void)snprintf(out, (size_t)out_size, "%s", s_help_text);
    return 1;
  }

  /* ---- INFO ---- */
  if (strcmp(tok[0], "INFO") == 0)
  {
    return cmd_info(out, out_size);
  }

  /* ---- IO（无参数 = 列出） ---- */
  if (strcmp(tok[0], "IO") == 0)
  {
    uint32_t id;

    if (ntok < 2UL)
    {
      return cmd_io_list(out, out_size);
    }

    if (parse_dec(tok[1], &id) == 0)
    {
      int idx = Board_IO_Find(tok[1]);       /* 也允许用名字：IO DS0 1 */
      if (idx < 0)
      {
        (void)snprintf(out, (size_t)out_size,
                       "ERR: bad IO id/name '%s'\r\n", tok[1]);
        return -1;
      }
      id = (uint32_t)idx;
    }

    /* 不带第三个参数 = 翻转（同 LED） */
    return cmd_io_op(id, (ntok >= 3UL) ? tok[2] : "T", out, out_size);
  }

  /* ---- LED（IO 的别名，语义上就是"第 n 个灯"） ----
   * 支持的写法：
   *   LED 0 1      第 0 个灯点亮
   *   LED 0        第 0 个灯翻转（不带参数默认翻转，最常用）
   *   LED0 1       紧凑写法，等价 LED 0 1
   *   LED0         紧凑写法，等价 LED 0（翻转）
   *   DS0 1        直接叫设备名也行 */
  if (strcmp(tok[0], "LED") == 0)
  {
    uint32_t id;

    if (ntok < 2UL)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: usage: LED <n> [0|1|T]   (no value = toggle)\r\n");
      return -1;
    }

    if (parse_dec(tok[1], &id) == 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: bad LED index '%s'\r\n", tok[1]);
      return -1;
    }

    return cmd_io_op(id, (ntok >= 3UL) ? tok[2] : "T", out, out_size);
  }

  /* ---- 紧凑写法 LED0 / DS1 / IO0 ---- */
  {
    char  saved[SHELL_MAX_LINE];
    char *nm  = NULL;
    char *num = NULL;

    /* split_name_num 会在字母/数字交界处插 '\0' 把 token 切开，而下面
     * Board_IO_Find() 需要完整的 "DS0"，所以先留一份完整的。 */
    (void)snprintf(saved, sizeof(saved), "%s", tok[0]);

    if (split_name_num(tok[0], &nm, &num) != 0)
    {
      /* 名字是 LED/IO/DS 开头才当命令，否则（比如 "HELLO1"）交回调用者 */
      if ((strcmp(nm, "LED") == 0) || (strcmp(nm, "IO") == 0) ||
          (strcmp(nm, "DS") == 0))
      {
        uint32_t id;

        if (strcmp(nm, "DS") == 0)
        {
          /* DS0/DS1 直接按设备名查，不按编号 —— 用切分前的完整名字 */
          int idx = Board_IO_Find(saved);
          if (idx < 0)
          {
            (void)snprintf(out, (size_t)out_size,
                           "ERR: unknown device '%s'\r\n", saved);
            return -1;
          }
          id = (uint32_t)idx;
        }
        else if (parse_dec(num, &id) == 0)
        {
          (void)snprintf(out, (size_t)out_size,
                         "ERR: bad index in '%s'\r\n", saved);
          return -1;
        }
        else
        {
          /* 走下面统一的 cmd_io_op */
        }

        return cmd_io_op(id, (ntok >= 2UL) ? tok[1] : "T", out, out_size);
      }
    }
  }

  /* ---- R / RB ---- */
  if ((strcmp(tok[0], "R") == 0) || (strcmp(tok[0], "RB") == 0))
  {
    uint32_t addr;

    if (ntok < 2UL)
    {
      (void)snprintf(out, (size_t)out_size, "ERR: usage: R <hex addr>\r\n");
      return -1;
    }
    if (parse_hex(tok[1], &addr) == 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: bad hex address '%s'\r\n", tok[1]);
      return -1;
    }

    return cmd_read(addr, (tok[0][1] == 'B') ? 1 : 0, out, out_size);
  }

  /* ---- W / WB ---- */
  if ((strcmp(tok[0], "W") == 0) || (strcmp(tok[0], "WB") == 0))
  {
    uint32_t addr;
    uint32_t val;

    if (ntok < 3UL)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: usage: W <hex addr> <hex value>\r\n");
      return -1;
    }
    if (parse_hex(tok[1], &addr) == 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: bad hex address '%s'\r\n", tok[1]);
      return -1;
    }
    if (parse_hex(tok[2], &val) == 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: bad hex value '%s'\r\n", tok[2]);
      return -1;
    }

    return cmd_write(addr, val, (tok[0][1] == 'B') ? 1 : 0, out, out_size);
  }

  /* 首关键字不认识 —— 不是命令。交给调用者（中文回声）处理。 */
  return 0;
}
