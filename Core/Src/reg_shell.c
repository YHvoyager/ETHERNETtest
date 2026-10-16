/**
  ******************************************************************************
  * @file    reg_shell.c
  * @brief   以太网命令解析 —— 见 reg_shell.h
  ******************************************************************************
  */

#include "reg_shell.h"
#include "board_io.h"
#include "ssd1306.h"
#include "echo_service.h"
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
  "  OLED               show what is currently on the OLED\r\n"
  "  OLED SCAN          scan I2C2 bus (is the panel alive?)\r\n"
  "  OLED CLR           clear screen (no argument = re-flush)\r\n"
  "  OLED TXT <l> <t>   write text on line l (0..3)\r\n"
  "  OLED RAW <hex>     send hex register bytes, bypassing the driver\r\n"
  "  OLED PIX <x> <y> [0|1]  draw one pixel\r\n"
  "  BROADCAST [port]   mirror frames to a 2nd socket (0 = off)\r\n"
  "  PING               liveness check the PC can use to probe the board\r\n"
  "examples: LED0  |  LED 1 1  |  W 40020014 3  |  OLED TXT 0 HELLO\r\n";

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
/* OLED 命令                                                                   */
/* ------------------------------------------------------------------------- */

/**
  * @brief  把整屏内容以文本形式描述出来（4 行 × 16 字符）
  * @note   面板上的**中文字库方块**和**未知字符**在这里显示成 '.',
  *         因为它们在图形缓冲里本来就是像素，没有字符可还原。
  */
static int cmd_oled_show(char *out, uint32_t out_size)
{
  const uint8_t *buf = SSD1306_GetBuffer();
  uint32_t       used;
  uint8_t        line;
  uint8_t        col;
  int            n;

  n = snprintf(out, (size_t)out_size, "OLED 128x64 (I2C2):\r\n");
  if (n < 0) { return -1; }
  used = (uint32_t)n;

  /* 每行 16 个字符 × 8 像素 = 128 列；每行 16 像素高 = 2 页 */
  for (line = 0U; line < 4U; line++)
  {
    uint8_t page = (uint8_t)(line * 2U);

    if (used + 20U >= (uint32_t)out_size) { break; }

    out[used++] = '|';

    for (col = 0U; col < 16U; col++)
    {
      /* 直接用图形缓冲判断"这一格有没有点亮的像素"，
       * 不反查字库 —— 缓冲区里存的是像素，不是字符。 */
      uint8_t  i;
      uint8_t  row;
      uint8_t  any = 0U;

      for (i = 0U; i < 8U; i++)
      {
        for (row = 0U; row < 16U; row++)
        {
          uint8_t px  = (uint8_t)(col * 8U + i);
          uint8_t py  = (uint8_t)(line * 16U + row);
          uint8_t pg  = (uint8_t)(py >> 3);
          uint8_t bit = (uint8_t)(py & 7U);

          if ((buf[(uint16_t)pg * SSD1306_WIDTH + px] & (uint8_t)(1U << bit)) != 0U)
          {
            any = 1U;
          }
        }
      }

      out[used++] = (any != 0U) ? '#' : '.';
    }

    out[used++] = '|';
    out[used++] = '\r';
    out[used++] = '\n';
  }

  out[used] = '\0';
  return 1;
}

/**
  * @brief  OLED <子命令> 的总入口
  */
