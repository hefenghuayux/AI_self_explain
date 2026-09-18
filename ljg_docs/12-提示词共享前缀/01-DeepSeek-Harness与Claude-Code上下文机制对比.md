# DeepSeek Harness 与 Claude Code 的上下文机制对比

编写日期：2026-09-16

## 结论先行

DeepSeek Harness 和 Claude Code 都没有把“会话历史”直接等同于“本次发给模型的上下文”。它们实际维护了三层内容：

1. 可持久化、可恢复的原始记录；
2. 从原始记录派生出的模型可见视图；
3. 供应商真正用于前缀缓存的请求序列。

两者的共同原则是稳定内容靠前、变化内容靠后、正常对话尽量追加，只有上下文压力变大时才替换或摘要旧内容。区别在于：DeepSeek Harness 把这套规则做成了较清楚的事件日志、surface 投影和压缩事务；Claude Code 为超长编码会话叠加了更多局部清理、缓存断点、缓存编辑和多级压缩机制。

若目标是 AI 自讲 Demo，建议以 DeepSeek Harness 的结构作为主干，吸收 Claude Code 的工具排序、预算控制和命中率观测。Claude Code 的全套上下文治理适合大型编码代理，对当前业务偏重。

对于“原因 A 的引导例子下一轮换成原因 B，并且 A 不应继续出现在模型上下文”这一具体场景，推荐结构是：

```text
稳定 system / tools
+ 可长期保留的业务对话
+ 当前轮任务数据
+ 当前轮一次性引导例子
```

下一轮重新构造模型视图时去掉 A、放入 B。这样会使缓存从 A 出现的位置开始失配，但 A 已经位于尾部，受影响的是较短的尾部，前面的稳定 system 和大部分历史仍有机会命中。这里存在一个无法绕开的取舍：保留 A 能得到更长缓存前缀，但会违背“A 后续不再出现”的语义要求；删除 A 会损失一小段尾部缓存。对教学场景，语义正确性应优先。

---

## 一、先区分三个容易混淆的概念

### 1. 原始记录

原始记录负责审计、恢复和复盘。它可以包含旧消息、压缩标记、被替换内容、工具结果和错误恢复信息。原始记录仍然存在，不等于模型每轮都能看到它。

### 2. 模型可见视图

模型可见视图是本轮请求真正使用的上下文。它可以从某个压缩边界开始，也可以把一段旧历史换成摘要，或把过大的工具结果换成占位文本。

### 3. 供应商缓存前缀

供应商按实际请求内容判断缓存。只要较早位置发生变化，变化点之后的内容通常不能继续沿用原来的前缀缓存。

DeepSeek 官方文档当前说明：上下文硬盘缓存默认开启；每个请求都会触发缓存构建；后续请求只有完整匹配已落盘的“缓存前缀单元”才能命中。缓存前缀可在输入结束、输出结束、公共前缀检测以及长内容的固定 token 间隔处落盘。缓存是尽力而为，构建需要秒级时间，不再使用后通常在数小时到数天后清理。命中情况通过 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens` 返回。

这意味着“内容放到后面”只能缩小失效范围，不能让一段已删除或已替换的内容继续命中。

官方说明：[DeepSeek 上下文硬盘缓存](https://api-docs.deepseek.com/zh-cn/guides/kv_cache/)

---

## 二、DeepSeek Harness 的上下文结构

### 2.1 逻辑结构

DeepSeek Harness 的单次请求可以概括为：

```text
请求配置与路由
├─ provider / model / generation config
├─ 有序、规范化的 tool schemas
└─ 从 session surface 派生的 messages
   ├─ system prompt 节点
   ├─ 已保留的 user / assistant / tool 历史
   ├─ 当前用户输入
   └─ 当前 runtime-context 快照（有变化时追加）
