# PCB 设计规则

以下规则用于检索辅助审查，不是自动 DRC 判定。每条规则都说明所需证据；缺少证据时只能提出待核查项。

## Connectivity Rule #1 — 复查 EDA 连接性错误
Category: Signal
Keywords: DRC, 连接性错误, Connection Error, 未连接, 飞线, 布线, 网络
Source: https://prodocs.lceda.cn/cn/pcb/design-check-drc/
RequiredEvidence: native_drc
ApplicableDrc: Connection Error

嘉立创 EDA 的连接性错误表示同一网络的对象尚未通过导线等完成连接。应在 DRC 面板定位具体错误及网络，完成布线后重新检查。铺铜孤岛也可能参与此类提示，需结合板上对象判断是否应忽略；仅共享网络名不能证明已布通。

## Clearance Rule #1 — 按当前设计规则复核间距
Category: Layout
Keywords: DRC, Clearance Error, 间距错误, 器件, 焊盘, 铜箔, 导线, 最小间距
Source: https://prodocs.lceda.cn/cn/pcb/design-design-rule/
RequiredEvidence: native_drc
ApplicableDrc: Clearance Error

原生间距错误说明对象不满足当前启用的间距规则。以本次 DRC 的对象、实测值、单位和规则名称为依据；阈值来自当前工程规则，不是知识库统一规定。外部工程导入后，应先核对原工程约束、导入规则与制造要求，再决定调整布局或规则；不能把当前报错数直接认定为原设计缺陷数。修改后重跑原生 DRC。

## Keepout Rule #1 — 核对禁止区域与对象重叠
Category: Layout
Keywords: DRC, Clearance Error, 禁止区域, Prohibited Region, 重叠, 导线, 约束, 工艺
Source: https://prodocs.lceda.cn/cn/pcb/place-prohibited-region/
RequiredEvidence: native_drc
ApplicableDrc: Clearance Error

禁止区域可对指定图层和对象施加限制。原生 DRC 报告对象与禁止区域重叠时，先核对区域的禁止对象类型、图层、定义与原设计用途。未取得这些约束时，不能推断违反的电气标准，也不应直接取消禁止区域来清零。确认适用条件后处理相关对象，再重新检查。

## Via Size Rule #1 — 核对过孔尺寸与工程规则
Category: Layout
Keywords: DRC, Physical Error, Via Size, 物理错误, 过孔, 内径, 外径, 孔径, 尺寸规则
Source: https://prodocs.lceda.cn/cn/pcb/design-design-rule/
RequiredEvidence: native_drc
ApplicableDrc: Physical Error

过孔尺寸检查以当前工程规则中配置的内径、外径等约束为准。应保留原生 DRC 的数值、单位与规则范围，结合原工程配置及板厂能力确认其适用性。导入工程的默认规则可能与原约束不同；不能仅因当前内径报错就断言孔无法制造，也不能随意放宽规则或扩大孔径。确认约束后再处理并重新检查。

## Power Integrity Rule #1 — 连续的供电与回流路径
Category: Power
Keywords: 电源完整性, PDN, 电源层, 地层, GND, 回流, 电机供电
Source: https://www.ti.com/lit/an/sprace6/sprace6.pdf
RequiredEvidence: copper, stackup, design_current, traces

供电与地参考应结合实际叠层规划，尽可能为电流提供连续、低阻抗的路径。审查电源分配时，应查看电源和地的铜皮、过孔、负载位置及回流路径。仅有层名称或网络名称，不能证明平面连续或电源完整性合格。

## Power Integrity Rule #2 — 开关电源的高 di/dt 回路
Category: Power
Keywords: 开关电源, DC-DC, Buck, 电机驱动, MOSFET, 高 di/dt, 热回路
Source: https://www.ti.com/lit/an/snva054c/snva054c.pdf
RequiredEvidence: schematic, components, pads, traces, copper

开关电源的高 di/dt 回路需要在布局和铜线设计中尽量缩小。应结合原理图与实际元件位置、走线和回流路径确认关键回路；单凭元件表与网络名不能断言回路面积过大。

## Decoupling Rule #1 — 去耦电容靠近供电引脚
Category: Power
Keywords: 去耦, 旁路, MCU, VDD, VCC, 电容, 电源引脚
Source: https://www.ti.com/lit/pdf/spraav0
RequiredEvidence: schematic, components, pads, traces

去耦电容应按器件数据手册选型并靠近其服务的供电引脚，减少供电路径寄生电感。检查时需要引脚到电容的拓扑、元件位置和连接方式；元件列表中的电容数量无法单独证明去耦布局质量。

## Decoupling Rule #2 — 去耦连接的低电感回路
Category: Power
Keywords: 去耦电容, 接地过孔, 电源过孔, 电感, 回路, 电源完整性
Source: https://www.ti.com/lit/an/sloa069/sloa069.pdf
RequiredEvidence: pads, traces, vias, stackup

