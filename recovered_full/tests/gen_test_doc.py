# -*- coding: utf-8 -*-
"""生成测试用 DOCX 文档，用于验证知识库解析+切片+检索功能。"""
import os
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
style = doc.styles['Normal']
style.font.name = '微软雅黑'
style.font.size = Pt(11)

# ===== 封面 =====
title = doc.add_heading('智能家电客服知识手册', level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('版本：v2.6.1  |  更新日期：2026年8月  |  适用产品线：空调/洗衣机/冰箱/热水器')
run.italic = True
doc.add_paragraph('')

# ===== 第一章 =====
doc.add_heading('第一章  产品概述与型号对照', level=1)
doc.add_heading('1.1 产品线简介', level=2)
doc.add_paragraph(
    '本手册覆盖公司四大智能家电产品线：智能变频空调、滚筒洗衣机、风冷无霜冰箱、'
    '即热式电热水器。所有产品均接入 IoT 云平台，支持手机 App 远程控制、'
    '语音助手联动、故障自诊断推送。客服人员在处理用户咨询时，'
    '应首先通过用户提供的设备 SN 码或 App 绑定手机号在后台查询设备型号、'
    '固件版本、历史工单记录，以便精准定位问题。'
)

doc.add_heading('1.2 型号对照表', level=2)
table = doc.add_table(rows=7, cols=4)
table.style = 'Light Shading Accent 1'
hdr = table.rows[0].cells
hdr[0].text = '产品线'
hdr[1].text = '型号前缀'
hdr[2].text = '示例型号'
hdr[3].text = '上市年份'
rows_data = [
    ('变频空调', 'KFR-', 'KFR-35GW/Bp3', '2024'),
    ('滚筒洗衣机', 'XQG-', 'XQG100-B14', '2025'),
    ('风冷冰箱', 'BCD-', 'BCD-458WPC', '2024'),
    ('即热热水器', 'DSF-', 'DSF-85K3', '2025'),
    ('智能扫地机', 'XSW-', 'XSW-R3000', '2026'),
    ('空气净化器', 'KJ-', 'KJ-800FPro', '2025'),
]
for i, (a, b, c, d) in enumerate(rows_data):
    cells = table.rows[i + 1].cells
    cells[0].text = a
    cells[1].text = b
    cells[2].text = c
    cells[3].text = d

# ===== 第二章 =====
doc.add_heading('第二章  常见故障代码及处理方案', level=1)
doc.add_paragraph(
    '本章列举各产品线高频故障代码、现象描述、可能原因及标准处理流程。'
    '客服人员接到用户报修后，应先引导用户查看设备面板或 App 推送的故障代码，'
    '对照本章内容给出初步处理建议。如远程无法解决，再派单上门维修。'
)

doc.add_heading('2.1 空调故障代码', level=2)

doc.add_heading('E1 - 室内温度传感器故障', level=3)
doc.add_paragraph('现象描述：空调运行 3-5 分钟后停机，面板显示 E1，App 推送温度传感器异常。')
doc.add_paragraph('可能原因：室内温度传感器阻值漂移（开路或短路）；传感器连接线接触不良；主板采样电路故障。')
doc.add_paragraph(
    '处理步骤：1) 让用户断电等待 5 分钟后重新上电，观察是否复现；'
    '2) 如复现，引导用户进入 App 设备诊断页面查看传感器实时阻值，'
    '正常范围 5kOhm 至 15kOhm（25度时约 10kOhm）；'
    '3) 阻值异常则派单更换传感器组件（备件号：SEN-RT01），'
    '预计上门费 80 元 + 配件费 45 元。'
)

doc.add_heading('E2 - 室内外通讯故障', level=3)
doc.add_paragraph('现象描述：室内机正常运行，室外机不启动，3 分钟后面板显示 E2。')
doc.add_paragraph('可能原因：内外机连接线松动或断路；室外机通讯模块损坏；强电磁干扰导致通讯丢包。')
doc.add_paragraph(
    '处理步骤：1) 确认用户家是否近期装修或雷雨天气后出现；'
    '2) 引导用户检查内外机连接线端子是否锈蚀（L/N/S 三线，S 为通讯线）；'
    '3) 如端子正常，尝试断电 10 分钟彻底放电后重启；'
    '4) 仍不恢复则派单检测室外机主板通讯模块，预计维修费 200-350 元。'
)

doc.add_heading('E3 - 压缩机过热保护', level=3)
doc.add_paragraph('现象描述：制冷效果明显下降，外机噪音增大，运行约 15 分钟后停机显示 E3。')
doc.add_paragraph('可能原因：外机散热器被异物遮挡（树叶、塑料袋）；冷媒泄漏导致压缩机负荷增大；室外环境温度超过 45 度。')
doc.add_paragraph(
    '处理步骤：1) 询问用户外机安装位置是否有遮挡，引导清理散热器表面；'
    '2) 确认近期制冷效果是否逐月下降（冷媒缓慢泄漏的典型特征）；'
    '3) 如清理后仍报 E3，需派单检测冷媒压力并补充 R32 冷媒，'
    '预计费用：冷媒补充 280 元 + 抽真空 100 元 + 上门费 80 元。'
)

doc.add_heading('2.2 洗衣机故障代码', level=2)

doc.add_heading('F1 - 进水超时', level=3)
doc.add_paragraph('现象描述：选择洗涤程序后 8 分钟内未达到设定水位，显示 F1 并报警。')
doc.add_paragraph('可能原因：水龙头未完全打开或停水；进水阀过滤网堵塞；水压过低（低于 0.02MPa）。')
doc.add_paragraph(
    '处理步骤：1) 引导用户检查水龙头是否打开、水管是否被压扁；'
    '2) 拧下进水管检查过滤网是否有杂质，用清水冲洗后装回；'
    '3) 如仍超时，派单检测进水阀线圈阻值（正常 4kOhm 至 6kOhm），'
    '异常则更换进水阀组件（备件号：VAL-INW03，配件费 60 元）。'
)

doc.add_heading('F3 - 排水故障', level=3)
doc.add_paragraph('现象描述：洗涤结束后排水超过 6 分钟，显示 F3。')
doc.add_paragraph('可能原因：排水泵被硬币或纸屑堵塞；排水管弯折或过长（超过 3 米）；排水泵叶轮损坏。')
doc.add_paragraph(
    '处理步骤：1) 引导用户打开洗衣机底部小盖板，旋开排水泵排污口清理异物（注意底下放毛巾接水）；'
    '2) 检查排水管走向是否顺畅；'
    '3) 清理后仍排水慢则派单更换排水泵（备件号：PMP-DR02，配件费 85 元）。'
)

doc.add_heading('2.3 冰箱故障代码', level=2)

doc.add_heading('d5 - 化霜传感器异常', level=3)
doc.add_paragraph('现象描述：冷冻室温度逐渐升高至 -10 度以上，App 推送化霜异常预警。')
doc.add_paragraph('可能原因：化霜传感器开路；化霜加热丝断路（阻值应为 150Ohm 至 200Ohm）；电脑板化霜继电器粘连。')
doc.add_paragraph(
    '处理步骤：1) 引导用户手动启动强制化霜模式（同时按住冷冻加冷藏键 5 秒），'
    '观察 30 分钟内化霜加热丝是否工作；'
    '2) 无声则派单检测加热丝阻值；'
    '3) 更换化霜加热丝组件预计费用 180 元。'
)

doc.add_heading('2.4 热水器故障代码', level=2)

doc.add_heading('H1 - 漏电保护触发', level=3)
doc.add_paragraph('现象描述：使用热水时突然断电，漏电保护插头跳闸，面板闪烁 H1。')
doc.add_paragraph('可能原因：加热管绝缘层老化导致漏电；内部水管接头渗水接触到电气元件；用户家接地线接触不良。')
doc.add_paragraph(
    '处理步骤：1) 安全提醒：让用户立即断开电源，不要触碰带电部件；'
    '2) 询问是否近期有搬家或装修导致水路改动；'
    '3) 派单检测加热管绝缘阻值（应大于 2MOhm），低于 0.5MOhm 必须更换加热管（备件号：HTC-85K，配件费 120 元）。'
)

# ===== 第三章 =====
doc.add_heading('第三章  客服话术规范与处理流程', level=1)

doc.add_heading('3.1 标准开场白', level=2)
doc.add_paragraph(
    '标准模板：您好，欢迎使用 XXX 智能家电 7 乘 24 客服服务，我是客服专员工号 XXXX，'
    '请问有什么可以帮您？ 注意语速适中（每分钟 180-200 字），'
    '语调上扬结尾，让用户感受到热情。避免使用 喂 、 你说 等随意用语。'
)

doc.add_heading('3.2 投诉处理四步法', level=2)
doc.add_paragraph(
    '第一步【倾听】：完整听取用户描述，不打断，记录关键词（故障现象、发生时间、设备型号）。'
    '第二步【共情】：用 我理解您的心情，这个问题确实影响使用了 等话术建立信任。'
    '第三步【方案】：给出明确的处理方案和时间节点，如 我现在帮您安排师傅明天上午 9-12 点上门检测。'
    '第四步【确认】：复述处理方案，确认用户无异议后结束通话，并在 30 分钟内录入工单系统。'
)

doc.add_heading('3.3 超时与升级标准', level=2)
doc.add_paragraph(
    '一级问题（设备完全无法使用）：4 小时内响应，24 小时内上门。'
    '二级问题（部分功能异常但可临时使用）：8 小时内响应，48 小时内上门。'
    '三级问题（咨询/使用指导）：24 小时内响应，无需上门。'
    '如用户对处理结果不满意并要求升级，客服应主动转接至主管（分机 8001），'
    '不得与用户争辩或暗示公司规定就是这样。'
)

# ===== 第四章 =====
doc.add_heading('第四章  FAQ 常见问题解答', level=1)

doc.add_heading('Q1：保修期是多久？哪些情况不在保修范围内？', level=2)
doc.add_paragraph(
    '整机保修 3 年，主要部件（压缩机、电机、电脑板）保修 6 年。'
    '不在保修范围的情况：人为损坏（进水、摔落、自行拆机）；'
    '使用环境不符合说明书要求（如电压不稳、无接地线）；'
    '非授权人员维修过的设备；自然灾害（雷击、洪水）。'
)

doc.add_heading('Q2：如何申请退换货？', level=2)
doc.add_paragraph(
    '购机 7 天内出现性能故障可全额退款，15 天内可换同型号新机。'
    '需提供购机发票或电子订单截图加设备 SN 码。'
    '退换货流程：用户在 App 我的-售后服务提交申请，客服 2 小时内审核，'
    '快递上门取件（运费由公司承担），收到旧机检测确认后 3 个工作日内退款到原支付账户。'
)

doc.add_heading('Q3：智能设备无法连接 Wi-Fi 怎么办？', level=2)
doc.add_paragraph(
    '排查步骤：1) 确认 Wi-Fi 为 2.4GHz 频段（暂不支持 5GHz）；'
    '2) 确认密码输入正确（注意大小写和特殊字符）；'
    '3) 设备与路由器距离不超过 5 米且中间无承重墙；'
    '4) 重置设备网络模块：通电状态下长按配网键 10 秒至指示灯快闪，'
    '然后在 App 重新配网；'
    '5) 如仍无法连接，检查路由器是否开启了 AP 隔离（需关闭）。'
)

doc.add_heading('Q4：设备固件升级失败怎么办？', level=2)
doc.add_paragraph(
    '升级失败通常由网络波动或中途断电导致。处理方式：'
    '1) 确保设备电量充足（或保持通电）且 Wi-Fi 信号稳定；'
    '2) 在 App 设备设置-固件升级中点击重试；'
    '3) 连续 3 次失败则暂停升级，派单由维修人员通过专业工具线下刷写固件，'
    '预计上门费 80 元（保修期内免费）。'
)

# ===== 保存 =====
desktop = os.path.join(os.environ.get('USERPROFILE', r'C:\Users\Administrator'), 'Desktop')
output_path = os.path.join(desktop, '智能家电客服知识手册.docx')
doc.save(output_path)

total_chars = sum(len(p.text) for p in doc.paragraphs)
print(f'文档已保存: {output_path}')
print(f'文件大小: {os.path.getsize(output_path)} bytes')
print(f'正文字符数: {total_chars}')
print(f'段落数: {len(doc.paragraphs)}')
print(f'表格数: {len(doc.tables)}')
