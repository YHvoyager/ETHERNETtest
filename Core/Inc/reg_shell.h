/**
  ******************************************************************************
  * @file    reg_shell.h
  * @brief   通过以太网下发命令，改 GPIO / 读写单片机寄存器
  *
  * 【为什么要有这个模块】
  *   需求是"后期能通过以太网传数据直接修改单片机寄存器"。做法是先把"命令 →
  *   动作"这一层独立出来：Reg_Shell_Exec() 是个**纯函数**，输入一行命令、
  *   输出一行应答，不碰网络。网络那侧（echo_service.c 的收包回调）只负责把
  *   字节喂进来、把应答发回去。这样：
  *     - 换传输方式（UDP → TCP → 串口）不用动命令实现；
  *     - 命令逻辑可以离线测试；
  *     - 以后 AI 只要生成这几种文本命令即可，不需要理解 lwIP。
  *
  * 【命令一览】（不区分大小写，多余空格会被忽略；可在末尾带 \r\n）
  *
  *   HELP                打印帮助
  *   IO                  列出已注册的板级 IO（DS0/DS1…）及其状态
  *   LED <n> [0|1|T]     第 n 个 LED：0=灭 1=亮 T=翻转（**省略默认翻转**）
  *   IO <id> [0|1|T]     按 ID 操作任意已注册 IO（LED 是它的别名）
  *   LED0 / DS1 [0|1|T]  紧凑写法，等价于上面两条（不带值 = 翻转）
  *   R <addr>            读 32 位寄存器，addr 为十六进制（可带 0x）
  *   W <addr> <val>      写 32 位寄存器，val 为十六进制
  *   RB <addr>           读 8 位（一个字节）
  *   WB <addr> <val>     写 8 位
  *   INFO                板子状态（tick、IO 数量）
  *
  * 例：
  *   LED0                 → OK IO 0 (DS0) = ON (toggled)      ← 最常用，就敲 4 个字符
  *   LED 0 1              → OK IO 0 (DS0) = ON
  *   W 40020014 3         → OK W 0x40020014 <= 0x00000003  (was 0x00000000)
  *   R 40020014           → OK R 0x40020014 = 0x00000003
  *
  * ⚠ 为什么要有"省略参数默认翻转"和"紧凑写法"：
  *   第一版要求严格写 `LED <n> <0|1|T>`，实测用户敲 `LED 0` 收到的是
  *   `ERR: usage: ...`，敲 `LED0` 收到的是中文回声"我收到你的信息了，是 LED0 吗？"，
  *   两个都很反直觉。命令行要好用，就得容忍人最自然的输入。
  *
  * 【安全阀 —— W 能写错就死机，必须拦】
  *   允许写的地址（地址必须 4 字节对齐）：
  *     - 外设区   0x40000000 ~ 0x5FFFFFFF  （APB/AHB 外设，含 GPIOx、RCC 等）
  *     - SRAM     0x20000000 ~ 0x2002FFFF  （F429IGT6 是 192KB + 64KB CCM，
  *                                          这里只放行主 SRAM 区）
  *     - CCMRAM   0x10000000 ~ 0x1000FFFF
  *   拒绝：
  *     - 0x00000000 ~ 0x1FFFFFFF  Flash 及其别名区（写它等于烧写固件/触发硬件错误）
  *     - 其它任何地址
  *
  *   ⚠ 这个白名单是"防手滑"，不是"防恶意"：外设区里照样能写 RCC/FLASH/PWR
  *   寄存器把自己搞死。真要限制到具体外设，得改成按外设基地址逐个放行。
  *
  * 【为什么直接写绝对地址】
  *   因为需求就是"验证通过数据直接修改单片机寄存器是否可行"。用
  *   volatile uint32_t * 直接访问物理地址，走的就是 CPU 的存储映射，
  *   和 C 代码里 GPIOB->ODR = x 是同一条路径。
  ******************************************************************************
  */
#ifndef __REG_SHELL_H
#define __REG_SHELL_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include <stddef.h>

/**
  * @brief  执行一行命令，并把应答写进 out
  * @param  cmd       命令行，不要求以 '\0' 结尾也可以带（内部按 len 处理）
  * @param  cmd_len   cmd 的有效字节数
  * @param  out       应答缓冲（调用者提供）
  * @param  out_size  out 的字节数
  * @retval  1 = 识别并执行了命令（out 里是应答，含结尾的 \r\n）
  *          0 = 这行不是命令（调用者应该走自己的普通处理，比如中文回声）
  *         -1 = 是命令但参数错/被拒绝（out 里是 ERR 说明）
  *
  * @note   返回 0 是给 echo_service.c 用的：敲 "hello" 时不要被当成命令。
  *         判据是**首关键字不认识**，而不是"整行解析失败"，这样
  *         "LED 9 1"（ID 越界）仍然会明确回 ERR，不会被当成聊天内容。
  */
int Reg_Shell_Exec(const char *cmd, uint32_t cmd_len, char *out, uint32_t out_size);

/**
  * @brief  帮助文本，也用于命令没带参数时的提示
  */
const char *Reg_Shell_Help(void);

#ifdef __cplusplus
}
#endif

#endif /* __REG_SHELL_H */