去耦路径应减少连接长度和寄生电感，关注电容到供电引脚和地参考的连接。需要查看实际铜线、过孔和叠层；不能根据电容封装或名称推断连接电感。

## MCU Layout Rule #3 — 晶振靠近 MCU
Category: Layout
Keywords: MCU, STM32, 晶振, 晶体, OSC_IN, OSC_OUT, XTAL, 时钟
Source: https://www.st.com/resource/en/application_note/an2867-guidelines-for-oscillator-design-on-stm8afals-and-stm32-mcusmpus-stmicroelectronics.pdf
RequiredEvidence: components, pads, traces, schematic

若设计使用外部晶振，应依所用 MCU 的官方布局指南将晶振靠近振荡器引脚，并保持相关连接短。ST AN2867 对 STM32 等器件给出此建议。要判断“晶振距离过远”，必须核对具体器件约束、振荡器引脚和相关走线；坐标只支持平面距离测量，不能单独作为违规判据。

## MCU Layout Rule #4 — 晶振网络避开高频干扰
Category: Layout
Keywords: MCU, 晶振, 晶体, 时钟, OSC, 高速信号, 电磁干扰
Source: https://www.st.com/resource/en/application_note/an2867-guidelines-for-oscillator-design-on-stm8afals-and-stm32-mcusmpus-stmicroelectronics.pdf
RequiredEvidence: components, traces, copper, stackup

振荡器路径应按器件指南与高频干扰路径保持合适隔离，并核对参考地。要判断是否受干扰，需查看布局、走线及地参考；仅有网络名不能证明隔离是否充分。

## Trace Width Rule #1 — 线宽取决于电流和温升
Category: Power
Keywords: PCB线宽, 走线宽度, 电流, 铜厚, 温升, 电机驱动, 电源线
Source: https://www.ti.com/lit/an/snva054c/snva054c.pdf
RequiredEvidence: traces, stackup, design_current

导线载流能力与线宽、铜厚、内外层、环境散热及允许温升有关。先取得设计电流、实际铜厚、目标温升和走线几何，再结合制造商与适用标准核算；不能仅根据网络名给出固定线宽或判定线宽不足。

## Trace Width Rule #2 — 审查压降与连接瓶颈
Category: Power
Keywords: 线宽, 压降, 电源, 过孔, 铜厚, 电阻, 供电
Source: https://www.ti.com/lit/an/snva054c/snva054c.pdf
RequiredEvidence: traces, vias, stackup, design_current

高电流供电路径还应检查走线电阻、压降和连接处瓶颈。需要路径长度、线宽、铜厚、过孔以及负载电流；应按本次采集的覆盖状态识别缺失数据，而不能从网络名推断这些量。

## EMC Rule #1 — 保持信号回流路径连续
Category: EMC
Keywords: EMC, EMI, 回流路径, 地平面, 地分割, 辐射, 信号完整性
Source: https://www.ti.com/lit/pdf/SCAA082A
RequiredEvidence: traces, copper, stackup

信号回流路径若被参考平面的裂缝或空洞迫使绕行，回路面积可能增大并影响辐射和信号质量。应检查走线下方的参考平面与跨分割情况；仅有层名称不能证明回流路径连续。

## EMC Rule #2 — 减小高频开关回路面积
Category: EMC
Keywords: EMC, EMI, DC-DC, 电机驱动, 开关节点, 高 di/dt, 回路面积
Source: https://www.ti.com/lit/an/snva054c/snva054c.pdf
RequiredEvidence: schematic, components, traces, copper, operating_frequency

高频开关电流回路宜缩小面积并控制开关节点铜区。确认风险需要实际布局、铜形状、电流路径与工作频率；不能从出现电机或 DC-DC 元件名称直接判断 EMC 不合格。

## High-Speed Rule #1 — 高速信号保持连续参考平面
Category: Signal
Keywords: 高速信号, USB, LVDS, 差分, 时钟, 参考平面, 回流, 地分割
Source: https://www.ti.com/lit/an/spraar7j/spraar7j.pdf
RequiredEvidence: traces, copper, stackup

高速信号应依接口和器件指南在连续的地参考上布线，尽量避免跨参考平面裂缝或空洞。是否满足需要实际走线、叠层与参考平面数据；网络名只能提示应检查此项。

## High-Speed Rule #2 — 差分对按接口约束设计
Category: Signal
Keywords: 高速信号, 差分对, USB, CAN, LVDS, 阻抗, 长度匹配, 过孔
Source: https://www.ti.com/lit/an/spraar7j/spraar7j.pdf
RequiredEvidence: traces, stackup, impedance, schematic

差分网络的阻抗、间距、长度与过孔约束应由具体接口标准、芯片手册和板厂叠层确定。仅凭 CAN_H/CAN_L、USB_D+/USB_D- 等名称可触发审查，不能推出阻抗或长度已经违规。
