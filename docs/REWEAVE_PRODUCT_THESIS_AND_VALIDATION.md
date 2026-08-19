---
document_id: reweave_product_thesis_and_validation.v1
status: FROZEN
document_type: product_thesis_and_validation_charter
created_at: 2026-08-14
last_updated: 2026-08-14
applies_to: Reweave
---

# Reweave 产品论证与验证协议

文档性质：产品论证、证据边界、验证协议与停止条件
当前状态：`FROZEN`
仓库位置：`docs/REWEAVE_PRODUCT_THESIS_AND_VALIDATION.md`

## 0. 执行摘要

### 0.1 当前最严格结论

```text
形式化 exact-version 能力可被再次组合和交付：已证明，范围有界
跨项目或真实生产复用：未知
复用收益超过正式化成本：未知
Reweave 存在联动的 domain model：已证明
Reweave 发明了新的计算原理：不成立
小模型在正式链路中运行：已证明
小模型是产品必要条件：无证据
“大 Agent → Reweave → 小模型”的同任务端到端分层：尚未证明
Agent-independent authority layer：数据模型部分支持，产品入口尚未成立
面对同权限恶意进程的 security authority：未实现
当前最少夸大的产品名称：Local bounded software reuse & delivery control plane
```

### 0.2 当前产品定义

> **Reweave 是一个本地、有界的软件复用与交付控制面。**
>
> 它把来源、精确版本、资格证据、合法组合、用户确认、执行、验收与失效传播绑定为同一条正式事实链；人或 Agent 可以操作这条链，但模型不能自行取得正式身份、连接、发布或授权权力。

这一定义描述 Reweave 当前实际做什么，不预先承诺它比成熟模块、文档、测试、版本控制与 CI 更便宜或更可靠。

### 0.3 当前产品论证

Reweave 的候选价值不是“模型不会写代码”，也不是“小模型比大模型更好”。它试图解决的是：

> 当稳定的软件行为需要被多次复用、跨版本交付、接受明确批准并在错误连接或事实漂移时失败关闭，是否值得把分散的软件工程实践统一为一条可复算、可审查的领域事实链。

用户始终可以绕过 Reweave 直接完成软件任务。用户选择 Reweave 时，购买或承担的不是“完成任务的唯一方式”，而是以下候选收益：

- 精确版本和资格证据不被“最新版”或模型猜测替代；
- 组合成员与 wiring 只能来自合法、可复算的 offer；
- 用户确认绑定具体事实，而不是一次泛化授权；
- execution、acceptance 与 provenance 保持同一身份链；
- 上游事实漂移会使下游结果失效，而不是静默迁移；
- 外部 Agent 可以成为操作入口，但不能成为正式事实所有者。

这些收益是否足以覆盖正式化、维护和用户确认成本，仍须由强基线对照证明。

### 0.4 下一阶段唯一核心问题

> **Reweave 的正式化是否在重复任务中为自己付费？**

判断不能依赖胶囊数量、测试数量、模型自评、一次演示成功或架构完整度。必须比较：

```text
A. Agent 直接开发
B. Agent + 成熟普通工程复用
C. Agent + Reweave
```

若 C 不能在重复任务中以更低累计成本、更少人工纠正或更强正确性持续优于强 B，则应收缩 Reweave 的适用面，而不是继续添加机制为项目寻找新解释。

---

## 1. 文档职责与权威关系

### 1.1 本文回答什么

本文回答五个问题：

1. Reweave 当前可以被怎样准确描述；
2. 它相对于普通软件复用的候选价值是什么；
3. 哪些结论已经有证据，哪些仍是研究假设；
4. 用什么实验允许这些假设升级或被否定；
5. 什么结果必须触发冻结、收缩、转向或停止扩建。

### 1.2 本文不回答什么

本文不是：

- 当前运行时实现规范；
- Schema、ABI、协议或数据库契约；
- 发布状态记录；
- 当前阶段验收报告；
- 前端体验规范；
- 自动修改路线图的授权文件。

### 1.3 文档层级

发生冲突时，按以下层级判断：

1. **代码、正式 Schema 与运行时契约**：当前行为事实；
2. **冻结验收证据与可复算 artifacts**：某项能力是否真正成立；
3. **Git Tag、托管 CI 与发布记录**：发布事实；
4. **`REWEAVE_PRODUCT_NORTH_STAR.md`**：长期方向、当前主线与硬边界；
5. **本文**：产品必要性论证、证据标准、实验和停止条件；
6. **讨论稿、设计候选、模型建议**：非正式输入。

本文不能通过文字把未实现能力升级为当前能力，也不能绕过北极星改变当前全局主线。若本文的实验结果要求改变交付模式、全局优先级或硬边界，必须另行修订北极星。

### 1.4 证据来源

本文以以下材料为基础：

- `docs/REWEAVE_PRODUCT_NORTH_STAR.md`，更新时间 2026-08-14；
- `docs/ARCHITECTURE.md`；
- `docs/reports/REWEAVE_LEVEL_THREE_MINIMUM_LOOP_ACCEPTANCE_INDEX.json`；
- 当前代码、冻结验收索引和相应 artifacts 的事实复核；
- 两轮针对复用、模型角色、Agent handoff、成本和强基线的 Codex 只读分析；
- 已确认的 `reweave_agent_jsonl.v2` Candidate handoff 行为。

本版论证绑定以下精确复核基线；后续冻结或修订必须重新计算，不得沿用“当前”二字：

```text
repository_commit =
  98c6a0f67af3c6bf34bd252a46f77a7d2c34c929

north_star_sha256 =
  655355b02b59a0cac292217a1ee242f5dc9be785fef2ee91399c401be976803d

architecture_sha256 =
  8377dcc4b0b90e80f0f508b0c565ea5f1855933eb832a522862b21e7ac59a437

acceptance_index_sha256 =
  33ef72c529b4a9ac9306e3ad90978e1d687625c8e25a7430ec8bc2ae21525f85

formal_warehouse_revision = 73
formal_warehouse_sha256 =
  0d1acbdf3c4fdc98290de31d38676dc395b7c99dcd84919f2000a3838c6c275b
```

关键外部冻结证据中，Codex 直接 Shuttle Candidate handoff 使用审计身份
`reweave-codex-direct-shuttle-candidate-handoff-v1-04`，其 checksum manifest
digest 为
`636cac5b70021f5df764abea9e0fc016eb60ce57b31ccfee591cab48f90e673d`。
等级三闭环、exact-version 复用、正式模型角色与非正式 experience 基线的精确
artifact 定位由上述验收索引负责；本文不复制会漂移的本地绝对路径。

源材料未支持的结论，在本文中必须标为 `HYPOTHESIS`、`UNKNOWN` 或 `NOT_IMPLEMENTED`，不得用流畅叙事补齐。

---

## 2. 反自我欺骗规则

### 2.1 五类语句必须显式区分

本文及后续文档中的关键陈述，应属于以下一种：

| 标签 | 含义 | 允许的依据 |
| --- | --- | --- |
| `FACT` | 当前已经成立的事实 | 代码、正式契约、冻结证据或可复算 artifact |
| `DECISION` | 产品所有者明确作出的取舍 | 已确认产品决定或北极星 |
| `HYPOTHESIS` | 可证伪的价值、市场或计算假设 | 明确预测、指标和否定条件 |
| `RISK` | 可能破坏结论的已知缺口 | 代码复核、协议缺陷、证据缺失 |
| `GATE` | 允许升级结论或扩建能力的门槛 | 预先登记的验收条件 |

不得把 `HYPOTHESIS` 写成产品现状，也不得把 `DECISION` 写成技术必然。

### 2.2 证据等级

为避免“一次通过”被写成“产品价值成立”，采用以下证据等级：

