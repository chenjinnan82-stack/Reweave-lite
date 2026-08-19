# RepoNavigator 只读研究评估

文档性质：只读研究评估

当前状态：未授权实施

本文迁移自 Reweave 产品北极星中的 RepoNavigator 研究边界。它只记录论文事实、可借鉴原则和可证伪原型条件，
不构成实现任务，也不改变 Reweave 的正式架构与路线优先级。

## 1. 论文实际证明范围

参考论文：[*One Tool Is Enough: Reinforcement Learning of LLM Agents for Repository-Level Code Navigation*，
arXiv:2512.20957 v6，2026-05-26](https://arxiv.org/html/2512.20957)。

论文研究 repository-level issue localization：输入代码仓库和 issue 描述，输出可能需要修改的文件与函数位置。
它没有研究代码抽取、胶囊边界、安全证明、行为等价或受控发布。

论文的核心工具 `jump` 由 language server 解析符号引用并返回定义代码。模型负责选择下一次跳转以及何时停止；
`jump` 不是自动揭示相关代码的 oracle。

实验的适用条件包括：

- 论文偏离原 SWE-bench 协议，为 RepoNavigator 和所有基线提供精确入口文件及对应入口函数。
- 实验只使用 Python 仓库。
- 作者只成功实现了 Python language server，其他语言仍待实现和验证。
- GRPO 训练中，7B 使用 8 张 NVIDIA Tesla A100 80G，14B 和 32B 使用 16 张同规格 GPU。

因此，论文没有证明能从完全未知的大型 JavaScript 仓库中自动找到用户需要的业务函数，也没有证明模型轨迹
可以成为 Reweave 的确定性依赖闭包。

本次迁移不访问网络，不更新或重新解释上述论文事实。

## 2. Reweave 可借鉴的只读导航原则

Reweave 只借鉴两个产品原则：

1. 沿真实词法绑定、import 和定义关系导航，比纯关键词检索更适合解释代码结构。
2. 一个清晰、只读的“跳到定义／查看依赖链”动作，优于增加搜索、向量库、RAG 和多套松散检索工具。

当前 `source_graph.v1` 已提供确定性基础：TypeScript lexical symbol graph、import/export resolution、
selected function identity、依赖闭包和失败关闭。任何导航界面都必须复用现有 node identity、逻辑路径和 UTF span，
不能建立第二个事实来源。

如果未来原型通过，普通模式可以显示简短的可操作结论，例如“可抓取；依赖若干 helper 和常量”，
或“不可抓取：依赖可变共享状态”。开发者模式可以提供只读“跳到定义”和“查看依赖链”。
源码只能按当前快照临时读取，不进入 SQLite、不缓存到前端，也不发送给 Ollama。

## 3. 明确不采用

- 不接入 RepoNavigator runtime，不进行本地 RL 训练。
- 不增加第二 language server、第二索引、第二事实图、向量库、RAG 或第二候选主线。
- 不把模型的 jump 轨迹当作 dependency closure；漏跳不能使危险依赖消失。
- 不让 RepoNavigator 或模型决定胶囊边界、纯度、data contract、安全、canonical evidence 或等价关系。
- 不用它解决业务字段映射，也不减少现有人工确认。
- 不把论文结果扩大为 JavaScript、DOM/Event、QWebEngine、bundle、SQLite 或 Composer 的有效性证明。

研究评估不改变 Intake、Source Graph、固定安全、Stage 3、Composer、模型输入或任何正式状态。

## 4. 基于现有 Source Graph 的可证伪展示原型门

该原型不在当前产品主线中。只有用户另行授权，并且用户仍难以理解目标函数和阻断依赖时，才允许进行一次
只改展示的对照原型；原型不得改变抓取结果。

固定研究方式：

- 使用 6–8 个冻结 JavaScript 项目。
- 对照当前 offer 详情与基于同一 `source_graph.v1` 的 jump／依赖链视图。
- 任务固定为定位目标函数、识别一个 helper、解释一个 fail-closed 原因。
- 记录完成时间、错误选择次数、源码查看次数和阻断原因复述准确性。
- 两组必须得到完全相同的 Source Graph、offer、canonical hash 和 Stage 3 outcome。
- 原型只能读取已有图证据，不增加持久化、模型输入或正式事实。

只有显著减少理解时间或误选，并且安全与持久化结果零变化时，才进入正式产品讨论；否则删除原型。
即使通过，也只能声称改善了结构导航体验，不能声称 Reweave 已能自动拆解普通旧项目。
