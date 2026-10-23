---
id: paper-quick-understanding
name: 快速理解
description: 用播客开场、核心机制、同一故事和引言论证地图快速理解一篇论文，保存本地快照供后续测验与 Obsidian 归档复用。
version: 1
contexts: single-paper
activation: manual
---

读取系统给出的 Paper learning local resources 下当前 note-template.md 和 references/workflow.md、writing.md、narrative.md。使用当前选择的服务商，按工具结果多轮完成任务。

先核对论文身份，执行 quick_review.py find。命中同一 PDF 时复用已有解释、故事、图像和逐段证据，只补缺口。使用 Zotero 工具按需读取 PDF、真实引言段落和关键实验，裁取原文图。将真实段落边界与证据保存到工作目录。

生成模板 0–4 节笔记稿，聊天只展示以下四节：

1. 序：180–260 字科技播客开场。具体场景 → 冲突 → 旧办法的困境 → 作者直觉 → 悬念，不提前罗列方法。
2. 快速理解论文：核心问题、机制、3–5 步流程、关键实验及条件、适用边界。benchmark 与 baseline 明确对应。
3. 故事类比：一个连贯生活故事。先用小白语言讲清动作，再以专业术语说明对应机制。表格为「方法环节｜希望读者理解什么｜故事类比如何对应」。每行各用简洁完整的一句话，故事列沿用同一因果链。交代类比边界。
4. 包装技巧：解释作者如何把直觉变成可检验问题。Introduction 表格固定为「引言位置｜希望读者接受什么｜小白认知对比」。覆盖实际段落及列表子项；故事列接住上段疑问，用同一故事的一句话解释本段为何必要。最后给整体论证链。

摘要译文、自检答案、引言逐段六项详解、写作迁移、个人归档内容只写入笔记稿。聊天使用标准 Markdown，不输出 YAML、Obsidian callout、HTML 或工具过程。段落短，术语固定，数字含比较条件与出处。

交付前必须 publish 成独立快照，再读返回的 chatMarkdownPath 并输出正文。这个保存步骤是任务的一部分。未完成的笔记专属材料写入 pending；后续归档只补这些项。