| 等级 | 名称 | 定义 |
| --- | --- | --- |
| `E0` | Narrative | 只有解释、愿景或模型推断 |
| `E1` | Implemented | 代码路径存在，局部测试通过 |
| `E2` | Frozen Acceptance | 在冻结输入、精确版本和正式标签下验收通过 |
| `E3` | Repeated Internal Use | 同一 exact version 在不同冻结任务中再次被选择和交付 |
| `E4` | External Production Use | 在真实外部项目、真实用户和持续使用中成立 |
| `E5` | Comparative Advantage | 对强基线证明更低累计成本、更少纠正或更高正确性 |

当前 Reweave 的 exact-version 复用达到 `E3` 的窄范围；生产收益未达到 `E4`；相对强 B 的产品优势未达到 `E5`。

### 2.3 升级与降级规则

- 结论只能在预先定义的 Gate 通过后升级；
- 新证据与旧结论冲突时，应先降级结论，再调查原因；
- 不允许先扩大叙事，再补实验；
- 不允许因为结果不理想，新增机制后不断改变问题；
- 只有 telemetry 缺失、环境漂移、实验实现错误或预注册违规可以使实验标记为 `INVALID` 并重跑；
- 失败、平局和负面结果必须进入长期记录，不能只保留成功演示。

### 2.4 机制扩建门

任何新机制、能力类型、模型角色、检索层或 Agent 入口，在开发前必须回答：

1. 它解决了哪个已观察到的真实失败？
2. 当前机制为什么不能通过更小修复完成？
3. 它直接验证哪一个产品假设？
4. 它是否增加第二个仓库、第二 Composer、第二事实链或隐藏 fallback？
5. 如果不做，当前价值实验是否仍可执行？

若第 1、3 项没有具体答案，或第 5 项为“仍可执行”，默认不做。

---

## 3. 当前产品事实

### 3.1 当前结构

Reweave 当前由三条用途不同的路径组成：

1. **正式胶囊生命周期**：来源或授权 source proposal 经过冻结、Intake、安全、监督、runtime、人工复核和用户发布，形成不可变正式版本；
2. **计划驱动的独立产品交付**：目标经过合法 offer、确定性绑定与执行，形成隔离 Candidate、业务验收和独立导出；
3. **Review-only 目标接入**：正式胶囊与目标快照形成 Weave Plan、结构化 Patch、Diff 和拒绝证据，当前不写真实项目。

三条路径共享同一正式仓库、Capsule IR、Composer 产品线和 Stage 3 发布主线。Agent 接入是操作入口，不是第三种交付方式。

### 3.2 已经成立的复用

`FACT / E3`：在冻结验收任务内，同一 `capsule_id + version_id + canonical_hash` 已被不同 Candidate 精确复用；已有 interaction、total computation 和 presentation 进入后续报价任务，只为缺失的折扣 computation 走 source proposal。

`FACT`：同一 capability group 的不同 immutable version 被不同历史 Candidate 精确选择，旧 Candidate 未迁移到新版本。

`FACT`：这证明了：

```text
形式化事实可以被再次选择、组合和交付
```

它尚未证明：

```text
形式化复用比成熟模块、文档和测试更省钱或更可靠
```

### 3.3 三种“使用”不得混称

| 概念 | 当前定义 | 当前状态 |
| --- | --- | --- |
| audit Candidate reuse | 不同冻结任务的 plan、execution、Candidate 精确引用同一正式版本 | `PROVEN` |
| formal warehouse reuse | 同一 exact version 从正式 catalog 被多次选入不同计划或 Candidate | `PROVEN_BY_ARTIFACTS`，尚非仓库内一等 usage 记录 |
| product usage | 正式晋升产品及其不可变版本记录所用 capsules | `NOT_IMPLEMENTED / NONE_RECORDED` |
| external production usage | 外部用户在真实生产环境持续使用 | `UNKNOWN` |

`product_capsule_usage = 0` 只说明正式库中没有 usage 行；由于正式 products 晋升与完整产品版本历史尚未实现，它既不能否定已复算的 Candidate reuse，也不能被解释为“生产使用已经发生但漏记”。

### 3.4 当前模型角色

`FACT`：

- `qwen3:14b-q4_K_M` 当前承担 outline、composition selection、部分锁定 Blueprint 的语义描述、受支持 computation source proposal，以及窄范围 experience 注入后的 offer selection；
- `qwen2.5-coder:7b` 当前承担 Stage 3 semantic supervision；
- offer 枚举、wiring、gap 投影、安全、runtime、正式身份和发布由确定性核心或用户掌握。

`UNKNOWN`：上述小模型是否比 frontier model、人工或更强规则系统具有已量化的成本、隐私或离线优势。

### 3.5 当前 Agent 接入

`FACT / E2`：当前 Codex 接入属于角色一的窄子集：

> **Codex 作为已确认产品计划的 Candidate 远程控制客户端。**

当前进程入口：

```text
python -m pimos_lite.reweave_agent_stdio
```

当前正式 wire protocol：

```text
reweave_agent_jsonl.v2
```

当前允许动作：

```text
bind_user_handoff
list_reusable_product_capabilities
get_confirmed_product_plan
start_confirmed_product_candidate
get_product_candidate_run
get_product_candidate
read_product_candidate_file
```

Codex 不能提交或决定 plan token、capsule/version、offer、dependencies、wiring、Composer、acceptance、发布或真实项目写入。它绑定用户签发的 handoff，发起高层动作，Reweave 内部完成确定性组合、Candidate runtime 与验收。

### 3.6 当前 Agent 协议限制

这些限制不否定当前窄 handoff，但阻止扩大其成熟度叙事：

| 事项 | 当前事实 |
| --- | --- |
| plan、confirmation、acceptance、capsule facts scope | 已冻结并持续复核 |
| protocol version / allowed actions 冻结 | 未实现；旧 handoff 可能随全局 action 集扩张而获得新动作 |
| Candidate 幂等 | Candidate identity 可确定性恢复 |
| management run 幂等与持久化 | run 状态为进程内，非 durable |
| revoke 对 in-flight worker 的语义 | 未冻结；代码推断为 worker 可继续、后续控制和读取失效 |
| bridge 重启后的 run recovery | 不支持 |
| 已持久化 Candidate artifact recovery | 支持，条件受限 |
| 并发模型 | `SEQUENTIAL_EXCLUSIVE`；不允许多个写者同时操作同一状态目录 |

这些问题只有在 Agent 入口扩大、并发或长期运行成为真实产品要求时，才进入对应设计门；当前不据此建设通用 Agent 平台。

---

## 4. Reweave 的最小不可约结构

### 4.1 不是某个单独 feature

Reweave 的核心不是 SQLite、胶囊卡片、Composer、stale check、审批或 provenance 中任意一个单独 feature。成熟普通工程都可以分别实现其中多数能力。

真正的分界是这些对象开始通过同一正式身份链联动：

```text
冻结来源字节
→ 不可变 exact version identity
→ 绑定该 identity 的 qualification
→ 仅由 eligible exact versions 枚举 legal composition
→ 用户确认绑定同一 catalog / plan / offer / acceptance
→ execution 只能展开该 offer
→ Candidate acceptance 与 provenance 绑定同一 execution 和内容 digest
→ 任一上游漂移使所有依赖的下游状态 stale
```

### 4.2 六项 invariant

#### 4.2.1 Exact identity invariant

能力不是名称、别名或“最新版”，而是精确：

```text
capsule_id + version_id + canonical_hash
```

历史计划、Candidate 和导出继续引用形成时的精确版本，不随 current 版本变化而迁移。

#### 4.2.2 Qualification invariant

eligible 状态必须绑定该精确版本的来源、安全、监督和 runtime 证据。资格不能从同名能力、较新版本或相似实现继承。

#### 4.2.3 Composition ownership invariant

合法成员、依赖和 wiring 由正式契约与确定性核心决定。模型可以选择一个完整 offer 或报告无匹配，但不能自行增删成员、跨组混合或选择 topology。

