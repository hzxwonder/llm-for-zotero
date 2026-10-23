---
id: paper-deep-reading
name: 论文透视
description: 用证据还原论文的问题、方法、公式、实验和局限，按用户已有知识解释关键机制并保存可复用材料。
version: 1
contexts: single-paper
activation: manual
---

先读取 Paper learning local resources 下 references/writing.md 与 narrative.md。使用当前选择的模型和 Zotero 论文工具。这个工作流借鉴 paper-xray 的怀疑式审读方法（https://github.com/Wang-auspicious/paper-xray），以下指令为独立编写的 Zotero 工作流。

先确认当前论文及用户的具体问题。已知背景从讨论中获取，缺失且影响深度时只问一个关键问题。先查本地已完成成果，再有针对性地读取原文，不把整个 PDF 转成 TXT 后一口气生成。

围绕「问题为什么成立 → 旧方法为何受限 → 关键洞察 → 模块怎样协作 → 实验支持什么 → 什么仍未证明」解释。每个公式说明变量、单位、假设、计算步骤和具体示例。没有原文支持的实现建议标为推断，不杜撰超参数或实验数值。

逐项检查主结果、baseline 公平性、benchmark 覆盖、消融和失败条件。区分作者主张、证据与自己的分析。引用关键页码、章节、表图，裁取真正相关的原文图；整页图仅作定位预览。

按工具返回的缺口继续阅读，及时保存已核验的材料和图像，后续追问直接复用。讲清直觉和实现中的决定性细节。短句、固定术语、短段落；最终交付解释，不附工具过程。