```

它的核心设计是维护仅追加的 session 事件日志，再由 surface 决定哪些消息节点对模型有效，而非直接修改一个长期存在的 `messages[]`。请求发出前，`session.deriveMessages()` 从当前 surface 生成本轮消息数组。

### 2.2 System Prompt 如何保持稳定

系统提示词由多个 `PromptSection` 组成：

- 按 `order` 升序拼接；
- `order` 相同时按 section 名称排序；
- 工具也在组装阶段进入规范顺序；
- 变量插值在最终渲染时完成。

固定排序很重要。即使内容集合相同，只要顺序每轮漂移，序列化后的请求也会变化，缓存前缀就不稳定。

系统提示词在模型视图中有一个明确的投影策略：

- 首次使用时，在 surface 头部创建 system 节点；
- 内容未变化时，不写入新节点；
- 路由支持在历史中更新 system、并且当前请求仍属于同一序列时，变化后的 system 可以追加在已有历史后面；
- 路由不支持这种更新、请求序列已经断开、工具集合变化或 surface 发生替换时，会归一化头部 system，并清空后续仍生效的旧 system 节点。

这套机制兼顾了两个目标：平时不改动长前缀；确实需要重建请求序列时，保证 system 语义只有一个权威版本。

### 2.3 动态 Runtime Context 如何加入

`PromptContext` 与 `PromptSection` 分开管理。动态上下文不会直接拼进 system prompt，而是渲染成一条 user 角色的 runtime-context 快照。

每个 step 的顺序是：

```text
从 inbox 领取本轮消息
→ 组装 system sections、contexts 和 tools
→ 渲染 runtime-context
→ 若快照有变化，将它放在本轮消息尾部
→ 将 system 更新和本轮 user 消息追加到 session
→ 从 surface 派生完整请求
```

快照没有变化时不重复追加；从有内容变成无内容时，会追加一条明确的清除声明，告诉模型较早的 runtime-context 已经不再适用。

这个设计对缓存很友好，因为它不回头修改旧历史。代价是旧快照仍可能留在模型视图中，只是由更新的快照覆盖语义。它适合“最新状态覆盖旧状态”的动态信息；若业务要求旧内容下一轮必须完全不可见，就不能直接照搬这一策略。

### 2.4 普通对话和工具结果如何加入

当前用户消息、assistant 输出、工具调用结果都采用追加方式写入：

```text
user message
→ assistant message / tool call
→ tool result（作为下一 step 的 user 内容）
→ assistant message
→ 下一轮 user message
```

请求配置和工具 schema 会形成规范化 header。header、surface 替换代次或显式的请求序列标记发生变化时，Harness 会记录新 series；正常情况下，新请求只是旧请求的尾部扩展。

仓库中的真实 API 测试覆盖了这一点：第一次请求后，工具续轮和后续用户轮都要求 `cacheReadTokens > 0`。DeepSeek 适配器会把供应商的 `prompt_cache_hit_tokens`，或兼容字段中的 `cached_tokens`，映射成统一的 `cacheReadTokens`。

---

## 三、DeepSeek Harness 如何压缩和“删除”上下文

### 3.1 先剪大工具结果

在生成摘要前，可以先运行独立的 tool-result pruner。默认策略是：

| 配置               | 默认值 | 含义                       |
| ------------------ | -----: | -------------------------- |
| `thresholdChars` |   8192 | 合并文本超过该字符数才剪枝 |
| `headChars`      |   4096 | 保留开头字符数             |
| `tailChars`      |   1024 | 保留末尾字符数             |

它用带标记的头尾内容替换原工具结果，既保留定位线索，也降低摘要和后续请求的 token 压力。替换记录会引用原事件，原始内容仍可审计。

### 3.2 再按压力选择压缩范围

`compaction-basic` 默认在路由上下文窗口的 80% 附近触发压力压缩，并尽量逐字保留最近 16% 的内容。实际值可以按模型覆盖。

范围选择有两个约束：

- 从较老的内容开始压缩，保留最近尾部；
- 不在未闭合的工具调用与工具结果之间切断。

如果工具结果剪枝已经让请求回到安全范围，系统可以不再调用摘要模型。

### 3.3 摘要本身也尽量复用缓存

摘要调用会逐字回放当前 system、工具定义和待压缩的历史，然后把压缩指令追加在最后。这样摘要请求本身也可以复用当前会话的热前缀。

生成的摘要必须确实比原范围更小，否则拒绝落地。默认摘要输出上限为 8192 token。

### 3.4 压缩以事务方式落地

一次完整压缩大致是：

```text
compaction/start
→ 验证 surface 与锁
→ 生成摘要
→ 再次验证待替换范围未变化
→ compaction/summary
→ 追加一条摘要 user message，并 replace 旧 surface 范围
→ compaction/end
```

这里的“删除”是模型视图中的遮蔽：旧节点仍在事件日志里，surface 中对应范围被一个摘要节点替代。这样既能恢复和审计，也能让后续请求只携带摘要。

### 3.5 DeepSeek Harness 的上下文生命周期

| 内容                       | 加入方式                         | 何时离开模型视图                   | 原始记录是否保留 |
| -------------------------- | -------------------------------- | ---------------------------------- | ---------------- |
| system prompt              | 首次创建；必要时追加或归一化替换 | system 重建或相关 surface 替换时   | 是               |
| 普通 user / assistant 消息 | 尾部追加                         | 被压缩范围覆盖时                   | 是               |
| runtime-context 快照       | 变化时尾部追加                   | 被后续快照语义覆盖；最终随压缩离开 | 是               |
| 工具结果                   | 尾部追加                         | 可先被头尾剪枝，再随摘要压缩       | 是               |
| 压缩摘要                   | 替换旧 surface 范围              | 后续再次被压缩时                   | 是               |

---

## 四、Claude Code 的上下文结构

> 版本说明：以下结论来自本地 `D:\lijianguo\code\claude-code` 仓库。该仓库属于反编译、重建性质的代码，不应无条件等同于 Anthropic 官方当前版本。本文描述的是这份本地源码呈现出的机制。

### 4.1 逻辑结构

Claude Code 发给模型的上下文可以概括为：

```text
system prompt blocks
├─ attribution / CLI prefix
├─ 缓存化 system sections
└─ systemContext