#### 4.2.4 Authorization invariant

用户确认必须绑定精确 plan、catalog、offer、acceptance 和对应 digest。授权不是“以后都允许这个 Agent 做类似事情”的泛化权限。

#### 4.2.5 Acceptance invariant

Candidate 的 runtime、业务结果和 provenance 必须绑定同一 execution 与内容身份。窗口启动、构建成功或模型自评不能替代业务 acceptance。

#### 4.2.6 Transitive stale invariant

来源、身份、资格、catalog、契约、确认或授权中任一上游事实漂移，依赖它的下游状态必须失效或重新确认，不能静默沿用。

### 4.3 与强普通工程复用的边界

单独增加 immutable version、审批、CI 或 lockfile，不会使普通模块库变成 Reweave。

当一个普通工程系统同时具备：

```text
版本资格
+ legal composition
+ 绑定精确事实的用户确认
+ execution / acceptance
+ 跨阶段 stale propagation
+ 同一正式身份链
```

它实际上已经在重新实现 Reweave 的 domain model。

### 4.4 不主张新的计算原理

`DECISION`：不得把 Reweave 描述为新的算法或软件计算范式。

它目前最准确的技术解释是：

> **把版本控制、Schema、资格、审批、组合验证、provenance、acceptance 与失效传播统一为一个 domain-specific state machine。**

统一可能具有产品价值，但价值来源应是更低的集成成本、更少的错误或更清晰的责任边界，而不是“发明了新的计算原理”。

---

## 5. 用户问题与产品必要性假设

### 5.1 候选 Job to Be Done

`HYPOTHESIS`：

> 当用户需要从已有稳定软件行为中反复交付新变体，并且版本、连接、来源、批准或验收错误具有实际成本时，Reweave 帮助用户只复用满足资格的精确能力，并交付可审查、可复算、失败关闭的结果，而不必让每个 Agent 每次重新解释全部来源。

### 5.2 用户可以绕过什么

用户和 Agent 可以绕过 Reweave：

- 直接读取旧项目；
- 重新实现功能；
- 修改目标代码；
- 运行测试；
- 完成一次交付。

因此 Reweave 不是完成任务的技术垄断点。

### 5.3 用户不能在正常协议中同时绕过什么

在 Reweave 支持的正常入口和可信本地状态假设下，Agent 不能绕过正式流程同时获得 Reweave 所承认的：

- formal capsule identity；
- qualification evidence；
- legal composition；
- confirmed plan；
- formal acceptance；
- user authorization state；
- transitive stale guarantee。

更严谨的表述是：

> Agent 可以在系统外完成任务，但不能通过 Reweave 支持的协议绕过正式流程，同时取得 Reweave 所承认的正式结果。

这不是面对同权限恶意写者的密码学保证。

### 5.4 产品必要性成立条件

Reweave 只有在至少一个条件成立时具有产品必要性：

1. **经济优势**：重复任务中的累计成本低于强 B；
2. **正确性优势**：在错误版本、非法组合或 stale 情况下显著减少失败与人工纠正；
3. **风险调整优势**：直接成本更高，但可量化地降低高损失错误，且真实用户愿意为保证付费；
4. **组织集成优势**：用户本来需要自行拼装身份、资格、审批、组合、验收和 Agent handoff，Reweave 用更低总成本提供统一控制面；
5. **本地或隐私约束**：离线、小模型或本地数据边界产生可测收益，而不是仅有价值偏好。

若这些条件均未被证明，Reweave 可继续作为研究系统或工程作品，但不能扩大“通用产品必要性”叙事。

---

## 6. 适用与不适用边界

### 6.1 当前 eligibility hard gate

能力进入正式化流程前，应满足：

```text
eligible =
  来源已授权
  AND 契约稳定、明确
  AND 当前副作用与类型边界受支持
  AND 可以通过确定性业务例或 runtime 进行验证
  AND（预期重复使用 OR 错误代价较高）
  AND 预期收益 > 正式化与维护成本
```

任何一项无法回答时，默认不正式化，先由 Agent 直接完成。

### 6.2 当前最适合的任务

| 任务类型 | 当前判断 | 原因 |
| --- | --- | --- |
| 成熟纯业务计算 | 适合 | 契约稳定、输入输出明确、可重复验证 |
| 报价与定价规则 | 最强候选 | 已有 exact-version 跨任务复用证据，版本与公式错误可验收 |
| 单位换算、面积、体积计算 | 适合验证机制 | 纯 computation、边界稳定，但持续复用收益仍弱 |
| 有限枚举分类 | 有界适合 | 已有 boolean 到有限字符串枚举的正式交付证据 |
| 支付或资格规则的纯计算部分 | 条件适合 | 公式和资格判定可验证；实际支付执行不在当前边界 |
| 企业审批中的稳定分类规则 | 条件适合 | 纯规则可；外部状态流转与写入不可 |
| 稳定共享 presentation | 谨慎 | 只有重复使用且契约稳定时可能值得，当前收益证据较弱 |

### 6.3 当前不应进入 Reweave 的任务

| 任务类型 | 当前判断 |
| --- | --- |
| 一次性 UI tweak | 直接让 Agent 完成 |
| 一次性文案 | 直接让 Agent 完成 |
| 高度不稳定功能 | 不正式化 |
| 实验脚本 | 不正式化 |
| 简单 CRUD | 当前不支持有状态数据库与副作用边界 |
| 网络 API wrapper | 当前不支持网络副作用正式组合 |
| 任意文件或二进制转换 pipeline | 当前文件系统与二进制边界不足 |
| 真实支付、账务写入、审批流转 | 当前不可 |
| 尚无明确契约和业务例的代码 | 先稳定实现和测试，不提前胶囊化 |

### 6.4 两种用户模式

Reweave 不应强迫所有任务进入正式流程。产品应明确提供两种选择：

#### Direct Development Mode

- 速度优先；
- Agent 可自由探索和实现；
- 不声称获得 Reweave 正式保证；
- 适合一次性、低风险、不稳定任务。

#### Reweave Mode

- 复用正式 exact versions；
- 获得合法组合、用户确认、acceptance、provenance 与 stale checks；
- 适合重复、高错误代价、版本敏感或需审批的任务。

正式化是有成本的产品选择，不是道德上更正确的默认路径。

---

## 7. 与 Agent、Harness 和外部模型的关系

### 7.1 正交关系

Reweave 的交付模式与操作入口是两个正交维度：

```text
交付模式
├── 独立产品
└── 目标接入

操作入口
├── Reweave Desktop
├── CLI / internal service
├── Codex
├── Claude / DeepSeek Harness / 其他 Agent
└── 未来 adapter
```

Agent 接入不应成为第三种正式交付方式。

### 7.2 当前 Agent 角色

#### 角色一：Control Entry

Agent 调用 Reweave 高层用例，正式事实和执行仍由 Reweave 掌握。

当前状态：`PROVEN_NARROWLY`。

#### 角色二：Restricted Execution Worker

未来由 Reweave 签发锁定执行任务，Agent 在隔离工作树修改、构建和测试，返回 Diff 与证据，Reweave 独立复验，用户决定是否应用。

当前状态：`NOT_IMPLEMENTED`。

#### 角色三：Formal Composer / Authority Owner

Agent 自由选择胶囊、决定 wiring、自动发布、写正式仓库或真实项目。

当前决定：`PROHIBITED`。这会破坏 Composition ownership、Authorization 和唯一事实链。

### 7.3 Canonical domain protocol 与适配器

`DECISION`：当前 JSONL 协议可继续作为 Reweave 自己的窄 domain protocol。未来 MCP、Skill、DeepSeek Harness Plugin 或其他集成应作为 adapter，而不是反过来定义 Reweave 的正式语义。

```text
Codex adapter ─┐
MCP adapter ───┼→ reweave_agent_jsonl.vN / AppService use cases → Reweave authority core
DSH adapter ───┤
其他 adapter ──┘
```