static int cmd_oled(uint32_t ntok, char *tok[], char *out, uint32_t out_size)
{
  int n;

  /* ---- OLED（无参数）= 把屏上内容读回来 ---- */
  if (ntok < 2UL)
  {
    return cmd_oled_show(out, out_size);
  }

  /* ---- OLED SCAN ---- */
  if (strcmp(tok[1], "SCAN") == 0)
  {
    uint32_t found = SSD1306_I2CScan(out, out_size);
    if (found == 0UL)
    {
      return -1;
    }
    /* 顺带报一下 0x3C 在不在，这是最常问的问题 */
    if (strstr(out, "0x3C") == NULL)
    {
      uint32_t used = (uint32_t)strlen(out);
      if (used + 48U < out_size)
      {
        (void)snprintf(out + used, (size_t)(out_size - used),
                       "note: 0x3C (SSD1306) NOT found -> wiring/power, not driver\r\n");
      }
    }
    return 1;
  }

  /* ---- OLED CLR ---- */
  if (strcmp(tok[1], "CLR") == 0)
  {
    SSD1306_Clear(0U);
    n = SSD1306_Flush();
    if (n != 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: flush failed (%d), I2C err=0x%08lX\r\n",
                     n, (unsigned long)HAL_I2C_GetError(&hi2c2));
      return -1;
    }
    (void)snprintf(out, (size_t)out_size, "OK OLED cleared\r\n");
    return 1;
  }

  /* ---- OLED FILL ---- */
  if (strcmp(tok[1], "FILL") == 0)
  {
    SSD1306_Clear(1U);
    n = SSD1306_Flush();
    (void)snprintf(out, (size_t)out_size,
                   (n == 0) ? "OK OLED filled (all pixels on)\r\n"
                            : "ERR: flush failed\r\n");
    return (n == 0) ? 1 : -1;
  }

  /* ---- OLED PIX <x> <y> [0|1] ---- */
  if (strcmp(tok[1], "PIX") == 0)
  {
    uint32_t x;
    uint32_t y;
    uint8_t  on = 1U;

    if (ntok < 4UL)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: usage: OLED PIX <x> <y> [0|1]\r\n");
      return -1;
    }
    if ((parse_dec(tok[2], &x) == 0) || (parse_dec(tok[3], &y) == 0))
    {
      (void)snprintf(out, (size_t)out_size, "ERR: x/y must be decimal\r\n");
      return -1;
    }
    if (x >= SSD1306_WIDTH || y >= SSD1306_HEIGHT)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: out of range (x 0..%u, y 0..%u)\r\n",
                     (unsigned int)(SSD1306_WIDTH - 1U),
                     (unsigned int)(SSD1306_HEIGHT - 1U));
      return -1;
    }
    if (ntok >= 5UL)
    {
      on = (tok[4][0] == '0') ? 0U : 1U;
    }

    SSD1306_DrawPixel((uint8_t)x, (uint8_t)y, on);
    n = SSD1306_Flush();
    (void)snprintf(out, (size_t)out_size,
                   "OK OLED (%u,%u) = %s\r\n",
                   (unsigned int)x, (unsigned int)y, (on != 0U) ? "ON" : "OFF");
    return (n == 0) ? 1 : -1;
  }

  /* ---- OLED TXT <line> <text...> ----
   * 文本可以带空格，所以从 tok[3] 起要**拼回去**，不能用单个 token。 */
  if (strcmp(tok[1], "TXT") == 0)
  {
    uint32_t line;
    uint8_t  y;

    if (ntok < 4UL)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: usage: OLED TXT <line 0..3> <text>\r\n");
      return -1;
    }
    if (parse_dec(tok[2], &line) == 0)
    {
      (void)snprintf(out, (size_t)out_size, "ERR: bad line '%s'\r\n", tok[2]);
      return -1;
    }
    if (line > 3UL)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: line must be 0..3 (4 lines of 16 chars)\r\n");
      return -1;
    }

    y = (uint8_t)(line * 16U);

    /* 先擦掉这一行（两页），否则新文本比旧文本短时会留下尾巴 */
    SSD1306_DrawString(0U, y,        "                ", 0U);
    SSD1306_DrawString(0U, (uint8_t)(y + 8U), "                ", 0U);

    /* 把 tok[3..] 用空格拼回来 */
    {
      char    joined[SHELL_MAX_LINE];
      uint32_t used = 0UL;
      uint32_t i;

      joined[0] = '\0';
      for (i = 3UL; i < ntok; i++)
      {
        size_t tl = strlen(tok[i]);

        if (used + tl + 2U >= sizeof(joined))
        {
          break;
        }
        if (i > 3UL)
        {
          joined[used++] = ' ';
        }
        memcpy(joined + used, tok[i], tl);
        used += (uint32_t)tl;
        joined[used] = '\0';
      }

      SSD1306_DrawString(0U, y, joined, 1U);
    }

    n = SSD1306_Flush();
    if (n != 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: flush failed (%d), I2C err=0x%08lX\r\n",
                     n, (unsigned long)HAL_I2C_GetError(&hi2c2));
      return -1;
    }

    (void)snprintf(out, (size_t)out_size, "OK OLED line %u updated\r\n",
                   (unsigned int)line);
    return 1;
  }

  /* ---- OLED RAW <hex...> ----
   * 直接往 I2C2 上发原始字节，**完全绕开驱动**。
   * 这是留给"以后要让 AI 直接操作 SSD1306 寄存器"的逃生口，
   * 也是排查"到底是驱动写错了还是屏不认命令"的最后手段。 */
  if (strcmp(tok[1], "RAW") == 0)
  {
    uint8_t  raw[64];
    uint32_t cnt = 0UL;
    uint32_t i;

    for (i = 2UL; (i < ntok) && (cnt < sizeof(raw)); i++)
    {
      uint32_t v;

      if (parse_hex(tok[i], &v) == 0 || v > 0xFFUL)
      {
        (void)snprintf(out, (size_t)out_size,
                       "ERR: bad hex byte '%s'\r\n", tok[i]);
        return -1;
      }
      raw[cnt++] = (uint8_t)v;
    }

    if (cnt == 0UL)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: usage: OLED RAW <hex byte> [hex byte ...]\r\n");
      return -1;
    }

    if (HAL_I2C_Master_Transmit(&hi2c2, SSD1306_I2C_ADDR, raw,
                                (uint16_t)cnt, SSD1306_I2C_TIMEOUT) != HAL_OK)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: I2C transmit failed, err=0x%08lX\r\n",
                     (unsigned long)HAL_I2C_GetError(&hi2c2));
      return -1;
    }

    (void)snprintf(out, (size_t)out_size, "OK sent %u byte(s) to 0x%02X\r\n",
                   (unsigned int)cnt, SSD1306_I2C_ADDR);
    return 1;
  }

  (void)snprintf(out, (size_t)out_size,
                 "ERR: unknown OLED subcommand '%s' (try: SCAN CLR FILL TXT PIX RAW)\r\n",
                 tok[1]);
  return -1;
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

  /* ---- OLED ---- */
  if (strcmp(tok[0], "OLED") == 0)
  {
    return cmd_oled(ntok, tok, out, out_size);
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

  /* ---- BROADCAST [port] ----
   * 让板子把大帧（目前只有 OLED 全屏图）同时发到这个端口。
   * 目的是让 PC 侧能用两个 socket：一个发命令、一个只收数据流，
   * 不用在同一个 socket 上区分"这是应答还是帧"。
   * 不带参数 = 关掉。0 = 关掉。 */
  if (strcmp(tok[0], "BROADCAST") == 0)
  {
    uint32_t port = 0UL;

    if ((ntok >= 2UL) && (parse_dec(tok[1], &port) == 0))
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: bad port '%s' (use BROADCAST <port> or BROADCAST 0)\r\n",
                     tok[1]);
      return -1;
    }

    if (port == 0UL)
    {
      (void)Echo_Service_SetBroadcast(NULL, 0U);
      (void)snprintf(out, (size_t)out_size, "OK broadcast off\r\n");
      return 1;
    }

    if (port > 65535UL)
    {
      (void)snprintf(out, (size_t)out_size, "ERR: port must be 1..65535\r\n");
      return -1;
    }

    /* 订阅方就是"最后发命令的那台 PC"（由 echo_service.c 记录），
     * 所以这里传 NULL，让它自己填 IP。 */
    if (Echo_Service_SetBroadcast(NULL, (uint16_t)port) != 0)
    {
      (void)snprintf(out, (size_t)out_size,
                     "ERR: no peer yet -- send any packet first\r\n");
      return -1;
    }

    (void)snprintf(out, (size_t)out_size,
                   "OK broadcast to port %u (from the PC that sent this)\r\n",
                   (unsigned int)port);
    return 1;
  }

  /* ---- PING ----
   * 给"活着吗"这个问题一个最便宜的回答（回 PONG + tick）。
   * ICMP 的 ping 走协议栈、有 ARP 开销；这个是应用层的，命令发出到
   * 应答只有一次 UDP 往返，AI 侧可以用它探测板子是否在线。 */
  if (strcmp(tok[0], "PING") == 0)
  {
    (void)snprintf(out, (size_t)out_size, "PONG tick=%lu\r\n",
                   (unsigned long)HAL_GetTick());
    return 1;
  }

  /* 首关键字不认识 —— 不是命令。交给调用者（中文回声）处理。 */
  return 0;
}