tools
├─ 稳定排序的内置工具
├─ 稳定排序的 MCP 工具
└─ 追加在缓存标记后的动态工具

messages
├─ userContext（项目指令、环境上下文）
├─ 最近 compact boundary 之后的活动历史
├─ 当前 user / tool result
└─ 最后一条消息上的 cache_control 断点
```

Claude Code 同样保留完整 transcript，但请求循环首先调用 `getMessagesAfterCompactBoundary()`，只取最近压缩边界之后的活动消息。若启用 history snip，还会在这个视图上继续过滤被裁剪消息。

### 4.2 System Prompt 如何保持稳定

它把 system prompt 拆成命名 section：

- 普通 `systemPromptSection` 只计算一次，缓存到 `/clear` 或 `/compact`；
- 必须逐轮计算的 section 使用 `DANGEROUS_uncachedSystemPromptSection`；
- 该名称直接提醒开发者：值一旦变化，会破坏 prompt cache。

`systemContext` 追加在 system prompt 后面。项目级 `claudeMd` 与其他 `userContext` 则转换成前置 user 消息，放在活动历史前。

这比“每轮重新拼一整段 system”更严格。动态内容进入 system 层需要显式承担缓存代价。

### 4.3 Tools 如何组织

Claude Code 对工具顺序做了专门优化：

- 内置工具按名称排序，并保持为连续前缀；
- MCP 工具单独排序，放在内置工具之后；
- 同名时内置工具优先；
- advisor 等动态工具追加在已有工具缓存标记之后。

这样新增、删除一个 MCP 或 advisor 工具时，只扰动工具列表的后半段，不会连带破坏所有内置工具形成的稳定前缀。

### 4.4 消息如何加入

用户输入处理完成后，Claude Code 会把由该输入产生的消息和附件追加到 `mutableMessages`，并在调用模型前先持久化 transcript。assistant 消息和工具结果继续追加到同一会话链。

真正调用模型时，它会：

1. 从最近 compact boundary 派生活动消息；
2. 对活动消息执行预算、剪枝和压缩；
3. 在最前面加上 `userContext`；
4. 附加完整 system prompt 和 tools；
5. 规范化消息格式后发送。

原始 transcript 的职责是恢复和 UI 回看，API 请求的职责是给模型提供当前有效上下文，两者并不完全相同。

### 4.5 缓存断点如何布置

Claude Code 通过 Anthropic API 的 `cache_control` 显式布置缓存断点：

- system prompt 被拆成有限数量的缓存块；
- tool schemas 上有缓存标记；
- 每次请求只在一条 message 上设置 message-level 缓存断点，正常请求位于最后一条消息；
- fire-and-forget fork 会把断点移动到倒数第二条，也就是与父会话共享的最后位置；
- advisor 等动态 schema 被放到工具缓存断点之后；
- 动态 beta header 一旦在当前 session 开启，就保持开启，直到 `/clear` 或 `/compact`，避免 header 中途变化导致大前缀失效。

这套做法比 DeepSeek Harness 更依赖供应商提供的显式缓存能力，但对“缓存应该停在哪里”控制得更细。

---

## 五、Claude Code 如何压缩、裁剪和删除上下文

Claude Code 会按成本从低到高逐层处理上下文，完整摘要只是其中一层。

### 5.1 请求前的实际处理顺序

本地源码中的主顺序为：

```text
最近 compact boundary 后的活动历史
→ 删除仅供 UI 使用的旧 raw toolUseResult 字段
→ 对单条工具结果执行大小预算
→ history snip
→ microcompact
→ context collapse（当前仓库中仍有 stub / feature gate）
→ auto compact
→ predictive compact
→ API 调用
→ prompt-too-long 时 reactive compact 后重试
```

这些操作处理的问题不同，不能都理解为“总结历史”。

### 5.2 工具结果预算

`applyToolResultBudget` 处理单条或聚合工具结果过大的情况，并可持久化 content replacement 记录。它优先限制最容易失控的文件读取、搜索和命令输出，避免一个工具结果提前吃满窗口。

旧消息对象中的 `toolUseResult` 原始字段也会从 API 工作副本中移除。这个字段只服务于 UI 渲染；真正发给模型的 `tool_result` 内容仍在 message content 中。这里释放的是进程内存，并未删除模型上下文。

### 5.3 History Snip

History snip 对历史中段做裁剪，并记录边界。完整历史仍可供 UI 滚动和 transcript 恢复，模型视图通过 `projectSnippedView` 过滤被 snip 的消息。

它比完整摘要便宜，但被移除的细节不会自动转成自然语言摘要，因此更依赖裁剪策略正确选中低价值内容。

### 5.4 Microcompact

Microcompact 主要针对旧工具结果：

- 普通路径把旧内容替换成 `[Old tool result content cleared]`；
- 如果判断供应商缓存已经过期，可以在发送新请求前直接清理旧工具结果，减少冷缓存重写成本；
- cached microcompact 路径利用缓存编辑能力，通过 `cache_reference` 和 `cache_edits` 删除缓存前缀里的旧工具结果，同时保留可继续命中的其他部分。

缓存编辑是一种供应商相关的高级能力。它删除的是缓存中的引用内容，不等同于从 transcript 中物理删除原消息。

### 5.5 Context Collapse

Context collapse 试图把多段历史变成更细粒度的折叠视图，折叠摘要单独存储，读取时重放 commit log 形成模型视图。它的目标是在触发整段 auto compact 之前，先用较细的粒度释放空间。

不过本地仓库里这部分仍带明显的 feature gate 和 stub 痕迹，不能把它当成所有 Claude Code 版本都已稳定启用的能力。

### 5.6 Auto、Predictive 与 Reactive Compact

Auto compact 的触发阈值按以下方式计算：

```text
有效上下文窗口
- 为摘要输出预留的 token
- 根据窗口大小设置的安全 buffer
```

普通窗口默认保留 13,000 token 的 buffer，较大窗口会提高到 30,000 或 50,000。Predictive compact 还会估计下一轮模型输出和工具结果可能增长多少，提前判断是否需要压缩。若 API 已返回 `prompt_too_long`，Reactive compact 会作为恢复路径尝试压缩并重试。

完整 compact 生成：

```text
compact boundary
→ summary messages
→ 需要原样保留的最近消息
→ 重新生成的文件、工具、异步 agent 等附件
→ compact hook 结果
```

下一轮只从最新 boundary 开始读取。旧记录仍在 transcript 中，因此这里同样属于“活动视图切换”，并非直接擦除原历史。

### 5.7 Claude Code 中几种“删除”的区别

| 操作                           | 删除或替换的对象                | 是否影响模型视图     | 原 transcript 是否保留      |
| ------------------------------ | ------------------------------- | -------------------- | --------------------------- |
| 移除`toolUseResult` 原始字段 | UI 用的内存载荷                 | 否，API content 仍在 | 通常保留                    |
| tool result budget replacement | 过大的工具内容                  | 是                   | 通过 replacement 记录可追溯 |
| history snip                   | 被选中的历史片段                | 是                   | 是                          |
| microcompact                   | 旧工具结果正文                  | 是                   | 是或有 replacement 记录     |
| cache editing                  | 供应商缓存中的旧内容引用        | 是                   | 是                          |
| full compact                   | compact boundary 之前的活动历史 | 是，以摘要替代       | 是                          |

---

## 六、两套方案的直接对比

| 维度          | DeepSeek Harness                              | Claude Code                                                    | 评价                              |
| ------------- | --------------------------------------------- | -------------------------------------------------------------- | --------------------------------- |
| 基础抽象      | append-only 事件日志 + surface                | transcript + 多种活动视图投影                                  | Harness 更统一                    |
| system 稳定性 | 有序 section；变化时由 system 投影处理        | section 默认 memoize；动态 section 显式标危险                  | Claude Code 约束更强              |
| 动态上下文    | 变化时追加 user 快照                          | userContext、附件、reminder、delta 等多种形式                  | Harness 更容易理解；Claude 更灵活 |
| 工具稳定性    | 组装后使用规范顺序                            | 内置工具与 MCP 分区排序，动态工具放断点后                      | Claude Code 更精细                |
| 缓存控制      | 主要依赖字节级稳定前缀和供应商自动缓存        | 显式`cache_control`、单消息断点、header latch、cache editing | Claude Code 更强，也更绑定供应商  |
| 小型内容治理  | 大工具结果头尾剪枝                            | 工具预算、snip、microcompact 多级处理                          | Claude Code 更成熟                |
| 完整压缩      | 80% 默认触发，保留约 16% 尾部，范围替换为摘要 | auto、predictive、reactive，多种阈值和恢复路径                 | Claude Code 更适合极长会话        |
| 审计与重建    | start/summary/end 事务和 source seq 明确      | transcript、boundary、replacement 多套状态共同工作             | Harness 边界更清楚                |
| 实现复杂度    | 较低，能力 seam 清晰                          | feature gate、供应商能力和路径很多                             | Harness 更易维护                  |
| 适用场景      | 业务型 Agent、规则清楚、任务类型有限          | 编码 Agent、工具多、会话长、多 Agent                           | 各自针对目标场景优化              |

### 谁的做法更好

如果只比较缓存命中率和超长会话生存能力，Claude Code 更强。它不仅控制 system、tools 和 messages 的断点，还会根据缓存是否仍然温热选择不同的 microcompact 路径，并准备了预测压缩和超限恢复。

如果比较架构可解释性、审计能力和在普通业务系统里的维护成本，DeepSeek Harness 更合适。日志、surface、动态快照和压缩事务的职责清楚，较容易验证“原始事实还在、模型只看到什么、何时发生替换”。

因此没有脱离场景的单一赢家：

- 大型编码代理：Claude Code 更成熟；
- AI 自讲 Demo：DeepSeek Harness 的主干更合适；
- 供应商频繁切换：Harness 的通用策略更稳，Claude Code 的缓存编辑未必可移植；
- 严格成本优化且上下文很长：可以在 Harness 式主干上逐步吸收 Claude Code 的局部预算和观测手段。

---

## 七、一次性引导例子应该怎样处理

### 7.1 A 换成 B 会不会导致缓存失效

会，但要看 A 放在哪里。

假设请求结构为：

```text
P = 稳定 system + tools + 可长期保留的历史
A = 本轮原因 A 的引导例子
B = 下一轮原因 B 的引导例子
```

两轮请求分别是：

```text
第 N 轮：P + A
第 N+1 轮：P + B
```

从 A 与 B 开始内容不同，原来以 `P + A` 形成的完整缓存单元不能被 `P + B` 完整匹配。稳定的 P 是否立即命中，还取决于供应商是否已经在 P 的结束位置、公共前缀检测点或固定 token 间隔处落盘。DeepSeek 官方明确说明缓存是按已落盘的完整前缀单元匹配，并且属于尽力而为，因此不能只根据字符串公共前缀推导 100% 命中。

但把 A 放到尾部仍然有价值：即使命中失败，变化也被限制在请求末端；system、tools 和前面的大段历史仍最有机会成为可复用前缀。若把 A 放进 system 中段，A 之后的所有任务说明和历史都会一起失去复用机会。

### 7.2 “保留旧 A”与“下一轮删除 A”的取舍

有两种实现方式：

| 方式                                 | 缓存表现                | 上下文表现                               | 建议                                         |
| ------------------------------------ | ----------------------- | ---------------------------------------- | -------------------------------------------- |
| 旧 A 留在历史，追加“当前以 B 为准” | 最容易延续长缓存前缀    | 模型仍能看到 A，可能混淆，token 持续增长 | 仅适合旧信息允许被覆盖但不要求消失的状态快照 |
| 下一轮模型视图移除 A，只加入 B       | 从 A 开始的后缀需要重算 | 满足一次性内容不再出现，语义更干净       | 适合当前教学引导例子                         |

DeepSeek Harness 的 runtime-context 快照更接近第一种：通过追加新快照保持缓存友好。Claude Code 的 active view、snip 和 compact 更接近“原始记录保留，但模型视图可以移除旧内容”。

对 AI 自讲 Demo，用户已经明确“一次性引导例子后续无需出现”，因此建议采用第二种。不要为了多命中一小段尾部缓存，让模型长期看到已经失效的教学材料。

### 7.3 推荐的上下文分层

```text
第一层：全局稳定前缀
  system 角色、业务边界、输出协议、稳定原因定义