MCP 或 Skill 可以解释如何调用，但安全和权限边界必须由 Reweave 协议与服务端校验实施，不能依赖 Prompt。

### 7.4 Agent-independent 的升级门

只有同时满足以下条件，才允许使用“Agent-independent software capability authority layer”：

1. Codex、Claude、DeepSeek 或人工生成的 proposal 能通过正式授权入口进入同一 authority；
2. supervision provider 可替换，且不改变正式身份、Review 与资格语义；
3. 外部 Agent 只依赖公开 use cases，不导入内部 Python 类或绕过 AppService；
4. 同一 formal result 可由不同 Agent 客户端操作并复算；
5. 强 B 对照下出现可测价值；
6. 文档明确 domain authority 与 adversarial security 的边界。

目前状态：`PARTIAL / NOT_PRODUCTIZED`。

---

## 8. 模型策略

### 8.1 小模型不是产品前提

`DECISION`：不得把 Reweave 的存在理由建立在“小模型不够聪明”上。

模型会进步，本地模型能力也会变化。Reweave 更持久的价值命题应是：

```text
模型能力 ≠ 正式事实
推理 ≠ 资格
生成 ≠ 验证
理解 ≠ 授权
```

即使未来本地模型足够强，也没有必要反复重新理解、重新决定和重新验证已经稳定的软件事实。

### 8.2 当前事实与长期假设

当前最新 Codex Candidate handoff 的实际顺序是：

```text
Reweave + Qwen3 先完成规划
→ 用户确认
→ Codex 后来作为受限 remote controller 启动 Candidate
→ 确定性核心编译、组合和验证
```

它不是：

```text
强 Agent 处理开放问题
→ Reweave 收敛问题
→ 小模型处理受限问题
→ 强 Agent 消费结果
```

因此“大模型和小模型协同分层”目前属于 `HYPOTHESIS`，不是已验收系统事实。

该 handoff 使用的三个历史 capsule version 的 supervision identity 为
`deterministic-fixture`，不是 `qwen2.5-coder:7b`。因此这次 handoff 本身也不能
证明 Codex、Qwen3 与 Qwen2.5-Coder 参与了同一 artifact lineage。

### 8.3 Model stratification hypothesis

`HYPOTHESIS H-MODEL-1`：

> Reweave 可以把开放、高歧义的软件任务逐步转化为边界明确、可验证的子问题，使 frontier Agent 只处理真正需要通用智能的部分，而让更多后续工作下沉给本地小模型和确定性程序。

预期结构：

```text
高熵、开放任务
→ frontier Agent：理解、探索、协商、候选生成
→ Reweave：冻结事实、资格化、缩小合法空间
→ local small model：受限语义判断或 proposal
→ deterministic core：身份、wiring、安全、runtime、acceptance
→ 用户：正式确认与发布
```

### 8.4 可证伪预测

若该假设成立，随着正式能力、契约和验证器增长，在冻结模型角色集合与任务分布下，应观察到：

- frontier model 调用比例下降；
- 重复源码读取量下降；
- 本地模型或确定性程序承担的任务比例上升；
- 交付成功率不下降；
- 人工纠正不增加；
- 单次和累计成本下降，或在高风险任务中出现可量化正确性收益。

若这些变化不出现，不能继续把“大小模型分层”作为 Reweave 的核心产品叙事。

### 8.5 Provider independence 当前边界

- 下游 Intake、安全、runtime、Review 和发布主要关心 artifact 与 evidence，具有 provider-neutral 潜力；
- 当前普通用户 capability-gap source proposal 入口仍从 workspace 读取冻结 Ollama/Qwen 身份；
- supervision evidence 的数据模型不硬编码具体 Qwen，但生产实现仍使用 `OllamaSupervisor`；
- 更换模型必须形成新的 evidence，不能静默替换旧证据。

当前允许表述：

> Reweave 的 authority data model 具有模型可替换性，但普通产品入口仍绑定当前 Ollama/Qwen 实现。

---

## 9. Authority 与 security 边界

### 9.1 当前成立的是 domain/protocol authority

在可信本地状态、正常入口和单一写者假设下，Reweave 可以决定：

- 哪个 exact version 是正式能力；
- 哪个资格证据与该版本绑定；
- 哪些组合合法；
- 哪个计划与 acceptance 已被用户确认；
- 哪个 Candidate 是正式链条的结果；
- 哪个状态因上游漂移而 stale；
- 外部 Agent 当前被允许执行哪些高层动作。

### 9.2 当前不成立的是 adversarial security authority

如果 Agent 或其他进程拥有 SQLite 和状态目录的同权限写入权，它可以：

- 修改 capsule/version/review 状态；
- 伪造 plan、confirmation、decision、admission 和 Candidate files；
- 重写无密钥 digest chain；
- 绕过 UI 确认。

现有 SHA-256、digest chain、DB constraint、append-only 结构、atomic write 和文件权限可以发现粗糙损坏、提高一致性，但无法抵抗知晓 Schema 的同权限恶意写者。

当前没有：

- cryptographic signature 或 MAC；
- external trusted root；
- 独立 OS 用户或强进程隔离；
- remote attestation。

### 9.3 允许与禁止的安全表述

允许：

> 在可信本地 writer 和正常入口假设下，Reweave 提供 fail-closed 的 domain/protocol authority。

禁止：

- “Agent 无法绕过 Reweave”；
- “不能伪造正式结果”而不说明信任假设；
- “tamper-proof”；
- “零信任”；
- “密码学安全”；
- “对恶意同权限 Agent 安全”。

### 9.4 安全机制扩建原则

除非出现真实多写者、远程共享、组织级审批或恶意进程威胁模型，不提前把 Reweave 扩建为密码学安全系统。届时应单独建立 threat model 和安全设计，不在产品价值实验中顺带添加。

---

## 10. 正式化成本模型

### 10.1 本质成本

即使产品成熟，以下成本仍然存在：

1. 来源授权与 provenance；
2. 输入、输出、错误与副作用契约确认；
3. 代表性业务 acceptance 定义；
4. 安全、监督与 runtime qualification；
5. 新能力、替换 current 或保留历史版本的身份决定；
6. 用户最终发布决定；
7. 源码或契约变化后的新版本与重新资格化；
8. 正式状态、验证器和兼容规则的维护。

这些不是 UI 缺陷，不能假设未来完全消失。

### 10.2 Prototype debt

当前历史审计中大量人工成本属于原型债务：

- 手工准备 fixture 和来源目录；
- 手工复制、核对隔离 SQLite；
- 为每个 gate 创建独立审计目录；
- 重复运行专用 runner；
- 人工拼装 mapping、manifest 和 gate 参数；
- 手工定位 Review、workspace 和 digest；
- 使用开发者命令编排本应连续执行的状态机。

这些成本可以通过产品化降低，不能全部计入长期本质成本；但在当前实验中必须如实计入实际成本。

### 10.3 理论最低摩擦

对于已经具有稳定签名、契约和测试的成熟函数，理想路径可以缩至：

```text
1. 用户选择来源并授权冻结
2. 系统自动 discovery / snapshot / intake / safety / supervision / runtime
3. 用户在一个 Review 中确认契约、正式身份和发布
```

即：

- 两次用户权威交互；
- 中间一次自动 qualification；
- 无开发者脚本编排。

如果能力没有稳定契约和业务例，额外澄清属于正式化本身，不是界面优化可以消除的债务。

### 10.4 累计成本向量

在没有预注册换算率时，不把不同量纲压成一个未定义的 `cumulative_cost`。
对 N 个顺序任务分别记录：

```text
CostVector_X(N) = {
  human_seconds,
  paid_model_cost,
  local_inference_seconds,
  agent_wall_seconds
}
```

其中 `human_seconds` 必须包含准备、正式化或文档整理、维护和人工纠正；
模型调用、Agent 运行和失败结果不能因为“已发生”而从累计口径中删除。

