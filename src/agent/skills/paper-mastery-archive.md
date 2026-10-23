---
id: paper-mastery-archive
name: 掌握测验与本地归档
description: 复用论文快读快照，围绕核心机制和细节逐题测验，组织真实讨论、批注和思考，合并到本地 Markdown 统一笔记；使用 Obsidian 仓库时更新图片索引。
version: 2
contexts: single-paper
activation: manual
---

读取 Paper learning local resources 下当前 note-template.md 及 references/workflow.md、writing.md、narrative.md。遵循其中的输入 schema 和命令顺序。使用当前选择的服务商和实际工具。

1. 核对父条目、DOI 和 PDF，先执行 quick_review.py find。已有 0–4 节、故事、图像、证据直接复用；只补 pending、模板新增项和用户明确要求的更新。chatOnly 缓存也是已完成成果，不能重新生成已有正文。
2. 通过 context_read 和 library_read 收集真实讨论、反馈、批注、评论、笔记，按问题组织理解演变。用户观点、AI 建议和原文证据分别标明。不要逐字堆放日志或虚构用户结论。
3. 设计 5–10 题，通常 7 题，quizPolicy=paper-core-v1。核心机制和关键细节至少占半数，覆盖机制、决定性细节、实验依据和边界。每题附真实 PDF 页码、定位及短证据片段，干扰项对应合理误解。按 next → request_user_input → 等待 → answer 顺序逐题进行，恢复时沿用已有进度。
4. 按模板生成 0–9 节。0–4 节用于快速唤起记忆，5–8 节重点组织用户思考及实际测验反馈，9 节由用户填写。只引用真实裁图，保留同一故事。归档字段 benchmark、baseline 给出原文名称和必要条件；故事类比用一句话保留困难、动作、结果；methodFigure 使用真实原文方案图。
5. 先 lookup 已有笔记，读取内容和图片，用 notePath + sha256 保护合并。archive 通过三方合并保留个人补充、属性和图片，存在冲突则保留原文并让用户决定。回读验证后给可点击笔记链接。

归档目录中一篇论文只保存整理后的 Markdown 笔记和正文引用图片。普通文件夹直接保存 Markdown；未配置目录时使用系统给出的默认 notes 目录。Obsidian 是可选的，仅当目录含 .obsidian 时生成共享索引，显示可点击论文名、benchmark、baseline、故事类比和方案图预览，采用不分组的展开表格。返回 notePath 的本地文件链接；助手返回 obsidianUrl 时可同时提供。原始 PDF、工作证据、原始讨论、测验状态和备份保存在工作目录。