第二层：任务稳定前缀
  当前 taskType 的固定规则、JSON Schema、长期不变的题目材料

第三层：可持续历史
  学生原话、模型正式反馈、确定性业务状态变化

第四层：当前轮数据
  当前回答、最新评价结果、规则层给出的动作

第五层：一次性尾部
  当前原因对应的引导例子、结构校验错误、仅本次有效的修复说明
```

下一轮构造上下文时：

- 第一、二层保持字节和顺序稳定；
- 第三层只追加，不回写旧消息；
- 第四层按当前轮生成；
- 第五层完全重建，不携带上一轮例子；
- 上下文接近阈值时，把第三层较老部分摘要化，而不是频繁重写前缀。

还应给每个一次性块带明确的内部元数据，例如 `turnId`、`evaluationId`、`mainReason`。这些字段由后端决定，模型只消费。这样即使日志里保留了旧例子，活动视图也能确定性地只选择当前记录。

---

## 八、对 AI 自讲 Demo 的落地建议

### 8.1 建议采用的最小方案

1. 保持一段真正稳定的共享 system，不把当前原因、当前状态、计数或例子放进去。
2. 各 taskType 的固定说明紧跟 system 之后，顺序固定，模板版本显式管理。
3. 原始交互日志采用追加式保存；另建一个确定性的 `model_view` 组装层。
4. 一次性引导例子只进入当前 `model_view` 的末尾，不进入下一轮活动视图。
5. 对话变长后，先限制大字段，再摘要旧历史；不要每轮重写整段历史。
6. 记录 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`、总输入 token、输出 token、taskType、模板版本和是否发生压缩。