只有在实验开始前冻结以下参数，才允许另算单一货币总额：

```text
human_time_rate
provider_price_and_effective_date
local_hardware_cost_basis
failure_loss_by_task
currency
```

此时可定义：

```text
MonetaryTotal_X(N)
= human_seconds × human_time_rate
  + paid_model_cost
  + local_inference_seconds × local_hardware_rate
  + Σ failure_loss
```

否则只做成本向量的逐项比较，并把风险或失败作为独立结果报告。广义产品优势必须在预注册口径下判断，不能在结果出来后临时改变费率、风险权重或成功定义。

### 10.5 Break-even 问题

每类能力必须回答：

- acquisition/formalization 成本是多少；
- 第一次复用后节省多少；
- 维护一个新版本增加多少成本；
- 到第几次复用累计成本低于强 B；
- 若永远无法 break even，是否仍存在可量化的风险调整价值。

没有这些数据时，不允许使用“复利”“飞轮”“压缩成本”作为既成产品收益。

---

## 11. 强替代方案与公平基线

### 11.1 A：Agent 直接开发

提供：

- 原始、已授权源码；
- commit history；
- 原始测试；
- 用户目标；
- 正常搜索、读写和测试工具。

不人为限制 Agent 的常规能力，也不故意移除源码中的自然信息。

### 11.2 B：Agent + 成熟普通工程复用

B 必须是强基线，而不是稻草人。至少提供：

- 与 C 完全相同的实现字节；
- 整理后的独立 modules；
- README / API contract；
- JSON Schema 或类型；
- 自动化测试；
- semver；
- commit SHA；
- lockfile；
- changelog；
- CI 结果；
- 必要的审批或 release note。

B 的整理和维护成本必须计入，不能把它假设为免费。

### 11.3 C：Agent + Reweave

提供同样的实现逻辑，但通过：

- formal capsule exact identity；
- qualification evidence；
- eligible catalog；
- deterministic composition offers；
- confirmed plan；
- deterministic connection；
- stale checks；
- user authorization receipts；
- runtime / business acceptance；
- provenance；
- Agent handoff。

C 的 formalization、Review、发布和维护成本必须计入，不能把现成胶囊免费送给 C。

### 11.4 C 相比 B 真正多出的候选价值

```text
qualification
+ exact immutable identity
+ legal composition owned by domain core
+ authorization bound to exact facts
+ execution / acceptance continuity
+ transitive stale propagation
+ unified Agent handoff boundary
```

强 B 可以用版本控制、Schema、CI、signed commit、审批流和集成测试重建其中多数能力。因此真正的判断不是“C 有更多 metadata”，而是：

> **C 是否用更低总成本持续减少错误、人工纠正或重复理解。**

若不能，Reweave 只是更重的流程包装。

### 11.5 其他替代方案

Reweave 还应与以下类别保持边界：

- package manager / module registry：管理包和版本，不等于绑定资格、组合、用户确认与 acceptance；
- CI/CD：验证和发布自动化，不等于完整能力生命周期；
- low-code / workflow builder：强调快速编排，不一定拥有 exact-version qualification 与 fail-closed chain；
- Agent harness：管理模型、工具、Session、Sandbox 和调度，不拥有 Reweave formal facts；
- 普通知识库或 RAG：提供检索上下文，不决定正式身份、合法 wiring 或发布；
- 软件供应链安全工具：解决签名、依赖和 provenance 的一部分，不等于产品计划与业务验收。

Reweave 的候选价值是将相关实践统一为特定领域控制面，而不是宣称这些类别不存在。

---

## 12. 第一个价值否证实验：报价任务族 A/B/C

### 12.1 实验目的

验证：

> 在稳定、重复、版本敏感、可业务验收的报价任务族中，Reweave 的正式化是否在第六个顺序任务前为自己付费，或至少以不更差的预注册成本向量取得更强正确性和更少人工纠正。

该实验是产品必要性门，不是模型 benchmark。

### 12.2 实验任务

| Task | 目标 | 主要验证 |
| --- | --- | --- |
| T1 | 固定单价 10 的总价 | 初次理解与 acquisition/formalization 成本 |
| T2 | `unit_price = 105 - quantity × 5` 的折扣报价 | 第一次 exact-version 复用 |
| T3 | 固定报价后增加 20 的服务费 | 新能力加入与合法组合 |
| T4 | 服务费升级为 25，但 T3 必须继续绑定旧版 20 | immutable version 与 stale/version 正确性 |
| T5 | 提供不兼容 interaction/computation/presentation，禁止创建新代码 | 正确拒绝非法组合 |
| T6 | 用不同自然语言重复 T2 | 历史复用、重新理解与上下文成本 |

T5 的正确结果是：

```text
NO_LEGAL_COMPOSITION
```

不是尽力生成替代实现。

### 12.3 实验单位与顺序

- 每个 arm 使用一个独立、持久的 project workspace 顺序运行 T1–T6；
- 每个 task 启动全新的 Agent session，但允许读取同一 arm 在更早 task 中合法创建的 artifacts；
- arm 之间不共享 workspace、轨迹、记忆或 artifacts；
- task 顺序固定，因 T3/T4 依赖版本历史；
- arm 的执行先后顺序随机化，减少环境时间偏差；
- 使用相同 Codex 模型版本、推理配置、工具、网络和文件权限；
- 使用相同的用户澄清与业务例；
- 禁止实验人员在某一 arm 中提供另一 arm 没有的解释；
- pilot 阶段可让每个 arm 各运行一次完整序列，但只允许裁决
  `PROTOCOL_VALID` 或 `PROTOCOL_INVALID`，不得据此声明产品优势、平局或停止项目；
- decisive 阶段的 replicate 数必须在运行前冻结；每个 arm 至少 3 次独立 replicate
  才能形成方向性证据，但 3 次重复仍不构成广泛统计证明；
- 第 12.10 节的产品裁决只适用于 decisive 阶段；跨第二任务族复现仍是推广结论的必要后续门。

具体任务材料、replicate 数、随机顺序、runner digest 和统计汇总方法必须写入独立、
不可变的 preregistration artifact；本文不是某次运行的 preregistration manifest。

### 12.4 材料等价性

三组必须满足：

- 相同源码逻辑；
- 相同公开 acceptance examples；
- hidden tests 对所有 arm 和所有 Agent 都不可见；
- C 的 qualification、formalization 和 validation 不得预先读取 A/B 看不到的 hidden tests；
- 相同版本历史；
- 相同 Agent 时间和调用限制；
- 相同禁止新增代码的 T5 约束；
- 相同输入目标和澄清；
- B 的 modules 与 C 的 capsules 来自相同实现字节；
- B 的 preparation 与 C 的 formalization 都从实验成本开始计入；
- C 使用全新 project scope，experience cases 为空，避免经验注入成为额外变量。
- 新版本只能在预注册 task 边界出现；例如 service-fee v2 在 T4 前对所有 arm 均不可见；
- A 可以跨 task 保留自己在该 arm 内创建的普通工程 artifacts，不能被人为削弱为每次从零开始。

### 12.5 正向任务成功标签

T1、T2、T3、T4、T6 必须同时满足：

```text
hidden_business_cases_pass = true
correct_version_selected = true
unauthorized_source_change = 0
runtime_error = 0
```

T4 额外要求：

```text
old_T3_artifact_still_uses_service_fee_v1 = true
new_T4_uses_service_fee_v2 = true
```

T5 要求：

```text
correct_refusal = true
generated_candidate = false
source_write = 0
```

### 12.6 必须记录的 telemetry

每个 arm、task 和 retry 记录：

