/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
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
#include "main.h"
#include "dma.h"
#include "i2c.h"
#include "lwip.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "debug_uart.h"
#include "eth_phy.h"
#include "board_io.h"       /* 板级 IO 注册表（DS0/DS1） */
#include "oled.h"        /* 波特律动 SSD1306 128x64 OLED（I2C2 PH4/PH5） */
#include "font.h"        /* afont16x8 / font16x16 字库 */
#include "echo_service.h"   /* 带话术的回声服务（当前启用） */
#include "udp_echo.h"       /* 原样回环（保留，未启用，端口与上面冲突） */
/* gnetif 定义在 LWIP/App/lwip.c，但 lwip.h 没有 extern 它，这里自己声明 */
extern struct netif gnetif;
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_USART1_UART_Init();
  MX_I2C2_Init();
  /* USER CODE BEGIN 2 */
  Debug_UART_Banner("ETHERNETtest boot (step 3: lwip)");
  printf("[OK] printf redirect works\r\n");

  /* 板级 IO（DS0=PB0 / DS1=PB1，低电平点亮）。必须在 MX_GPIO_Init() 之后
   * —— GPIO 时钟由它使能。放这里是因为它和网络无关，早配早干净：
   * 上电后 LED 立刻处于"灭"的确定状态，而不是保持复位后的 ODR=0（对低电平
   * 点亮的灯来说 ODR=0 就是亮）。 */
  Board_IO_Init();

  /* 【关键顺序】PHY 复位必须先释放，否则 MX_LWIP_Init() 内部的 HAL_ETH_Init()
   * 会对着一个没上电的 PHY 返回"成功"，然后你就得到一个永远 ping 不通的 lwIP。 */
  if (ETH_PHY_ReleaseReset() != 0)
  {
    printf("[ERR] PHY reset release failed -- lwIP would be a zombie, stopping.\r\n");
    while (1) { HAL_Delay(1000); }
  }

  MX_LWIP_Init();

  printf("[OK] MX_LWIP_Init() returned\r\n");
  printf("[IP ] board = %u.%u.%u.%u  mask = %u.%u.%u.%u  gw = %u.%u.%u.%u\r\n",
         ip4_addr1(&gnetif.ip_addr), ip4_addr2(&gnetif.ip_addr),
         ip4_addr3(&gnetif.ip_addr), ip4_addr4(&gnetif.ip_addr),
         ip4_addr1(&gnetif.netmask), ip4_addr2(&gnetif.netmask),
         ip4_addr3(&gnetif.netmask), ip4_addr4(&gnetif.netmask),
         ip4_addr1(&gnetif.gw),      ip4_addr2(&gnetif.gw),
         ip4_addr3(&gnetif.gw),      ip4_addr4(&gnetif.gw));
  printf("[MAC] %02X:%02X:%02X:%02X:%02X:%02X\r\n",
         gnetif.hwaddr[0], gnetif.hwaddr[1], gnetif.hwaddr[2],
         gnetif.hwaddr[3], gnetif.hwaddr[4], gnetif.hwaddr[5]);
  printf("[IP ] ping 192.168.1.30 from the PC now\r\n");

  /* UDP 回声服务。必须在 MX_LWIP_Init() 之后（netif 得先 add/up，udp_bind 才有意义）。
   * 失败不阻塞主循环，否则连 ping 都做不了。
   *
   * 【注意】echo_service.c 和 udp_echo.c 功能重叠且默认都用 8080 端口，
   * 一个 UDP 端口只能被一个 pcb 绑定，所以这里二选一。当前用带话术的
   * echo_service（回复"我收到你的信息了，是 xxx 吗？"）。要换回原样回环，
   * 把下面这行注释掉、启用 UDP_Echo_Init()/UDP_Echo_Poll() 即可（二者端口
   * 相同，绝不能同时开）。 */
  if (Echo_Service_Init() != 0)
  {
    printf("[ERR] Echo_Service_Init() failed -- echo service unavailable\r\n");
  }

  /* SSD1306 OLED（I2C2，和 PCF8574 共用总线）—— 用波特律动驱动 oled.c。
   *
   * 【为什么放在 ETH_PHY_ReleaseReset() 之后】
   * 同一根 I2C2 上挂着 PCF8574（管 ETH_RESET）。OLED 插上后总线负载变大，
   * 如果 OLED 初始化把总线拉死，紧接着的 ETH_PHY_ReleaseReset() 就会失败，
   * 而那个函数失败是 while(1) 直接停 —— 板子永远起不来。
   * 放在后面，最坏情况也只是屏不亮，网络照常。
   *
   * 【为什么不检查返回值】波特律动的 OLED_Init() 返回 void，它内部
   * OLED_Send() 把 HAL 错误全吞了。所以这里没法判断成功与否，只能画完
   * 让用户看屏。屏不亮就发 'OLED INIT' 手动重试。
   *
   * 【上电时序】模块上的复位电容要充电，STM32 启动比 OLED 上电快，
   * 所以这里等 100ms 再初始化（oled.c 原注释也提示要等 20ms 以上）。 */
  HAL_Delay(100);

  OLED_Init();

  /* 【开机画面为什么用阻塞版】
   * OLED_ShowFrame() 现在是异步的（只启动第一页就返回），本意是别让刷屏
   * 卡住 lwIP。但开机这一刻还没有网络要伺候，用阻塞版反而更简单：
   * 画完就完整显示在屏上，不用等主循环来推进。
   * 主循环一旦跑起来，后面所有 OLED 命令走的都是异步版。 */
  OLED_NewFrame();

  /* 波特律动的打印函数形参是 char*（非 const），字面量要转一下。
   * 这是 main() 的栈帧，只在这几行用，转成可写指针是安全的。 */
  {
    static char l0[] = "ETHERNETtest";
    static char l1[] = "192.168.1.30";
    static char l2[] = "UDP :8080";
    static char l3[] = "type HELP";

    OLED_PrintASCIIString(0U,  0U, l0, &afont16x8, OLED_COLOR_NORMAL);
    OLED_PrintASCIIString(0U, 16U, l1, &afont16x8, OLED_COLOR_NORMAL);
    OLED_PrintASCIIString(0U, 32U, l2, &afont16x8, OLED_COLOR_NORMAL);
    OLED_PrintASCIIString(0U, 48U, l3, &afont16x8, OLED_COLOR_NORMAL);
  }

  OLED_ShowFrameBlocking();
  printf("[OLED] boot screen drawn (BaudDance driver, I2C2 PH4/PH5)\r\n");
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    MX_LWIP_Process();

    Echo_Service_Poll();   /* 非阻塞，内部 1 秒节流；只在收到过包之后才发 */

    /* 推进 OLED 后台刷屏，每步 ≤ 约 2.8ms。
     *
     * 【为什么必须放在主循环里】OLED_ShowFrame() 现在只启动第一页就返回，
     * 剩下的 7 页靠这里一句一句喂完。少了这一句，整屏只会送出第一页，
     * 屏上会是"第一行对、下面全乱"。 */
    OLED_FlushPoll();
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 180;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Activate the Over-Drive mode
  */
  if (HAL_PWREx_EnableOverDrive() != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