### 8.2 不建议现在照搬的 Claude Code 能力

- cache editing：依赖供应商协议，当前收益和维护成本未知；
- 多套 feature gate 下的 microcompact：业务历史规模尚未证明需要；
- context collapse：状态和恢复路径复杂，本地 Claude Code 仓库本身也仍有实验痕迹；
- 为 fork agent 定制多级缓存断点：当前 AI 自讲流程没有同等规模的 agent 分叉。

### 8.3 建议先观测再调参

上线后至少观测：

| 指标                                 | 用途                                 |
| ------------------------------------ | ------------------------------------ |
| `cache_hit_tokens / prompt_tokens` | 判断共享前缀是否真正被复用           |
| 各 taskType 的首次与后续命中率       | 区分跨任务共享和同任务续轮收益       |
| 一次性例子平均 token                 | 判断移除它导致的尾部重算是否值得关注 |
| 压缩前后 token                       | 验证摘要是否真的缩小上下文           |
| 压缩后评价一致性                     | 发现摘要丢失学生关键证据的问题       |
| 输入与输出费用占比                   | 判断继续优化输入缓存是否是最高优先级 |

不要先假设 80%/16% 是适合当前业务的最优值。DeepSeek Harness 自己也把这两个默认比例列为尚缺少语料依据的固定默认值。AI 自讲的单轮消息较短、关键信息密度高，压缩阈值应通过真实会话长度和评价回归测试确定。

