/**
  ******************************************************************************
  * @file    board_io.c
  * @brief   板级 IO 注册表 —— 见 board_io.h 的说明
  *
  * 【扩展方式】
  *   加一个可控 GPIO，只需要两步：
  *     1) 在 s_io_table[] 里加一行，填 ID / 名字 / 端口 / 引脚 / 有效电平；
  *     2) 如果所在的 GPIO 端口时钟还没开，在 Board_IO_Init() 里补一行
  *        __HAL_RCC_GPIOx_CLK_ENABLE()。
  *   不需要改 reg_shell.c、echo_service.c、main.c。
  *
  * 【注意 MX_GPIO_Init() 与这里的关系】
  *   MX_GPIO_Init() 已经把 GPIOA/B/C/G/H 的时钟都使能了（见 Core/Src/gpio.c）。
  *   这里仍然把 CLK_ENABLE 再写一遍：HAL 的 __HAL_RCC_*_CLK_ENABLE 是置位
  *   RCC->AHB1ENR 的对应位，重复调用无害。这样本模块不依赖 gpio.c 的具体
  *   内容，别人改动 gpio.c 也不会让 LED 突然不亮。
  ******************************************************************************
  */

#include "board_io.h"
#include "main.h"

#include <stdio.h>
#include <string.h>

/* ------------------------------------------------------------------------- */
/* 设备表 —— 扩展就在这里加行                                                  */
/* ------------------------------------------------------------------------- */

typedef struct
{
  uint32_t       id;         /* 对外暴露的逻辑编号（也用于命令里的下标） */
  const char    *name;       /* 对外暴露的名字 */
  GPIO_TypeDef  *port;       /* GPIO 端口 */
  uint16_t       pin;        /* GPIO_PIN_x */
  GPIO_PinState  on_level;   /* 亮/有效时引脚输出的电平 */
  const char    *note;       /* 备注，打印用 */
} board_io_entry_t;

/**
 * 【当前板：正点原子阿波罗V2】
 *   DS0 = PB0，DS1 = PB1，两个都是**低电平点亮**（引脚经限流电阻接 LED 阳极到 3V3，
 *   阴极接 GPIO；GPIO 输出低才有电流）。所以 on_level = GPIO_PIN_RESET。
 *
 * ⚠ 将来换板或改接线，改这一张表即可，上层命令不变。
 */
static const board_io_entry_t s_io_table[] =
{
  { 0U, "DS0", GPIOB, GPIO_PIN_0, GPIO_PIN_RESET, "PB0, active-low" },
  { 1U, "DS1", GPIOB, GPIO_PIN_1, GPIO_PIN_RESET, "PB1, active-low" },
};

#define BOARD_IO_NUM   (sizeof(s_io_table) / sizeof(s_io_table[0]))

/* ------------------------------------------------------------------------- */
/* 内部工具                                                                    */
/* ------------------------------------------------------------------------- */

/**
  * @brief  不区分大小写的字符串比较（嵌入式里不用 strcasecmp，非标准且可能没有）
  */
static int name_eq_ci(const char *a, const char *b)
{
  while ((*a != '\0') && (*b != '\0'))
  {
    char ca = *a;
    char cb = *b;

    if ((ca >= 'a') && (ca <= 'z')) { ca = (char)(ca - 'a' + 'A'); }
    if ((cb >= 'a') && (cb <= 'z')) { cb = (char)(cb - 'a' + 'A'); }

    if (ca != cb)
    {
      return 0;
    }
    a++;
    b++;
  }

  return (*a == '\0') && (*b == '\0');
}

/**
  * @brief  把逻辑状态换算成要写进 ODR 的电平
  */
static GPIO_PinState level_for(const board_io_entry_t *e, uint32_t on)
{
  if (on != 0U)
  {
    return e->on_level;
  }

  /* 灭 = 有效电平的反面 */
  return (e->on_level == GPIO_PIN_SET) ? GPIO_PIN_RESET : GPIO_PIN_SET;
}

/* ------------------------------------------------------------------------- */
/* 对外接口                                                                    */
/* ------------------------------------------------------------------------- */

