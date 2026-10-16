/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    dma.c
  * @brief   This file provides code for the configuration
  *          of all the requested memory to memory DMA transfers.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "dma.h"

/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/*----------------------------------------------------------------------------*/
/* Configure DMA                                                              */
/*----------------------------------------------------------------------------*/

/* USER CODE BEGIN 1 */

/* USER CODE END 1 */

/**
  * Enable DMA controller clock
  */
void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMA1_CLK_ENABLE();

  /* DMA interrupt init */
  /* DMA1_Stream2_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Stream2_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream2_IRQn);
  /* DMA1_Stream7_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Stream7_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream7_IRQn);

  /* -------------------------------------------------------------------------
   * 【本工程新增】I2C2 事件/错误中断使能
   *
   * 【为什么必须手写这一句】.ioc 里 I2C2 的 NVIC 没勾上（只勾了 DMA1_Stream2/7），
   * 所以 CubeMX 不会生成这两句。但 OLED 异步刷屏要用
   * HAL_I2C_Master_Transmit_DMA()，它的收尾**必须**靠 I2C2_EV_IRQHandler 里的
   * TC（Transfer Complete）中断才能把 hi2c2.State 从 BUSY_TX 放回 READY。
   * 只开 DMA 中断的话：DMA 只说明"数据搬进 I2C2 的 TXDR 了"，不代表"已经从
   * 总线上移出去了"。不开这两个中断，第一次刷屏会成功，但状态机永远卡在
   * BUSY_TX —— 之后连 PCF8574 的 PHY 复位都会 HAL_BUSY 失败。
   * 详见 Core/Src/stm32f4xx_it.c 末尾 I2C2_EV_IRQHandler 的注释。
   *
   * 优先级：CMSIS 里**数值越小优先级越高**。这里给 I2C2 也设最高（0），
   * 与 DMA 同级，保证 TC 中断不被耽误。
   * ------------------------------------------------------------------------- */
  HAL_NVIC_SetPriority(I2C2_EV_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(I2C2_EV_IRQn);
  HAL_NVIC_SetPriority(I2C2_ER_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(I2C2_ER_IRQn);

}

/* USER CODE BEGIN 2 */

/* USER CODE END 2 */