---

## 九、合理性批判与不足

1. **“全部动态内容放尾部”并不自动保证高命中率。** DeepSeek 当前按已落盘的完整缓存前缀单元匹配，公共前缀需要先被识别并落盘；缓存还可能因为过期或资源调度而未命中。排列策略只能提高概率，不能当成命中承诺。
2. **追加旧快照会用缓存收益换取上下文污染。** DeepSeek Harness 的动态快照策略适合环境状态、工作目录等“最新值覆盖旧值”的信息。教学例子具有较强语义，原因从 A 变成 B 后，旧 A 可能干扰模型。当前业务应使用活动视图移除，而不应机械复制 append-only 可见历史。
3. **摘要会破坏细粒度证据。** 学生原话、评价依据和已给出的提示之间可能存在细微关系。若摘要器遗漏一个否定词或条件，后续评价会偏移。建议保留最近若干轮原文，并把确定性的业务状态独立存储，不能只依赖自然语言摘要恢复。
4. **Claude Code 的高级策略有明显场景依赖。** 它面对的是大量工具输出、长文件、并行 agent 和超长编码会话。把同样的多级压缩引入教学 Demo，会增加状态恢复、测试和供应商兼容成本，收益未必覆盖复杂度。
5. **缓存成本不是唯一目标。** 如果输出 token 或模型推理成本占大头，继续细化输入缓存的边际收益可能很小。应先基于实际 usage 做费用拆分，再决定是否投入复杂的上下文治理。