void Board_IO_Init(void)
{
  GPIO_InitTypeDef gpio = {0};
  uint32_t i;

  /* 端口时钟。MX_GPIO_Init() 已经开过，这里再开一次是幂等的，见文件头说明。 */
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /* 同端口只配置一次：把这张表里出现过的所有引脚合并成一个掩码 */
  {
    uint32_t mask = 0U;

    for (i = 0U; i < BOARD_IO_NUM; i++)
    {
      mask |= (uint32_t)s_io_table[i].pin;
    }

    gpio.Pin   = (uint16_t)mask;
    gpio.Mode  = GPIO_MODE_OUTPUT_PP;      /* 推挽输出，直接驱动 LED */
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;      /* 点灯的边沿速度，低速即可，少辐射 */

    HAL_GPIO_Init(GPIOB, &gpio);
  }

  /* 全部置为"灭"。必须在 HAL_GPIO_Init() 之后 —— 复位后 ODR 是 0，
   * 对低电平点亮的 LED 来说 0 就是"亮"，上电会先闪一下甚至常亮。 */
  for (i = 0U; i < BOARD_IO_NUM; i++)
  {
    (void)Board_IO_Set(i, 0U);
  }

  printf("[IO ] board_io: %u device(s) registered\r\n", (unsigned int)BOARD_IO_NUM);
  for (i = 0U; i < BOARD_IO_NUM; i++)
  {
    printf("[IO ]   id=%u name=%s %s  (off at boot)\r\n",
           (unsigned int)s_io_table[i].id,
           s_io_table[i].name,
           s_io_table[i].note);
  }
}

uint32_t Board_IO_Count(void)
{
  return (uint32_t)BOARD_IO_NUM;
}

const char *Board_IO_Name(uint32_t id)
{
  if (id >= (uint32_t)BOARD_IO_NUM)
  {
    return NULL;
  }

  return s_io_table[id].name;
}

int Board_IO_Find(const char *name)
{
  uint32_t i;

  if (name == NULL)
  {
    return -1;
  }

  for (i = 0U; i < BOARD_IO_NUM; i++)
  {
    if (name_eq_ci(s_io_table[i].name, name) != 0)
    {
      return (int)i;
    }
  }

  return -1;
}

int Board_IO_Set(uint32_t id, uint32_t on)
{
  if (id >= (uint32_t)BOARD_IO_NUM)
  {
    return -1;
  }

  HAL_GPIO_WritePin(s_io_table[id].port,
                    s_io_table[id].pin,
                    level_for(&s_io_table[id], on));

  return 0;
}

int Board_IO_Toggle(uint32_t id)
{
  if (id >= (uint32_t)BOARD_IO_NUM)
  {
    return -1;
  }

  HAL_GPIO_TogglePin(s_io_table[id].port, s_io_table[id].pin);

  return 0;
}

int Board_IO_Get(uint32_t id)
{
  GPIO_PinState lvl;

  if (id >= (uint32_t)BOARD_IO_NUM)
  {
    return -1;
  }

  lvl = HAL_GPIO_ReadPin(s_io_table[id].port, s_io_table[id].pin);

  return (lvl == s_io_table[id].on_level) ? 1 : 0;
}

int Board_IO_Describe(uint32_t id, char *out, uint32_t len)
{
  const board_io_entry_t *e;
  GPIO_PinState lvl;
  int n;

  if ((id >= (uint32_t)BOARD_IO_NUM) || (out == NULL) || (len == 0U))
  {
    return -1;
  }

  e   = &s_io_table[id];
  lvl = HAL_GPIO_ReadPin(e->port, e->pin);

  /* 端口名从指针推不出来，这里直接按已知的 GPIOB 写死；将来表里出现别的端口，
   * 这里也要跟着加一个映射（用 if/else 链，够用且不引入额外数据表）。 */
  n = snprintf(out, (size_t)len,
               "%s (id %u) = %s, port=%s pin=0x%04X ODR=0x%08lX (%s)\r\n",
               e->name,
               (unsigned int)e->id,
               (lvl == e->on_level) ? "ON " : "OFF",
               (e->port == GPIOB) ? "GPIOB" : "?",
               (unsigned int)e->pin,
               (unsigned long)e->port->ODR,
               (e->on_level == GPIO_PIN_RESET) ? "active-low" : "active-high");

  return n;
}
