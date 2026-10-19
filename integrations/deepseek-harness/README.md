# DeepSeek Harness for Zotero

DeepSeek Harness 在 Agent 设置中提供独立卡片，用于执行多步任务。Harness 负责模型循环与工具调度；Zotero 负责工具校验、Safe / Auto / Yolo 审批、变更凭据、历史记录和撤销。模型、API 地址和 API 密钥来自聊天面板中选中的服务商。

## 安装与启用

需要 Node.js `^22.19.0 || >=24.0.0`，以及支持工具调用的 OpenAI Chat Completions 兼容服务商。

在仓库根目录安装工作进程依赖：

```sh
npm ci --ignore-scripts --prefix integrations/deepseek-harness
```

安装构建生成的 XPI 后，进入 Zotero 设置 → LLM-for-Zotero → Agent → DeepSeek Harness：

1. 开启 **DeepSeek Harness** 卡片的开关。原生 Agent 和 Harness 共用聊天中的 Agent 按钮，开启其中一个会选中对应引擎。
2. “Node 可执行文件”填写 Node 的绝对路径，可通过 `node -p process.execPath` 查看。
3. “Harness 工作进程脚本”填写本目录 `worker.mjs` 的绝对路径。
4. 在聊天面板选择服务商及模型，开启 Agent 后发送任务。权限与网页搜索配置位于原生 Agent 卡片中。

工作进程目录应保留在稳定位置，并保留其 `node_modules`。更新时，安装同一构建中的 XPI 和工作进程依赖，然后重启 Zotero。执行引擎选择对 Original Agent 的侧栏、独立窗口和扩展 API 生效。默认使用内置执行引擎。

## 接入方式与研究依据

采用官方 `@deepseek-ai/dsh-agent-loop` 等内核包，以 **0.2.0-rc.2** 锁定版本及依赖。Zotero 的 Firefox 运行环境通过原有 Gecko Subprocess 能力启动 Node 工作进程，使用私有标准输入/输出管道交换请求、流事件与工具结果。

官方 TypeScript SDK 使用 Node 子进程；ACP 提供会话、取消和审批协议。此集成直接组合官方 Agent、Session、SystemPrompt、Tools、LLM 和 AgentLoop 服务，使现有 Zotero 工具注册表成为每次调用的执行入口，保留完整的原生工具目录和原生权限评估。

每轮创建独立的内存会话，按角色回放 Zotero 提供的用户与助手历史。轮次结束后回收进程，持久记录保存在 Zotero 中。工作进程加载限定的 agent 内核和模型适配器，工具能力由 Zotero 当前轮次提供。凭据通过进程管道传递，在工作进程内存中用于当前服务商认证。

当前支持文本上下文和 Zotero 工具读取论文。内联图片、原生文件上传及其他 API 协议会显示明确的兼容性提示。每轮模型运行预算为十分钟。等待 Zotero 工具或用户回答时暂停计时，工具结束后使用剩余预算继续。模型和工具失败返回错误。用户停止、会话清除及插件关闭均受执行期检查约束。

## 自动压缩

工作进程加载官方 TokenMeter、ToolResultPruner 和 BasicCompaction 组件。上下文容量使用 Zotero 当前模型的解析结果；用户设置的输入容量优先。输出上限沿用本轮配置。

每个模型步骤开始前，Harness 检查历史、系统提示和工具定义的估算用量。接近容量的 80% 时触发压缩；输出预留和安全余量可以使压缩提前发生。工作进程先裁剪大型工具结果，再按需用当前服务商和模型生成摘要。摘要保留任务、约束和后续步骤，近期消息继续保留。压缩不会拆开工具调用与结果的配对。

服务商明确返回上下文超限时，Harness 尝试压缩并重试一次模型请求。该重试沿用已经完成的工具结果。压缩失败、取消或再次超限时，运行返回错误。认证错误和普通服务错误沿用原有错误处理。

聊天中显示自动压缩标记。用量统计包含成功提交的摘要请求。压缩修改当前工作进程提供给模型的上下文，Zotero 中的完整对话记录继续保留。

摘要仍需模型处理。如果单条当前输入、系统提示或工具定义本身过大，或摘要请求也超过服务商上限，压缩无法保证继续运行。用户应将这类输入拆成较小任务，或用工具按需读取资料。

官方参考：

- [Harness 仓库与 MIT 许可证](https://github.com/deepseek-ai/deepseek-harness)
- [AgentLoop 服务](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/core/agent-loop)
- [工具注册与执行管道](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/core/tools)
- [OpenAI 兼容模型适配器](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/llm/llm-pi-ai)
- [TypeScript SDK](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/sdk/client)
- [ACP 接口](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/acp/acp)

## 验证

```sh
npm ci
npm run build
npm run test:harness
```

协议测试运行真实 Harness 循环和本地模拟模型，覆盖工具调用后的继续推理、角色历史、文本流、错误结果、取消、密钥脱敏、历史压缩、工具结果裁剪、超限重试、摘要失败和重复操作防护。

真实服务商测试通过独立的 Zotero 测试配置运行，并创建临时论文和笔记：

```sh
ZOTERO_PLUGIN_ZOTERO_BIN_PATH=/absolute/path/to/zotero \
LLM_FOR_ZOTERO_LIVE_PROFILE_PATH=/absolute/path/to/prefs.js \
LLM_FOR_ZOTERO_LIVE_MODEL=deepseek-flash \
npm run test:harness:live
```

测试从指定配置读取模型凭据，向该模型发起真实请求。覆盖论文搜索与摘要读取、Safe 模式拒绝写入、批准后笔记落库、历史信息回读、长历史压缩后继续读取文献和运行中停止。报告写入 `tmp/deepseek-harness-provider-b.json`，仅包含模型名称、场景和验证结果。

2026-10-19 验证：协议测试 **13/13 通过**。服务商 B 的 `deepseek-flash` 在独立 Zotero 测试配置中 **6/6 通过**，包含长历史自动压缩、口令保留和压缩后继续读取文献。日常 Zotero 使用同一服务商完成 FreeToken 原 PDF 第 1 页读取。