---

## 十、源码索引

### DeepSeek Harness

- 系统 section、动态 context 与顺序规则：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\core\system-prompt\src\index.ts:52`
- system 与 runtime-context 投影：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\core\agent-loop\src\runtime-context.ts:52`
- pre-step 中把 runtime-context 放到本轮尾部：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\core\agent-loop\src\agent.ts:240`
- 追加 user 与 assistant 消息：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\core\agent-loop\src\agent.ts:352`
- 从 surface 派生请求：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\core\agent-loop\src\agent.ts:552`
- 真实 API 缓存命中测试：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\core\agent-loop\tests\request-cache.e2e.ts:14`
- DeepSeek usage 字段映射：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\llm\llm-deepseek\src\translate.ts:46`
- 压缩默认值和事务说明：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\compaction\compaction-basic\README.zh.md:64`
- 工具结果剪枝默认值：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\packages\compaction\compaction-tool-result-pruner\README.zh.md:50`
- surface 替换与压缩事件：`D:\lijianguo\code\deepseek-harness-master\deepseek-harness-master\docs\subsystems\compaction.zh.md:9`

### Claude Code

- system section 缓存与危险动态 section：`D:\lijianguo\code\claude-code\src\constants\systemPromptSections.ts:16`
- systemContext 与 userContext 组装：`D:\lijianguo\code\claude-code\src\utils\api.ts:431`
- 内置工具与 MCP 工具稳定排序：`D:\lijianguo\code\claude-code\src\tools.ts:362`
- 用户消息追加与提前持久化：`D:\lijianguo\code\claude-code\src\QueryEngine.ts:440`
- 请求前上下文处理流水线：`D:\lijianguo\code\claude-code\src\query.ts:523`
- 活动历史从最新 compact boundary 开始：`D:\lijianguo\code\claude-code\src\utils\messages.ts:5070`
- 动态工具放在缓存标记之后：`D:\lijianguo\code\claude-code\src\services\api\claude.ts:1488`
- 每请求单一 message-level 缓存断点：`D:\lijianguo\code\claude-code\src\services\api\claude.ts:3223`
- system prompt 缓存块：`D:\lijianguo\code\claude-code\src\services\api\claude.ts:3374`
- auto compact 阈值和安全 buffer：`D:\lijianguo\code\claude-code\src\services\compact\autoCompact.ts:28`
- microcompact 与 cache editing：`D:\lijianguo\code\claude-code\src\services\compact\microCompact.ts:52`
- compact 后消息顺序：`D:\lijianguo\code\claude-code\src\services\compact\compact.ts:331`
- transcript、压缩和错误恢复总览：`D:\lijianguo\code\claude-code\docs\internals\session-transcript-persistence.md:423`
