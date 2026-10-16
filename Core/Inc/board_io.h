/**
  ******************************************************************************
  * @file    board_io.h
  * @brief   板级 IO 注册表 —— 把"板子上有哪些可控的 GPIO"做成一张表
  *
  * 【为什么要有这一层】
  *   目的不是"点亮一个 LED"，而是给上层（以太网命令、未来的 AI 控制）一个
  *   **稳定的抽象**：应用层只说 "LED 0 打开"，不需要知道它是 PB0 还是 PC13、
  *   是高电平点亮还是低电平点亮。指针指向哪、极性如何，全部封在这张表里。
  *
  *   以后要扩展（蜂鸣器、RS485_RE、任意 GPIO），**只改 board_io.c 里那张表**，
  *   reg_shell.c 和 echo_service.c 一行都不用动。
  *
  * 【当前注册的设备】
  *   ID 0  "DS0"  PB0   低电平点亮（正点原子阿波罗V2）
  *   ID 1  "DS1"  PB1   低电平点亮
  *
  * 【极性约定】
  *   表中 `on_level` 存的是"点亮/有效时引脚该输出的电平"。
  *   DS0/DS1 是低电平点亮，所以 on_level = GPIO_PIN_RESET。
  *   所有对外的 Set/Get/Toggle 都以"逻辑上的亮/灭"为准，不暴露电平。
  ******************************************************************************
  */
#ifndef __BOARD_IO_H
#define __BOARD_IO_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/**
  * @brief  配置所有已注册 IO 的 GPIO 模式，并把它们置于"灭/无效"状态
  * @note   必须在 MX_GPIO_Init() 之后调用（GPIO 时钟由它使能）。
  *
  *         为什么不把 PB0/PB1 的配置写进 gpio.c —— 那是 CubeMX 生成的文件，
  *         重新生成工程时 USER CODE 段以外的内容会被覆盖，LED 配置会丢。
  */
void Board_IO_Init(void);

/**
  * @brief  已注册的 IO 数量
  */
uint32_t Board_IO_Count(void);

/**
  * @brief  按 ID 查找设备名
  * @param  id  设备 ID
  * @retval 名字（静态字符串，不要释放）；ID 非法时返回 NULL
  */
const char *Board_IO_Name(uint32_t id);

/**
  * @brief  按名字查找设备 ID（不区分大小写）
  * @param  name  设备名，如 "DS0"
  * @retval >=0 为 ID；找不到返回 -1
  */
int Board_IO_Find(const char *name);

/**
  * @brief  设置某个 IO 的逻辑状态
  * @param  id  设备 ID
  * @param  on  0 = 灭/无效，非 0 = 亮/有效
  * @retval 0 = 成功，-1 = ID 非法
  */
int Board_IO_Set(uint32_t id, uint32_t on);

/**
  * @brief  翻转某个 IO
  * @retval 0 = 成功，-1 = ID 非法
  */
int Board_IO_Toggle(uint32_t id);

/**
  * @brief  读取某个 IO 的逻辑状态
  * @retval 0 = 灭/无效，1 = 亮/有效；ID 非法时返回 -1
  */
int Board_IO_Get(uint32_t id);

/**
  * @brief  把某个 IO 的实际寄存器信息填进调用者给的缓冲
  * @param  id   设备 ID
  * @param  out  输出缓冲
  * @param  len  缓冲大小
  * @retval 写入的字符数；ID 非法返回 -1
  *
  * 形如：DS0 (id 0) = ON, port=GPIOB pin=0x0001 ODR=0x0000 (active-low)
  * 打印 ODR 是为了让人能直接对照 "R 0x40020014" 的结果。
  */
int Board_IO_Describe(uint32_t id, char *out, uint32_t len);

#ifdef __cplusplus
}
#endif

#endif /* __BOARD_IO_H */