```text
experiment_id
arm
replicate_id
task_id
model_name
model_digest
inference_configuration_digest
tool_version_digest
start_at / end_at
preparation_human_seconds
task_human_correction_seconds
agent_wall_seconds
source_files_read
source_bytes_returned
docs_schema_bytes_read
projection_bytes_read
input_tokens
output_tokens
local_model_prompt_tokens
local_model_eval_tokens
retry_count
model_call_count
correct_version_selected
hidden_business_cases_pass
correct_refusal
unauthorized_source_change
runtime_error
fallback_source_read
source_read_capture_complete
shell_or_subprocess_bypass_detected
final_status
```

若 provider 不返回 token，只记录 request/response bytes 并标记为 proxy，不估算 token。

### 12.7 Source read 记录

实验 wrapper 记录文件工具事件：

- 相对路径 digest；
- 文件读取次数；
- 返回字节数；
- 是否为 source、docs、schema、test 或 Reweave projection；
- C 中任何 fallback 直接读 source 的行为必须单独标记。

wrapper 必须覆盖 Agent 通过文件工具、shell、Python、构建脚本和测试进程触发的 source
读取。只有同时满足：

```text
source_read_capture_complete = true
shell_or_subprocess_bypass_detected = false
```

source-read 指标才可用于支持或否定上下文减少假设。若完整捕获不可行，该指标必须标记
为 `UNMEASURED`，不得估算或据此声称“语义压缩”；其余成功率、纠正和成本实验仍可在
满足自身数据完整性的前提下继续。为此只实现实验 wrapper 所需的最小观测，不建设通用
telemetry 平台。

审计报告不复制完整源码，避免实验 telemetry 本身成为新的代码泄露面。

### 12.8 人工纠正定义

正常提交目标与最终验收不计入 correction。以下计入：

- 补充本应已经存在的契约；
- 指正错误模块或版本；
- 要求 Agent 重试；
- 手工改代码；
- 修 Prompt；
- 修 wiring；
- 解释历史实现；
- 恢复错误状态或重建实验环境。

每次 correction 记录原因、开始/结束时间、涉及 arm 和是否改变任务信息；不能只记次数。

### 12.9 成本比较点

```text
T1：acquisition / formalization
T2：第一次复用
T4：出现版本历史与 stale 风险
T6：五次后续任务后的主终点
```

成本向量必须覆盖：

```text
preparation
+ formalization / documentation
+ maintenance
+ 所有模型调用
+ Agent 运行
+ 人工纠正
```

逐 arm 报告第 10.4 节的 `CostVector`。若要折算为金钱，必须在实验开始前冻结全部
换算率；否则不得事后合并为一个标量。

### 12.10 预注册裁决

#### C 胜 B

必须同时满足：

```text
success_set_C ⊇ success_set_B
correction_time_C <= correction_time_B
CostVector_C_at_T6 <=componentwise CostVector_B_at_T6
并且至少一项严格更好
```

`<=componentwise` 表示 C 的每个预注册主要成本分量均不高于 B。

若预注册了单一货币口径，可用
`MonetaryTotal_C_at_T6 <= MonetaryTotal_B_at_T6` 替代成本向量条件，但不能在看到
结果后选择更有利的口径。

裁决：

```text
PRODUCT_ADVANTAGE_DEMONSTRATED_IN_QUOTE_FAMILY
```

只能证明报价任务族内的优势，不能直接推广到通用软件能力系统。

#### 正确率更高但成本更高

```text
TRADEOFF
```

成本向量出现交叉、C 的任一预注册主要成本分量更高，或正确率提高但成本不满足
第 12.10 节的支配条件，均进入 `TRADEOFF`。不得写成广义产品优势。只有在失败损失被
预先量化、真实用户愿意付费时，才可进一步探索高保证窄市场。

#### 平局

```text
任务结果相同
AND correction 无明确改善
AND T6 成本向量或预注册货币总额无明确改善
→ PARITY_WITH_STRONG_BASELINE
```

结论：Reweave 的额外正式化在该任务族尚未产生产品收益。

#### C 未支配 B

```text
到 T6 后 C 未支配 B
→ PRODUCT_ADVANTAGE_NOT_DEMONSTRATED
→ 冻结新增 capability 类型、模型角色和检索机制
```

#### C 明显更差

```text
success_C < success_B
OR (
  corrections_C > corrections_B
  AND CostVector_C >=componentwise CostVector_B
)
→ PRODUCT_DISADVANTAGE_OBSERVED
→ 停止扩建通用 Reweave
```

此时可保留现有系统作为窄领域 control plane、研究原型或工程作品，但不得继续扩大“通用软件能力系统”叙事。

### 12.11 实验无效条件

只有以下情况可标记 `INVALID` 并重跑：

- telemetry 丢失或字段定义冲突；
- arm 获得不等价材料；
- 模型或推理配置发生未冻结变化；
- 环境、工具或权限漂移；
- hidden tests 泄露；
- 实验 runner 存在影响某 arm 的实现错误；
- 预注册协议被违反。

“结果不符合预期”不是重跑理由。

---

## 13. 当前自然观察计划与 A/B/C 的关系

### 13.1 北极星当前主线

当前北极星主线是：

```text
封板项目内 experience 记录与 Planner 注入
→ 使用真实新任务自然观察规划、拒绝、人工纠正和 experience 回退
→ 达到 10 个真实新任务或封板后 30 天时复盘，以先到者为准
```

该主线继续有效，本文不自动修改它。

### 13.2 自然观察能证明什么

自然观察可以：

- 发现真实任务族；
- 记录规划、拒绝和人工纠正；
- 发现 experience-associated regression；
- 暴露缺失 telemetry；
- 为 A/B/C 选择任务和成本参数。

自然观察不能单独证明：

- Reweave 相对强 B 的产品优势；
- semantic compression；
- 小模型必要性；
- 跨项目复用；
- Agent-independent authority。

### 13.3 与正式实验的建议顺序

```text
1. 完成当前 10 个真实任务或 30 天观察门
2. 冻结 telemetry 字段和报价任务材料
3. 预注册 A/B/C 协议
4. 用户明确授权后执行 T1–T6
5. 按预注册裁决冻结产品结论
```

若当前观察已自然产生足够成熟的第二任务族，可在报价实验后复现；不能在第一个实验结果不佳时临时更换更容易的任务。

---

## 14. 产品与研究假设登记表

### H1：重复复用经济性

- **陈述**：正式能力的 acquisition 成本会在后续重复任务中被摊薄；
- **当前状态**：`UNPROVEN`；
- **已有支持**：结构上避免了部分 source proposal；
- **缺失数据**：人时、token、source reads、维护成本；
- **验证**：报价 A/B/C；
- **否定**：T6 时 C 未支配 B。

### H2：可验证语义缓存 / 上下文减少

- **陈述**：formal projection 能减少 Agent 对原始 source 的重复读取；
- **当前状态**：`UNMEASURED`；
- **允许词**：可验证能力抽象、结构化投影；
- **暂不允许词**：已证明的语义压缩；
- **验证**：记录 source files、bytes、projection bytes、input tokens；
- **否定**：C 的 source/context 总量不低于 B，且无其他收益。

### H3：模型分层

- **陈述**：强 Agent 处理开放问题，Reweave 形式化，更多子任务下沉给小模型与确定性程序；
- **当前状态**：`ARCHITECTURALLY_PLAUSIBLE / NOT_E2E_PROVEN`；
- **验证**：同一端到端任务中记录 frontier Agent、local model 和 deterministic core 的实际顺序与工作量；
- **否定**：小模型角色没有带来成本、隐私、离线或覆盖收益，或始终只是部署配置。

### H4：Agent-independent authority

- **陈述**：不同 Agent 可通过同一正式入口提交或消费 artifacts，而不改变 authority 语义；
- **当前状态**：`PARTIAL`；
- **验证**：外部 Agent proposal 进入同一授权、Intake、Review 与发布链；
- **否定**：正式流程持续依赖特定 Qwen/Ollama 产品入口或内部 Python 调用。

### H5：跨项目复用

- **陈述**：同一 qualified capability 可在不同真实项目中产生复用收益；
- **当前状态**：`UNKNOWN`；
- **验证**：至少两个外部项目、独立授权边界、无源码泄露、相同 exact version 被复用；
- **否定**：复用仅在为验收构造的同源任务中成立。

### H6：统一控制面价值

- **陈述**：将身份、资格、组合、授权、acceptance 和 stale 链统一，比组织自行拼装更低成本；
- **当前状态**：`UNPROVEN`；
- **验证**：强 B 的准备/维护与 C 的 formalization/维护对照；
- **否定**：B 以相同或更低成本达到相同正确性。

### H7：Experience 的窄收益

- **陈述**：项目内、同模型 digest 的少量 experience cases 可改善 composition selection，而不增加可归因回退；
- **当前状态**：`NARROWLY_ENABLED / OBSERVATION_PENDING`；
- **验证**：当前 10 个真实任务或 30 天观察；
- **否定**：出现经 control 复放确认的 experience-caused regression，且收益不能覆盖回退风险。

### H8：真实用户需求

- **陈述**：真实用户愿意在直接 Agent 和 Reweave 模式之间主动选择后者，并接受其确认成本；
- **当前状态**：`UNKNOWN`；
- **验证**：外部用户在没有项目作者代操作的情况下完成授权、Review、发布并重复使用；
- **否定**：用户持续选择直接 Agent，或必须由开发者人工编排才能完成。

---

## 15. 结果后的产品决策树

### 15.1 C 在报价族胜出

允许：

- 将“报价/定价规则”确认为首个优势任务族；
- 在同一能力边界内优化普通用户流程；
- 选择第二个相似、稳定、版本敏感任务族复现；
- 评估真实外部用户。

仍不允许：

- 直接升级为通用软件能力系统；
- 自动扩展网络、文件系统、数据库或多能力拓扑；
- 宣称小模型必要性；
- 宣称跨项目或生产级价值。

### 15.2 出现 Tradeoff

若 C 正确率更高但成本更高：

- 只探索高错误代价、强审批或版本敏感的窄场景；
- 预先量化失败损失和付费意愿；
- 不使用“更高效”的广义宣传；
- 不为普通低风险任务扩建。

### 15.3 与强 B 平局

- 冻结通用扩建；
- 保留 Reweave 作为研究系统、FDE/Agent 工程作品或内部控制面；
- 只修复明显 prototype debt；
- 不新增 capability 类型、模型角色、检索平台或 Agent 框架；
- 重新评估是否存在更窄、明确付费的治理场景。

### 15.4 C 明显更差

- 停止扩建通用 Reweave；
- 不再用“未来模型分层”解释当前成本劣势；
- 将可复用部分拆为独立工程资产：
  - formal identity / stale library；
  - Candidate acceptance harness；
  - Agent handoff protocol；
  - 作品与研究报告；
- 由产品所有者决定归档、窄化或转为内部工具。

### 15.5 产品成功不能由代码量替代

以下均不构成产品成功：

- 新增更多 capsule 类型；
- 更多测试；
- 更复杂的 Graph、RAG、MCP 或插件层；
- 更强模型；
- 更漂亮前端；
- 一次演示；
- 模型认为结果合理；
- 文档叙事更完整。

成功必须回到真实任务、强基线、累计成本、纠正、正确拒绝与用户选择。

---

## 16. 命名与对外表述政策

### 16.1 当前正式名称

建议当前使用：

> **Local bounded software reuse & delivery control plane**
> **本地、有界的软件复用与交付控制面**

它描述当前已经存在的 capability lifecycle、exact identity、composition、confirmation、Candidate、acceptance、export 与 Agent handoff，不预先宣称经济收益。

### 16.2 当前可以说

- Reweave 已证明窄范围 exact-version 能力可被再次组合和交付；
- Reweave 把身份、资格、合法组合、用户确认、验收和 stale 传播绑定为同一领域事实链；
- Codex 已能作为已确认计划 Candidate 的窄控制入口；
- 小模型已在部分规划、source proposal 和监督角色中真实运行；
- Reweave 当前 authority 是可信本地 writer 假设下的 domain/protocol authority；
- 复用经济性和强 B 优势仍待验证。

### 16.3 当前不能说

- Reweave 已证明生产级复用价值；
- Reweave 比 Codex 或成熟软件复用更高效；
- Reweave 已实现语义压缩；
- Reweave 是 Agent-independent authority layer；
- 小模型是 Reweave 的必要条件；
- Reweave 能防止恶意同权限 Agent 伪造状态；
- Reweave 已覆盖任意框架、任意能力或通用软件组合；
- Reweave 已形成数据飞轮或训练飞轮；
- 用户无法绕过 Reweave。

### 16.4 升级为 authority layer 的条件

只有同时满足：

- 外部 Agent/人工 proposal 正式接入；
- supervision provider 可替换；
- 同任务大小模型分层真实发生；
- 强 B 对照证明收益；
- authority/security 边界明确；
- 至少一个真实外部使用场景；

才允许升级名称为：

> **Agent-independent software capability authority layer**

### 16.5 “语义压缩”升级条件

只有在冻结任务和模型配置下，实际测得：

- source files/bytes 明显下降；
- input context 或 token 明显下降；
- 成功率不下降；
- formalization 成本在复用 horizon 内回收；

才允许使用“verified semantic compression”或类似词。此前使用“可验证能力抽象”或“结构化投影”。

---

## 17. 当前路线与近期行动

### 17.1 不改变北极星当前主线

本文发布后，当前全局路线仍以北极星为准：

```text
封板 experience
→ 观察 10 个真实新任务或 30 天
→ 复盘
```

### 17.2 立即补充的观测

不建设新平台，只补最小 telemetry：

1. capsule 正式化实际人时；
2. Agent 读取 source 文件数、字节和次数；
3. docs/schema/projection 字节；
4. 模型 input/output tokens 或 byte proxy；
5. 人工纠正原因和耗时；
6. 每次复用的累计交付成本；
7. 错误版本、非法组合、stale 与正确拒绝标签。

### 17.3 报价实验准备

在不执行实验前可完成：

- 冻结 T1–T6 业务例和隐藏测试；
- 构建强 B modules/docs/schema/tests 资产；
- 定义相同实现字节的映射；
- 编写只负责 telemetry 的实验 wrapper；
- 冻结模型和推理配置；
- 生成预注册 manifest；
- 由用户明确授权后开始。

### 17.4 当前禁止事项

在 A/B/C 或真实任务失败没有提出具体需求前，不新增：

- MCP 主协议；
- Plugin marketplace；
- 新 Agent framework；
- 第二仓库、第二 Composer 或第二事实图；
- 向量数据库、独立 RAG 服务或更多检索抽象；
- 训练平台、LoRA 或在线自训练；
- 网络、文件系统、数据库写入类 formal capability；
- fan-in、fan-out 或跨 capability group 通用拓扑；
- 以“未来可能有用”为依据的 telemetry 平台。

---

## 18. 文档维护与变更治理

### 18.1 状态

本文可处于：

- `DRAFT`：正在讨论，不作为决策基线；
- `PROPOSED_FOR_FREEZE`：内容完整，等待用户确认；
- `FROZEN`：作为产品论证与验证基线；
- `SUPERSEDED`：被后续精确版本替代；
- `ARCHIVED`：项目停止或转向后保留历史。

### 18.2 修订触发条件

仅在以下情况下修订核心结论：

- 北极星产品定义或交付模式改变；
- 新冻结证据改变“已证明/未证明”状态；
- A/B/C 或外部生产实验产生正式结果；
- authority/security 边界改变；
- 模型分层或 Agent-independent Gate 通过；
- 产品停止、窄化或转向决定已作出。

测试数量、临时路径、局部 bug 和单次开发过程不进入本文主结论。

### 18.3 每次修订必须包含

1. 变更摘要；
2. 受影响的 `FACT / DECISION / HYPOTHESIS / RISK / GATE`；
3. 新证据引用；
4. 哪些旧结论被升级、降级或撤销；
5. 是否需要同步修改北极星；
6. 是否改变已有实验的预注册条件；
7. 新文档版本和生效日期。

### 18.4 结论降级优先

若新代码或证据与本文冲突：

- 先把结论降级为 `PARTIAL`、`UNKNOWN` 或 `INVALIDATED`；
- 再调查代码、证据或文档谁过期；
- 不允许为保持叙事稳定而忽略反证。

### 18.5 决策记录模板

```markdown
## Decision D-YYYYMMDD-NN

- 状态：PROPOSED / ACCEPTED / REJECTED / SUPERSEDED
- 问题：
- 当前事实：
- 备选方案：
- 决定：
- 理由：
- 被放弃的收益：
- 风险：
- 需要的验证：
- 复盘触发条件：
- 关联证据：
```

### 18.6 假设记录模板

```markdown
## Hypothesis H-<ID>

- 陈述：
- 当前状态：
- 支持证据：
- 反证：
- 可观测预测：
- 验证方法：
- 通过条件：
- 否定条件：
- 截止或复盘门：
- 结果：
```

---

## 19. 最终产品判断基线

本版冻结为：

```text
CURRENT_PRODUCT_NAME = LOCAL_BOUNDED_SOFTWARE_REUSE_AND_DELIVERY_CONTROL_PLANE

REUSE_MECHANICS = PROVEN_NARROWLY
REUSE_ECONOMICS = UNPROVEN
PRODUCTION_USAGE = UNKNOWN
CROSS_PROJECT_REUSE = UNKNOWN
IRREDUCIBLE_DOMAIN_MODEL = PROVEN
NEW_COMPUTATIONAL_PRINCIPLE = NO
AGENT_CONTROL_ENTRY = PROVEN_NARROWLY
AGENT_INDEPENDENCE = PARTIAL_NOT_PRODUCTIZED
SMALL_MODEL_RUNTIME_ROLE = PROVEN
SMALL_MODEL_PRODUCT_NECESSITY = NO_EVIDENCE
MODEL_STRATIFICATION = HYPOTHESIS
SEMANTIC_COMPRESSION = HYPOTHESIS_UNMEASURED
DOMAIN_PROTOCOL_AUTHORITY = BOUNDED_PASS
ADVERSARIAL_SECURITY_AUTHORITY = NOT_IMPLEMENTED

CURRENT_ROADMAP = NORTH_STAR_EXPERIENCE_OBSERVATION
NEXT_VALUE_GATE = STRONG_A_B_C_FALSIFICATION
MECHANISM_EXPANSION = FROZEN_UNLESS_REAL_FAILURE_REQUIRES_IT
```

最重要的长期原则是：

> **Reweave 不需要证明所有软件都应该被正式化。它只需要证明：在一类稳定、重复、版本敏感、错误代价明确的任务中，把软件行为变成同一条可验证事实链，能够以可接受的成本持续减少重复理解、错误连接、版本漂移或人工纠正。**

如果连这一窄命题也无法在强 B 对照下成立，就应停止扩大项目理论，而不是继续增加机制。

---

# 附录 A：指标定义

## A.1 成功集合

`success_set_X` 是 arm X 在 T1–T6 中满足全部预注册标签的 task 集合。部分通过、人工修复后通过和模型自评通过不得自动计为成功，必须按实验协议单独标记。

## A.2 人工纠正

- `correction_count`：独立纠正事件数；
- `correction_seconds`：纠正实际耗时；
- `correction_category`：contract、version、wiring、prompt、code、environment、explanation、other；
- `information_added`：纠正是否向某 arm 增加原本没有的新信息。

## A.3 Formalization cost

至少包括：

- 来源选择和授权；
- 契约与业务例准备；
- Intake、qualification 和 Review；
- 用户确认与发布；
- 为实验需要但可长期复用的产品化工作；
- 为单次实验临时制作的 fixture/runner 工作应单独标记为 prototype debt。

## A.4 Maintenance cost

包括：

- 新版本正式化；
- tests/schema/docs 更新；
- stale 处理；
- 兼容规则和 validation 修订；
- B 的 changelog、semver、CI 与审批维护；
- C 的 capsule、contract、offer 与 evidence 维护。

## A.5 Source/context cost

分别记录：

- raw source reads；
- docs/schema reads；
- test reads；
- Reweave projection reads；
- prompt bytes/tokens；
- output bytes/tokens；
- fallback source reads。

不得把“projection 比某个单文件小”直接解释为整体上下文压缩。

---

# 附录 B：实验结果报告模板

```markdown
# Reweave Quote Family A/B/C Report

## 1. Identity
- experiment_id:
- preregistration_digest:
- date:
- runner_digest:
- model/inference configuration:
- phase: PILOT / DECISIVE
- replicate_count_per_arm:

## 2. Validity Check
- material parity:
- environment parity:
- hidden test secrecy:
- telemetry completeness:
- source_read_capture_complete:
- shell_or_subprocess_bypass_detected:
- deviations:
- validity: VALID / INVALID

## 3. Arm Results
### A. Codex only
### B. Strong conventional reuse
### C. Reweave

## 4. Task Matrix
| Task | A result | B result | C result | Notes |

## 5. Cost Matrix
| Metric | A | B | C |

## 6. Error and Correction Analysis

## 7. Pilot Verdict
- PROTOCOL_VALID
- PROTOCOL_INVALID
- NOT_APPLICABLE_DECISIVE_PHASE

## 8. Pre-registered Decisive Verdict
- PRODUCT_ADVANTAGE_DEMONSTRATED_IN_QUOTE_FAMILY
- TRADEOFF
- PARITY_WITH_STRONG_BASELINE
- PRODUCT_ADVANTAGE_NOT_DEMONSTRATED
- PRODUCT_DISADVANTAGE_OBSERVED
- INVALID
- NOT_APPLICABLE_PILOT_PHASE

## 9. Claim Changes
- Claims upgraded:
- Claims downgraded:
- Claims unchanged:

## 10. Product Decision
- expand / replicate / narrow / freeze / stop

## 11. Evidence References
```

---

# 附录 C：术语表

**Capability**
一个可被描述的能力概念；不自动等于 formal capsule。

**Formal capsule**
通过唯一 Intake、资格门、Frozen Review 和用户发布形成的不可变能力版本。

**Candidate**
由确认计划和正式能力形成、经过 runtime 与业务验收的审阅候选；不等于正式 product 晋升。

**Audit Candidate reuse**
在不同冻结验收任务中，精确版本被再次引用和交付。

**Formal warehouse reuse**
同一正式 exact version 从 catalog 被多次选择；当前主要由 artifacts 交叉复算，不是完整 usage ledger。

**Product usage**
正式晋升产品的不可变版本记录其使用的 capsules；当前未实现完整语义。

**Qualification**
来源、安全、监督和 runtime 等证据与 exact version 的绑定。

**Legal composition**
由正式契约和确定性核心枚举、连接并验证的完整组合。

**Authority**
对 Reweave domain facts 的正式决定权；当前以可信本地 writer 为假设。

**Security authority**
面对恶意或同权限写者仍可证明状态真实的能力；当前未实现。

**Shuttle / 梭子**
Agent 与 Reweave AppService 之间窄本地适配入口的非正式昵称，不是正式产品对象。

**Strong B**
模块、契约、Schema、tests、semver、commit SHA、lockfile、changelog、CI 和审批等成熟普通工程复用基线。

**Model stratification**
强 Agent 处理开放问题、Reweave 形式化、受限任务下沉给小模型和确定性程序的待验证假设。

**Transitive stale**
任一上游正式事实漂移会使所有依赖的下游状态失效，而不是静默迁移。
