# Reweave 旧项目清洗入库与唯一胶囊仓库设计

文档状态：阶段 0 已封板；阶段 1–6 在 Static Web V1 支持面内为 `PASS`；附录 S 的 JavaScript 计算抓取阶段 D–G 为 `PASS`。阶段 G 已用三个冻结第三方项目证明 `computation_adapter.v2` 的 `validated_positive`，并把 Grapheme 的外部 computation 胶囊与既有 presentation/interaction 组合，在真实 QWebEngine 中完成业务断言；这不扩大为外部 presentation/interaction 自动拆分已经完成。本地真实桌面与 Python 3.11/Node 24 CI 等价门已通过，本次最终字节尚未 push、未触发托管 CI；classic script、普通应用顶层 bootstrap、框架源码与需构建项目明确留在 V1 外

初版日期：2026-07-14

阶段 1 完成日期：2026-07-15

阶段 2 完成日期：2026-07-15

阶段 3 完成日期：2026-07-15

阶段 4 完成日期：2026-07-15

阶段 5 完成日期：2026-07-15

阶段 6 受支持范围桌面验收日期：2026-07-15

适用仓库：/Users/hack/Documents/Codex/projects/reweave-fresh-main

基线提交：1209bdad6a8cd7cff765eb7786bae330ef18e4e7

阶段 1–6 初始实现 checkpoint：f27b5dc6c17fcf82d18a43911b55f8e36b464b66

Windows 托管 CI 修复提交：bdec38b8b92f9f56df737568cf36c69f8f05fd28

实施状态：阶段 1–3 的唯一 SQLite、来源快照、原子提取、固定安全、loopback Ollama 监督和三个隔离验证基础已完成并冻结。当前 `extraction_contract.v2` 在 v1 固定角色入口之外，只接纳能通过同一原子闭包、形参、DOM/Event 和 data contract 全部证明的普通 ESM 顶层具名函数；它不会包装 classic script、重写源码或把模型变成边界决策者。阶段 4 已在原桌面前端和唯一 ReweaveAppService 中激活来源、品牌、模型、复核、仓库、备份恢复与旧 JSON 重新清洗管理。阶段 5 已完成单次生成切换：只查询 eligible active-current SQLite 版本，只向 `module_native` 传递内存对象，并原子写入产品 manifest 与精确 usage；`generationActive=true`、`generationFromSqlite=true`。旧 `generate_preview`、Stage4 demo 和旧引擎生成不再属于正式发布调用图。阶段 6 已用一个受支持的单入口静态 ES module 项目，在可见原桌面窗口中完成“绑定来源→清洗监督→人工发布→同页面刷新正式胶囊→生成→真实 QWebEngine 产品交互→恢复后同页面清除旧状态”；来源项目零写入和 manifest/SQLite 精确版本追溯均已证明。仓库自带的代表性旧 `customer-quote-widget` 使用 classic script，按已封板的 Static Web V1 产品边界在项目确认时明确返回 `classic_script_unsupported_v1`，因此本文不把受支持夹具的成功扩大为“现有 classic-script 旧项目已经可入库”。

## 1. 文档目的

本文把已确认的产品架构转成可以直接实施和验收的阶段 0 设计。它覆盖：

- 来源根目录、项目和单入口静态闭包。
- 固定规则清洗、本地 Ollama 监督和独立验证。
- 唯一 SQLite 正式胶囊仓库。
- 完整能力、原子胶囊、变体和不可变版本。
- module_native 的唯一内存输入边界。
- 产品生成资格和精确版本追溯。
- 备份、恢复、故障隔离和状态恢复。

本文不是整个产品的无限范围完成声明。阶段 1–6 已按各自阶段门完成；阶段 6 已证明封板支持面内的真实桌面和真实产品交互闭环，GitHub 托管 Ubuntu/Windows runner 也已通过。classic script、CommonJS、TypeScript/JSX、框架组件源码、需构建来源和多页面自动推断明确留在 V1 外，不以 wrapper、模型改写或 fallback 绕过。阶段 5 的产品启动探针、阶段 6 的真实产品点击、模型辅助截图检查与人工视觉签字仍是四种不同证据，不能互相替代。

## 2. 锁定边界

### 2.1 目标

Reweave 将旧项目中的可复用能力转成干净、最小、可独立验证、可追溯且不会互相污染的胶囊。权威主线只有一条：

~~~text
来源根目录
→ 项目和入口确认
→ 只读一致性快照
→ 原子能力候选
→ 敏感数据清除
→ HTML/CSS/JavaScript/资产固定规则
→ 本地 Ollama 监督
→ 独立子进程验证
→ 精确重复、等价建议、变体和版本判断
→ 必要人工复核
→ SQLite 原子发布
→ module_native 组合
→ index.html / styles.css / app.js / manifest
→ 产品精确版本历史
~~~

### 2.2 非目标

V1 不做：

- 第二个正式仓库、第二套清洗工序或第二个 composer。
- JSON 兼容 repository、repository 接口、存储工厂或可插拔数据库。
- 模板、fallback、preview/export/promote 新系统。
- 后台文件监听、云模型或多模型投票。
- React、Vue、Svelte 等框架源码清洗。
- 自动安装来源项目依赖或执行来源构建脚本。
- 多页面应用自动推理。
- SVG 或字体资产入仓。
- 物理删除正式胶囊。
- 模型直接发布正式胶囊。
- 来源项目写入。

### 2.3 阶段门

阶段 0 已完成契约闭合并经用户确认，阶段 1–3 已完成并冻结，阶段 4 已激活 SQLite 入库和管理查询，阶段 5 已在资格查询、组合器内存契约、manifest 与 usage 原子登记全部通过后完成一次性生成切换。正式前端和 CLI 不提供旧 JSON/SQLite 二选一，也没有运行时双仓开关。

## 3. 当前实现事实与目标差距

以下是基线提交的只读复核结果，不代表目标设计已经实现。

| 关注点 | 当前事实 | 目标差距 |
|---|---|---|
| 应用状态目录 | reweave_source_registry.state_dir() 已支持 macOS、Windows、Linux 和 REWEAVE_STATE_DIR | 新数据库和备份必须复用它 |
| Source Box 身份 | source ID 是绝对路径 SHA-256 的短摘要 | 项目需要独立 UUID，移动后可重连 |
| 扫描 | 默认最多 800 文件、深度 8、单文件 1 MiB；跳过符号链接和常见依赖/构建目录；主要记录元数据 | 缺少内容快照、项目递归确认、父子排除和变化中止 |
| 候选 | reweave_capsule_draft 按文件扩展名和入口文件产生建议 | 必须改为具有业务语义的原子能力角色 |
| 正式仓库 | state_dir()/capsule_warehouse/capsules.json，记录可被覆盖 | 需要 SQLite、不可变版本和数据库级约束 |
| 第二历史路径 | LumoLiteReweaveEngine 读取 state_dir()/stage4_behavior_modules | 最终生成切换后必须退出活跃调用图 |
| composer | module_native 接收 capsule_path 并自行 load_module_capsules | 必须改为只接收应用服务提供的内存态正式版本 |
| 本地模型 | 现有 Ollama 调用已限制 localhost，但主要是可选生成增强 | 正式新胶囊必须有用途级监督模型和 digest |
| 前端模型 | app.js 硬编码 qwen2.5-coder:1.5b | 必须改为应用服务提供的用户选择 |
| 前端生成分流 | app.js 根据 stage4_module_native 来源数量决定模式 | 必须删除旧架构业务判断 |
| QWeb 验证 | 已使用子进程，但当前允许 data/blob/about，并开启本地文件访问 | 新验证器只允许最小临时包登记文件 |
| CI | Python 3.11、Node 24，Ubuntu 和 Windows | 主应用和既有 Static Web V1 必须保留该支持门；附录 S 的 `javascript_computation_capture.v1` 首版仅支持 macOS/Linux，Windows 必须在读取来源字节和写索引前结构化返回 `source_platform_unsupported_v1` |
| 本地桌面 | 计划使用 Python 3.14.5、Node 22.22.3、PySide6 6.11.1 | 真实 QWeb 是本地发布门，不冒充 CI 覆盖 |

保留原前端是保留界面、主要结构和用户体验，不是保留上述模型硬编码、Stage4 来源分流或旧仓读取。

## 4. 权威术语

### 4.1 完整能力

capability_key 表示用户理解的一项完整能力，例如 quote_calculation。

完整能力只用于语义分组和仓库展示，不形成第二种载荷或第二个仓库。

### 4.2 原子胶囊

胶囊是完整能力中可以独立声明、验证和复用的原子角色。capability_kind 固定为：

- presentation：声明输入到局部界面。
- interaction：局部用户事件到声明输出。
- computation：声明输入到结构化计算结果。

例如：

~~~text
capability_key: quote_calculation

presentation / quote_summary / default
interaction  / quote_input   / default
computation  / total_price   / precise
~~~

只有同时满足以下条件才允许拆开：

- 有独立输入和输出契约。
- 可以脱离另外两个角色独立验证。
- 可以在其他完整能力中独立复用。
- 拆开后仍有明确业务语义。

禁止退化为 HTML 胶囊、CSS 胶囊、JavaScript 胶囊、单按钮胶囊或无业务语义的文件片段。

### 4.3 变体和版本

- role_key 表示完整能力内的原子业务角色。
- variant_key 表示同一角色中具有实质可观察差异的方案。
- version 表示同一角色和变体的不可变实现演进。

精度、舍入、错误规则、操作流程、界面结果或允许影响不同，形成不同变体。安全清洗、资产或实现升级但契约和可观察语义保持同一变体时，形成新版本。

### 4.4 原子提取契约

原子边界由固定静态规则决定，当前版本标识为 extraction_contract.v2，正式记录字段为 extraction_contract_version。v2 相比 v1 只扩展普通 ESM 顶层具名函数的确定性角色发现，不改变 DOM、数据、原子闭包或运行契约。Ollama 不能选择代码、扩大闭包、删除依赖或决定输入输出契约；它只能在固定提取完成后监督语义、提出名称和分组建议。

固定工序：

1. 从用户确认的单一 HTML 入口和项目根建立只读文件图。
2. 解析 HTML 节点、表单控件、template、data-ref、data-action、id/for 和登记资产。
   UI 原子根按固定顺序选择：恰好一个 `data-capsule-root` 优先；没有显式标记时使用唯一 `<main>`；否则使用唯一 `<form>`。多个显式标记或仍无法得到唯一根时，presentation/interaction 以 `html_capsule_root_invalid` 拒绝，computation 不受 UI 根门禁影响。阶段 2 和阶段 3 必须使用同一规则，且只清洗选中子树，不修改来源 HTML。
3. 解析 CSS selector 到 HTML 节点的静态引用。
4. 解析全部本地 ES module、import/export、函数和局部符号引用。
5. 记录 DOM 查询、DOM 更新、事件注册、事件移除、ports.emit、函数返回和纯函数调用边。
6. 从固定种子形成候选：显式导出的 render、mount、compute 继续分别对应三类角色；入口模块中任意名称的顶层具名 function 或 immutable const function，只有完整通过对应正式 render(root,input)、mount(root,ports) 或 compute(input) 静态契约时，才分别成为 presentation、interaction 或 computation 种子。函数名、export 名和模型建议不能单独决定角色。
7. 沿静态调用和数据流边递归收集依赖闭包，再按第 9 节收集模块闭包。
8. 从闭包实际读取和写出的字段生成 data_contract.v1，并从契约生成合成验证样例。
9. 只有闭包、契约、作用域和样例均可静态证明时，候选才进入敏感数据门。

一个原子候选必须同时满足：

- 只有一个 capability_kind 和一个 activation 入口。
- 只有一个可用业务动词和一个可描述的业务结果。
- 所需 HTML、CSS、JavaScript 和资产依赖闭合。
- 输入来源、输出去向和错误结果全部可枚举。
- presentation 和 interaction 只触及同一个最小 HTML 根。
- computation 不依赖 DOM、事件、时间、随机数或外部状态。
- 移除候选闭包不会要求把无关页面区域或无关业务流程一起纳入。

边界处理固定为：

- 仅缺少 capability/role/variant 命名或两个安全闭包的分组关系时进入 review_required；用户只决定身份和分组，不决定代码闭包。
- 仅缺少“此字面数据是否虚构、是否保留品牌”的事实时进入 waiting_user，并按第 15 节处理。
- 固定追踪发现同一根、同一原子角色内的直接静态依赖时自动扩大到该依赖；每次扩大都写入脱敏 extraction_summary_json。
- TypeScript 提取器只接收 snapshot_before 内的模块逻辑路径、UTF-8 源码和 SHA-256；它不得接收来源项目根路径或重新读取来源目录。入口、import、CSS 或登记资产不在同一快照时，本次 run 失败关闭且不得形成 no_change 缓存。
- 同一入口模块或其闭包暴露多个角色种子时，以 non_atomic_role_closure_v1 拒绝相关角色；不通过 tree shaking、删除业务语句或只选择一个 export 伪造原子性。不同角色可以共享只导出纯 helper 的模块。
- 任意名称种子唯一通过完整角色证明后，提取器只在候选内存副本的 entry module 末尾追加稳定的 `export { originalName as render|mount|compute };`。该固定别名不写回来源、不改变业务语句，进入 canonical hash，并使安全分析、隔离 worker 和唯一组合器继续只接收固定正式入口。别名冲突、多个种子同时成立或无法证明完整正式入口时失败关闭。
- v2 不把 classic script、顶层 document/window 查询、顶层事件注册、裸标量参数、裸成功返回或缺失 emit/dispose 的旧代码自动包装成胶囊；这些内容仍为 unsupported_v1。扩大这部分范围必须先定义新的确定性 AST 迁移契约，不能交给 Ollama、模板或 fallback。
- 静态字符串证据使用有界、循环安全的 immutable const 传播，覆盖 identifier、字符串加法和 template 组合；传播最多 32 层、4096 步，不执行候选代码。无法解析的字符串组合不得作为“未命中敏感/品牌”证据。
- `join`、`concat`、`String.fromCharCode/fromCodePoint`、`JSON.parse/stringify`、运行时字符串转换以及其他无法由上述传播器完全证明的字符串构造，以 `unsupported_string_construction_v1` 失败关闭；禁用成员作为别名、回调或可执行值引用时同样拒绝，不得让间接调用绕过敏感或品牌门。`input.parse`、`input.join` 等普通 data_contract 字段在不作为可执行值使用时仍是合法数据读取。
- 入口函数内部的局部 function/arrow 必须证明属于该角色：interaction 只接纳被 addEventListener 直接引用的 handler 和最终返回的具名 disposer；presentation/computation 的局部函数以及任何未使用、阴影或间接别名函数 V1 均以 unsupported_extraction_boundary_v1 拒绝。
- 普通局部 `const` 也必须能从返回值、允许的 DOM/emit 副作用或支配守卫反向证明为必需；未使用的局部绑定、裸表达式、可变局部状态和不支持的语句一律以 `unsupported_extraction_boundary_v1` 拒绝，不能依赖 bundler 消除。
- 需要跨根、动态 selector、动态属性、未知回调、运行时反射、隐式全局、未解析调用目标或无关业务代码才能闭合时，候选以 unsupported_extraction_boundary_v1 拒绝。
- 禁止为了“尽量成功”把整个页面、整个入口模块或整个项目扩大成一个胶囊。

契约和测试样例的生成规则：

- presentation 输入取自 render 参数中实际读取的字段；输出固定为 no_output.v1，DOM 效果由 dom_scope 和 QWeb 断言描述。
- interaction 输入取自 ports.input 实际读取字段；每个静态 ports.emit 名称形成一个声明输出端口，其 value 形成独立 data_contract.v1。
- computation 输入取自 compute 参数实际读取字段；成功 value 和声明 error 分别形成输出、错误契约。
- HTML 表单值只通过已证明位于 root 内的绑定元素读取，形成 interaction 输出字段，不伪装成 ports.input。min、max、step、minlength 和 maxlength 只作为控件元数据，不能单独证明 emit 契约；数值值必须在同一同步 handler 内先转换，再由支配 emit 的整数和上下界 guard 证明，无法证明时以 ambiguous_data_contract_v1 拒绝。
- interaction 必须唯一地在 mount 最后返回一个同步、无参数的 dispose 函数；只有该返回函数体内与 mount 顶层 addEventListener 按元素、事件和 handler 精确配对的 removeEventListener 才构成清理证据。mount 或 handler 其他位置的 remove 不得闭合契约。
- 字段类型必须由静态操作和固定字面约束唯一确定；类型不唯一时以 ambiguous_data_contract_v1 拒绝，不能由用户或模型猜测代码语义。
- 验证样例只根据脱敏后的 schema 生成：每个契约至少一个正常值、每个有限边界一个边界值、每类拒绝条件一个无效值。
- 来源中的真实记录和原始示例不得复制成 fixture；字符串使用固定合成值，十进制和整数使用边界内合成值。

原始文件图、源码符号图和初始契约只存在于当前任务内存；其中的字符串、enum 和样例在第 15 节敏感门完成前不得写入 review_items、日志或模型请求。每个正式版本保存 extraction_contract_version 和脱敏后的 extraction_summary_json。摘要只包含逻辑路径、入口符号、依赖边类型、被纳入/拒绝原因、脱敏契约字段名和样例类别，不保存来源原文。提取规则升级后，所有曾贡献当前版本的项目必须重新扫描；受影响正式胶囊进入 pending_revalidation，旧 extraction 结论不能用于精确重复短路。

## 5. 稳定 Key 生命周期

### 5.1 格式和唯一性

- capability_key：全局唯一 snake_case。
- role_key：在 capability_key 内唯一 snake_case。
- variant_key：在 capability_key + role_key 内唯一 snake_case。
- 首个变体默认使用 default。
- 所有数据库主 ID 使用应用生成的 UUID，不使用路径、时间或模型文本作为 ID。

### 5.2 产生和冻结

1. 候选阶段只有 suggested_capability_key、suggested_role_key 和 suggested_variant_key，不是正式身份。
2. 固定规则根据脱敏后的语义摘要产生 snake_case 建议；模型可以建议，但不能冻结 key。
3. 精确重复候选继承已存在版本的全部正式 key。
4. 新身份发布时，在同一个事务中插入 capability group 和 capsule，正式 key 从此冻结。
5. 建议 key 冲突时追加 canonical hash 前 8 位；不使用路径或时间。
6. 展示名称与 key 分离，展示名称允许修改。

### 5.3 发布后的修正

- 仅名称不理想：只改 capability group 的 display_name。
- 语义分组确实错误：重新产生候选，完成全部门禁，由用户选择 semantic_split。
- semantic_split 可以在新身份下保留相同 canonical hash，但必须记录旧身份、新身份、理由和用户决定。
- 新身份发布后停用旧身份；旧版本和已有产品引用不改变。
- V1 不提供通用 rekey API，也不原地修改已发布 key。

canonical hash 不包含 capability_key、role_key 和 variant_key，因此 key 生命周期不会改变内容身份。canonical_hash 建立普通索引而非全局唯一约束；自动精确重复门禁止重复，semantic_split 是唯一人工例外。

## 6. dom_scope 与 usage_scope

### 6.1 dom_scope

dom_scope 是技术隔离契约：

~~~json
{
  "root_contract": "capsule_root",
  "selectors": [
    "[data-ref='unit-price']",
    "[data-action='calculate']"
  ],
  "classes": ["is-invalid", "is-hidden"],
  "attributes": ["aria-invalid", "data-state"],
  "events": ["input", "click", "submit"]
}
~~~

它只决定：

- 根内查询。
- 允许事件。
- 可修改 class 和 attribute。
- CSS 根作用域。
- QWeb 根外哨兵。

它不包含项目、品牌、客户或生成资格。

### 6.2 usage_scope

usage_scope 是语义使用范围：

~~~json
{"kind": "general"}
~~~

或：

~~~json
{
  "kind": "brand_limited",
  "brand_profile_id": "7bd8dcf1-8e61-4c48-a78c-1d56de7bf321",
  "brand_profile_digest": "sha256:..."
}
~~~

它只决定：

- 能否参与当前产品生成。
- 品牌配置变化后是否需要重审。
- manifest 和产品使用历史中的范围追溯。

它不参与 DOM selector、CSS scope 或运行时根生成。

### 6.3 固定约束

- 两个 scope 分开存储和验证。
- 两者都参与 canonical hash。
- 任一 scope 改变必须产生新版本。
- CSS 正式载荷使用字面占位符 __CAPSULE_ROOT__。
- composer 为每次产品生成一个唯一根 token，并安全替换占位符。
- 运行时 token 不进入 canonical hash。
- JavaScript 只接收 root，不允许查询运行时 token。
- 一个胶囊根不得包含另一个胶囊根。
- 来源根按“唯一显式标记 → 唯一 `main` → 唯一 `form`”确定；多个显式标记或最终仍不唯一时失败关闭。阶段 2 提取与阶段 3 清洗不得采用不同回退规则。
- `data-capsule-root` 只用于来源根选择，清洗后的正式 HTML 不保留该属性。

允许示例：

~~~css
__CAPSULE_ROOT__ .quote-total { color: #111827; }
~~~

拒绝示例：

~~~css
body .quote-total { color: #111827; }
~~~

## 7. 三种运行契约

### 7.1 公共规则

V1 的 render、mount、compute 全部同步执行。以下内容拒绝：

- Promise 返回值。
- async 函数。
- generator。
- top-level await。
- NaN、Infinity。
- 函数、DOM 节点或循环引用输出。
- 未处理异常越过边界。

运行器先对 input 执行结构化克隆，再递归冻结。所有输出必须是有限的 JSON 兼容值。

### 7.2 presentation

~~~javascript
export function render(root, input) {
  root.querySelector("[data-ref='name']").textContent = input.name;
}
~~~

正式模型：

~~~json
{
  "capability_kind": "presentation",
  "activation": {
    "mode": "declared_input_render",
    "entry_module": "presentation.js",
    "entrypoint": "render"
  },
  "runtime_allowlist": [
    "local_computation",
    "scoped_ui_update",
    "bundled_asset_read"
  ]
}
~~~

规则：

- 不绑定任何事件。
- 同样输入产生同样界面结果。
- 重复 render 不累计重复节点。
- 空输入和错误输入表现必须写入契约。
- 动态列表只能克隆根内 template 并写回根内声明容器。

### 7.3 interaction

~~~javascript
export function mount(root, ports) {
  const button = root.querySelector("[data-action='calculate']");
  const onClick = () => ports.emit("calculate_requested", {
    unit_price: 12.8,
    quantity: 10
  });
  button.addEventListener("click", onClick);
  let disposed = false;
  return function dispose() {
    if (disposed) return;
    disposed = true;
    button.removeEventListener("click", onClick);
  };
}
~~~

正式模型：

~~~json
{
  "capability_kind": "interaction",
  "activation": {
    "mode": "declared_event_mount",
    "entry_module": "interaction.js",
    "entrypoint": "mount",
    "cleanup": "returned_dispose"
  },
  "runtime_allowlist": [
    "scoped_input_read",
    "declared_event_handling",
    "memory_state",
    "scoped_ui_update",
    "declared_output_emit"
  ]
}
~~~

ports V1 只包含：

- ports.input：深拷贝、深冻结的声明输入。
- ports.emit(name, value)：受输出名称和 schema 校验的声明输出。

规则：

- mount 必须返回幂等 dispose。
- 输入变化只使用 dispose → mount，不增加 update。
- dispose 后不得响应旧监听或 emit。
- 不提供任意 invoke，不允许发现仓库中的其他胶囊。

### 7.4 computation

~~~javascript
export function compute(input) {
  if (input.quantity < 0) {
    return {
      ok: false,
      error: {
        code: "INVALID_QUANTITY",
        field: "quantity",
        details: {"minimum": 0}
      }
    };
  }
  return {
    ok: true,
    value: {"total_price": input.unit_price * input.quantity}
  };
}
~~~

正式模型：

~~~json
{
  "capability_kind": "computation",
  "activation": {
    "mode": "declared_input_compute",
    "entry_module": "compute.js",
    "entrypoint": "compute"
  },
  "runtime_allowlist": ["local_computation"]
}
~~~

ComputeResult 固定为：

~~~text
{ok: true, value: JsonObject}
或
{ok: false, error: {code: string, field?: string, details?: JsonObject}}
~~~

规则：

- value 必须是对象，裸数字、字符串和数组拒绝。
- 只有契约明确把某个业务状态定义为正常值时才可使用 ok:true；契约定义的无效输入或计算失败必须使用 ok:false。
- error.details 不得包含完整输入、真实记录或堆栈。
- 不允许 memory_state、DOM、时间、随机数或跨调用状态。

### 7.5 data_contract.v1

input_contract、成功输出中的数据和 error.details 只使用 data_contract.v1。它不是完整 JSON Schema，也不接受实现自定义关键字。

对象示例：

~~~json
{
  "schema": "data_contract.v1",
  "type": "object",
  "properties": {
    "quantity": {
      "type": "integer",
      "minimum": 0,
      "maximum": 10000
    },
    "unit_price": {
      "type": "decimal",
      "minimum": "0",
      "maximum": "999999.99",
      "max_scale": 2
    }
  },
  "required": ["quantity", "unit_price"],
  "additional_properties": false
}
~~~

允许节点：

- object：properties、required、additional_properties=false；属性名是非空 UTF-8 字符串。
- array：items、min_items、max_items；max_items 必填且不超过 1000。
- string：min_length、max_length、enum；max_length 必填且不超过 10000 个 JavaScript UTF-16 code unit。
- boolean。
- integer：minimum、maximum、enum；上下界必填，只允许 JavaScript 安全整数 `-9007199254740991` 至 `9007199254740991`。
- decimal：minimum、maximum、max_scale、enum；运行值是规范十进制字符串，不是二进制浮点数。

规范十进制的整数部分只能是 0 或不带前导零的数字，可有负号和小数部分；禁止正号、指数、NaN、Infinity、负零和尾随小数零。0.00 规范化为 0，12.80 规范化为 12.8。整数位最多 18 位，max_scale 为 0 至 18。

公共限制：

- enum 最多 100 个同类型规范值，去重后排序。
- 契约嵌套深度最多 8，属性总数最多 128。
- required 必须是 properties 的子集并排序。
- minimum 不得大于 maximum，min_items/min_length 不得大于对应 maximum。
- 可选字段通过不进入 required 表示；V1 不接受 null 类型。
- 所有未列出的关键字拒绝。
- 属性名、required、事件名和错误码必须是可严格编码为 UTF-8 的非空字符串，拒绝 C0/DEL 控制字符以及 `__proto__`、`prototype`、`constructor`；string enum 和运行时 string 值同样必须可严格编码为 UTF-8，孤立 UTF-16 surrogate 不能通过验证。
- 合成 fixture 最多 64 个无效样例、65536 个 JSON 节点和 512 KiB；预算不足以覆盖每类适用拒绝条件时失败关闭，不能截断后宣称闭合。
- integer 即使把 minimum/maximum 设为完整 JavaScript 安全区间，也必须生成 `-9007199254740992` 和 `9007199254740992` 两个可精确表示但非 safe integer 的拒绝样例，不能因为契约已经到全局边界而漏掉安全整数类别。

明确拒绝：

- $ref、$id、definitions 和递归。
- oneOf、anyOf、allOf、not、if/then/else。
- pattern、patternProperties 和任意正则。
- additional_properties=true 或 schema 未声明字段。
- number/float、tuple array、任意类型和隐式类型转换。

允许的嵌套节点：

~~~json
{"schema":"data_contract.v1","type":"string","min_length":1,"max_length":40,"enum":["draft","final"]}
~~~

拒绝：

~~~json
{"schema":"data_contract.v1","oneOf":[{"type":"integer"},{"type":"string"}]}
~~~

三个运行入口的外层格式固定：

- presentation.input_contract 是 data_contract.v1；output_contract 固定为 {"schema":"no_output.v1"}。应用边界先按 input_contract 拒绝无效输入，只有已接受输入才调用 render；成功 render 必须返回 undefined。error_contract 保存固定输入拒绝码，供应用边界和审计使用，不授权 QWeb 把无效输入直接交给 render。
- interaction.input_contract 是 data_contract.v1；Static Web V1 的 output_contract 使用 event_outputs.v1，且 `events` 必须恰好包含一个静态 emit 名称及其 data_contract.v1。
- computation.input_contract 和 output_contract 均是 data_contract.v1，其中 output_contract 描述 ComputeResult.value；error_contract 使用 error_contract.v1。

所有 input_contract、computation value 和 interaction emit value 的根类型必须是 object；array、string、boolean、integer 和 decimal 只作为嵌套字段使用。no_output.v1 不接受其他字段，仅表示该入口没有数据输出。

~~~json
{
  "schema": "event_outputs.v1",
  "events": {
    "calculate_requested": {
      "schema": "data_contract.v1",
      "type": "object",
      "properties": {
        "quantity": {"type": "integer", "minimum": 0, "maximum": 10000}
      },
      "required": ["quantity"],
      "additional_properties": false
    }
  }
}
~~~

~~~json
{
  "schema": "error_contract.v1",
  "errors": {
    "INVALID_QUANTITY": {
      "field": "quantity",
      "details": {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
          "minimum": {"type": "integer", "minimum": 0, "maximum": 0}
        },
        "required": ["minimum"],
        "additional_properties": false
      }
    }
  }
}
~~~

event_outputs.v1 的 `events` 在 Static Web V1 必须且只能包含一个事件；事件名和 error_contract.v1 的错误码必须是静态、非空、唯一字符串，其内部数据节点仍全部遵守 data_contract.v1。零事件或多事件 interaction 在正式规范化入口失败关闭，不能等到 composer 才拒绝。presentation 的 error_contract 也使用 error_contract.v1；没有声明错误时 errors 是空对象。

组合兼容检查方向固定为“来源输出的所有合法值都必须被目标输入接受”：

- 类型必须完全相同，不做字符串、整数和十进制之间的转换。
- 来源 object 的每个可能输出属性都必须在目标 properties 中；目标 required 的每个属性必须是来源 required；同名属性递归兼容。
- 来源 enum 必须是目标 enum 的子集；目标有 enum 而来源无 enum时不兼容。
- 来源数值范围、字符串长度范围和数组长度范围必须是目标范围的子集。
- decimal 的来源 max_scale 不得大于目标 max_scale，且来源范围必须包含于目标范围。
- array 的 items 必须递归兼容。
- event 输出先按静态事件名选定 data contract，再执行上述检查。
- V1 连接只传完整声明值，不执行字段重命名、默认值填充、裁剪、计算或任意 adapter。
- 任一上界、类型或包含关系无法静态证明时判定 incompatible_contract，不能由 Ollama 放宽。

## 8. 根内 DOM 与 Event 白名单

### 8.1 Selector

- selector 必须是源码中的静态字符串。
- selector 必须逐字出现在 dom_scope.selectors。
- 查询起点只能是传入的 root 或已证明属于 root 的元素。
- 禁止动态拼接、模板字符串和变量 selector。

允许：

~~~javascript
root.querySelector("[data-ref='quantity']");
~~~

拒绝：

~~~javascript
document.querySelector("[data-ref='quantity']");
root.querySelector("[data-ref='" + name + "']");
~~~

### 8.2 读取白名单

允许：

- root.querySelector
- root.querySelectorAll
- textContent
- value
- checked
- selectedIndex
- disabled
- hidden
- 已声明的 data-* 属性
- 已声明的 aria-* 属性

### 8.3 更新白名单

允许：

- textContent
- value
- checked
- selectedIndex
- disabled
- hidden
- classList.add/remove/toggle，参数必须在 dom_scope.classes
- aria-*，名称必须在 dom_scope.attributes
- data-state，必须在 dom_scope.attributes
- 对既有根内节点执行 append/replaceChildren，仅限固定安全分析能证明节点来源和目标均在声明 root 内的情形。

`template.content.cloneNode` 在 V1 当前固定分析器尚不能证明 template selector 与克隆来源的一一对应，因此实现失败关闭；它不是宽松回退。若后续增加该证据，必须升级 security_rules_version 并让旧版本 pending_revalidation。

setAttribute/removeAttribute 只有在属性名为静态字符串且出现在 dom_scope.attributes 时允许；其他属性拒绝。

### 8.4 明确拒绝

- document、window、globalThis
- ownerDocument、getRootNode
- parentElement、parentNode；V1 不允许向上遍历，因此不存在“验证后允许”的分支
- closest
- innerHTML、outerHTML、insertAdjacentHTML
- element.style
- 任意 createElement 或动态资源节点
- 删除 root
- 未声明 selector、class 或 attribute
- DOM 节点通过 ports.emit 输出

### 8.5 Event

允许事件固定为：

- click
- input
- change
- select
- submit
- reset

规则：

- presentation 不允许 addEventListener。
- interaction 只能监听根内声明元素。
- 事件名必须是静态字符串且在 dom_scope.events。
- 不允许 capture、全局委托、自定义事件、dispatchEvent。
- submit handler 必须 preventDefault。
- 每个 addEventListener 都必须有对应 removeEventListener。
- 验证器必须证明 dispose 幂等且 dispose 后没有输出。
- handler 的事件参数只能直接调用 event.preventDefault()；不得读取、保存、解构、返回或传递该对象。
- event.target、currentTarget、view、srcElement、type、key、detail、composedPath 和其他全部事件属性或方法均拒绝。
- 需要读取控件值时，只能读取注册监听时已经证明位于 root 内的绑定元素变量；不得通过 event 重新取得节点。

允许：

~~~javascript
button.addEventListener("click", onClick);
~~~

~~~javascript
const form = root.querySelector("[data-ref='form']");
const field = root.querySelector("[data-ref='value']");
const onSubmit = (event) => {
  event.preventDefault();
  ports.emit("submitted", {value: field.value});
};
form.addEventListener("submit", onSubmit);
~~~

拒绝：

~~~javascript
window.addEventListener("click", onClick);
button.addEventListener(eventName, onClick, true);
button.addEventListener("click", (event) => ports.emit("clicked", {
  value: event.target.value,
  view: event.view
}));
~~~

### 8.6 JavaScript 固定安全门

runtime allowlist 只允许以下七项：

- scoped_input_read
- declared_event_handling
- local_computation
- memory_state
- scoped_ui_update
- declared_output_emit
- bundled_asset_read

固定拒绝：

- fetch、XMLHttpRequest、WebSocket、EventSource、sendBeacon。
- location、history、open、alert、confirm、print。
- localStorage、sessionStorage、cookie、indexedDB、Cache API、service worker。
- eval、Function、字符串执行、动态 script/module。
- setTimeout、setInterval、requestAnimationFrame、queueMicrotask。
- Worker、SharedWorker、WebAssembly。
- Date、performance.now、Math.random、crypto random。
- clipboard、camera、microphone、geolocation、notification、USB、文件系统。
- console 和隐藏通信。
- 全局变量写入、输入对象写入和原型修改。

AST 分析必须追踪：

- 直接引用和别名。
- 解构。
- 计算属性。
- 可选链。
- bind/call/apply。
- 构造调用。
- 函数返回的可调用值。

无法证明目标属于允许白名单时失败关闭。纯计算可使用有限 Math、Number、String、Boolean、JSON 和确定性的数组/对象转换；具体方法集合与测试常量一起固定，不允许运行时扩展。

允许：

~~~javascript
const total = Number(input.price) * Number(input.quantity);
return {ok: true, value: {total}};
~~~

拒绝：

~~~javascript
const request = globalThis["fetch"];
request("/prices");
setTimeout(() => ports.emit("done", {}), 10);
~~~

## 9. 本地 JavaScript 模块闭包

### 9.1 支持范围

V1 支持无需安装依赖或执行来源构建器即可解析的本地 ES module 闭包。

允许：

- .js 和 .mjs。
- 静态相对 import。
- named import、default import。
- named export，以及有稳定声明名称的 default export；匿名 default function/class V1 拒绝，避免入口身份随格式变化。
- 在确认项目根内解析的 ./ 和 ../。

拒绝：

- bare specifier 和 node_modules。
- HTTP(S)、data、blob import。
- dynamic import。
- import map。
- side-effect-only import。
- JSON、CSS、WASM import。
- import assertion。
- CommonJS、TypeScript、JSX。
- export * 和所有 re-export。
- top-level await。
- 模块循环。
- 符号链接。
- 越出项目根或进入父项目已排除子项目的路径。
- Windows 大小写折叠后冲突的路径。
- 顶层调用、赋值、IIFE 或其他可执行副作用。

允许模块：

~~~javascript
import {multiply} from "./math.js";

export function compute(input) {
  return {ok: true, value: {total: multiply(input.price, input.quantity)}};
}
~~~

拒绝模块：

~~~javascript
import "analytics.js";
import helper from "some-package";
const config = await fetch("/config.json");
~~~

### 9.2 闭包算法

1. 从 activation.entry_module 和 activation.entrypoint 开始。
2. 使用 TypeScript AST 读取静态 import。
3. 将路径规范化为项目根内 POSIX 相对路径。
4. 模块来源只取 Python 已建立的 snapshot_before 内存表，并在 Node 内复核每项 SHA-256；不向分析器传 project_root，也不读取实时来源目录。
5. 拒绝快照外 import、符号链接、越界和大小写冲突；`.git`、`dist`、`build`、`node_modules`、虚拟环境等固定 ASCII 目录名按大小写无关方式比较，大小写变体不能重新进入快照或模块闭包。
6. 深度优先解析依赖，发现回边立即以 module_cycle 拒绝。
7. 最多 32 个模块，最大深度 8。
8. 每个模块都执行完整 JavaScript 安全策略。
9. presentation 必须导出同步 render。
10. interaction 必须导出同步 mount。
11. computation 必须导出同步 compute。
12. 闭包暴露多个 capability_kind 的角色入口时拒绝全部相关候选；纯 helper 共享不视为多角色。
13. 保存所有闭包模块；不依赖 tree shaking 来移除危险代码。入口函数内部无法证明属于角色的局部 function/arrow、普通局部绑定或表达式也必须拒绝，不能因为 esbuild 可能移除而放行。
14. 按逻辑路径排序后进入 canonical payload。

capsule_versions 保存：

~~~json
{
  "javascript_modules": [
    {
      "path": "compute.js",
      "source": "export function compute(input) { ... }\n"
    },
    {
      "path": "math.js",
      "source": "export function multiply(a, b) { return a * b; }\n"
    }
  ]
}
~~~

组合时使用仓库已安装的 esbuild：

- bundle: true
- platform: browser
- external: none
- sourcemap: false
- 禁止运行时依赖和远程加载

esbuild 输出必须再次经过统一 AST 安全分析和 node --check。来源模块与最终 app.js 的贡献关系写入产品 provenance。

## 10. Canonicalization V1

### 10.1 正式定义

每个版本保存：

~~~text
canonicalization_version = 1
canonical_hash = SHA-256(UTF-8(canonical JSON))
~~~

canonical payload：

~~~json
{
  "capability_kind": "computation",
  "activation": {},
  "input_contract": {"schema":"data_contract.v1","type":"object","properties":{},"required":[],"additional_properties":false},
  "output_contract": {"schema":"data_contract.v1","type":"object","properties":{},"required":[],"additional_properties":false},
  "error_contract": {"schema":"error_contract.v1","errors":{}},
  "runtime_allowlist": [],
  "dom_scope": {"selectors":[],"classes":[],"attributes":[],"events":[]},
  "usage_scope": {},
  "html": "",
  "css": "",
  "javascript_modules": [],
  "assets": []
}
~~~

参与 hash：

- capability_kind
- activation
- input_contract
- output_contract
- error_contract
- runtime_allowlist
- dom_scope
- usage_scope
- 清洗后的 HTML
- 清洗后的 CSS
- 全部模块逻辑路径和清洗后源码
- 资产逻辑路径、媒体类型和 SHA-256

不参与 hash：

- capability_key、role_key、variant_key
- capsule_id、version_id
- 来源项目、来源路径、读取时间
- 模型名称、digest、监督时间
- 验证时间
- 用户决定
- extraction_contract_version、redaction_rules_version 和其他门禁规则版本
- PRAGMA user_version
- warehouse revision

### 10.2 规范化规则

- 所有文本先按 UTF-8 严格解码，非法字节和 lone surrogate 拒绝。
- 只对清洗后的 HTML、CSS 和每个 JavaScript 模块源码执行 CRLF/CR 转 LF；契约 enum、错误码、品牌值和其他语义字符串保留原值，避免不同运行时值产生同一 hash。
- JavaScript 除换行外不删除或重写空白、注释、分号和字符串。
- HTML 和 CSS 使用固定清洗器输出，不做额外 minify。
- JSON key 按 Unicode code point 升序。
- JSON key、集合成员和逻辑路径中的 C0/DEL 控制字符拒绝；不同原始 key 不能经规范化静默覆盖。
- JSON 使用逗号和冒号紧凑分隔符，不输出 ASCII 转义。
- 布尔值固定为 true/false，null 固定为 null。
- 禁止 float、NaN、Infinity 和负零进入 canonical payload。
- 合同中的非整数十进制约束使用规范化十进制字符串，例如 precision_decimal: "0.01"。
- 可选字段缺失时显式 null。
- 缺失集合使用空数组或空对象。
- runtime_allowlist、selector、class、attribute、event 等集合去重后排序。
- javascript_modules 按逻辑路径排序。
- assets 按逻辑路径、媒体类型、SHA-256 排序。
- 逻辑路径使用正斜杠，不得为绝对路径，不得包含空段、. 或 ..。

生成 canonical JSON 时使用一个具体函数，不建立可插拔 canonicalizer。函数需要在 Python 3.11/3.14、Ubuntu、Windows 上用相同测试向量产生相同字节和 hash。

上述空 computation 对象是 canonicalization.v1 的跨环境固定向量。规范化后的 UTF-8 字节必须逐字节等于：

~~~text
{"activation":{},"assets":[],"capability_kind":"computation","css":"","dom_scope":{"attributes":[],"classes":[],"events":[],"selectors":[]},"error_contract":{"errors":{},"schema":"error_contract.v1"},"html":"","input_contract":{"additional_properties":false,"properties":{},"required":[],"schema":"data_contract.v1","type":"object"},"javascript_modules":[],"output_contract":{"additional_properties":false,"properties":{},"required":[],"schema":"data_contract.v1","type":"object"},"runtime_allowlist":[],"usage_scope":{}}
~~~

其 SHA-256 必须为 `b4b152b0eae2d1eddb7fbd3d237e8b1bf290b53c79d8fb441e48ae6cebaa1c32`。任何支持环境产生其他字节或 hash 都必须阻断阶段门，不能自动升级 canonicalization_version。

### 10.3 精确 hash 与语义身份

canonical_hash 表示正式载荷完全相同，不表示业务 key 相同。自动重复判断先以 hash 寻找现有版本，再继承其正式 key。若同一 hash 已经存在于多个正式身份，系统不得任意选择，候选进入 review_required，原因 duplicate_identity_conflict。

## 11. 重复、等价、变体和版本门禁

### 11.1 固定顺序

1. 建立扫描前一致性快照。
2. 按当前 extraction_contract_version 提取原子能力候选、依赖证据和初始 data_contract.v1。
3. 识别敏感数据并脱敏。
4. 检查 HTML、CSS、JavaScript 语法。
5. 执行固定安全策略。
6. 在图片子进程中清洗资产。
7. 形成完整原子契约。
8. 计算 canonical hash。
9. 合并同一任务中的精确重复。
10. 查询正式仓库精确重复。
11. 执行 Ollama 监督。
12. 执行计算或 QWeb 独立运行验证。
13. 产生语义相似和变体建议。
14. 必要时人工复核。
15. 发布事务开始前重新计算来源项目快照；只有 snapshot_after 等于 snapshot_before 才执行 SQLite 原子发布。

### 11.2 同任务精确重复

同一任务中相同 canonical hash 的候选只保留一个代表执行后续门禁，其他候选仅积累脱敏来源引用。代表失败时，同组全部保持失败或等待状态，但不影响其他 hash 组。

### 11.3 正式仓库精确重复短路

只有以下条件全部满足才能跳过模型和运行验证：

- canonical hash 相同。
- usage_scope 相同。
- 命中的 version_id 必须等于该 capsule 的 current_version_id。
- 现有版本的 extraction_contract_version 等于当前版本。
- 现有版本的 redaction_rules_version 等于当前版本。
- 现有版本的 canonicalization_version 等于当前版本。
- security_rules_version 等于当前版本。
- supervision_rules_version 等于当前版本。
- validation_contract_version 等于当前版本。
- 正式胶囊状态为 active。
- 不处于 pending_revalidation。

canonical hash 命中历史 version、非 current version 或 disabled/pending capsule 时，只把该版本作为人工对比证据，不追加 capsule_sources、不继承 key、不标记 duplicate。若同一 hash 同时命中一个合格 active current version 和历史版本，只使用前者执行短路并在详情中列出历史证据。

处理：

- 继承现有 capability/role/variant key。
- 不建立新版本。
- 在事务中只插入 capsule_sources。
- relationship 记录 exact。
- 增加 warehouse revision。
- intake candidate 记为 duplicate。

上述资格预查不能替代写入时校验。`BEGIN IMMEDIATE` 后必须重新读取命中 version，确认它仍是同一个 active current version、canonical hash 与全部完整证据仍合格；否则以目标已过期失败关闭，不追加来源。`merge_existing` 在同一个写事务内执行相同二次校验。

若 hash 和 usage_scope 命中 active current version，但 extraction/redaction/canonicalization/security/supervision/validation 任一版本门不满足：

- 不复用旧结论。
- 继续执行模型和独立验证。
- 通过后建立同内容新版本，以保存新规则证据。
- disabled 胶囊不会被重复候选自动重新启用。

### 11.4 代码不同

代码不同即 canonical hash 不同，绝不自动合并。即使输入、输出和固定样例相同，也必须：

1. 完成固定安全门。
2. 完成模型监督。
3. 完成独立运行验证。
4. 生成结构化等价比较。
5. 进入 review_required。

用户选择 merge_existing 时：

- 默认保留现有当前 version。
- 被保留版本还必须满足当前 extraction/redaction/canonicalization/security/supervision/validation 版本，保存的 validation status 必须 passed，且监督证据满足生成资格；过期、失败或只有未确认 review 结论的实现不能作为 retained version。
- 新来源以 relationship=human_equivalent 连接到被保留 version。
- review_items 保存来源项目、来源 hash、候选 canonical hash、比较结果、用户决定和 retained_version_id。

用户选择 replace_current 时：

- 候选作为同一角色和变体的新不可变 version。
- 当前指针在发布事务中切换。
- 旧版本保持历史可追溯。
- 普通 replace_current 仍要求 usage_scope 相同。品牌全贡献重审是唯一 scope-changing 例外：目标必须是该项目贡献的 exact current version、状态为 pending_revalidation、具有 `brand_profile_changed` 重审证据，且 activation、输入、输出、错误、运行白名单和 dom_scope 全部相同；发布事务内再次核对后才允许以同一 identity 创建新不可变版本。

无法充分证明时选择 create_variant。模型只能推荐，不能提交决定。

### 11.5 变体

以下任一差异形成不同 variant：

- activation 模式不同。
- 输入或输出含义不同。
- 错误码、精度、舍入或边界行为不同。
- 用户流程不同。
- 展示结果有实质差异。
- runtime allowlist 不同。
- dom_scope 可观察能力不同。
- usage_scope 不同；品牌全贡献重审按上一节的严格同身份例外处理。
- 无法充分证明等价。

## 12. HTML V1 安全子集

### 12.1 解析

使用 Python 标准库 html.parser 构建严格片段解析器和显式标签栈：

- 不依赖浏览器错误恢复宣布安全。
- 标签不平衡、错误嵌套、重复关键属性或无法理解的实体直接拒绝。
- 注释解析后删除，不进入正式载荷。
- DOCTYPE 和处理指令拒绝。

### 12.2 允许标签

- 布局：div、main、section、article、header、footer
- 文字：p、span、strong、em、small、h1 至 h6
- 表单：form、fieldset、legend、label、input、button、select、option、textarea
- 列表：ul、ol、li
- 表格：table、thead、tbody、tr、th、td
- 资源和模板：img、template

### 12.3 允许属性

通用：

- class
- role
- data-ref
- data-action
- data-state
- 声明过的 aria-*

标识：

- 来源 id 必须清洗为 __CAPSULE_ID__-logical-name 占位形式。
- label 的 for 使用同一占位形式。
- JavaScript 不通过 id 查询，只使用 data-ref/data-action。

表单：

- name、value、checked、selected、disabled、required、readonly
- placeholder、min、max、step、minlength、maxlength
- input type 仅 text、number、radio、checkbox
- button type 仅 button、submit、reset

图片：

- src，只能是已登记资产逻辑路径
- alt
- width、height
- loading，只能 lazy 或 eager

表格：

- colspan、rowspan，只允许 1 至 20 的整数

### 12.4 拒绝

- script、style、iframe、object、embed
- meta、base、link
- svg、math
- a 和 href
- 内联事件属性
- 内联 style
- form action、formaction、method、target、enctype
- srcset
- javascript/data/blob/http/https URL
- 未登记资产
- meta refresh
- 不符合 dom_scope 的 id、selector、data-ref 或 data-action

允许：

~~~html
<section class="quote">
  <label>
    Quantity
    <input data-ref="quantity" type="number" min="0">
  </label>
  <p data-ref="total"></p>
</section>
~~~

拒绝：

~~~html
<button onclick="fetch('/track')">Calculate</button>
<img src="https://example.com/logo.png">
<svg onload="alert(1)"></svg>
~~~

## 13. CSS V1 安全子集

### 13.1 解析器

实现一个具体的 tokenizer/parser，不使用正则匹配结果直接宣布安全。解析器：

- 只接受普通规则块。
- 验证括号、字符串和声明边界。
- 删除已正确闭合的注释。
- 拒绝 CSS escape，防止转义隐藏关键字。
- 拒绝所有无法解析或未列入 V1 的语法。

### 13.2 Selector 子集

每个 selector 必须以 __CAPSULE_ROOT__ 开头。允许：

- 后代和直接子代组合符。
- V1 HTML 标签。
- class。
- 已声明的 data-ref、data-action、data-state 和 aria-* attribute selector。
- :hover、:focus、:focus-visible、:disabled、:checked。
- :first-child、:last-child、:nth-child(正整数)。
- 逗号分组，但每个分支都必须独立以根占位符开头。

拒绝：

- html、body、:root。
- 通用选择器。
- ID selector。
- ::before、::after 和其他 pseudo-element。
- :has、:not 和未列出的 pseudo-class。
- 根外或缺少根占位符的 selector。
- CSS nesting。

### 13.3 Property 白名单

布局和盒模型：

- display、box-sizing
- width、min-width、max-width
- height、min-height、max-height
- margin 及四个方向
- padding 及四个方向
- gap、row-gap、column-gap
- overflow、overflow-x、overflow-y
- position，仅允许 static 或 relative

Flex：

- flex、flex-basis、flex-direction、flex-flow、flex-grow、flex-shrink、flex-wrap
- align-content、align-items、align-self
- justify-content、justify-items、justify-self
- order

Grid：

- grid-template-columns、grid-template-rows
- grid-auto-columns、grid-auto-rows、grid-auto-flow
- grid-column、grid-row

文字：

- color、font-family、font-size、font-style、font-weight、line-height
- letter-spacing、text-align、text-decoration、text-overflow、text-transform
- white-space、word-break、overflow-wrap

视觉：

- background-color
- border、border-width、border-style、border-color
- 四方向 border 属性
- border-radius、box-shadow
- opacity、visibility

列表、表格和图片：

- list-style、list-style-position、list-style-type
- border-collapse、border-spacing、caption-side、table-layout
- object-fit、aspect-ratio

交互：

- cursor、pointer-events、user-select

### 13.4 Value 规则

允许：

- 整数和有限小数。
- px、rem、em、%、fr。
- 十六进制颜色。
- rgb、rgba、hsl、hsla。
- 固定关键字和本地系统字体名。

拒绝：

- 所有 @ 规则。
- url、var、expression、attr、env。
- CSS 自定义变量。
- animation、transition。
- !important。
- position:absolute/fixed/sticky。
- top、right、bottom、left、inset、z-index。
- transform。
- viewport 单位。
- calc、min、max、clamp。
- 远程字体和图片。

允许：

~~~css
__CAPSULE_ROOT__ .quote {
  display: grid;
  gap: 0.75rem;
  background-color: #ffffff;
}
~~~

拒绝：

~~~css
@import url("https://example.com/theme.css");
body { position: fixed; inset: 0; }
__CAPSULE_ROOT__ .quote { background: url("/track.gif"); }
~~~

## 14. 资产 V1

V1 只接纳 PNG、JPEG、WebP。

固定限制：

- 单个来源资产最大 1 MiB。
- 单个原子胶囊清洗后资产总量最大 5 MiB。
- 单边最大 4096 像素。
- 总像素最大 16,777,216。

固定验证：

1. 父进程只读来源字节并复制到用户专用临时目录。
2. 不把来源项目路径传给图片 worker。
3. 先检查 magic bytes，不信任扩展名。
4. 子进程使用 QImageReader 实际解码。
5. 校验媒体类型、尺寸和像素量。
6. 重新编码成同一允许媒体类型，清除原始元数据。
7. 对清洗后字节计算 SHA-256。
8. 只有清洗后字节进入 capsule_assets。

拒绝：

- SVG 和字体。
- HTML/XML 伪装图片。
- 解码失败或 Qt 缺少对应插件。
- 符号链接。
- 项目根外路径。
- 目录穿越。
- 超时或 worker 崩溃。

JSON schema 和虚构 fixture 作为规范化契约/验证 JSON 保存，不作为任意 BLOB 资产。

允许示例：父进程读取一个 640×480、实际内容为 PNG、大小 80 KiB 的普通文件字节；image worker 成功解码并重新编码后，只把新字节、image/png、尺寸和新 SHA-256 返回父进程。

拒绝示例：扩展名为 .png 但 magic bytes 为 HTML、包含 SVG、尺寸为 5000×100 或经解码超过像素上限的输入，均在进入正式载荷前拒绝。

## 15. 敏感数据与品牌边界

### 15.1 模型前门

来源内容先经过固定规则分类：

- 明确是代码、结构或虚构 fixture：进入清洗。
- 能安全替换的敏感字面值：替换为类型占位符并记录 redaction code。
- 无法确认是否包含真实记录：候选进入 waiting_user。

waiting_user 原文不得进入 Ollama。这是产品安全决定，不因自动化效果降低而放宽。

waiting_user 的确认分成两个互不替代的决定：

- sensitivity_decision：confirm_fictional_fixture、confirm_safe_redaction、confirm_real_record_reject。
- brand_decision：remove_brand、retain_brand_limited。
- asset_decision：confirm_assets_contain_no_real_records；只表示用户确认候选登记图片像素不含真实业务记录，不替代 sensitivity 或 brand 决定。

决定闭环：

1. 每个决定绑定 project_id + source_relpath + source_hash + redaction_rules_version；brand_decision 还必须绑定候选提取时的有效 brand_profile_id + brand_profile_digest。
2. review_items 保存基础四元绑定、决定枚举和决定时间；安全 redaction summary 额外保存品牌 profile 的 ID/digest，不保存品牌原文或来源原文。
3. confirm_fictional_fixture 只确认数据性质，下一 run 仍执行固定脱敏并只生成合成 fixture。
4. confirm_safe_redaction 授权固定规则替换已展示的敏感类别，不授权保留原值。
5. confirm_real_record_reject 使匹配候选直接 rejected，不调用 Ollama、不运行候选代码、不入库。
6. retain_brand_limited 只允许已确认的品牌标识进入 brand_limited usage_scope，不允许真实业务记录；remove_brand 继续执行默认品牌清除。
7. 新 run 只有基础四元绑定完全相同才可复用 sensitivity/asset 决定；brand 决定还要求有效 profile ID 和 digest 同时相同。任一绑定变化，旧决定自动失效并重新 waiting_user。
8. 即使决定为 fictional、safe_redaction 或 retain_brand_limited，发送给 Ollama 的仍只是脱敏结构、契约和合成样例，绝不发送来源原文。
9. 同一绑定若出现多个 sensitivity 决定，confirm_real_record_reject 是不可逆的安全优先结论；后续安全放行决定拒绝。其余 sensitivity 冲突、brand 冲突或 asset 冲突全部失败关闭，不按 review 时间挑选一个结果。
10. 登记图片在进入 image worker、Ollama 或正式门禁前必须存在同一四元绑定的 asset_decision；图片字节变化会改变 source_hash 并使决定失效。用户未确认时保持 waiting_user，像素不会交给模型。

sensitivity_decision、brand_decision 和 asset_decision 在单个 review item 内各自只能从 null 写入一次；用户要更改决定时创建新 review item 和新 run，旧证据保持不变，但同一绑定的冲突仍按上一条处理。
retain_brand_limited 只能导向后续 publish_brand_limited；remove_brand 必须先证明品牌信号已清除才能 publish_general。发布服务若发现两个决定与最终 usage_scope 不一致，拒绝事务。
应用服务必须从当前 review 的脱敏证据重新计算 allowed_decisions，不能信任前端提交的按钮类型；intake 写事务内再次计算允许类别，并在写 brand_decision 前复核当前项目的有效 profile ID/digest。决定不属于当前证据或 profile 已变化时整笔事务失败。

### 15.2 不允许持久化的内容

review_items、日志、清洗报告、备份和模型记录均不得保存：

- 来源原文或原始代码片段。
- 客户、订单、人员、联系方式或交易记录。
- 模型完整提示。
- 模型原始响应。
- 异常堆栈。

review_items 只保存：

- 脱敏后的候选结构和语义摘要。
- 来源项目 ID、相对位置和来源 hash。
- canonical hash。
- redaction 类型和计数。
- redaction_rules_version，以及与来源 hash 绑定的 sensitivity/brand/asset 决定。
- 结构化监督结论及其输出 hash。
- 等价比较和用户决定。

waiting_user 和 rejected 候选是更窄的例外：sanitized_candidate_json 只保存固定 schema、extraction_contract_version、受控 capability_kind 和 requires_reextract=true，不保存输入、输出、错误契约、selector、模块路径或静态证据。决定保存后必须创建新 run，从来源快照重新提取。若敏感字面值成为属性名、required 引用、事件名、错误码、error.field、enum 或其他契约结构字符串，V1 不做局部 JSON 改名；无法证明源码和全部交叉引用一致替换时以 sensitive_contract_identifier_unsupported 拒绝，原值不得进入 SQLite 或 Ollama。

用户查看来源时按 project ID 和相对路径临时只读加载；页面关闭后不缓存。来源消失时显示 source_unavailable，不能从数据库恢复原文。

### 15.3 品牌

默认移除品牌名、公司名、客户名、产品专名、Logo、口号和客户专属视觉标识。只有用户明确保留时使用 brand_limited usage_scope。

品牌 profile 中每个用户已确认的非空字符串都是信号，不按字符数静默丢弃；HP、华为等短名称同样进入品牌门。短词误命中可以保守进入 waiting_user，但不得直接归为 general。颜色值和 HTTP(S) 地址不作为名称信号。

brand_profile_id 是应用使用标准 UUID 生成器产生并按规范小写字符串保存的 UUID，不由名称、路径或内容 hash 推导；前端提交的 ID 一律忽略：

- 根品牌首次创建时生成并保存在 source_roots.brand_profile_id。
- project 的 brand_mode=inherit 时使用根 profile 的 id/digest/version。
- brand_mode=replace 时生成并保存项目自己的 brand_profile_id；projects.brand_profile_json 保存完整有效配置。
- brand_mode=extend 在 SQLite V1 schema 中只保留为不可用的预留枚举；V1 前端、应用服务和 intake API 必须拒绝它。旧库若已存在 extend，intake 和正式发布失败关闭；用户改选 inherit/clear/replace 时允许恢复，并把既有 active 贡献转为 pending_revalidation。没有固定合并契约前不得把增量配置写入项目，也不得在运行时临时合并根配置。
- brand_mode=clear 时有效品牌 profile 为空；已有项目 profile 字段保留但不参与有效配置，避免复用旧身份时丢失审计信息。
- 同一 profile 内容编辑保留 brand_profile_id，brand_profile_version 加一，brand_profile_digest 重新计算。
- digest 是规范化品牌 JSON UTF-8 字节的 SHA-256；名称和更新时间不参与。
- 不同 profile 不得复用 id；合并或拆分品牌配置必须生成新 id。
- usage_scope.brand_profile_id 和 brand_profile_digest 必须来自入库时该项目的有效 profile 快照，二者不可由前端填写。

品牌配置变化时：

1. 找出该项目贡献过的所有 current version，包括 general 和 brand_limited。
2. 对每个对应 Formal capsule 记录 revalidation_required 事件并转为 pending_revalidation。
3. 对正式清洗内容执行新版品牌规则扫描；brand_limited 还必须核对有效 brand_profile_id 和 digest。
4. 来源可用时重新执行提取、脱敏、固定安全、监督和验证；快速扫描无命中也只能缩短内容清洗，不能跳过 profile 身份核对。
5. general 内容无品牌命中且其他规则仍有效时可恢复 active；有命中则发布清除品牌后的新版本或经用户确认发布 brand_limited 新版本。
6. brand_limited 只有内容和当前有效 profile id/digest 都匹配时才可发布新版本并恢复 active。
7. 无法修复或用户拒绝时 disabled；来源不可用时保持 pending_revalidation。

因此“品牌全贡献重审”覆盖该项目贡献过的全部当前 general 和 brand_limited 胶囊，不只扫描 general。

## 16. Ollama 监督契约

### 16.1 选择

- 查询 loopback Ollama 的 /api/tags。
- 不提供默认模型。
- 不自动下载模型。
- 不选择列表第一项。
- 应用级保存 capsule_supervision_model，不与文案生成模型共用配置。
- 保存 name、digest、selected_at。
- 同名模型 digest 改变后要求用户重新选择。

地址只允许 127.0.0.1、localhost、::1。远程地址拒绝。

允许示例：用户从 http://127.0.0.1:11434/api/tags 返回的模型列表中明确选择一个 name/digest，应用只发送已经通过固定脱敏门的结构化候选。

拒绝示例：https://ollama.example.com、局域网 IP、未确认是否含真实记录的原文，以及“未选择模型时自动使用第一项”，均不得发起监督请求。

### 16.2 结构化结论

~~~json
{
  "schema_version": "capsule_supervision.v1",
  "verdict": "approve",
  "capability_kind": "computation",
  "semantic_summary": "Calculate total price from unit price and quantity.",
  "keep_reason_codes": ["DECLARED_LOCAL_COMPUTATION"],
  "remove_reason_codes": [],
  "brand_signals": [],
  "sensitive_data_status": "clear",
  "hidden_dependency_codes": [],
  "duplicate_suggestions": [],
  "review_required": false
}
~~~

verdict 固定为 approve、review、reject。系统只保存通过 schema 校验的结构化对象和原始响应 SHA-256，不保存原始响应文本。

模型返回的 capability_kind、名称、分组和 duplicate_suggestions 都只是监督建议：它不能改变 extraction_contract.v2 已确定的代码闭包、DOM 根、依赖、data contract 或合成样例。建议与固定证据冲突时进入 review_required 或 rejected，绝不按模型输出重新切代码边界。

每次正式监督记录：

- 模型 name 和 digest。
- supervision_rules_version。
- supervised_at。
- 结构化结论。
- response_hash。

模型不可用、输出损坏或不明确时只影响当前候选，已有正式仓库继续可用。

## 17. 验证子进程

不建立通用插件框架，只定义两个 worker：

- Node 计算验证脚本。
- Python/PySide worker，固定 mode=image 或 mode=qweb。

### 17.1 纯计算子进程

~~~text
父进程完成清洗和 AST 门禁
→ esbuild 生成临时 bundle
→ Node 子进程加载固定 harness
→ vm context 调用 compute
→ stdout 返回一行结构化 JSON
~~~

要求：

- 桌面进程不执行候选计算代码。
- vm context 不暴露 process、require、fetch、Buffer、timer。
- cwd 是一次性临时目录。
- 环境变量使用最小白名单。
- fixture 深拷贝、深冻结。
- 每个 case 最长 2 秒。
- 整个候选最长 10 秒。
- Node 使用 64 MiB old-space 上限；每个序列化 case 最大 64 KiB。
- stdout 最大 1 MiB。
- stderr 非空、非 JSON 输出、超时、崩溃均失败。
- 父进程在 POSIX 上为 worker 建立独立 process group，超时后终止整个组，避免候选或 QWeb 后代残留；其他平台至少终止直接 worker，并由阶段 6 支持矩阵验证平台级后代清理。

Node vm 只是崩溃隔离和纵深防御，不是固定安全门的替代品。

验证用例至少包括：

- 正常输入。
- 边界输入。
- 无效输入。
- 重复相同输入。
- 输入对象是否变化。
- 全局状态是否变化。
- 输出 schema。
- 声明错误结果。

### 17.2 图片清洗子进程

~~~text
父进程复制单个图片字节
→ PySide worker mode=image
→ QImageReader 解码和限制检查
→ 重新编码
→ 返回清洗文件逻辑名、媒体类型、尺寸和 SHA-256
~~~

worker 不接收来源项目路径，不访问网络。超时、崩溃、非结构化输出或临时目录外写入均失败。

### 17.3 QWeb 子进程

~~~text
桌面任务线程负责扫描、模型和编排
→ 父进程生成清洗后的最小临时包
→ PySide worker mode=qweb
→ 子进程 Qt 主线程创建 QWebEngine
→ 返回结构化验证结果
~~~

临时包只包含：

- harness index.html。
- 清洗后的 styles.css。
- bundle 后 app.js。
- 登记图片。
- fixture 和声明契约。

QWebEngineProfile 使用 off-the-record 模式：

- MemoryHttpCache。
- NoPersistentCookies。
- LocalStorageEnabled=false。
- LocalContentCanAccessFileUrls=true，仅用于入口加载同一临时包中的登记文件；请求拦截器仍逐个拒绝未登记或越界 file URL。
- DnsPrefetchEnabled=false。
- LocalContentCanAccessRemoteUrls=false。

请求拦截器只允许清单中登记且解析后仍位于临时根内的 file URL。只允许启动所需的 about:blank；拒绝 data、blob、HTTP(S)、WebSocket、qrc、javascript 和其他 scheme。所有阻断请求只记录 scheme 和脱敏逻辑路径；临时根外的 file 请求固定记为 `<outside>`，不得返回外部 basename、查询或完整 URL。

阻断结果进入 stage3_failure.v1.details.blocked_requests；最多 100 条，每条只含受控 scheme 和最长 256 字符的脱敏逻辑路径，不保存查询参数、来源绝对路径、控制字符或控制台原文。证据结构异常时改以 qweb_blocked_request_evidence_invalid 失败关闭。

CSP：

~~~text
default-src 'none';
script-src 'self';
style-src 'self';
img-src 'self';
font-src 'none';
connect-src 'none';
object-src 'none';
frame-src 'none';
worker-src 'none';
base-uri 'none';
form-action 'none';
~~~

验证完成、超时或崩溃后都删除临时包和 profile。超时、子进程崩溃、控制台错误或任何未预期请求均不得正式入库。

QWeb 对 input_contract 产生的全部 normal 和 boundary fixture 逐一执行；每个 case 从相同的清洗后 root 状态开始。presentation 对每个 case 连续 render 两次并比较 DOM 属性/值/文字可观察状态。interaction 在每个 case 中 mount、触发全部声明事件、dispose 两次、验证 dispose 后不再响应；相邻 case 形成 `dispose → mount` 输入变化流程。invalid fixture 由应用边界按 data_contract 拒绝，不交给 render/mount，验证结果仍记录 invalid case 数量。

interaction 的 emit 必须先在原始值上递归验证有限 plain JSON：拒绝函数、undefined、DOM、NaN/Infinity、循环和非 plain object；单次值最大 64 KiB。只有验证通过后才能复制并交给父进程检查 event contract，禁止依靠 JSON.stringify 静默删除或替换非法成员。

### 17.4 验证标签

报告必须明确区分：

- static_analysis
- synthetic_declared_interaction
- real_qwebengine_render
- real_qwebengine_interaction

presentation 只有 real_qwebengine_render=passed、interaction 只有 real_qwebengine_interaction=passed 才能发布。PySide/QWeb 不可用时进入 waiting_validation，不能用 synthetic 结果替代。

## 18. SQLite 唯一正式仓库

### 18.1 路径和连接

数据库路径：

~~~python
state_dir() / "capsule_warehouse.sqlite3"
~~~

备份目录：

~~~python
state_dir() / "backups"
~~~

继续支持 REWEAVE_STATE_DIR。V1 使用：

- Python 标准库 sqlite3。
- SQLite 默认 journal mode。
- PRAGMA foreign_keys=ON。
- PRAGMA busy_timeout=5000。
- 一个应用级串行写入队列。
- 每个线程自己的连接。
- 短事务。
- 不使用 WAL、SHM 或 checkpoint。

POSIX 上状态目录和备份目录使用 0700，数据库和备份文件使用 0600。Windows 使用当前用户 APPDATA，并避免创建共享权限。

### 18.2 数据字典

| 表 | 权威内容 | 可变性 |
|---|---|---|
| warehouse_state | 正式仓库修订号、最近备份修订号 | 单行计数可变 |
| app_settings | 用途级本地设置 | 可变 |
| source_roots | 绑定根目录、根品牌信息 | 可变，不是正式胶囊 |
| projects | 稳定项目身份、入口和品牌覆盖 | 可变，不是正式胶囊 |
| intake_runs | 刷新、导入和重审任务 | 状态可变 |
| review_items | 脱敏候选和用户决定 | 状态/决定可变 |
| capability_groups | 完整能力 key 和展示名称 | 只允许改展示名称 |
| capsules | 原子身份、当前版本、状态 | 只允许改当前版本和状态 |
| capsule_versions | 不可变正式载荷和证据 | 只追加 |
| capsule_sources | 不可变来源关系 | 只追加 |
| capsule_assets | 不可变清洗资产 | 只追加 |
| capsule_status_events | 有限状态审计 | 只追加 |
| product_capsule_usage | 产品精确使用记录 | 只追加 |
| legacy_capsule_aliases | 旧 ID 到新版本的关系 | 只追加 |

结构版本只使用 PRAGMA user_version。warehouse_state 不是第二套结构版本。

### 18.3 DDL 草案

以下 DDL 是阶段 1 的权威起点。实施允许调整 SQL 排版，不允许改变字段语义、不可变边界或外键关系。

~~~sql
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA user_version = 1;

CREATE TABLE warehouse_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    warehouse_revision INTEGER NOT NULL DEFAULT 0 CHECK (warehouse_revision >= 0),
    last_backed_up_revision INTEGER NOT NULL DEFAULT 0
        CHECK (
            last_backed_up_revision >= 0
            AND last_backed_up_revision <= warehouse_revision
        )
);

INSERT INTO warehouse_state(singleton_id) VALUES (1);

CREATE TABLE app_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE source_roots (
    root_id TEXT PRIMARY KEY,
    root_kind TEXT NOT NULL CHECK (root_kind IN ('single_project', 'project_collection')),
    current_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('bound', 'source_missing')),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (brand_profile_version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    source_root_id TEXT NOT NULL REFERENCES source_roots(root_id),
    project_relpath TEXT NOT NULL,
    entry_relpath TEXT NOT NULL,
    display_name TEXT NOT NULL,
    project_state TEXT NOT NULL CHECK (
        project_state IN (
            'discovered_unconfirmed',
            'ready',
            'unsupported_v1',
            'source_missing'
        )
    ),
    discovery_signature TEXT NOT NULL,
    last_snapshot_hash TEXT,
    brand_mode TEXT NOT NULL DEFAULT 'inherit' CHECK (
        brand_mode IN ('inherit', 'extend', 'replace', 'clear')
    ),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (brand_profile_version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_root_id, project_relpath, entry_relpath),
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);

CREATE TABLE intake_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id),
    run_kind TEXT NOT NULL CHECK (
        run_kind IN (
            'refresh_project',
            'refresh_all_child',
            'legacy_import',
            'brand_revalidation'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'queued',
            'running',
            'no_change',
            'completed',
            'completed_with_pending',
            'failed',
            'cancelled',
            'interrupted'
        )
    ),
    snapshot_before TEXT,
    snapshot_after TEXT,
    extraction_contract_version TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    legacy_source_path_hash TEXT,
    legacy_source_file_hash TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE review_items (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    project_id TEXT REFERENCES projects(project_id),
    candidate_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL CHECK (
        candidate_status IN (
            'extracted',
            'waiting_user',
            'waiting_model',
            'waiting_validation',
            'review_required',
            'publishable',
            'published',
            'duplicate',
            'merged',
            'rejected'
        )
    ),
    source_relpath TEXT NOT NULL,
    source_location_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    candidate_canonical_hash TEXT,
    sanitized_candidate_json TEXT NOT NULL,
    redaction_summary_json TEXT NOT NULL,
    supervision_result_json TEXT,
    supervision_response_hash TEXT,
    equivalence_comparison_json TEXT,
    sensitivity_decision TEXT CHECK (
        sensitivity_decision IS NULL OR sensitivity_decision IN (
            'confirm_fictional_fixture',
            'confirm_safe_redaction',
            'confirm_real_record_reject'
        )
    ),
    sensitivity_decided_at TEXT,
    brand_decision TEXT CHECK (
        brand_decision IS NULL OR brand_decision IN (
            'remove_brand',
            'retain_brand_limited'
        )
    ),
    brand_decided_at TEXT,
    asset_decision TEXT CHECK (
        asset_decision IS NULL OR asset_decision = 'confirm_assets_contain_no_real_records'
    ),
    asset_decided_at TEXT,
    decision TEXT CHECK (
        decision IS NULL OR decision IN (
            'merge_existing',
            'replace_current',
            'create_variant',
            'semantic_split',
            'publish_general',
            'publish_brand_limited',
            'reject'
        )
    ),
    retained_version_id TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (sensitivity_decision IS NULL AND sensitivity_decided_at IS NULL)
        OR
        (sensitivity_decision IS NOT NULL AND sensitivity_decided_at IS NOT NULL AND project_id IS NOT NULL)
    ),
    CHECK (
        (brand_decision IS NULL AND brand_decided_at IS NULL)
        OR
        (brand_decision IS NOT NULL AND brand_decided_at IS NOT NULL AND project_id IS NOT NULL)
    ),
    CHECK (
        (asset_decision IS NULL AND asset_decided_at IS NULL)
        OR
        (asset_decision IS NOT NULL AND asset_decided_at IS NOT NULL AND project_id IS NOT NULL)
    )
);

CREATE TABLE capability_groups (
    capability_key TEXT PRIMARY KEY CHECK (
        length(capability_key) > 0
        AND capability_key NOT GLOB '*[^a-z0-9_]*'
        AND capability_key NOT GLOB '[0-9]*'
    ),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE capsules (
    capsule_id TEXT PRIMARY KEY,
    capability_key TEXT NOT NULL REFERENCES capability_groups(capability_key),
    role_key TEXT NOT NULL CHECK (
        length(role_key) > 0
        AND role_key NOT GLOB '*[^a-z0-9_]*'
        AND role_key NOT GLOB '[0-9]*'
    ),
    variant_key TEXT NOT NULL CHECK (
        length(variant_key) > 0
        AND variant_key NOT GLOB '*[^a-z0-9_]*'
        AND variant_key NOT GLOB '[0-9]*'
    ),
    capability_kind TEXT NOT NULL CHECK (
        capability_kind IN ('presentation', 'interaction', 'computation')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'pending_revalidation', 'disabled')
    ),
    current_version_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(capability_key, role_key, variant_key),
    FOREIGN KEY(current_version_id) REFERENCES capsule_versions(version_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE capsule_versions (
    version_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    extraction_contract_version TEXT NOT NULL,
    extraction_summary_json TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    canonical_hash TEXT NOT NULL,
    activation_json TEXT NOT NULL,
    input_contract_json TEXT NOT NULL,
    output_contract_json TEXT NOT NULL,
    error_contract_json TEXT NOT NULL,
    runtime_allowlist_json TEXT NOT NULL,
    dom_scope_json TEXT NOT NULL,
    usage_scope_json TEXT NOT NULL,
    html_text TEXT NOT NULL DEFAULT '',
    css_text TEXT NOT NULL DEFAULT '',
    javascript_modules_json TEXT NOT NULL DEFAULT '[]',
    cleaning_summary_json TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    supervision_model_name TEXT NOT NULL,
    supervision_model_digest TEXT NOT NULL,
    supervised_at TEXT NOT NULL,
    supervision_result_json TEXT NOT NULL,
    supervision_response_hash TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    validation_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(capsule_id, version_number)
);

CREATE TABLE capsule_sources (
    source_link_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    project_id TEXT REFERENCES projects(project_id),
    source_identity TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('project', 'legacy_json')),
    source_relpath TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    candidate_canonical_hash TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('exact', 'human_equivalent', 'published_implementation')
    ),
    read_at TEXT NOT NULL,
    CHECK (
        (
            source_kind = 'project'
            AND project_id IS NOT NULL
            AND source_identity = 'project:' || project_id
        )
        OR
        (
            source_kind = 'legacy_json'
            AND project_id IS NULL
            AND source_identity GLOB 'legacy:?*'
        )
    ),
    UNIQUE(version_id, source_identity, source_relpath, source_hash)
);

CREATE TABLE capsule_assets (
    asset_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    logical_path TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (
        media_type IN ('image/png', 'image/jpeg', 'image/webp')
    ),
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0 AND size_bytes <= 1048576),
    width INTEGER NOT NULL CHECK (width >= 1 AND width <= 4096),
    height INTEGER NOT NULL CHECK (height >= 1 AND height <= 4096),
    content BLOB NOT NULL,
    UNIQUE(version_id, logical_path)
);

CREATE TABLE capsule_status_events (
    event_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'enabled',
            'disabled',
            'revalidation_required',
            'current_version_changed',
            'usage_scope_changed'
        )
    ),
    from_status TEXT,
    to_status TEXT,
    version_id TEXT REFERENCES capsule_versions(version_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE product_capsule_usage (
    usage_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    capsule_id TEXT NOT NULL REFERENCES capsules(capsule_id),
    version_id TEXT NOT NULL REFERENCES capsule_versions(version_id),
    capability_key TEXT NOT NULL,
    role_key TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    usage_scope_json TEXT NOT NULL,
    contribution_role TEXT NOT NULL CHECK (
        contribution_role IN (
            'presentation',
            'interaction',
            'computation',
            'asset',
            'wiring'
        )
    ),
    generated_at TEXT NOT NULL,
    UNIQUE(product_id, version_id, contribution_role)
);

CREATE TABLE legacy_capsule_aliases (
    alias_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    legacy_file_hash TEXT NOT NULL,
    legacy_capsule_id TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN (
            'exact',
            'cleaned_successor',
            'merged',
            'variant',
            'rejected',
            'pending'
        )
    ),
    new_capsule_id TEXT REFERENCES capsules(capsule_id),
    new_version_id TEXT REFERENCES capsule_versions(version_id),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (new_capsule_id IS NULL AND new_version_id IS NULL)
        OR
        (new_capsule_id IS NOT NULL AND new_version_id IS NOT NULL)
    ),
    UNIQUE(import_run_id, legacy_capsule_id)
);

CREATE INDEX idx_projects_root ON projects(source_root_id);
CREATE INDEX idx_intake_runs_project ON intake_runs(project_id, created_at);
CREATE INDEX idx_review_items_status ON review_items(candidate_status, created_at);
CREATE INDEX idx_review_content_decision ON review_items(
    project_id,
    source_relpath,
    source_hash,
    redaction_rules_version
);
CREATE INDEX idx_capsules_group ON capsules(capability_key, role_key, variant_key);
CREATE INDEX idx_capsule_versions_hash ON capsule_versions(canonical_hash);
CREATE INDEX idx_capsule_versions_capsule ON capsule_versions(capsule_id, version_number);
CREATE INDEX idx_capsule_sources_project ON capsule_sources(project_id);
CREATE INDEX idx_usage_product ON product_capsule_usage(product_id);
~~~

review_items.retained_version_id 在所有正式表创建后通过迁移 DDL 加外键不是必要的；V1 由应用校验该可空引用，避免为了审核工作表制造循环建表依赖。正式发布表仍全部使用数据库外键。

capsule_sources.source_identity 是不含绝对路径的稳定来源命名空间：项目来源使用 project:<project_id> 且 project_id 必填；旧仓来源使用 legacy:<legacy_file_hash> 且 project_id 必须为空。source_identity 始终非空，确保 SQLite 的 NULL 唯一性语义不会生成重复来源关系。没有 project_id 的旧仓条目若存在敏感性或品牌歧义，V1 直接拒绝并要求用户先把原项目登记为只读来源，不建立无绑定的确认决定。

`capsule_sources.relationship` 为 `exact` 或 `published_implementation` 时，`candidate_canonical_hash` 必须等于目标 version 的 canonical hash；只有 `human_equivalent` 允许不同内容 hash。`legacy_capsule_aliases` 必须绑定同一 `legacy_import` run 的 `legacy_source_file_hash`：`exact/cleaned_successor/merged/variant` 必须同时指向匹配的 capsule/version，`rejected/pending` 必须没有正式目标。触发器和恢复审计同时执行这些约束。

### 18.4 不可变触发器

~~~sql
CREATE TRIGGER warehouse_state_update_guard
BEFORE UPDATE ON warehouse_state
WHEN NEW.singleton_id <> OLD.singleton_id
  OR NEW.warehouse_revision < OLD.warehouse_revision
  OR NEW.last_backed_up_revision < OLD.last_backed_up_revision
BEGIN
    SELECT RAISE(ABORT, 'warehouse_state_must_be_monotonic');
END;

CREATE TRIGGER warehouse_state_no_delete
BEFORE DELETE ON warehouse_state
BEGIN
    SELECT RAISE(ABORT, 'warehouse_state_delete_forbidden');
END;

CREATE TRIGGER review_items_source_binding_immutable
BEFORE UPDATE ON review_items
WHEN NEW.project_id IS NOT OLD.project_id
  OR NEW.source_relpath <> OLD.source_relpath
  OR NEW.source_hash <> OLD.source_hash
  OR NEW.redaction_rules_version <> OLD.redaction_rules_version
BEGIN
    SELECT RAISE(ABORT, 'review_source_binding_immutable');
END;

CREATE TRIGGER review_items_content_decision_once
BEFORE UPDATE ON review_items
WHEN (OLD.sensitivity_decision IS NOT NULL AND NEW.sensitivity_decision IS NOT OLD.sensitivity_decision)
  OR (OLD.sensitivity_decided_at IS NOT NULL AND NEW.sensitivity_decided_at IS NOT OLD.sensitivity_decided_at)
  OR (OLD.brand_decision IS NOT NULL AND NEW.brand_decision IS NOT OLD.brand_decision)
  OR (OLD.brand_decided_at IS NOT NULL AND NEW.brand_decided_at IS NOT OLD.brand_decided_at)
  OR (OLD.asset_decision IS NOT NULL AND NEW.asset_decision IS NOT OLD.asset_decision)
  OR (OLD.asset_decided_at IS NOT NULL AND NEW.asset_decided_at IS NOT OLD.asset_decided_at)
BEGIN
    SELECT RAISE(ABORT, 'review_content_decision_immutable');
END;

CREATE TRIGGER capability_groups_update_guard
BEFORE UPDATE ON capability_groups
WHEN NEW.capability_key <> OLD.capability_key
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'capability_group_only_display_name_mutable');
END;

CREATE TRIGGER capability_groups_no_delete
BEFORE DELETE ON capability_groups
BEGIN
    SELECT RAISE(ABORT, 'capability_group_delete_forbidden');
END;

CREATE TRIGGER capsules_identity_immutable
BEFORE UPDATE ON capsules
WHEN NEW.capsule_id <> OLD.capsule_id
  OR NEW.capability_key <> OLD.capability_key
  OR NEW.role_key <> OLD.role_key
  OR NEW.variant_key <> OLD.variant_key
  OR NEW.capability_kind <> OLD.capability_kind
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'capsule_identity_immutable');
END;

CREATE TRIGGER capsules_no_delete
BEFORE DELETE ON capsules
BEGIN
    SELECT RAISE(ABORT, 'capsule_delete_forbidden');
END;

CREATE TRIGGER capsules_insert_not_active
BEFORE INSERT ON capsules
WHEN NEW.status = 'active' OR NEW.current_version_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'new_capsule_requires_version_before_activation');
END;

CREATE TRIGGER capsules_active_requires_current_version
BEFORE UPDATE ON capsules
WHEN NEW.status = 'active' AND NEW.current_version_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'active_capsule_requires_current_version');
END;

CREATE TRIGGER capsules_current_version_belongs_to_capsule
BEFORE UPDATE OF current_version_id ON capsules
WHEN NEW.current_version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.current_version_id
       AND v.capsule_id = NEW.capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'current_version_capsule_mismatch');
END;

CREATE TRIGGER capsules_status_transition
BEFORE UPDATE OF status ON capsules
WHEN NEW.status <> OLD.status
 AND NOT (
     (OLD.status = 'active' AND NEW.status IN ('pending_revalidation', 'disabled'))
     OR
     (OLD.status = 'pending_revalidation' AND NEW.status IN ('active', 'disabled'))
     OR
     (OLD.status = 'disabled' AND NEW.status = 'active')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid_capsule_status_transition');
END;

CREATE TRIGGER capsule_versions_no_update
BEFORE UPDATE ON capsule_versions
BEGIN
    SELECT RAISE(ABORT, 'capsule_version_immutable');
END;

CREATE TRIGGER capsule_versions_no_delete
BEFORE DELETE ON capsule_versions
BEGIN
    SELECT RAISE(ABORT, 'capsule_version_delete_forbidden');
END;

CREATE TRIGGER capsule_sources_no_update
BEFORE UPDATE ON capsule_sources
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_immutable');
END;

CREATE TRIGGER capsule_sources_no_delete
BEFORE DELETE ON capsule_sources
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_delete_forbidden');
END;

CREATE TRIGGER capsule_sources_canonical_relationship
BEFORE INSERT ON capsule_sources
WHEN NEW.relationship IN ('exact', 'published_implementation')
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.version_id
       AND v.canonical_hash = NEW.candidate_canonical_hash
 )
BEGIN
    SELECT RAISE(ABORT, 'capsule_source_canonical_mismatch');
END;

CREATE TRIGGER capsule_assets_no_update
BEFORE UPDATE ON capsule_assets
BEGIN
    SELECT RAISE(ABORT, 'capsule_asset_immutable');
END;

CREATE TRIGGER capsule_assets_no_delete
BEFORE DELETE ON capsule_assets
BEGIN
    SELECT RAISE(ABORT, 'capsule_asset_delete_forbidden');
END;

CREATE TRIGGER capsule_status_events_no_update
BEFORE UPDATE ON capsule_status_events
BEGIN
    SELECT RAISE(ABORT, 'capsule_status_event_immutable');
END;

CREATE TRIGGER capsule_status_events_no_delete
BEFORE DELETE ON capsule_status_events
BEGIN
    SELECT RAISE(ABORT, 'capsule_status_event_delete_forbidden');
END;

CREATE TRIGGER capsule_status_events_version_belongs_to_capsule
BEFORE INSERT ON capsule_status_events
WHEN NEW.version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.version_id
       AND v.capsule_id = NEW.capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'status_event_version_capsule_mismatch');
END;

CREATE TRIGGER capsule_status_events_match_state
BEFORE INSERT ON capsule_status_events
WHEN NOT EXISTS (
    SELECT 1
    FROM capsules c
    WHERE c.capsule_id = NEW.capsule_id
      AND c.status = NEW.to_status
      AND (
          (NEW.event_type = 'enabled'
           AND NEW.from_status IN ('pending_revalidation', 'disabled')
           AND NEW.to_status = 'active')
          OR
          (NEW.event_type = 'disabled'
           AND NEW.from_status IN ('active', 'pending_revalidation')
           AND NEW.to_status = 'disabled')
          OR
          (NEW.event_type = 'revalidation_required'
           AND NEW.from_status = 'active'
           AND NEW.to_status = 'pending_revalidation')
          OR
          (NEW.event_type = 'current_version_changed'
           AND NEW.from_status IN ('active', 'pending_revalidation', 'disabled')
           AND NEW.to_status = 'active')
          OR
          (NEW.event_type = 'usage_scope_changed'
           AND NEW.from_status IN ('active', 'pending_revalidation')
           AND NEW.to_status = NEW.from_status
           AND NEW.to_status = c.status)
      )
      AND NEW.version_id = c.current_version_id
)
BEGIN
    SELECT RAISE(ABORT, 'status_event_state_mismatch');
END;

CREATE TRIGGER product_capsule_usage_matches_version
BEFORE INSERT ON product_capsule_usage
WHEN NOT EXISTS (
    SELECT 1
    FROM capsules c
    JOIN capsule_versions v ON v.capsule_id = c.capsule_id
    WHERE c.capsule_id = NEW.capsule_id
      AND v.version_id = NEW.version_id
      AND c.current_version_id = NEW.version_id
      AND c.status = 'active'
      AND c.capability_key = NEW.capability_key
      AND c.role_key = NEW.role_key
      AND c.variant_key = NEW.variant_key
      AND v.usage_scope_json = NEW.usage_scope_json
)
BEGIN
    SELECT RAISE(ABORT, 'product_usage_not_generation_eligible');
END;

CREATE TRIGGER product_capsule_usage_manifest_consistent
BEFORE INSERT ON product_capsule_usage
WHEN EXISTS (
    SELECT 1
    FROM product_capsule_usage u
    WHERE u.product_id = NEW.product_id
      AND u.manifest_digest <> NEW.manifest_digest
)
BEGIN
    SELECT RAISE(ABORT, 'product_manifest_digest_mismatch');
END;

CREATE TRIGGER product_capsule_usage_no_update
BEFORE UPDATE ON product_capsule_usage
BEGIN
    SELECT RAISE(ABORT, 'product_usage_immutable');
END;

CREATE TRIGGER product_capsule_usage_no_delete
BEFORE DELETE ON product_capsule_usage
BEGIN
    SELECT RAISE(ABORT, 'product_usage_delete_forbidden');
END;

CREATE TRIGGER legacy_capsule_aliases_no_update
BEFORE UPDATE ON legacy_capsule_aliases
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_immutable');
END;

CREATE TRIGGER legacy_capsule_aliases_no_delete
BEFORE DELETE ON legacy_capsule_aliases
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_delete_forbidden');
END;

CREATE TRIGGER legacy_capsule_aliases_target_matches
BEFORE INSERT ON legacy_capsule_aliases
WHEN NEW.new_version_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM capsule_versions v
     WHERE v.version_id = NEW.new_version_id
       AND v.capsule_id = NEW.new_capsule_id
 )
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_version_capsule_mismatch');
END;

CREATE TRIGGER legacy_capsule_aliases_contract
BEFORE INSERT ON legacy_capsule_aliases
WHEN NOT EXISTS (
    SELECT 1
    FROM intake_runs r
    WHERE r.run_id = NEW.import_run_id
      AND r.run_kind = 'legacy_import'
      AND r.legacy_source_file_hash = NEW.legacy_file_hash
)
 OR NOT (
    (
        NEW.relationship IN ('exact', 'cleaned_successor', 'merged', 'variant')
        AND NEW.new_capsule_id IS NOT NULL
        AND NEW.new_version_id IS NOT NULL
    )
    OR
    (
        NEW.relationship IN ('rejected', 'pending')
        AND NEW.new_capsule_id IS NULL
        AND NEW.new_version_id IS NULL
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'legacy_alias_contract_mismatch');
END;
~~~

重新启用 disabled 胶囊前，应用服务必须先证明当前版本仍满足全部当前门禁；数据库触发器只验证合法状态迁移，不替代安全资格判断。

### 18.5 原子发布

新版本发布使用 BEGIN IMMEDIATE：

1. 确认来源 snapshot_after 等于 snapshot_before。
2. 如有需要插入 capability_groups。
3. 如有需要插入 capsules，初始 status 为 pending_revalidation、current_version_id 为 null。
4. 插入 capsule_versions。
5. 插入 capsule_assets。
6. 插入 capsule_sources。
7. 更新 capsules.current_version_id 和 status。
8. 插入 current_version_changed 或 usage_scope_changed 事件。
9. warehouse_revision 加一。
10. COMMIT。

任何一步失败 ROLLBACK。生成资格查询只读取 capsules.current_version_id 指向的不可变版本，因此未提交数据不可见。

提取、脱敏、安全、监督、验证或品牌规则升级时，状态服务在一个短事务中把每个受影响 active capsule 改为 pending_revalidation，并插入 revalidation_required 事件；状态更新和事件任一失败则整体回滚。

数据库触发器要求状态事件的 to_status 等于 capsule 当前真实状态、事件类型只使用封闭的合法 from/to 组合，且 version_id 必须是该 capsule 的 current_version_id。事件仍是有限审计，不负责自动更新状态或发展成通用事件系统。

精确重复事务只插入 capsule_sources 并增加 revision。人工等价合并也只追加来源和审核决定；只有 replace_current 才创建新版本。

### 18.6 生成资格查询

应用服务只能返回：

- capsules.status=active。
- version_id 等于 current_version_id。
- 当前 extraction/redaction/canonicalization/security/supervision/validation 版本均满足。
- supervision verdict=approve；或 verdict=review 且不可变 extraction_summary_json.stage3_evidence.human_approval 保存了有效人工发布决定、review_id 和 decided_at。verdict=reject 永远不可发布。
- 独立验证 passed。
- usage_scope 与产品上下文匹配。

资格判断必须严格复核完整不可变证据，而不是只看 `status=passed` 或 `verdict=approve`：`extraction_summary_json.stage3_evidence` 的字段集合、清洗和安全结果、模型身份、监督完整 schema、监督响应 SHA-256，以及按 capability_kind 区分的真实验证 schema/scope 都必须与 `capsule_versions` 对应列一致。旧的最小 JSON、畸形 JSON 或 scope 不匹配版本一律视为过期，不能用于生成、精确重复或人工合并目标。

pending_revalidation、disabled、历史版本、候选和旧 JSON 条目不得返回。

人工发布不会改写模型原 verdict；human_approval 是独立证据。这样 review 候选经用户确认后可以进入生成资格，而没有人工证据的 review 版本不能被 exact duplicate 或 merge_existing 复用。

## 19. 备份和恢复

### 19.1 备份

触发：

- 数据库结构升级前。
- 一次产生正式变化的批量任务成功后。
- 应用正常退出且 warehouse_revision 已变化时。
- 用户点击立即备份。

要求：

- 使用 sqlite3.Connection.backup。
- 不直接复制打开中的数据库。
- 完成后对备份执行 PRAGMA integrity_check。
- 只有结果为 ok 才更新 last_backed_up_revision。
- 升级前备份失败时停止升级。
- 入库后备份失败不回滚正式事务，但显示警告。
- 退出备份失败在下次启动提示。
- 普通自动备份保留 7 个。
- 升级前备份保留 3 个。
- 手动备份不自动删除。
- 自动或升级保留名额只计算经完整 schema、integrity 和 foreign-key 验证通过的普通文件；目录、symlink、断链和损坏 SQLite 仍在备份列表中显示为 invalid，但不得挤占名额或触发有效备份删除。

备份界面明确说明备份包含本地项目路径、品牌配置、胶囊代码和资产、产品使用历史；不包含来源项目原文件或真实业务记录。

### 19.2 恢复预检

恢复是整个本地仓库回到备份时点，不是合并。

1. 停止接受入库、生成和导入任务。
2. 等待当前任务完成或取消。
3. 对选中备份执行完整 schema 指纹、integrity_check、foreign_key_check 和永久跨行不变量审计；未知对象、同名伪触发器、半个 capsule 身份、非法来源/状态/usage/legacy alias 均拒绝。
4. 读取 PRAGMA user_version。
5. 高于当前应用版本的备份拒绝。
6. 低于当前版本的备份只在存在已测试迁移路径时处理。
7. 旧备份复制到临时文件并在临时文件上迁移，原备份不修改；V1 还必须严格解析每个版本 JSON，按 canonicalization.v1 和资产 metadata 重建 canonical hash，并复核资产实际 BLOB 长度、SHA-256、单文件/总量/尺寸/像素上限。
8. 当前数据库可完整验证时，使用 backup API 创建并验证恢复前备份；当前文件存在但已损坏时，备份枚举和候选验证不得依赖当前库初始化，并先保存受限权限、带 SHA-256 的原始字节副本。该 raw 文件只用于失败回退，不冒充合法 SQLite 备份。
9. 当前数据库可验证时比较当前库和候选恢复库，显示将消失的 capsule、version 和 product usage 数量；当前库损坏时三项差异明确显示 unknown，不得按零处理。
10. 用户明确确认后关闭全部 SQLite 连接。

### 19.3 原子替换和失败回退

1. 收到携带用户确认 SHA-256 的恢复请求后，先把所选备份复制为受限权限的私有 `confirmed snapshot`，并立即核对其摘要；后续检查和迁移只消费该私有快照，不再读取或信任可能已经变化的原备份路径。同 schema 候选必须继续等于确认摘要；旧 schema 候选必须通过已测试迁移、逐表等价、exact schema 与永久不变量验证，随后才允许替换。
2. 设置当前用户文件权限。
3. fsync 临时文件和父目录。
4. os.replace 原子替换正式数据库。
5. 重新打开并执行 foreign_key_check 和 integrity_check。
6. 任一步失败时关闭连接；原库可验证时使用恢复前 SQLite 备份执行同样的原子替换，原库损坏时使用已校验 SHA-256 的 raw 副本原子恢复精确字节。
7. SQLite 回退后再次执行完整性检查；raw 回退只能验证精确字节摘要，因为其内容本来就是损坏库。

### 19.4 恢复后语义

- 来源项目和旧 capsules.json 不修改。
- 数据库中的来源登记、品牌配置和使用历史回到备份时点。
- 产品目录和 manifest 不删除。
- 备份后产生的产品可能引用恢复后不存在的 version。
- 打开此类产品时显示 historical_version_unavailable_after_restore 和恢复前备份路径。
- 初始状态只通过 `historicalProducts` 暴露 product_id、状态、manifest digest 和最近恢复前备份路径；这些产品不得进入 registered history、补登记队列或代码加载路径。前端使用原生只读 details 展示诊断。
- 不自动从产品文件反向导入缺失版本。
- 不合并恢复前和恢复后的数据库。
- 用户可以通过合法的恢复前 SQLite 备份回到恢复操作之前；损坏库的 raw 保护副本只用于本次失败回退，不作为可选恢复点。

## 20. 来源根、项目、入口与快照

### 20.1 绑定和发现

用户可以绑定：

- 一个单项目目录。
- 一个包含多个项目的总目录。

总目录递归寻找候选项目。第一次发现及以后新增的嵌套项目都必须确认。每个确认入口获得独立 project UUID。

项目 UUID 不由路径计算。路径只是当前位置。discovery_signature 只用于提示可能的移动或重复，不能自动重连。用户确认重连后保留原 project_id 并更新 current path。

来源绑定必须在打开或创建 SQLite 前完成路径门禁：`state_dir()`、实际注入的 `store.path` 及其备份目录均不得等于来源根或位于来源根内。两个已绑定来源根不得是同一路径，也不得互为祖先和后代；V1 不为重叠来源建立跨 root 身份关联。

一次发现先在内存中完成全部入口、大小写冲突和支持性检查，再以一个短事务写入全部结果并只增加一次仓库修订号；任一入口失败时本次发现零写入。已登记但本次未发现的项目转为 `source_missing`。同一位置重新出现时仍保持 `source_missing`，直到用户重新确认。项目移动后必须由用户显式选择新位置：应用服务保留旧 `project_id`；若新位置只有发现器刚创建且从未确认、无快照、无品牌配置、无 intake run 的临时记录，可以在同一重连事务中删除该临时记录，任何已有证据的目标记录都必须拒绝覆盖。

发现理由必须结构化，例如：

- static_index_entry
- local_module_entry
- nested_static_entry
- requires_build
- framework_source
- generated_output_only

### 20.2 Static Web V1

支持条件：

- 用户确认一个入口 HTML。
- 不需要 npm install。
- 不需要运行来源 build。
- 不需要解释框架 runtime。
- 所需 HTML、CSS、JavaScript 和图片能形成项目根内的自包含静态闭包。

unsupported_v1：

- React/Vue/Svelte 等组件源码。
- TypeScript/JSX。
- 依赖包安装或构建后才能运行。
- 需要框架 runtime。
- 无法形成静态闭包。
- 只存在未经单独批准的 dist/build 输出。

Vite 名称本身不决定支持性。一个含 vite 配置但入口能作为原生静态闭包运行的项目可以支持；必须构建的 Vite 项目不支持。

多页面项目每个 project 记录只绑定一个 entry_relpath。其他 HTML 入口分别确认并登记，V1 不跨页面推断完整应用。

### 20.3 父子项目

- 已独立登记的子项目根必须从父项目扫描中排除。
- 未确认子项目不得混入父项目正式候选；父项目任务显示 discovered_unconfirmed。
- 不跟随任何符号链接。
- 规范化真实路径后再次验证项目根边界。
- 检测符号链接循环和大小写路径冲突。
- 项目目录或已确认入口消失时，项目转为 `source_missing`；扫描器不得自动把它恢复为 `ready`。

### 20.4 一致性快照

快照包含所有进入支持闭包的文件：

- POSIX 相对路径。
- 文件类型。
- 字节大小。
- 修改时间，仅作诊断。
- SHA-256 内容摘要。

固定提取器只能消费 `snapshot_before` 中登记的 UTF-8 模块字节和对应 SHA-256，不得接收来源项目路径，也不得再次读取来源目录。HTML 引用、ES module import 或其他闭包边访问快照未登记文件时失败为 `static_closure_outside_snapshot`；被忽略的 `dist`、`build` 等目录不能因入口引用而绕过快照边界。

项目整体 hash 使用排序后的路径、大小和内容 SHA-256；mtime 不参与整体 hash。扫描上限固定为：800 个受支持文件、深度 8、单普通文件 1 MiB、受支持闭包总字节 64 MiB；送入 TypeScript 提取子进程的全部 `.js/.mjs` 快照总字节另限 16 MiB，Node 使用 256 MiB old-space 上限。达到任一上限时在构造 Node JSON 请求前失败关闭，不能以截断结果发布。

每个文件使用稳定只读句柄读取：Unix 在可用时启用 `O_NOFOLLOW`，所有平台都在读取前后比较路径 `lstat`、打开句柄 `fstat`、根目录与文件的设备号、inode、类型、大小和 mtime，并在前后逐级拒绝符号链接、确认解析路径仍位于项目根。检查后被替换为符号链接、其他文件或其他根目录时失败为 `static_closure_symlink_forbidden` 或 `source_changed_during_scan`，不得留下 review item 或成功快照。

刷新顺序：

1. 取得 snapshot_before。
2. 执行全部候选处理。
3. 发布前取得 snapshot_after。
4. 两者不同则 run 失败为 source_changed_during_scan。
5. 不发布任何候选，用户手动重试。

同一 project 同时只允许一个刷新任务。取消只设置取消标志；运行器在每个门之间检查并在发布事务前再次检查。取消不能留下半个正式版本。

只有内容、有效品牌 profile、extraction_contract_version、redaction_rules_version、canonicalization_version、安全规则、监督规则和验证契约均未变化时，run 才可为 no_change；此时模型调用和新版本数量都必须为零。extraction_contract_version 升级必须为曾贡献 current version 的项目创建刷新任务，并把相关 Formal capsule 标记 pending_revalidation。

## 21. 四套状态机

### 21.1 Project

| 当前 | 事件 | 下一状态 | 修改者 | 可重试 |
|---|---|---|---|---|
| discovered_unconfirmed | 用户确认且支持 | ready | 用户/应用服务 | 是 |
| discovered_unconfirmed | 判断超出 V1 | unsupported_v1 | 固定规则 | 重新确认入口 |
| ready | 路径消失 | source_missing | 扫描器 | 路径恢复后 |
| source_missing | 用户确认重连 | ready | 用户/应用服务 | 是 |
| unsupported_v1 | 用户选择新的支持入口 | ready | 用户/应用服务 | 是 |

no_change、running、failed 都不是项目状态。

### 21.2 Intake run

| 当前 | 事件 | 下一状态 | 重启处理 |
|---|---|---|---|
| queued | worker 开始 | running | 重启后 interrupted |
| running | snapshot 未变化且无工作 | no_change | 终态 |
| running | 全部完成 | completed | 终态 |
| running | 有等待候选 | completed_with_pending | 用户处理后新建重试 run |
| running | 项目级失败 | failed | 用户新建重试 run |
| queued/running | 用户取消 | cancelled | 终态 |
| queued/running | 应用异常退出 | interrupted | 不自动恢复 |
| interrupted | 用户重试 | 新 run=queued | 旧 run 保留 |

刷新全部是多个 refresh_all_child run，不引入跨项目大事务。一个项目失败不阻止其他项目。

### 21.3 Candidate

| 当前 | 事件 | 下一状态 |
|---|---|---|
| extracted | 敏感性无法确定 | waiting_user |
| extracted | 模型不可用 | waiting_model |
| extracted | 子进程不可用 | waiting_validation |
| extracted | 需要品牌/等价/变体决定 | review_required |
| extracted | 全部门禁完成 | publishable |
| publishable | 发布成功 | published |
| extracted | 精确重复短路 | duplicate |
| review_required | 用户合并现有实现 | merged |
| review_required | 用户发布或替换 | publishable |
| waiting_user | 用户确认真实记录 | rejected |
| 任意未正式状态 | 固定拒绝或用户拒绝 | rejected |
| waiting_user | 来源绑定完全匹配的虚构/脱敏/品牌/图片决定已保存 | 新 run 中重新 extracted |
| waiting_model/waiting_validation | 条件恢复 | 新 run 中重新 extracted |

等待状态恢复时从 extracted 重新执行全部后续门，不从内存中断点继续。单个候选失败不阻断同项目其他 hash 组。

### 21.4 Formal capsule

| 当前 | 事件 | 下一状态 | 新生成可用 |
|---|---|---|---|
| active | 规则或品牌需要重审 | pending_revalidation | 否 |
| active | 用户停用/安全失败 | disabled | 否 |
| pending_revalidation | 无法修复 | disabled | 否 |
| disabled | 当前版本重新证明合格并由用户启用 | active | 是 |

只有 active 且当前版本满足资格查询才可生成。停用不自动回退到旧版本。

状态事件的合法组合固定为：enabled 为 pending_revalidation/disabled→active；disabled 为 active/pending_revalidation→disabled；revalidation_required 为 active→pending_revalidation；current_version_changed 为 active/pending_revalidation/disabled→active；usage_scope_changed 只记录 active 或 pending_revalidation 的同状态新 current version。事件写入时 capsule 已处于 to_status，且 version_id 必须等于 current_version_id。

### 21.5 非法迁移、修改者和重试

每套状态机只允许上表列出的迁移；未列出的迁移一律拒绝，并返回 invalid_state_transition，不通过“先改字段再补证据”绕过门禁。

| 状态机 | 权威修改者 | 明确非法示例 | 合法重试语义 |
|---|---|---|---|
| Project | 发现器只能写 discovered/unsupported/source_missing；用户经应用服务确认 ready | ready→discovered_unconfirmed、source_missing→ready 自动发生 | 用户确认新入口或重连后按合法边迁移 |
| Intake run | 串行任务编排器；取消由用户请求、编排器落库 | completed/failed/cancelled/interrupted→running；修改任一终态结果 | 创建新的 queued run，旧 run 不改 |
| Candidate | 当前 run 的门禁编排器；decision 只能由用户经应用服务提交 | published/duplicate/merged/rejected→extracted；waiting 状态原地跳过前门进入 publishable | 条件恢复后在新 run 中重新 extracted 并重跑后续门 |
| Formal capsule | 发布服务和用户显式停用/启用操作 | disabled→pending_revalidation、pending_revalidation→当前旧版本直接 active 且无新证据、disabled 自动重启 | 完成当前规则下全部门禁；必要时发布新版本，再按合法边迁移 |

应用启动时把遗留 queued 和 running run 统一改为 interrupted；不恢复候选进程内状态。正式胶囊状态不因应用重启改变。

## 22. 旧 capsules.json 导入

旧仓始终只读，不是正式 repository。

启动时发现旧文件后显示：

- 可识别条目数。
- 重新清洗导入。
- 稍后。
- 查看旧路径。

导入规则：

1. 记录旧文件路径 hash、文件 SHA-256 和条目数。
2. 整体 JSON 无法解析时停止，不猜测修复。
3. 每个可识别条目作为不可信来源进入同一入库主线。
4. 不信任 active、ready、verified、passed 等旧状态。
5. 单条损坏只拒绝当前条目。
6. 已完成条目通过 legacy_capsule_aliases 跳过。
7. pending 条目在新的 import run 中重新处理，旧 pending 记录保留。
8. 新生成永远不读取旧 JSON。

relationship 固定为：

- exact
- cleaned_successor
- merged
- variant
- rejected
- pending

旧产品文件不改变。可以映射时显示新版本；不能映射时明确显示历史未迁移。

阶段 4 的具体导入语义已经封闭为：

- 导入器直接稳定读取 `state_dir()/capsule_warehouse/capsules.json`，不调用可能为损坏文件写副本的旧 warehouse loader；读取前后核对 inode、设备、大小和 mtime，文件保持只读。
- 旧 envelope 只有不可信 metadata，不具备 V1 HTML/CSS/JavaScript、data contract 或验证证据，因此绝不直接执行、复制为正式版本或伪造旧状态。整体 JSON 损坏时 import run=failed 且不写 alias；单条损坏使用 `item_<index>` 安全索引形成 rejected，其他条目继续。
- 只有旧生产器格式 `cap_[0-9a-f]{12}` 的 ID 可以保存为 legacy_capsule_id；电话号码、客户 ID 或任意旧字符串不会进入 SQLite。来源必须经旧 registry 的 source_id 映射到恰好一个已经在新 SQLite 登记为 ready 的项目，否则只形成 pending，且不会为该条调用模型、图片、Node 或 QWeb worker。项目匹配使用规范化后的 `source_root.current_path / project.project_relpath` 有效路径；不能只比较根路径。父项目和已单独登记的嵌套子项目同时 ready 时仍必须唯一命中实际项目路径。
- 有唯一项目绑定时，导入器只调用当前同一个 `_refresh_project → intake → Stage 3` 主线；同一项目在一次 import run 中只刷新一次。取消在每个条目、项目重清洗返回后和 alias 发布事务前检查；已经进入原子提交后不再伪装为取消。
- 同一旧文件 hash 的 non-pending alias 在后续 run 跳过；pending 必须在新 run 中重新处理，旧记录保持只追加。阶段 4 人工 link 只接受 cleaned_successor、merged、variant；DDL 中的 exact 仍是受约束关系值，但导入 UI 和 importer 不把人工决定标成 exact。
- 人工目标必须是 active current version，capsule/version 必须一致，而且该 version 必须具有同一个重新清洗项目的 project source；disabled、历史版本和无关项目目标失败关闭。成功时追加 alias，并以 source_kind=legacy_json、relationship=human_equivalent 追加不可变来源证据。
- 管理状态只显示每个 legacy ID 最新一条 alias 的受控 ID、固定关系、正式 capsule/version ID、reason code 和时间；pending alias 另带由服务端按同一重清洗项目计算的 eligible active-current 目标。它不显示旧条目、旧文件 hash、来源 hash 或原始内容。原前端允许用户查看旧仓路径和统计，并只从该 alias 的 eligible target 列表选择受控关系；前端不从全仓自行推断资格，后端仍重复执行同项目约束。

## 23. module_native 唯一组合器契约

### 23.1 内存输入

应用服务完成 SQLite 资格查询后，向 module_native 传递普通 Python 内存对象。它不是 repository 接口。

~~~json
{
  "capsule_id": "cap_...",
  "version_id": "ver_...",
  "capability_key": "quote_calculation",
  "role_key": "total_price",
  "variant_key": "precise",
  "capability_kind": "computation",
  "activation": {
    "mode": "declared_input_compute",
    "entry_module": "compute.js",
    "entrypoint": "compute"
  },
  "input_contract": {"schema":"data_contract.v1","type":"object","properties":{},"required":[],"additional_properties":false},
  "output_contract": {"schema":"data_contract.v1","type":"object","properties":{},"required":[],"additional_properties":false},
  "error_contract": {"schema":"error_contract.v1","errors":{}},
  "runtime_allowlist": ["local_computation"],
  "dom_scope": {
    "root_contract": "capsule_root",
    "selectors": [],
    "classes": [],
    "attributes": [],
    "events": []
  },
  "usage_scope": {"kind": "general"},
  "html": "",
  "css": "",
  "javascript_modules": [],
  "assets": [
    {
      "logical_path": "assets/example.webp",
      "media_type": "image/webp",
      "sha256": "...",
      "content": "<bytes in memory>"
    }
  ]
}
~~~

module_native 不得：

- 打开 SQLite。
- 接收 capsule_path。
- 扫描胶囊目录。
- 读取 stage4_behavior_modules。
- 读取旧 capsules.json。
- 发现或调用未传入的胶囊。

### 23.2 组合

组合计划显式记录连接：

~~~json
{
  "connections": [
    {
      "from_version_id": "interaction-version",
      "output": "calculate_requested",
      "to_version_id": "compute-version",
      "input": "$"
    },
    {
      "from_version_id": "compute-version",
      "output": "value",
      "to_version_id": "presentation-version",
      "input": "$"
    }
  ]
}
~~~

规则：

- interaction 只能 emit 声明输出。
- 生成的 wiring adapter 调用 computation。
- computation 结果由 wiring adapter 交给 presentation。
- interaction 不获得任意 invoke。
- 连接前必须验证端口和 schema 兼容。
- 一个完整能力的三个角色可以组合，也可以被别的 capability 复用。

module_native 返回：

- index.html 内容。
- styles.css 内容。
- app.js 内容。
- 本地资产文件映射。
- composition manifest。
- provenance。

安全写入由应用服务现有受限写入层执行。module_native 不直接访问来源项目。

### 23.3 产品使用记录

manifest 至少包含：

~~~json
{
  "product_id": "product_...",
  "generated_at": "...",
  "capsules": [
    {
      "capsule_id": "cap_...",
      "version_id": "ver_...",
      "capability_key": "quote_calculation",
      "role_key": "total_price",
      "variant_key": "precise",
      "usage_scope": {"kind": "general"},
      "contributions": ["computation", "wiring"]
    }
  ]
}
~~~

数据库 product_capsule_usage 和 manifest 必须在生成成功后保持一致。新产品只使用当时的 current version；旧产品始终保留原 version ID。

文件系统与 SQLite 不能共享一个原子事务，因此生成提交顺序固定为：

1. 在目标目录旁的受限临时目录完成组合、静态检查、运行检查和 manifest，计算 manifest_digest。
2. 再次确认所有引用仍是 active current version。
3. 由安全产品写入层把临时目录原子提升为带唯一 product_id 的最终目录。
4. 最终目录确认存在后，在一个 BEGIN IMMEDIATE 事务中一次性插入该 product_id 的全部 product_capsule_usage；任一行失败则整组回滚。
5. usage 提交成功后才向用户报告生成成功。

若第 4 步在当前进程内失败，安全写入层只删除本次唯一 product_id 的新目录，不触碰其他产品。若应用在第 3、4 步之间崩溃，启动时把“存在 manifest 但没有对应 usage 行”的目录标记为 usage_registration_incomplete，不列入成功历史、不参与生成输入，也不从产品文件反向导入胶囊。用户重试登记时必须重新校验 manifest_digest、所有 version 是否存在及其身份是否匹配；通过后只补写不可变 usage 行，失败则保留该目录供用户导出或删除。该恢复流程不新增产品仓库或第二状态机。

## 24. 应用服务与前端桥接

### 24.1 唯一服务边界

桌面和 CLI 都通过 ReweaveAppService。V1 不再让前端构造模型名称、胶囊 origin 或选择后端。

目标方法：

| 方法 | 作用 | 长任务 |
|---|---|---|
| get_initial_state | 来源、项目、模型、待确认和仓库摘要 | 否 |
| discover_source_root | 只读发现项目入口 | 是 |
| confirm_projects | 确认项目和品牌信息 | 否 |
| start_refresh_project | 创建单项目 intake run | 是 |
| start_refresh_all | 为每个 ready 项目创建独立 run | 是 |
| get_intake_run | 查询状态和脱敏统计 | 否 |
| cancel_intake_run | 请求取消 | 否 |
| list_supervision_models | 查询 loopback Ollama tags | 是 |
| select_supervision_model | 重新核对 loopback tag/digest 后保存选择 | 是 |
| list_review_items | 查询脱敏待确认项 | 否 |
| decide_review_item | 提交绑定来源 hash 的 sensitivity/brand 或等价/发布固定决定；process_candidate 创建新 run | 混合 |
| list_capability_groups | 按完整能力分组查询 | 否 |
| rename_capability_group | 只修改可编辑 display_name；key 和版本不变 | 否 |
| get_capsule_detail | 查询版本、来源、验证和产品使用 | 否 |
| set_capsule_status | 停用或重新启用合格当前版本 | 否 |
| create_backup | 立即备份 | 是 |
| list_backups | 列出完整性和类型 | 否 |
| inspect_backup | 只读验证备份并计算恢复影响 | 否 |
| restore_backup | 执行恢复闭环 | 是 |
| start_legacy_import | 创建旧仓导入 run，可带受控人工 alias links | 是 |
| generate_product（阶段 5） | 资格查询、组合、安全写入、usage 记录 | 是 |

桌面桥另提供 `choose_source_root`，只由原生 `QFileDialog` 取得用户选择目录并转交 `discover_source_root`；它不读取目录内容，也不把异常文本返回前端。所有阶段 4 slot 只接收或返回 JSON object，畸形 payload 和内部异常使用固定错误码。

桌面使用一个 `max_workers=1` 的受控管理线程处理扫描、模型和任务编排，并以一个 operation lock 串行化 SQLite 管理操作。任务状态固定为 queued/running/completed/failed/cancelled；服务端与当前页面都保留全部非终态任务，并只保留最近 100 条终态 UI 回执，不建立任务历史仓库。只允许取消显式 cooperative task，已经完成原子提交的动作不能被事后改标 cancelled。恢复不可取消；设置 restore_pending 后拒绝新管理操作，等待已经进入的短连接操作和排队任务结束，再在没有其他 SQLite 连接的边界执行 store 恢复。它不是后台 watcher。计算、图片和 QWeb 仍通过独立子进程。

decide_review_item 只接收 review_id 和固定决定值；project/path/hash/redaction version 及品牌 profile 绑定由应用服务从当前 review 脱敏证据读取，前端不能覆盖。服务端在分发前按当前证据重新计算 allowed_decisions，intake 对 sensitivity/brand/asset 决定在写事务内再次复核。

### 24.2 桥接通用结果

成功：

~~~json
{"ok": true, "data": {}}
~~~

长任务启动：

~~~json
{"ok": true, "run_id": "run_...", "status": "queued"}
~~~

失败：

~~~json
{
  "ok": false,
  "error": {
    "code": "source_changed_during_scan",
    "message_key": "sourceChangedDuringScan"
  }
}
~~~

错误不得包含堆栈、来源原文或真实记录。前端用 message_key 本地化。

### 24.3 原前端增量原则

保留：

- 原页面整体结构和视觉。
- Source Box 主流程。
- 胶囊浏览和任务输入体验。
- 桌面启动方式。

必须移除：

- qwen2.5-coder:1.5b 硬编码。
- stage4_module_native 数量分流。
- 旧 origin 决定生成策略。
- 模拟运行结果冒充真实 QWeb 的文案。

新增：

- 来源根和项目确认。
- 应用级监督模型选择。
- 风琴复核。
- 按 capability_key 分组的 Capsule Warehouse。
- 备份和恢复。

阶段 4 在原 `index.html`、`styles.css`、`app.js` 内增量加入一个 Capsule Warehouse popover，没有引入框架或第二个前端入口。六个原生 details 区域分别承载来源项目、监督模型、待复核项、能力分组、备份/恢复与旧仓、入库任务。来源确认支持项目级 inherit/clear/replace 品牌模式；replace 只接收用户输入的 JSON object，前端不生成 brand_profile_id/digest，extend 在 V1 失败关闭。品牌有效身份变化时，应用服务在同一个 SQLite 事务内把该项目贡献过的全部 active current 胶囊转为 pending_revalidation 并写 revalidation_required，然后才排队新的 refresh run；pending 或由 pending 停用的旧 current version 不能手工重新启用。

`capsuleIngestionV1` 是独立管理状态，不写入旧 `data.capsules`、`usedCapsuleIds` 或现有生成通知。前端已经删除硬编码模型、本地模型 toggle、stage4_module_native 数量分流和 origin/count 决定生成策略；为保持阶段 5 单次切换边界，后端旧生成读取、`module_native`、产品写入和 Lumo Lite 旧只读显示逻辑本阶段不改。前端审核 payload 使用决定类型白名单，不发送 source path、source hash 或 redaction 绑定字段。

## 25. 入库报告

每个 run 保存并显示脱敏统计：

- 读取项目数。
- no_change 项目数。
- 成功、失败、取消和 interrupted 项目数。
- 新胶囊、新版本、精确重复来源数。
- 人工等价合并数。
- 新变体数。
- waiting_user、waiting_model、waiting_validation 数。
- 品牌确认和归类确认数。
- 验证失败数。
- 清除品牌信号数。
- 拦截敏感数据数。
- 各 error code 数。

报告不保存原始内容，不用总分或“全部通过”隐藏失败。

## 26. 字段生产、消费和 Hash 矩阵

| 字段 | 生产者 | 消费者 | 参与 canonical hash |
|---|---|---|---|
| capability_key | 固定建议 + 发布/人工决定 | 仓库 UI、composer、manifest | 否 |
| role_key | 固定建议 + 发布/人工决定 | composer、manifest | 否 |
| variant_key | 变体判断/人工决定 | composer、manifest | 否 |
| capability_kind | 提取器 + 模型复核 | 验证器、composer | 是 |
| extraction_contract_version/summary | 固定提取器 | 重扫、重复门、审计 | 否 |
| redaction_rules_version | 固定脱敏器 | 决定绑定、重复门、资格查询 | 否 |
| activation | 提取器 | 模块解析、验证器、composer | 是 |
| input/output/error contract | 提取器 + 固定规则 | 验证器、wiring | 是 |
| runtime_allowlist | 固定策略 | AST、运行验证、composer | 是 |
| dom_scope | 提取器 + 固定策略 | AST、CSS、QWeb | 是 |
| usage_scope | 品牌规则/用户决定 | 资格查询、manifest | 是 |
| HTML/CSS | 清洗器 | QWeb、composer | 是 |
| javascript_modules | 模块闭包清洗器 | Node/QWeb、esbuild | 是 |
| asset logical path/media/SHA | 图片 worker | QWeb、composer | 是 |
| asset bytes | 图片 worker | QWeb、产品写入 | 通过 SHA 间接参与 |
| 来源项目/path/hash | 扫描器 | 追溯、临时查看 | 否 |
| 模型 name/digest/result | Ollama 监督 | 资格判断、详情 | 否 |
| 验证结果和时间 | 子进程编排器 | 资格判断、详情 | 否 |
| 用户决定 | 前端/应用服务 | 发布和审计 | 否 |
| 运行时 root token | composer | 最终产品 | 否 |

### 26.1 SQLite 字段所有权

下表列出 DDL 的每个字段；同一单元格中以逗号分隔的字段具有相同生产者、消费者和 hash 语义。“是”只表示该值进入 capsule version 的 canonical payload，不表示数据库行本身被再次 hash。

| 表 | 字段 | 生产者 | 读取者 | 参与 canonical hash |
|---|---|---|---|---|
| warehouse_state | singleton_id | DDL | 仓库 | 否 |
| warehouse_state | warehouse_revision, last_backed_up_revision | 发布/备份服务 | 备份、UI | 否 |
| app_settings | setting_key, value_json, updated_at | 应用设置服务 | 模型选择、UI | 否 |
| source_roots | root_id, root_kind, current_path, status | 来源绑定服务 | 发现器、UI | 否 |
| source_roots | brand_profile_id, brand_profile_json, brand_profile_digest, brand_profile_version | 用户/品牌服务 | 候选清洗、重审 | 否；派生出的 usage_scope 才参与 |
| source_roots | created_at, updated_at | 来源绑定服务 | UI、审计 | 否 |
| projects | project_id, source_root_id, project_relpath, entry_relpath | 项目确认服务 | 扫描器、UI | 否 |
| projects | display_name, project_state, discovery_signature, last_snapshot_hash | 发现器/扫描器 | 编排器、UI | 否 |
| projects | brand_mode, brand_profile_id, brand_profile_json, brand_profile_digest, brand_profile_version | 用户/品牌服务 | 候选清洗、重审 | 否；派生出的 usage_scope 才参与 |
| projects | created_at, updated_at | 项目服务 | UI、审计 | 否 |
| intake_runs | run_id, project_id, run_kind, status | 任务编排器 | 门禁、UI、恢复器 | 否 |
| intake_runs | snapshot_before, snapshot_after | 扫描器 | 发布前一致性门 | 否 |
| intake_runs | extraction_contract_version, redaction_rules_version, security_rules_version, supervision_rules_version, validation_contract_version, canonicalization_version | 应用当前规则集 | 重复门、报告 | 否 |
| intake_runs | counts_json, error_code | 任务编排器 | 报告、UI | 否 |
| intake_runs | legacy_source_path_hash, legacy_source_file_hash | 旧仓导入器 | 导入去重、审计 | 否 |
| intake_runs | started_at, completed_at, created_at | 任务编排器 | UI、审计 | 否 |
| review_items | review_id, run_id, project_id, candidate_id, candidate_status | 候选编排器 | 复核 UI、发布服务 | 否 |
| review_items | source_relpath, source_location_json, source_hash, redaction_rules_version | 只读扫描器/脱敏器 | 临时来源查看、决定绑定、追溯 | 否 |
| review_items | candidate_canonical_hash | canonicalizer | 重复门、复核 UI | 否；这是结果值 |
| review_items | sanitized_candidate_json, redaction_summary_json | 固定清洗器 | 模型门、复核 UI | 否；正式发布时由其中的正式字段重新形成 payload |
| review_items | supervision_result_json, supervision_response_hash | Ollama 监督器 | 复核、资格判断 | 否 |
| review_items | equivalence_comparison_json | 等价比较器 | 复核 UI | 否 |
| review_items | sensitivity_decision, sensitivity_decided_at, brand_decision, brand_decided_at, asset_decision, asset_decided_at | 用户经应用服务 | 新 run 敏感/品牌/图片像素门、审计 | 否 |
| review_items | decision, retained_version_id, decided_at | 用户经应用服务 | 发布服务、审计 | 否 |
| review_items | created_at, updated_at | 候选编排器 | UI、审计 | 否 |
| capability_groups | capability_key | 发布服务 | 仓库 UI、composer | 否 |
| capability_groups | display_name | 用户/发布服务 | 仓库 UI | 否 |
| capability_groups | created_at, updated_at | 发布/名称编辑服务 | UI、审计 | 否 |
| capsules | capsule_id | 发布服务 | 仓库、composer、manifest | 否 |
| capsules | capability_key, role_key, variant_key | 发布/人工决定 | 仓库、composer、manifest | 否 |
| capsules | capability_kind | 提取器、发布服务 | 验证器、composer | 是 |
| capsules | status, current_version_id | 发布/状态服务 | 资格查询、仓库 UI | 否 |
| capsules | created_at | 发布服务 | 审计 | 否 |
| capsule_versions | version_id, capsule_id, version_number | 发布服务 | 资格查询、manifest、历史 | 否 |
| capsule_versions | extraction_contract_version, extraction_summary_json, redaction_rules_version | 固定提取/脱敏器 | 重扫、重复门、资格查询、审计 | 否 |
| capsule_versions | canonicalization_version, canonical_hash | canonicalizer | 重复门、审计 | 否；二者描述 hash 而非进入自身 |
| capsule_versions | activation_json, input_contract_json, output_contract_json, error_contract_json, runtime_allowlist_json, dom_scope_json, usage_scope_json | 契约形成门 | AST、验证器、composer、资格查询 | 是 |
| capsule_versions | html_text, css_text, javascript_modules_json | 固定清洗器/模块闭包器 | QWeb、composer | 是 |
| capsule_versions | cleaning_summary_json | 固定清洗器 | 详情、审计 | 否 |
| capsule_versions | security_rules_version | 安全门 | 重复门、资格查询 | 否 |
| capsule_versions | supervision_rules_version, supervision_model_name, supervision_model_digest, supervised_at, supervision_result_json, supervision_response_hash | Ollama 监督器 | 重复门、资格查询、详情 | 否 |
| capsule_versions | validation_contract_version, validation_result_json | 子进程编排器 | 重复门、资格查询、详情 | 否 |
| capsule_versions | created_at | 发布服务 | 历史、审计 | 否 |
| capsule_sources | source_link_id, version_id | 发布/重复服务 | 追溯、仓库 UI | 否 |
| capsule_sources | project_id, source_identity, source_kind, source_relpath, source_hash, candidate_canonical_hash, relationship, read_at | 扫描/导入/人工合并服务 | 追溯、等价证据 | 否 |
| capsule_assets | asset_id, version_id | 发布服务 | 仓库、composer | 否 |
| capsule_assets | logical_path, media_type, sha256 | image worker/发布服务 | canonicalizer、QWeb、composer | 是 |
| capsule_assets | size_bytes, width, height | image worker | 限额、详情 | 否 |
| capsule_assets | content | image worker | QWeb、产品写入 | 通过 sha256 间接参与 |
| capsule_status_events | event_id, capsule_id, event_type, from_status, to_status, version_id, reason_code, created_at | 状态/发布服务 | 有限审计、UI | 否 |
| product_capsule_usage | usage_id, product_id, manifest_digest, capsule_id, version_id, capability_key, role_key, variant_key, usage_scope_json, contribution_role, generated_at | 生成提交服务 | 产品历史、恢复诊断 | 否 |
| legacy_capsule_aliases | alias_id, import_run_id, legacy_file_hash, legacy_capsule_id, relationship, new_capsule_id, new_version_id, reason_code, created_at | 旧仓导入器 | 导入跳过、历史 UI | 否 |

## 27. 门禁 I/O、失败和重试

| 门 | 输入 | 成功输出 | 失败状态 | 重试 |
|---|---|---|---|---|
| 项目发现 | root path | 未确认项目列表 | project unsupported/source_missing | 用户重选 |
| 快照 | ready project | snapshot hash | run failed | 新 run |
| 原子提取 | 项目静态图 | 闭合候选、data contract、合成样例 | waiting_user/review_required/rejected | 用户确认事实或来源修复后新 run |
| 敏感数据门 | 来源候选 | 脱敏候选 | waiting_user/rejected | 用户确认后新 run |
| HTML/CSS/JS 固定门 | 脱敏候选 | 安全载荷 | rejected | 来源修复后新 run |
| 图片清洗 | 临时图片字节 | 干净图片 | waiting_validation/rejected | 环境恢复或来源修复 |
| 精确重复 | canonical payload | 现有 version 或继续 | review_required 冲突 | 用户决定 |
| Ollama | 脱敏结构 | 结构化监督 | waiting_model/review_required/rejected | 选模后新 run |
| 计算/QWeb | 正式候选 + fixture | 结构化验证 | waiting_validation/rejected | 环境恢复或来源修复 |
| 等价判断 | 全部验证证据 | 新/合并/变体建议 | review_required | 用户决定 |
| 发布 | publishable candidate | 正式 version/source/assets | run failed，事务回滚 | 新 run |
| 生成 | active current versions | 产品 + usage | 生成失败，无 usage | 用户重试 |

除发布和精确重复来源追加外，前置门不得写正式胶囊表。

## 28. 契约闭合场景

下表中的“正式写入”只指胶囊正式表；intake_runs 和脱敏 review_items 可以按状态更新。

| 场景 | 状态机与状态 | 模型 | 子进程 | 正式写入与版本 | 生成资格 | 用户可见与重启 |
|---|---|---|---|---|---|---|
| 1. 单 presentation 从来源到产品 | Candidate: extracted→publishable→published；Formal capsule: active | 必须 | QWeb | 新 group/capsule/version/source，必要时 assets；current 激活 | 是 | 显示通过证据；重启后读取正式版本 |
| 2. 报价能力三个角色 | 三个 Candidate 各自完成；三个 Formal capsule 各自 active | 每个新角色必须 | interaction/presentation 用 QWeb，computation 用 Node | 每个原子角色独立原子发布，共享 capability_key | 全部 active 后可按连接组合；已通过的独立角色可单独复用 | 仓库按一个完整能力分组显示三个角色 |
| 3. 同批次精确重复 | Candidate: 同 hash 只留一个代表，其余随组 | 代表一次 | 代表一次 | 一份 version，多条 capsule_sources | 是 | 报告 duplicate 来源数；重启无重复工作 |
| 4. 仓库精确重复且规则仍当前 | Candidate: duplicate；命中 version 是 active Formal capsule 的 current_version_id | 否 | 否 | 只追加 capsule_sources，不建版本；历史 hash 命中只显示证据 | 保持原 active | UI 显示新增来源和历史命中证据 |
| 5. 精确重复但规则升级 | extraction/redaction/canonicalization/security/supervision/validation 任一升级；Candidate 重跑，Formal capsule pending_revalidation→active | 必须重跑 | 必须重跑 | 同内容新 version，保存新证据并切 current | 新版本 active 后是 | 旧版本留在历史 |
| 6. 不同代码、样例相同 | Candidate: review_required→merged 或 publishable | 必须 | 必须 | 决定前不写；merge 时只追加 human_equivalent 来源；replace 时新版本 | 决定完成后 | 重启保持 review_required，不自动合并 |
| 7. 展示有实质差异 | Candidate: review_required→publishable→published；新 Formal capsule active | 必须 | QWeb | 新 variant/capsule/version | 新变体 active 后可选 | UI 对比变体，不覆盖现有 |
| 8. 品牌配置变化 | 该项目贡献的 general 和 brand_limited Formal capsule 全部 active→pending_revalidation；重审 Candidate 从 extracted 开始 | 必须 | 按 kind 重跑 | 每个 current contribution 核对 profile id/digest；可修复则新版本，不可修复 disabled，无来源 pending | 重审完成前否 | 显示每个贡献的原因；重启保持正式状态 |
| 9. 扫描中来源变化 | Intake run: running→failed，error=source_changed_during_scan | 可能已调用但结论不发布 | 可能已运行但结论不发布 | 无 | 否 | 用户看到来源变化并手动重试 |
| 10. compute 超时 | Candidate: extracted→rejected，validation_timeout | 已完成 | Node 超时被终止 | 无 | 否 | 显示验证失败；来源修复后新 run |
| 11. 图片 worker 崩溃 | Candidate: 环境不可用为 waiting_validation；同输入可复现崩溃为 rejected | 未进入或已完成固定门 | image worker | 无 | 否 | 环境恢复或来源修复后新 run |
| 12. QWeb 越界请求 | Candidate: extracted→rejected，undeclared_request | 已完成 | QWeb 记录阻断请求 | 无 | 否 | 显示脱敏 scheme/path，不保存 URL 参数 |
| 13. 发布事务中应用退出 | Intake run: running→interrupted；Candidate 不发布 | 已完成但不代表发布 | 已完成 | SQLite 自动回滚，无半版本 | 否 | 用户手动新建 run |
| 14. 旧结构备份恢复 | 不属于四套状态机；这是停止任务后的独占恢复操作 | 否 | 否 | 临时副本迁移并原子替换整个 DB | 恢复后重新查询 | 显示差异和恢复前备份 |
| 15. 恢复后产品缺失版本 | 不属于四套状态机；这是不可变产品 manifest 的查看错误 | 否 | 否 | 不自动回填 | 该历史引用不可解析 | historical_version_unavailable_after_restore |
| 16. 模块 import 越界 | Candidate: extracted→rejected，module_path_outside_project | 否 | 否 | 无 | 否 | 显示逻辑路径和 error code |

## 29. 测试矩阵

### 29.1 支持环境

本地实测门：

- Python 3.14.5
- Node 22.22.3
- PySide6 6.11.1

CI 支持门：

- Python 3.11
- Node 24
- Ubuntu
- Windows

托管实测：GitHub Actions run `29438141570` 在 Ubuntu 与 Windows 上均通过 Python 3.11、Node 24、`npm ci`、全量 pytest、公开 CLI `--help` 和前端 `node --check`。CI 不安装 PySide6；PySide 真实窗口验收仍是 macOS 本地发布门，不能声称托管 CI 已覆盖桌面交互或视觉检查。Windows 桌面壳保持 experimental。

### 29.2 SQLite

- DDL 可在空数据库执行。
- PRAGMA user_version 正确。
- foreign_key_check 和 integrity_check。
- key、version、source、asset、event、usage、legacy alias 的 UPDATE/DELETE 被触发器拒绝。
- current version 指向其他 capsule 被拒绝。
- product usage 使用非当前、disabled 或不匹配 version 被拒绝。
- 同一 product_id 的不同 manifest_digest 被拒绝。
- source_kind=project 且 project_id 为空、或 legacy_json 带 project_id 均被拒绝。
- review item 的来源/hash/redaction 绑定不可修改，敏感和品牌决定写入后不可覆盖。
- revalidation_required 是合法且不可变的状态事件。
- 新版本发布任一步失败整体回滚。
- 精确重复只增加来源。
- 默认 journal mode 下短事务和 busy_timeout 行为。
- POSIX 权限。

### 29.3 Canonicalization

- CRLF/CR/LF 得到相同换行规范。
- JSON key 顺序和集合输入顺序不影响结果。
- JavaScript 空白或注释变化产生不同 hash。
- capability/role/variant key 变化不改变 hash。
- dom_scope 或 usage_scope 变化改变 hash。
- 模块路径或资产 SHA 变化改变 hash。
- NaN、Infinity、float、绝对路径和 .. 拒绝。
- Python 3.11/3.14、Ubuntu/Windows 使用固定向量产生相同字节和 hash。

### 29.4 提取和数据契约

- HTML 根、事件 handler、纯函数三类种子产生预期原子角色。
- 显式 `data-capsule-root`、唯一 `main` 和唯一 `form` 正例在阶段 2/3 选择同一子树；多个显式根、歧义根和嵌套显式根失败关闭，且 UI 根无效不会阻断独立 computation。
- 静态调用和数据流依赖被纳入；跨根、动态 selector、未知回调和隐式全局拒绝。
- 无法证明边界时不会扩大为整个页面或项目。
- extraction_contract_version 升级触发贡献项目重扫并阻止旧结论精确短路。
- input/output/error wrapper 和所有 data_contract.v1 节点使用固定正反例。
- decimal 规范值、范围、enum、object required、array 长度和嵌套上限。
- $ref、递归、正则、组合器、null、float 和 additional properties 拒绝。
- 输出到输入的范围/enum/required/scale 包含关系；无法证明兼容时拒绝 wiring。
- 合成 fixture 不包含来源原始样例。

### 29.5 安全策略

JavaScript 对直接、别名、解构、计算属性、可选链、bind/call/apply 和构造器绕过逐项测试。

Event 对象只允许直接 preventDefault()；target、currentTarget、view、解构、保存和传递逐项拒绝。

HTML 覆盖：

- 内联事件。
- script/iframe/object/embed/meta refresh。
- 外部 form。
- URL scheme。
- 可执行 SVG。
- 未声明 selector 和错误嵌套。

CSS 覆盖：

- @import、url、转义关键字。
- html/body/:root。
- 根外 selector。
- fixed/absolute 覆盖。
- 远程字体和图片。
- 变量、动画、nested CSS 和不支持语法。

资产覆盖：

- magic bytes 与扩展名不一致。
- HTML 伪装 PNG。
- SVG 和字体。
- 符号链接、越界和大小写冲突。
- 超限尺寸、像素和字节数。
- 元数据清除后的 SHA。

任何解析失败都必须失败关闭。

### 29.6 运行契约

presentation：

- 正常、空和错误输入。
- 特殊字符以文本显示。
- 重复 render 不累计。
- 不绑定事件。
- 根外哨兵不变。

interaction：

- mount、声明事件和输出。
- 非法输出名和 schema。
- ports.input 不可修改。
- dispose 幂等。
- dispose 后无监听和 emit。
- 输入变化执行 dispose → mount。

computation：

- 正常、边界、无效和异常数值。
- 重复输入确定性。
- 输入不变。
- 无全局状态。
- ComputeResult schema。
- 业务校验与执行失败区分。

### 29.7 来源和故障隔离

- 单项目和总目录。
- 嵌套项目首次确认。
- 父项目排除已登记子项目。
- 项目移动人工重连。
- 同项目并发刷新拒绝。
- 无变化时模型和新版本为零。
- 扫描中变化不发布。
- 取消不留半成品。
- 一个项目/候选失败不影响其他项。
- 刷新前后来源摘要一致，source_project_write=false。

### 29.8 模型、旧仓和生成

- 首次无选择模型。
- /api/tags 为空。
- 模型缺失和同标签 digest 改变。
- 非 loopback URL 拒绝。
- 无法脱敏时 Ollama 未被调用。
- sensitivity/asset 决定只在 project/path/hash/redaction version 全匹配时复用；brand 决定还要求有效 profile ID/digest 一致。来源或品牌身份变化后重新 waiting_user；真实记录拒绝优先，其他同绑定冲突失败关闭。
- 用户确认后 Ollama 仍只收到脱敏结构和合成样例。
- 结构化输出损坏。
- 旧 JSON 整体损坏、单条损坏、恢复导入和 alias。
- 旧 ID 字段像电话号码或客户号时不持久化原值；无唯一项目绑定时不调用模型或 worker。
- pending alias 的前端目标完全来自服务端 same-project eligible_targets；全仓无关 active/current 不显示，历史、disabled 和无关项目在后端再次拒绝。
- 旧 JSON 与 stage4_behavior_modules 不进入新生成。
- 只选择 active current version。
- 品牌范围过滤。
- 品牌 id/digest 生命周期，以及 general/brand_limited 全贡献重审。
- 历史 canonical hash 命中不追加来源，只有 active current version 可自动 duplicate。
- manifest 和 product_capsule_usage 一致。
- 历史产品不随 current version 漂移。

### 29.9 前端和桌面

- 原前端关键 DOM、文字和主要操作。
- 不再硬编码模型。
- 不再按 stage4_module_native 分流。
- 来源确认、风琴复核、仓库分组、备份恢复。
- 品牌 JSON 非对象或无法解析时前端失败关闭；有效 profile 变化原子写 pending_revalidation/event，并验证 pending→disabled→active 不能绕过重审。
- 管理任务在 cooperative cancel 点停止；原子提交已经完成后不能被事后标成 cancelled；恢复等待同步操作且本身不可取消。
- `capsuleIngestionV1` 操作前后旧生成胶囊、已选 ID 和 notify_generate 调用保持不变。
- 真实 QWeb 完成 presentation/interaction。
- 模拟检查明确标为 synthetic_declared_interaction。
- 截图只做人工或容差对照，不做严格像素相等。

### 29.10 标准命令

~~~shell
npm ci

/opt/homebrew/bin/uv run --no-project --with pytest \
  python -m pytest tests -q -p no:cacheprovider

/opt/homebrew/opt/node@22/bin/node --check reweave_frontend/app.js
/opt/homebrew/opt/python@3.14/bin/python3.14 -m compileall -q pimos_lite
git diff --check
~~~

PySide 真实验收使用独立 .venv-reweave 和现有 pimos_lite/requirements-desktop.txt，不把 PySide6 加入核心依赖。

## 30. 旧路径退出顺序

阶段 1–3 期间 SQLite 基础不在应用调用图；阶段 4 只激活 SQLite 入库、复核、仓库管理和备份恢复，不激活 SQLite 生成。前端不提供旧 JSON/SQLite 生成二选一，`generationActive=false`、`generationFromSqlite=false`。

阶段 5 单次切换前必须证明：

- SQLite 资格查询完成。
- 三类固定策略和三个子进程完成。
- Ollama 强制监督完成。
- module_native 接收内存对象并通过端到端测试。
- 桌面和 CLI 均只通过 ReweaveAppService。
- manifest 和 usage 精确一致。

切换时从活跃调用图移除：

- capsule_path 输入。
- stage4_behavior_modules。
- 旧 capsules.json 正式读取。
- Stage4 bridge 生成分流。
- 前端 origin 业务判断。
- 前端硬编码 Ollama 模型。

历史代码是否物理删除不属于本阶段；首先证明它不再被导入或调用。不得整体恢复、cherry-pick 或重建旧系统。

## 31. 实施阶段

### 阶段 0：本文（已完成）

- 完成设计文档。
- 完成 DDL、触发器、状态机、安全策略和测试向量复核。
- 只允许本文发生仓库修改。
- 用户确认后才能进入阶段 1。

### 阶段 1：非活跃 SQLite（已完成）

- 一个具体 sqlite3 store。
- DDL、结构迁移、事务、canonicalization，以及本文确定的 extraction/redaction/brand 版本字段和数据库约束。
- 备份和恢复。
- 不切换生成读取。

### 阶段 2：来源和候选（已完成）

- 根目录发现、单入口确认、UUID、父子排除。
- 内容快照和 no_change。
- extraction_contract.v2、模块闭包和原子候选。
- data_contract.v1、合成 fixture 和兼容判断。
- 敏感数据门及绑定来源 hash 的确认决定。

### 阶段 3：安全、模型和验证（已完成）

- JavaScript AST。
- HTML/CSS 子集。
- 图片 worker。
- Ollama 监督。
- Node computation 和 QWeb worker。
- 精确重复、等价复核、变体和版本。

### 阶段 4：原前端增量和旧仓（已完成，生成未激活）

- 来源管理。
- 模型选择。
- 风琴复核。
- capability 分组仓库。
- 备份恢复。
- 旧 JSON 逐条重清洗。

### 阶段 5：单次生成切换（已完成）

- module_native 内存输入。
- ReweaveAppService 唯一入口。
- 旧正式读取退出活跃调用图。
- 产品 manifest 和 usage。

### 阶段 6：验收

- 本地和 CI 支持矩阵。
- 真实桌面项目绑定、刷新、复核、入仓、生成和交互。
- 来源项目零写入证据。
- 旧产品精确版本追溯。

## 32. 优先级

P0：

- 固定原子提取边界和 data_contract.v1。
- 敏感数据边界。
- JavaScript/HTML/CSS/资产失败关闭。
- 三个子进程边界。
- 不同代码禁止自动合并。
- SQLite 数据库级不可变和原子发布。
- module_native 内存契约。
- 唯一正式生成读取和精确版本追溯。

P1：

- 根目录发现、父子排除和变化中止。
- 品牌全贡献重审。
- 四套状态机和重启语义。
- 备份恢复闭环。
- 原前端增量界面。
- 本地真实桌面验收。

P2 暂不做：

- WAL。
- repository 接口和存储工厂。
- 通用事件系统。
- React/Vite 构建支持。
- 多页面自动推理。
- SVG/字体净化。
- 云模型、后台监听、第二 composer、模板和 fallback。

## 33. 阶段 1 进入门（已通过）

进入阶段 1 前必须全部满足：

- 本文 33 个章节完整。
- 当前事实和目标实现明确分开。
- capability、capsule、variant、version 无双重含义。
- dom_scope 与 usage_scope 独立且在 storage/hash/validator/composer 中一致。
- 根内 DOM/Event 白名单封闭。
- extraction_contract.v2 明确固定名和任意名称正式角色种子、依赖闭包、稳定候选别名、契约/样例生成、歧义处理和模型权限，并可触发重扫。
- data_contract.v1 语法和输出到输入的兼容算法封闭。
- waiting_user 的 sensitivity/asset 决定绑定 project/path/hash/redaction version，brand 决定再绑定有效 profile ID/digest；任一绑定变化后失效。
- Event 对象除直接 preventDefault() 外无可读能力。
- 本地模块闭包封闭。
- canonicalization 有跨环境固定向量。
- 重复候选不能绕过过期门禁。
- 自动精确重复只命中 active capsule 的 current_version_id，历史版本只作证据。
- 计算、图片和 QWeb 均是独立子进程。
- DDL 和触发器可在空 SQLite 执行。
- brand_profile_id 生命周期、全贡献重审、来源 project 约束、manifest digest 一致性和 revalidation_required 事件已进入 DDL/正文。
- 不可变、原子发布和恢复失败回退语义闭合。
- review_items、日志、模型和备份不保存来源原文。
- module_native 不读取目录或数据库。
- 前端保留体验但不保留旧架构判断。
- 16 个契约场景都能回答状态、模型、子进程、写入、版本、资格、UI 和重启。
- 用户明确确认本文。

用户已确认本文并批准阶段 1。阶段 1 已按本门完成，未因此批准阶段 2，也未批准 SQLite 进入生成活跃路径。

## 附录 A：阶段 0 契约闭合索引

本附录记录设计层复核结论，不代表业务代码已经实现或真实桌面流程已经通过。

| 封板项 | 正文位置 | 设计层结论 |
|---|---|---|
| dom_scope 与 usage_scope 分离 | 第 6、10、18、23、26 节 | 独立存储、独立消费、共同参与 hash；变化只产生新版本 |
| 根内 DOM/Event 白名单 | 第 8、12、13、29 节 | 查询、修改、事件、HTML 和 CSS 均使用失败关闭白名单 |
| 原子能力提取 | 第 4、9、11、20、29 节 | 固定种子和静态依赖闭包决定代码边界；模型只监督和命名；规则升级触发重扫 |
| data_contract.v1 | 第 7、10、23、29 节 | 小型类型系统、外层端口/错误格式和保守兼容算法已封闭 |
| 敏感确认闭环 | 第 15、18、21、29 节 | sensitivity/asset 绑定 project/path/hash/redaction version，brand 另绑定 profile ID/digest；确认后模型仍只看脱敏结构 |
| 纯计算与图片子进程 | 第 14、17、27、28 节 | 候选代码和图片解码均不在桌面进程执行 |
| 重复候选门禁顺序 | 第 11、27、28 节 | 精确重复只能复用满足全部当前门禁版本的 active current version，历史命中只作证据 |
| 本地 JavaScript 模块闭包 | 第 9、10、17、28 节 | 单入口、静态相对 import、路径/数量/深度限制和全闭包 AST 已封闭 |
| 稳定 key 生命周期 | 第 4、5、18、26 节 | 建议、首次发布冻结、冲突后缀、展示名和语义拆分规则已分离 |
| SQLite 数据库级不可变 | 第 18、21、29 节 | DDL、外键、唯一约束、只追加触发器和有限状态迁移已给出 |
| 品牌身份与全贡献重审 | 第 6、15、18、28、29 节 | profile UUID/digest 生命周期明确，general 和 brand_limited 当前贡献统一重审 |
| 恢复语义 | 第 19、23、28、29 节 | 全库时点恢复、版本门、原子替换、失败回退和缺失历史版本语义已封闭 |

跨契约复核结论：唯一正式仓库是 SQLite，唯一组合器是 module_native；旧 JSON 只读且逐条重新进入同一主线；模型、固定安全门和三个验证 mode 不产生第二条发布路径；前端只经 ReweaveAppService；生成只消费 active current version 并记录精确 version。阶段 1 仅完成非活跃基础，未改变现有生成读取。

## 附录 B：阶段 1 实施封板记录

完成日期：2026-07-15。

已实现：

- `pimos_lite/reweave_capsule_store.py` 是唯一具体 sqlite3 store；没有 repository 接口、工厂或第二实现。
- 数据库路径为 `state_dir() / "capsule_warehouse.sqlite3"`，备份位于同一状态目录的 `backups`；继续支持 `REWEAVE_STATE_DIR` 测试隔离。
- `PRAGMA user_version = 1`；首个 SQLite 版本没有前代迁移，非空 version 0、低于或高于当前版本且没有已测试迁移路径的数据库均失败关闭。
- DDL 共 14 张业务表和 31 个触发器；代码中的 `SCHEMA_SQL` 与本文两个 SQL 块逐字一致。
- 外键、默认非 WAL 日志、5000 ms busy timeout、短事务、发布回滚、正式版本和来源/资产/事件/usage/alias 不可变约束已经落地。
- 新 capsule 必须以非 active 且空 `current_version_id` 创建，随后在同一发布事务中插入版本并切 current；INSERT 和 UPDATE 均不能绕过 version 归属约束。
- canonicalization.v1 只有一个具体函数；固定向量、换行/集合/模块/资产排序、严格 JSON、逻辑路径和代码字节差异均有测试。
- 备份使用 SQLite backup API；恢复要求确认 SHA-256，执行结构版本、完整性和外键预检，显示丢失数量，创建恢复前备份，同目录原子替换并在替换后失败时回退。
- POSIX 状态目录/备份目录和文件权限分别为 0700/0600。
- 发布面审计把该模块登记为 `included_non_active_foundation`，不属于默认入口或支持运行时。

非活跃证明：

- 现有应用、CLI、前端、`module_native` 和旧 JSON 仓均不导入 `reweave_capsule_store`。
- 构造 store 对象不会创建数据库，只有显式 `initialize()` 才写入状态目录。
- 未修改前端、组合器、生成路径或旧 JSON 读取；没有运行时双仓开关。

该阶段首次完成时验证（最终冻结验证见附录 F）：

- 本地 Python 3.14.5：阶段 1 与发布面聚焦测试 17 passed；全量 451 passed、10 subtests passed。
- 临时 Python 3.11.15：同一聚焦测试 17 passed，固定 hash 相同。
- Python 编译、DDL/文档逐字一致性和 diff whitespace 检查通过。
- 本节记录形成时，Ubuntu、Windows 和 Node 24 尚未执行；最终冻结版本的本机 Node 24 正式工作流等价验证见附录 F，远端双平台 runner 仍单独列明。
- 阶段 1 不包含 PySide/QWeb 工作，因此本记录不声明桌面真实验收完成。

阶段门结论：阶段 1 完成；本记录形成时阶段 2 尚未开始，后续实施结论见附录 C。

## 附录 C：阶段 2 实施封板记录

完成日期：2026-07-15。

已实现：

- `pimos_lite/reweave_capsule_intake.py` 是唯一非活跃阶段 2 intake 对象；它复用阶段 1 的唯一 SQLite store，没有 repository 接口、工厂、第二仓库或第二条发布路径。
- 来源根支持单项目和项目集合绑定，使用应用生成 UUID；已确认移动可重连且保留 root/project 身份。首次绑定和重连共用目录、重复绑定及 `state_dir()` 不得位于来源内的门禁。
- 项目发现记录结构化理由和单一 HTML 入口。父项目在独立子项目尚未确认时失败关闭；确认后父快照排除子根。同一项目进程内只允许一个 intake run。
- 快照最多读取 800 个受支持文件、深度 8、单文件 1 MiB；不跟随符号链接，检测大小写冲突和读取期间变化。整体摘要覆盖排序后的逻辑路径、类型、大小和内容 SHA-256，mtime 仅作诊断。
- `scripts/analyze_reweave_extraction.mjs` 使用仓库 TypeScript AST 建立最多 32 模块、深度 8 的本地 `.js`/`.mjs` 闭包；只消费 Python snapshot_before 传入的模块字节和 SHA-256，不接收或读取来源项目根。它支持静态相对 named/default import、named export 和有稳定声明名称的 default export，拒绝匿名 default、re-export、动态/bare import、循环、快照外 import、越界、大小写冲突和顶层执行副作用。
- 首次实现的 extraction_contract.v1 从明确导出的 `render`、`mount`、`compute` 形成三类原子候选；当前 extraction_contract.v2 另接纳唯一通过完整正式角色证明的任意名称顶层具名 ESM 函数，并只在候选副本追加稳定正式入口别名。同一入口或闭包出现多个角色种子时失败为 non_atomic_role_closure_v1；immutable const 字符串经过有界传播后再进入敏感/品牌证据；入口内未证明属于角色的局部函数失败关闭。interaction 只有返回式 dispose 精确闭合 listener 且 DOM 数值经过 handler 内显式 guard 时才能形成候选。一个角色的边界或契约不能证明时只拒绝该角色，不阻断同一项目其他合法角色。
- HTML 入口、登记 CSS/图片和模块内容共同形成候选来源证据；只保存逻辑路径和 SHA-256。非 `.css` 样式、非 `.js/.mjs` 模块以及非 PNG/JPEG/WebP 登记资源在静态闭包确认时失败关闭；内容级 HTML/CSS/图片安全判断仍属于阶段 3。
- `pimos_lite/reweave_data_contract.py` 是唯一 data_contract.v1 实现，封闭对象、数组、字符串、布尔、JavaScript 安全整数和规范十进制语法；字符串长度按 UTF-16 code unit，结构成员拒绝控制字符、保留原型名和非 UTF-8 值。实现严格规范化、值验证、数组 item 递归合成、最多 64 个且覆盖每个适用拒绝类别的 fixture，以及保守的来源输出到目标输入兼容判断。覆盖预算不足或类别不闭合时失败关闭。
- 敏感门先扫描当前候选涉及的 JS、入口 HTML 和登记 CSS。secret 直接拒绝；真实记录性质、品牌去留或图片像素性质不明确时进入 waiting_user。sensitivity/asset 决定只在 project ID、来源入口、覆盖 HTML/CSS/登记资产/JS 的 source hash 和 redaction_rules.v1 全部相同时复用；brand 决定还要求有效 profile ID/digest 一致。真实记录拒绝优先，其他同绑定冲突失败关闭。
- extracted review item 只保存已通过敏感结构门的契约、数量摘要、逻辑路径和 SHA-256；waiting_user/rejected 只保存固定安全摘要，不保存契约、模块路径或静态证据。敏感字面进入契约标识且无法一致改写时直接拒绝；来源变化使旧敏感或品牌决定自动失效。
- no_change 同时要求内容快照、有效品牌 digest、extraction/redaction/canonicalization 以及当前阶段安全、监督和验证版本完全相同。阶段 2 将后三者明确记为 `not_run.stage2`，因此阶段 3 接入真实规则版本后不会错误复用阶段 2 结论。
- queued/running run 在重启恢复时转为 interrupted；取消、来源扫描中变化或候选事务失败不会留下半个 review item。阶段 2 不写 capsules、capsule_versions 或其他正式发布表。
- 发布面审计把 intake、data contract、SQLite store 和 TypeScript 提取脚本登记为 `included_non_active_foundation`；缺少任一文件都会使审计不通过。

非活跃证明：

- 现有桌面应用、CLI、前端、`module_native` 和旧 JSON 读取均不导入 `reweave_capsule_intake` 或 `reweave_data_contract`。
- 只有显式构造 intake 并调用绑定、发现或刷新 API 才会写非活跃 SQLite 表；来源目录只读。
- 阶段 2 没有调用 Ollama，没有执行候选 compute/render/mount，没有图片解码或 QWeb 验证，也没有产生 canonical capsule 或正式版本。
- 未修改前端、组合器、现有生成入口、旧 JSON 仓或产品 manifest；没有双仓运行时开关。

该阶段首次完成时验证（最终冻结验证见附录 F）：

- 本地 Python 3.14.5、Node 22.22.3：阶段 1/2/3 与发布面聚焦测试 58 passed、22 subtests passed；全量 492 passed、32 subtests passed。
- 临时 Python 3.11 环境：同一聚焦测试 58 passed、22 subtests passed。
- 新 TypeScript AST 脚本通过 `node --check`；Python 新模块通过编译检查。
- 快照字节唯一输入、忽略目录闭包拒绝、多角色闭包失败关闭、返回式 dispose、DOM 数值显式 guard、短品牌、敏感契约标识不落盘、数组 item 与宽契约拒绝类别覆盖，以及原有 named/default 导出、越界/缺失 import、父子排除、来源变化和决定 hash 失效均有独立行为断言。
- 本节记录形成时，Node 24、Ubuntu 和 Windows 尚未执行；最终冻结版本的本机 Node 24 正式工作流等价验证见附录 F。阶段 2 本身不声明真实桌面验收完成。

阶段门结论：阶段 2 完成。本记录形成时阶段 3 尚未开始；其后续完成证据见附录 D。在附录 D 的门禁完成前，任何阶段 2 候选都不能发布、进入生成资格查询或替代旧生成路径。

## 附录 D：阶段 3 实施封板记录

完成日期：2026-07-15。

已实现：

- `pimos_lite/reweave_capsule_stage3.py` 是一个显式调用、非活跃的阶段 3 服务。它复用阶段 1 的唯一 SQLite store 和阶段 2 的只读 intake；没有 repository 接口、工厂、第二仓库、第二 composer 或运行时双仓开关。
- 每次处理 review item 都重新只读快照来源、重新执行当前 extraction_contract_version（当前为 v2）并复算 candidate/source hash。来源快照、候选边界、品牌 profile 或绑定决定变化时不复用旧内存结果，正式写事务前再次复核快照。
- `scripts/analyze_reweave_security.mjs` 使用 TypeScript AST 检查全部模块：拒绝网络、导航、存储、动态执行、timer、未知全局、动态属性、模块级可变状态、输入修改、根外 DOM、未声明 selector/class/attribute/event、Event 对象读取、错误 listener 清理和异步入口。事件对象只允许直接调用 `preventDefault()`；submit 必须阻止默认提交。
- HTML 清洗使用严格标签栈和失败关闭白名单，抽取唯一 `data-capsule-root`，删除注释，重写 id/for，占位并校验登记资产；拒绝 script/iframe/svg、内联事件/style、外链、表单提交属性、嵌套根、重复 id、未声明 ARIA/data-state 和无法解析结构。
- CSS 清洗使用一个具体 tokenizer/parser，只接纳普通规则、根占位符作用域、后代/直接子代 selector 及固定 property/value 子集；拒绝 at-rule、escape、URL、全局 selector、相邻/兄弟组合、fixed/sticky、变量、动画、未知函数和无法解析语法。
- 敏感字面值先由固定规则处理；JavaScript 评论、标识符或结构字符串中无法安全替换的残留直接拒绝。模型输入删除来源路径、源码、HTML/CSS 和原始 fixture，只保留脱敏契约、计数、hash 及资产序号元数据。模型输出也执行封闭 schema、代码 token、大小和敏感值检查。
- `OllamaSupervisor` 只允许 `127.0.0.1`、`localhost` 或 `::1`，禁用代理和 redirect；没有默认模型，不选择第一项。用户选择的 name/digest 保存为独立 `capsule_supervision_model`，每次监督前重新读取 `/api/tags` 并核对 digest。只保存结构化监督结论及模型原始输出 SHA-256，不保存提示或原始响应。
- `scripts/validate_reweave_compute.mjs` 在独立 Node 子进程的 `vm` context 中运行 esbuild bundle；不暴露 process、require、fetch、Buffer 或 timer，关闭字符串/WASM 代码生成。fixture 在 VM 内深冻结；正常、边界和无效输入、相同输入重复结果、有限 JSON 输出及 data_contract/error_contract 均由父进程复核。
- `pimos_lite/reweave_capsule_worker.py` 只有固定 `image` 和 `qweb` 两个 mode。图片只从一次性临时文件读取，按 magic、实际 Qt 格式、大小、尺寸和像素数验证，以新 QImage 重编码并只返回清洗字节和摘要；SVG、字体、伪装文件、插件错误、超时和崩溃均失败关闭。
- QWeb mode 在子进程 Qt 主线程创建 off-the-record QWebEngineProfile，关闭持久 cookie/cache/storage、DNS 预取和远程访问。请求拦截器只允许临时包登记文件；CSP 默认拒绝网络、data/blob、frame/object/worker/font 和表单提交。阻断请求只记录 scheme 与脱敏逻辑名。
- presentation 在真实 QWebEngine 中逐一运行全部正常/边界 fixture，并验证重复 render 不累计可观察 DOM，标签为 `real_qwebengine_render`。interaction 对全部正常/边界 fixture 执行 dispose→mount、声明事件、原始 emit 严格 JSON、输出契约、submit preventDefault、两次 dispose 以及 dispose 后不再响应，标签为 `real_qwebengine_interaction`。无效 fixture 在应用边界拒绝，不直接交给 render/mount；这两个标签不等于模拟声明交互。
- 精确重复只短路到满足全部当前规则版本的 active current version；历史、disabled、pending 或规则过期版本不能自动挂来源。规则过期但唯一 current 身份仍可证明时，完成模型和运行验证后发布同内容新版本。不同 canonical hash 永不自动合并。
- 同一 run 的相同 canonical hash 复用一个代表的脱敏证据；代表失败时同组保持相同等待/拒绝结果。人工 `merge_existing` 只连接来源到被保留且满足当前规则、监督和验证资格的 active current version；`create_variant`、`replace_current` 和新身份发布都产生不可变版本。模型 review 经人工发布时保留原 verdict，并把独立 human_approval 写入不可变版本证据。
- waiting_user、waiting_model、waiting_validation、review_required 或尚未处理的 extracted candidate 会使项目的 no-change 快照缓存失效，恢复条件后必须创建新 run；阶段 3 不把已经终止的 intake run 非法改回 running，也不从进程内断点继续。
- 自动精确重复后的人工 `semantic_split` 可以复用同一个合格 current version 的验证证据，在一个 SQLite 事务中创建新身份、新版本并停用旧身份；key 仍由用户决定并在首次发布时冻结。人工拒绝形成不可逆 review 决定。
- 发布事务插入 capability group、capsule、version、清洗资产、来源和状态事件，再切换 current 指针；任一步失败整体回滚。阶段 3 不写产品目录、不登记 product usage，也不改变来源项目。
- 发布面审计把阶段 3 服务、固定 PySide worker、TypeScript 安全脚本和 Node 计算脚本登记为 `included_non_active_foundation`；缺少任一文件都会使审计不通过。

非活跃证明：

- 现有桌面应用、CLI、原前端、`module_native`、旧 JSON 读取和生成路径均不导入阶段 3 服务或 worker。
- Ollama、图片、Node VM 和 QWebEngine 只有显式调用 `ReweaveCapsuleStage3` 后才运行；构造服务本身不联网、不创建窗口、不读取来源或写正式版本。
- PySide6 继续只位于独立 `.venv-reweave` 桌面环境，未加入核心 Python 依赖。esbuild 和 TypeScript 复用仓库现有 npm 依赖。
- 没有前端硬编码模型、Stage4 分流、模板、fallback、preview/export/promote 或新的生成读取路径。

该阶段首次完成时验证（最终冻结验证见附录 F）：

- 本地环境为 Python 3.14.5、pytest 9.1.1、Node 22.22.3、PySide6 6.11.1；`npm ci` 成功且 npm audit 为 0 vulnerability。
- 临时 Python 3.11 环境的阶段 1/2/3 与发布面聚焦测试为 58 passed、22 subtests passed。
- 本地 Python 3.14.5 的阶段 3 与发布面聚焦测试为 17 passed、20 subtests passed；全量为 492 passed、32 subtests passed。
- Python 编译、两个新 Node 脚本和现有前端 JavaScript 的 `node --check`、release audit、Ruff、已跟踪与未跟踪文件的 whitespace 检查均通过。
- 真实 QWebEngine 已在独立子进程中完成 presentation render、interaction click/emit/dispose 和越界 file 请求阻断。它不是 synthetic declared interaction；但阶段 4 管理界面和阶段 6 可见桌面端到端流程尚未完成。
- 本节记录形成时 Node 24 尚未在本机执行；附录 F 记录最终冻结版本的 Node 24 正式工作流等价验证。本文仍不声称已经通过未触发的远端 Ubuntu/Windows runner。

跨阶段仍保留、不得在活跃切换前遗漏的 P1：恢复操作仍依赖未来唯一应用服务先停止任务并关闭连接。store 已封闭 status event 和 legacy alias 的 version/capsule 归属，但它不建立连接管理器或第二套任务编排。

阶段门结论：阶段 3 的非活跃安全、模型、三个隔离验证、重复/人工复核和不可变版本发布路径完成。阶段 4 尚未开始；原前端、旧仓和现有生成路径保持不变，任何新正式版本仍不会被现有生成读取。

## 附录 E：阶段 2 深度审计修复记录

完成日期：2026-07-15。

本轮只修正阶段 2/3 非活跃基础及其测试，没有修改原前端、CLI、module_native、旧 JSON 仓或现有生成路径：

- Node 提取器不再从实时项目目录读取模块；Python 传入 snapshot_before 的模块字节和 SHA-256，Node 复核 hash，快照外闭包失败关闭。测试在 Node 调用期间替换并恢复实时源码，结果仍严格来自快照；dist 等忽略目录不能进入闭包，也不能形成错误 no_change。
- 同一入口或闭包暴露多个 capability_kind 时不再复制完整模块形成多个候选，而是以 non_atomic_role_closure_v1 拒绝相关角色。独立入口仍可共享纯 helper 模块。
- waiting_user/rejected 只持久化固定安全摘要。敏感字面成为契约标识时，用户确认后仍不保存或发送原值；V1 不能证明全引用一致改写则以 sensitive_contract_identifier_unsupported 拒绝。
- 品牌 profile 的非空已确认短名称不再被长度门丢弃；HP 等信号会进入 waiting_user，确认保留后形成 brand_limited usage_scope。
- interaction 只有 mount 最终返回的同步 dispose 内的精确 remove 才能闭合 listener；阶段 3 继续用真实 QWebEngine 验证两次 dispose 和 dispose 后无 emit。
- HTML 数值属性不再直接证明 emit 契约；只有同一 handler 内显式 Number 转换、整数校验、上下界 guard 且 guard 支配 emit 时才提取数值输出。
- 数组合成 fixture 递归覆盖 item 边界和无效值；最多 64 个无效样例先覆盖每个适用拒绝类别，宽契约不再被前 64 个 missing_required 挤掉其他类别。更严格 fixture 暴露出的旧计算测试样例已通过补足候选根输入校验修正，验证器没有放宽。

该轮复验结果：Python 3.14.5 全量 492 passed、32 subtests passed；Python 3.11 阶段 1/2/3 与发布面聚焦 58 passed、22 subtests passed；Python 编译、全部前端/脚本 JavaScript node --check、Ruff 和 whitespace 检查通过。最终冻结数字见附录 F。真实 QWebEngine 测试重新通过，但可见桌面端到端流程仍属于阶段 6，不能由本轮结果替代。

审计结论：上述七项 P0/P1 已闭合，阶段 2 可恢复为完成；阶段 3 的非活跃门禁保持通过。该轮记录形成时的跨阶段遗留是附录 D 所列恢复并发应用服务边界，以及尚未执行的 Node 24/Ubuntu/Windows CI；最终冻结状态见附录 F。

## 附录 F：阶段 1–3 有边界最终收口记录

收口日期：2026-07-15。

本附录取代附录 B 至附录 E 中较早的测试数字，作为阶段 1–3 非活跃基础的最终冻结验证记录。它不扩大实现范围，不表示阶段 4 至阶段 6 已完成。

### F.1 冻结边界

阶段 1–3 源码、脚本和测试在最终验证前冻结为以下 13 个文件；验证期间不再修改：

- `pimos_lite/reweave_capsule_store.py`
- `pimos_lite/reweave_data_contract.py`
- `pimos_lite/reweave_capsule_intake.py`
- `pimos_lite/reweave_capsule_stage3.py`
- `pimos_lite/reweave_capsule_worker.py`
- `scripts/analyze_reweave_extraction.mjs`
- `scripts/analyze_reweave_security.mjs`
- `scripts/validate_reweave_compute.mjs`
- `tests/test_reweave_capsule_store.py`
- `tests/test_reweave_capsule_intake.py`
- `tests/test_reweave_capsule_stage3.py`
- `pimos_lite/reweave_release_surface_audit.py`
- `tests/test_reweave_release_surface_audit.py`

冻结摘要使用 `shasum -a 256 <上述文件> | shasum -a 256` 计算，结果为：

```text
97954d4ce890810f98c9fc8182af65e7cacd698317f1e3e8a19903804c511cbd
```

Python 3.11、正式 CI 命令链和限定 diff 审阅完成后复算结果相同。设计文档是冻结后唯一允许更新的仓库文件；原前端、App、CLI、`module_native`、旧 JSON 仓和现有生成路径均未修改。

### F.2 最终修复闭合

阶段 1：

- 恢复验证从对象名称检查收紧为完整 schema 指纹，精确比较表、显式索引、触发器及其 SQL，拒绝未知、缺失和同名伪造对象。
- canonical JSON 在键换行规范化后检测冲突并失败关闭；正式版本恢复时重建 canonical payload，拒绝未知 canonicalization 版本、畸形或重复键 JSON 和 hash 不一致。
- 恢复候选绑定用户确认的 SHA-256，原子替换前再次校验，关闭候选替换 TOCTOU；恢复审计同时复核资产字节、SHA-256、大小、尺寸和像素限制。
- capsule/current version、source relationship、status event、product usage、manifest digest 和 legacy alias 的跨行关系由数据库触发器与恢复审计共同封闭。空库权威结构为 14 张表、9 个显式索引、31 个触发器，默认日志模式为 `delete`。

阶段 2：

- 提取器只消费 Python 一致性快照中的模块字节和 SHA-256，不再读取实时项目目录；忽略目录、快照外闭包、符号链接和读取中替换均失败关闭。
- 普通文件使用稳定只读句柄：读取前后核对根与路径、`lstat`/`fstat`、设备号、inode、类型、大小和 mtime；可用时启用 `O_NOFOLLOW`。根或文件在检查与打开之间被替换时不留下 review item 或成功快照。
- waiting/rejected 只保存固定安全摘要；敏感契约标识无法一致改写时拒绝。短品牌信号、间接字符串构造、JSON/String 别名、JavaScript 安全整数、非 UTF-8 字符串、数组 item 拒绝类别和 fixture 上限均已失败关闭。
- 原子角色闭包、mount 返回的同步 dispose、DOM 数值显式 guard、忽略目录大小写、64 MiB 总快照、16 MiB JavaScript 输入和 Node 256 MiB 内存边界均有回归断言。

阶段 3：

- HTML、CSS、JavaScript 和资产安全门、loopback Ollama 监督、Node computation worker、PySide image/qweb worker 保持单一路径和失败关闭。
- 精确重复与人工合并在 `BEGIN IMMEDIATE` 发布事务内重新检查 active current version、规则版本和完整不可变证据；历史、disabled、pending 或证据过期版本不能自动命中。
- 生成资格不只读取 `passed/approve` 字面值，而是核对固定 stage3 evidence schema、清洗/安全结果、模型 identity/digest、监督响应 hash 及按 capability_kind 区分的真实 validation scope。旧最小证据和畸形证据不合格。
- QWeb 被阻断的外部文件只记录 `<outside>`，不泄漏越界路径 basename。presentation 和 interaction 分别保存 `real_qwebengine_render` 与 `real_qwebengine_interaction`，不得用 synthetic 声明交互替代。

### F.3 最终冻结验证

独立 Python 3.11 门：

```text
Python 3.11.15
pytest 9.1.1
523 passed, 76 subtests passed
```

命令为：

```bash
/opt/homebrew/bin/uv run --python 3.11 --no-project --with pytest \
  python -m pytest tests -q -p no:cacheprovider
```

随后逐条执行 `.github/workflows/ci.yml` 的正式命令链，使用独立临时 Python 3.11.15 环境和独立临时 Node v24.18.0：

- `npm ci` 成功，npm audit 为 0 vulnerability。
- `python -m pip install --upgrade pip` 与 `python -m pip install -r requirements-dev.txt` 成功。
- `python -m pytest tests -q`：523 passed、76 subtests passed。
- public Reweave demo 成功，规定产物完整。
- Stage4 estimate 与 data demo 均成功，规定产物完整。
- `node --check reweave_frontend/app.js` 成功。

本次是在 macOS 上对正式 workflow 命令的等价执行。冻结提交尚未 push，因此没有触发 GitHub 托管的 Ubuntu/Windows runner；本文不把本机结果表述为远端双平台 CI 已通过。

仓库存在独立 `.venv-reweave`，全量测试中的 PySide 流程实际执行了 image 与真实 QWebEngine 子进程测试，包括 presentation render、interaction event/emit/dispose 和越界 file 请求阻断。它验证的是候选运行隔离，不是阶段 6 的可见桌面端到端用户流程；后者仍未完成，不能由这些结果替代。

### F.4 限定范围最终 diff 审阅

最终审阅只覆盖本附录 F.1 的冻结文件、本文档和发布面登记，不再派生新的独立探针。结果：

- Git 工作树只有 14 个预期路径：13 个冻结源码/脚本/测试文件和本文档；没有前端、组合器、CLI、App 或旧仓修改。
- `git diff --check`、全部冻结文件尾随空白检查、Python 编译和三个新增 JavaScript 脚本的 `node --check` 通过；没有 `TBD`、`TODO`、`FIXME`、`XXX` 或 `NotImplementedError`。
- 非活跃模块在 `pimos_lite` 其他模块和 `reweave_frontend` 中没有导入命中；发布面审计把 8 个基础运行文件全部标记为 `included_non_active_foundation`。
- store 与发布面聚焦复核为 26 passed、21 subtests passed；完整 schema/DDL、不可变关系和发布面登记继续由测试覆盖。
- 冻结摘要复算不变；本轮未发现新增可复现 P0 或 P1。

### F.5 收口结论与剩余门

- 阶段 1：`PASS`，限非活跃 SQLite store、canonicalization、备份和恢复实现。
- 阶段 2：`PASS`，限非活跃来源发现、稳定只读快照、原子候选和数据契约实现。
- 阶段 3：`PASS`，限非活跃安全、监督、隔离验证、重复/人工复核和正式发布事务实现。
- 整体迁移：`PARTIAL`；阶段 4 前端与旧仓逐条重清洗、阶段 5 唯一组合器切换和阶段 6 可见桌面端到端验收尚未实施。
- P0：无。
- 新增可复现 P1：无。
- 已知活跃切换前置门：恢复操作必须由未来唯一应用服务先停止任务并关闭全部 SQLite 连接；当前非活跃 store 不承担连接管理，也不因此新增第二任务系统。
- P2：发布面审计当前以显式非活跃文件清单为主，import graph 仍由限定 `rg` 检查；GitHub 托管 Ubuntu/Windows runner 尚未对未 push 的冻结提交执行。

本冻结版本满足建立本地 checkpoint 的前置条件。checkpoint 后停止阶段 1–3 的独立审计；后续只有进入已批准的新阶段或出现来自真实使用、正式 CI 的可复现回归时，才重新打开相应范围。

## 附录 G：阶段 3 对抗性边界补充收口记录

收口日期：2026-07-15。

本附录记录 checkpoint 后由具体对抗性复现重新打开的阶段 3 限定修复，并取代附录 F 中旧的冻结摘要、测试数字和阶段 3 最终判断。修复范围只包含阶段 3 安全分析、固定 PySide worker、阶段 3 服务及其测试；没有修改阶段 1/2、原前端、App、CLI、`module_native`、旧 JSON 仓或活跃生成路径。

### G.1 已闭合的具体问题

- JavaScript AST 现在把入口 `root`、合法查询返回值及其全部 DOM 派生值纳入 provenance。只有以已声明 selector 建立的直接 DOM binding 才能执行白名单读写；`offsetParent`、祖先、根外对象以及查询链上的派生属性均失败关闭。实现没有继续扩张 property denylist。
- `addEventListener` 和 `removeEventListener` 只能引用当前模块中可静态解析到唯一函数体的 handler。导入 handler、无法解析 handler 和读取 Event 属性的嵌套 handler 均拒绝；Event 仍只允许直接调用 `preventDefault()`。
- 真实 QWeb harness 使用 `MutationObserver` 监测整个文档的 `attributes`、`childList` 和 `characterData`。候选执行期间，除 capsule root 及其后代外的任一 mutation 都以 `qweb_root_escape_detected` 失败；原有文本哨兵继续作为冗余检查。
- 图片只从清洗后原子 root 实际引用的 `<img src>` 形成资产闭包。文档其他区域登记的图片不会触发人工像素确认、不会进入 worker，也不会写入 `capsule_assets`。
- 根内资产在进入 image worker 前使用阶段 2 现有稳定只读句柄重新读取，并立即与本次 snapshot SHA-256 比较。文件替换、父级符号链接和越界 resolved path 继续失败关闭；worker 不接收来源项目路径。
- 图片后缀、magic、Qt 实际格式和返回 media type 使用固定映射交叉验证；PNG 字节使用 `.jpg` 等伪装路径以 `image_format_mismatch` 拒绝。位图像素仍必须由用户确认不含真实记录，未引入 OCR，也不把图片交给模型。
- `semantic_split` 在 `BEGIN IMMEDIATE` 内重新绑定当前 review 的 comparison evidence，并要求被停用目标为同 kind 的 `active + current_version_id`。`pending_revalidation` 或过期目标使整笔事务回滚；成功拆分把被保留的旧 version 写入 `retained_version_id`。
- 发布、人工合并、精确重复挂接和人工拒绝均在任何正式副作用前，以预期 candidate status 加 `decision IS NULL` 执行条件更新并检查 `rowcount = 1`。并发决定冲突返回 `review_decision_conflict`，不能覆盖先到决定，也不留下 capsule、version、source 或 event 残留。
- presentation/interaction 继续运行全部正常和边界 fixture；无效 fixture 仍在应用边界检查。interaction 继续覆盖 dispose→mount、两次 dispose、dispose 后无 emit 且 DOM 不再响应。本轮没有把 synthetic 声明交互冒充真实 QWebEngine 验收。

### G.2 冻结摘要与验证

阶段 1–3 的 13 个冻结源码、脚本和测试文件继续使用附录 F.1 的固定顺序计算摘要；本轮最终值为：

```text
6b04e94df506b44ac1e875c0ab6a7f7f151a4794d1ad051ec1d0ab81589e520b
```

限定验证结果：

- 阶段 3 聚焦：`24 passed, 26 subtests passed`。
- 独立 Python 3.11.15、pytest 9.1.1 全量：`526 passed, 76 subtests passed`。
- Node v24.18.0 与 Python 3.11 按 `.github/workflows/ci.yml` 的正式命令链在本机等价复验：`npm ci`、全量测试、public Reweave demo、Stage4 estimate/data demo、规定产物检查和前端 `node --check` 全部通过；npm audit 为 0 vulnerability。
- 独立 `.venv-reweave` 实际运行 PySide image worker 与真实 QWebEngine；正常 interaction 和对抗性根祖先 mutation 用例均通过预期断言。它仍不是阶段 6 的可见桌面端到端用户验收。
- Python 编译、阶段 3 安全脚本 `node --check`、`git diff --check` 和限定 diff 审阅通过。
- 两组独立只读复核分别重跑资产竞态/闭包/格式探针以及 semantic split/CAS 探针，未发现限定范围内新的可复现 P0/P1。

冻结提交尚未 push，因此没有把本机等价复验表述为 GitHub 托管 Ubuntu/Windows runner 已通过。该项保持 P2，并应在下一次获准 push 后由正式 runner 验证。

### G.3 阶段判断

- 阶段 1：`PASS`，本轮未修改。
- 阶段 2：`PASS`，本轮只复用其稳定读取器，未修改其契约或实现。
- 阶段 3：`PASS`，上述具体 P0/P1 已闭合；无新增可复现 P0/P1。
- 整体迁移：仍为 `PARTIAL`，因为阶段 4 至阶段 6 尚未实施。
- 阶段 4 进入判断：`READY`。可以开始原前端增量管理界面与旧 `capsules.json` 逐条重新清洗，但不得提前修改 `module_native`、生成读取、旧路径退出或引入双仓开关；这些仍分别属于阶段 5 及其后续门。
- 阶段 4 必须承担的既有 P1 是：未来唯一应用服务在恢复前停止任务并关闭全部 SQLite 连接。它不阻止开始阶段 4，但在恢复 UI 或活跃切换验收时必须闭合。

本附录完成后停止阶段 1–3 独立审计。除真实使用或托管 CI 提供新的可复现回归外，不再以无边界探针继续重开阶段 1–3。

## 附录 H：阶段 4 入库管理面封板记录

完成日期：2026-07-15。

本附录取代附录 G 中“阶段 4 尚未实施”的当前状态判断，但不改写附录 B–G 形成时的历史事实。阶段 4 只激活入库和管理面；阶段 5 SQLite 生成切换与阶段 6 完整桌面端到端验收不在本附录完成范围内。

### H.1 冻结边界

阶段 4 的实现和回归文件固定为：

- `pimos_lite/reweave_app_service.py`
- `pimos_lite/desktop_reweave_static.py`
- `reweave_frontend/index.html`
- `reweave_frontend/styles.css`
- `reweave_frontend/app.js`
- `tests/test_reweave_app_service.py`
- `tests/test_reweave_frontend_static_release.py`
- `tests/test_reweave_phase4_bridge.py`
- `tests/test_reweave_phase4_management.py`
- `tests/test_reweave_phase4_legacy_import.py`

上述 10 个阶段 4 文件按本节顺序执行 `shasum -a 256 <files> | shasum -a 256`，最终摘要为：

```text
72cdca31cce1e55a3a61230bd33b1a2869e8be5726a4025088a8feff11f4dc0d
```

阶段 1–3 的 13 个冻结文件没有 diff，按附录 F.1 固定顺序复算摘要仍为：

```text
6b04e94df506b44ac1e875c0ab6a7f7f151a4794d1ad051ec1d0ab81589e520b
```

`module_native`、CLI、后端生成读取、product builder、behavior runtime、quality gate 和安全产品写入没有修改。原 `app.js` 的生成请求构造确有阶段 4 必要改动：删除硬编码模型、本地模型开关、stage4_module_native 数量分流和 origin/count 生成策略；它没有让 SQLite 正式版本进入旧生成，也没有新增运行时双仓开关。

### H.2 已实现管理闭环

- 唯一 `ReweaveAppService` 注入阶段 1 的一个 `CapsuleWarehouseStore` 及阶段 2/3 intake、supervisor、Stage 3 服务；没有新增 repository 接口、工厂、第二仓库、第二 composer 或应用服务分叉。数据库仍按需初始化，单纯打开初始页面不会创建新库。
- `capsuleIngestionV1` 与旧 `capsules`、`warehouseCapsules`、`useLocalCapsules` 和 generation selection 完全分离，明确返回 `generationActive=false`、`generationFromSqlite=false`、`singleWarehouse=true`、`singleComposer=true`。
- 原桌面窗口只增加薄 JSON QWebChannel slots 和一个 Source Root 文件夹选择器。扫描、模型、备份、恢复、候选处理和旧仓导入立即返回 run_id，并由一个串行 worker 执行；Qt slot 不直接运行候选代码、模型请求或 QWebEngine 验证。
- 同步查询、写入和长任务共享 operation lock。恢复设置 restore_pending 后拒绝新操作、等待已经进入的操作释放短连接，再执行不可取消恢复；应用关闭会 cooperative cancel 可取消任务并等待唯一 worker。启动时遗留 queued/running run 转 interrupted，不恢复进程内状态。
- 取消只在动作明确确认 cooperative cancel 时改变任务终态。已经完成数据库提交但在返回前收到 cancel 的动作保持 completed；refresh_all、单候选 gate 之间和 legacy alias 发布前均有取消点，不能出现“SQLite 已完成但管理任务显示 cancelled”或“任务 cancelled 仍写 alias”。
- 来源发现、项目确认、项目/全量刷新、loopback 模型查询和选择、脱敏 review、固定人工决定、按 capability_key 分组仓库、版本/来源/usage/status 查看、停用、备份、恢复和任务轮询均通过该唯一服务。
- 项目品牌 inherit/clear/replace 由前端提交；replace profile 是 JSON object，brand_profile_id/digest 仍只由后端生成。extend 在 V1 前端、应用服务和 intake 三层拒绝。有效品牌身份变化、该项目贡献的 active current 胶囊转 pending_revalidation、revalidation_required event 和仓库 revision 位于同一事务，事务提交后才排队新 refresh。pending 或携带当前 version revalidation_required 证据的 disabled 胶囊不能通过手工状态切换恢复旧 current。
- review UI 只发送每种决定允许的 identity/target 字段，不发送 project、source path、source hash 或 redaction 绑定字段。waiting_user/model/validation 的 process_candidate 创建新 refresh run，旧 review 不回写；发布决定继续使用阶段 3 的事务内 CAS 和不可变版本路径。
- 原前端只新增一个 Capsule Warehouse popover，使用六个原生 details 区域承载项目/品牌、模型、风琴复核、能力分组、备份/旧仓和任务。管理操作前后旧生成胶囊、已选胶囊和 notify_generate 保持不变。

### H.3 旧 JSON 重新清洗

- 旧 `capsules.json` 和旧 source registry 只做稳定只读读取；整体坏 JSON 形成 failed legacy run 且零 alias，单条损坏只形成安全 `item_<index>` rejected。非旧生产器格式 ID 不持久化，电话号码和客户 ID 探针没有进入 SQLite。
- 没有唯一 ready 项目绑定的条目只形成 pending，不调用 refresh、Ollama 或 worker；有绑定时每个项目只复用一次当前 `_refresh_project → intake → Stage 3` 主线。旧 metadata、active/verified/passed 状态和代码摘要都不能直接形成 V1 正式版本。
- 人工映射只接收 cleaned_successor、merged、variant，目标必须是 active current、capsule/version 一致且具有同一重新清洗项目的 project source。历史、disabled、无关项目和直接伪造目标均失败关闭。
- 管理状态按 SQLite rowid 倒序只展示每个 legacy ID 的最新 alias。服务端针对每条 pending alias 计算 same-project `eligible_targets`；前端不从全仓推断，合法目标可实际 linked，无来源或无关目标不会显示。返回数据不含旧条目、旧文件 hash、来源 hash、来源路径或原始内容。
- legacy alias 和 legacy_json/human_equivalent source 在最终短事务中只追加；取消发生在事务前时不写半批 alias。旧文件前后 SHA-256 不变，新 SQLite 生成仍为关闭。

### H.4 最终验证

本地 Python 3.14.5、pytest 9.1.1 全量：

```text
548 passed, 79 subtests passed
```

阶段 4、App service、桥接、前端静态和发布面聚焦：

```text
39 passed, 3 subtests passed
```

使用已经按官方 SHASUMS256 校验的 Node v24.18.0（tarball SHA-256 `e1a97e14c99c803e96c7339403282ea05a499c32f8d83defe9ef5ec66f979ed1`）和独立 Python 3.11.15 环境，逐条执行 `.github/workflows/ci.yml`：

- `npm ci` 成功，7 个 package，0 vulnerabilities；npm 11 对 esbuild postinstall 给出 allowScripts 提示但命令退出 0，后续 esbuild/测试均正常。
- pip 和 `requirements-dev.txt` 安装成功。
- Python 3.11 全量为 548 passed、79 subtests passed。
- public Reweave demo、规定 artifact 检查、Stage4 estimate demo、Stage4 data demo 和 Node 24 `node --check reweave_frontend/app.js` 全部通过；两个 demo 均报告 source_project_write=false。
- Python 编译、阶段 4 Ruff 限定检查、`git diff --check` 和阶段 1–3 摘要复算通过。

独立 `.venv-reweave` 使用 Python 3.14.5、PySide6 6.11.1 完成真实 QWebEngine 阶段 4 管理验收：

- Capsule Warehouse 可从 welcome 页面打开，六个 details 区域存在。
- Source Root 发现、项目确认和 refresh 经真实 QWebChannel 完成，来源项目写入为 false；测试静态项目产生三个 review item，Stage 3 结果均为 rejected，因此本记录不把它表述为正式胶囊发布成功。
- 品牌 replace JSON 可见；非法 JSON 在前端失败关闭、焦点回到 textarea，confirm_projects 调用数为 0。
- pending legacy alias 只显示服务端返回的 same-project 合法目标；无关 active/current 不显示，无 eligible target 时没有映射控件。合法点击只发送 legacy_capsule_id、relationship、capsule_id、version_id 四字段并实际形成 linked=1。
- 管理操作前后旧 generation capsule count 不变、used IDs 为空、notify_generate 调用数为 0。

以上是 `real_qwebengine_management_flow`，不是 synthetic_declared_interaction；但它也不是阶段 5 生成产品的真实浏览器效果或阶段 6 的“绑定→发布→生成→产品交互”完整用户验收。未 push 的工作树没有触发 GitHub 托管 Ubuntu/Windows runner，本机 macOS 等价执行不冒充远端双平台 CI。

### H.5 阶段判断

- 阶段 1：`PASS`，冻结摘要不变。
- 阶段 2：`PASS`，冻结摘要不变。
- 阶段 3：`PASS`，冻结摘要不变。
- 阶段 4：`PASS`，限入库、复核、仓库管理、备份恢复和旧仓重新清洗；限定范围无新增可复现 P0/P1。
- 整体迁移：`PARTIAL`，因为 SQLite 正式版本尚未进入唯一生成，完整桌面产品流程尚未验收。
- 阶段 5 实施进入判断：`READY`。可以迁移 `module_native` 到 SQLite 应用服务提供的唯一内存对象并做单次生成切换；在至少一个 eligible active current version 完成真实“发布→生成→manifest/usage→产品交互”证明前，阶段 5 不得宣称激活验收通过。
- P0：无。
- P1：无。
- P2：GitHub 托管 Ubuntu/Windows runner 尚未运行；npm 11 的 esbuild allowScripts 提示应在依赖策略专门变更中处理，不在阶段 4 临时扩大 package policy。

阶段 4 文件当前保持未提交，不在本附录中创建 checkpoint 或 push。后续只在用户确认进入阶段 5 后修改组合器和生成读取，不再继续无边界扩展阶段 4 审计。

## 附录 I：阶段 5 唯一生成切换收口记录

完成日期：2026-07-15。

本附录取代附录 H 中“SQLite 生成尚未激活”的当前状态判断，但不改写附录 A–H 形成时的历史事实。阶段 5 只完成正式版本到本地静态产品的单次生成切换；阶段 6 从真实来源项目发现、清洗、人工决定、发布到产品交互的完整可见桌面流程仍是独立验收门。

### I.1 唯一入口和选择边界

- 桌面前端只提交 `task`、正式 `capsule_ids` 和固定 `selection_mode=manual`；不提交来源路径、版本 ID、模型、旧 origin、Stage4 数量或 fallback 选项。桌面 QWebChannel 和公开 CLI 都只调用同一个 `ReweaveAppService.generate_product()`，并用现有串行任务的 `run_id` 查询结果。
- 前端没有自动匹配分支。未选择正式胶囊时，生成按钮只显示“请先选择至少一个可生成的正式胶囊”并停止，不向桥发送空 `capsule_ids`；一旦发送，请求中的 `selection_mode` 是字面固定的 `manual`。服务端独立再次要求一至三个非空、互不重复的正式 capsule ID。
- 服务只接受一至三个正式 capsule ID。每个 ID 必须在 SQLite 中同时满足 `active`、`current_version_id` 命中、当前提取/脱敏/canonical/security/supervision/validation 版本证据完整且 `_eligible_exact=true`。历史 version ID、pending revalidation、disabled、证据过期和 canonical 重建不一致均失败关闭。
- 所选原子角色必须共享一个 `capability_key`，同一种 `capability_kind` 最多一个，并至少包含 presentation 或 interaction。V1 不做任务文本自动语义选择，也不恢复旧 JSON、Stage4 behavior module 或模型生成分流。
- `get_initial_state()` 的生成胶囊只来自上述正式查询，明确返回 `generationActive=true`、`generationFromSqlite=true`、`canGenerateProduct=true`、`canGeneratePreview=false`。旧 `generate_preview()` 固定返回 `legacy_generation_inactive`；`run_public_stage4_demo.py` 固定返回 `legacy_stage4_demo_inactive` 并以非零状态退出。

### I.2 module_native 内存组合

- `compose_capsule_product()` 是阶段 5 的唯一正式组合入口。它只接收第 23.1 节定义的普通内存对象，不打开 SQLite、不读取来源项目、旧仓或 `capsule_path`，也不写最终产品目录。旧 `compose_module_native_preview()` 代码仅保留为历史实现，不在正式桌面、CLI 或服务调用图中。
- 正式 AppService 构造与 `get_initial_state()` 不创建旧 engine，也不导入旧 JSON warehouse、preview/export/promote、旧 engine 或旧 composer 依赖；发布面审计把这一点作为显式门禁。仍保留的历史支持函数只在用户明确调用历史动作时按需导入，不能从正式生成入口到达。
- 组合器重新规范化 data contract、activation、runtime allowlist、`dom_scope`、`usage_scope`、模块路径和资产。presentation/interaction 共用同一已清洗 HTML 根；无法证明单能力、单角色、唯一事件或确定契约连接时拒绝。
- 每个本地 ES module 闭包使用仓库锁定的 esbuild 生成无 external、无 source map、无运行依赖的 IIFE。候选模块和 bundle 都运行固定 TypeScript AST 安全分析，最终 `app.js` 再执行 `node --check`。固定可信 wiring adapter 只连接声明 event、compute 和 render。
- 输出固定为根目录 `index.html`、`styles.css`、`app.js` 及登记图片。HTML 只精确连接 `./styles.css` 和 `./app.js`，使用严格 CSP；CSS 的 `__CAPSULE_ROOT__` 替换为产品唯一根，`__CAPSULE_ID__` 替换为产品唯一 ID 前缀。资产按内容摘要命名并保存来源 version 证据。

### I.3 产品提交、manifest 和恢复

- 应用服务在 `state_dir()/products` 同目录建立 0700 临时包，逐文件使用受限 POSIX 相对路径写入，执行静态检查和独立真实 QWebEngine 启动检查，再生成 provenance、quality receipt 和 runtime receipt。
- manifest 使用以下唯一字节编码：UTF-8、JSON key 排序、紧凑分隔符、禁止非有限数字，并在末尾添加一个 LF。`manifest_digest` 是这组精确字节的 SHA-256。manifest 记录产品任务、产品 usage scope、精确 capsule/version/key/kind/scope/contributions、确定 connections 和除 manifest 自身外的完整文件哈希清单。
- 提升前再次检查所有选择仍是 eligible active-current；临时目录完整 fsync 后以 `os.replace` 原子提升。随后在 `BEGIN IMMEDIATE` 中第三次检查当前资格，并把 manifest 的完整 usage 集合只追加到 `product_capsule_usage`。任何确定的零 usage 失败会删除刚提升目录；若提交结果无法确定，保留孤儿产品供启动诊断，绝不猜测为零。
- 已登记产品只有在 canonical manifest、完整文件集合、文件哈希以及 capsule/version/key/scope/contribution/`generated_at`/manifest digest 的整集 usage 全部精确一致时才进入历史和“打开产品”。篡改、额外文件、符号链接、部分 usage 和混合 digest 都不能被显示为 registered。
- 崩溃发生在产品提升后、usage 提交前时，管理状态只显示受控 `product_id` 和 `usage_registration_incomplete`。补登记操作受同一 operation lock 串行化，重新查询当前正式对象，并用 manifest 中相同的 task、product ID、generated_at 和当前正式胶囊重新调用唯一 composer。只有 composer version、完整 connections（包括 output/input）、capsule contributions、产品 scope、确定性 composer 输出、provenance 和精确文件集合全部相同才允许补写 usage；随后再完整重读。历史版本缺失、身份或 scope 变化、连接改写、额外文件或确定性输出改写均拒绝。

### I.4 真实验收口径

阶段 5 保留两个不同标签，不能互相替代：

- 产品提交内的固定 worker 证明最终包被独立、off-the-record 的真实 QWebEngine 加载，所有请求都在登记包内，结果为 `real_qwebengine_runtime`。前端把它显示为“真实 QWebEngine 已完成产品启动；完整交互仍需验收”，并返回 `previewAcceptance.verdict=needs_review`、`reason=real_qwebengine_product_bootstrap`。
- 本次本地收口另用独立 QWebEngine 打开同一个已登记正式产品，实际把 quantity 改为 4 并点击 calculate。页面得到 total=8、`emission_count=1`、runtime status=passed、阻断请求 0、console message 0，profile 为 off-the-record。这是最终产品的真实浏览器交互探针，不是 synthetic_declared_interaction。

这项产品交互证明不包含阶段 6 的完整用户旅程：尚未在同一个可见桌面会话中从真实旧项目执行 Source Root 发现、候选清洗、Ollama 监督、人工发布、生成和交互。因此本文不把阶段 5 探针表述为阶段 6 已完成。

### I.5 验证结果

在仓库重新执行 `npm ci`：7 个 package，0 vulnerabilities。随后验证冻结工作树：

- Python 3.14.5、pytest 9.1.1 全量：`526 passed, 83 subtests passed`。
- 独立 Python 3.11.15 + Node v24.18.0 全量：`526 passed, 83 subtests passed`。
- 阶段 5 生成、发布面、公开 CLI 和桌面桥聚焦：`21 passed, 4 subtests passed`。
- Node 22 与 Node 24 均通过前端、提取/安全分析和计算验证脚本语法检查；Python compileall 与 `git diff --check` 通过。
- 真实正式产品记录为 `registered`，manifest digest 与精确字节一致，六条 contribution usage 全部绑定三个正式 version，`source_project_write=false`。
- `.venv-reweave` 使用 Python 3.14.5、PySide6 6.11.1 完成真实 QWebEngine 启动与上述真实产品点击交互。
- 发布面审计为 `passed`：25 个正式 included、39 个 historical excluded、0 个 unknown；八项门禁全部通过，其中包括正式启动不急加载历史依赖。

未 push 的工作树没有触发 GitHub 托管 Ubuntu/Windows runner。本机对 `.github/workflows/ci.yml` 的 Python 3.11、Node 24 命令链是等价复验，不冒充远端双平台 CI 已通过。

### I.6 阶段判断

- 阶段 1–3：`PASS`，冻结实现未修改。
- 阶段 4：`PASS`；其 App、桌面桥和原前端在阶段 5 发生了已批准的生成激活增量，不改变入库契约。
- 阶段 5：`PASS`。唯一 SQLite 正式读取、唯一内存组合器、原子产品提交、精确 manifest/usage、恢复补登记、桌面与 CLI 单入口和真实产品交互均已闭合；限定范围没有剩余可复现 P0/P1。
- 整体迁移：`PARTIAL`，仅因为阶段 6 完整可见桌面端到端验收及托管 CI 尚未执行。
- P0：无。
- P1：无。
- P2：GitHub 托管 Ubuntu/Windows runner 待获准 push 后执行；阶段 6 应使用一个真实旧项目完成“绑定→刷新→监督/复核→发布→生成→真实交互”，并再次证明来源项目零写入和恢复后的历史版本提示。

本阶段未创建 commit、未 push，也没有引入第二仓库、第二 composer、模板、fallback、preview/export/promote 系统或来源项目写入。

## 附录 J：阶段 4 安全决定与恢复边界最终修复记录

完成日期：2026-07-15。

本附录取代附录 H、I 中关于阶段 4 无剩余 P0/P1 的旧判断，但不改写当时的历史测试事实。本轮只修复已经稳定复现的决定授权、品牌身份、恢复和旧仓项目关联问题；阶段 5 架构与生成契约没有重做。

### J.1 已闭合问题

- `decide_review_item` 不再信任前端提交的决定枚举。应用服务从当前 review 脱敏证据计算 allowed_decisions，intake 在 `BEGIN IMMEDIATE` 写事务内再次计算；品牌确认不能伪装成图片确认，越权决定以 `review_decision_not_allowed` 失败且不写字段。
- brand 决定除 project/path/source hash/redaction version 外，还绑定候选时的有效 brand_profile_id 和 digest。profile 身份或内容变化后旧 retain/remove 决定均不复用，新 run 回到 waiting_user；送往 Ollama 的内容仍只有脱敏结构。
- V1 前端只提供 inherit/clear/replace；应用服务和 intake setter 拒绝 extend。旧库已经保存的 extend 在 intake 和任何 `publish_review` 分支前失败关闭，不能利用历史 duplicate/merge 证据发布；用户可改选受支持模式恢复，既有 active 贡献保守转为 pending_revalidation。
- restore_pending 在等待 operation lock 前检查，获得锁后再次检查。恢复开始后同步管理调用立即返回 restore_in_progress；`get_initial_state` 返回结构化恢复状态并关闭生成可用性，不阻塞 Qt 主线程或泄漏 RuntimeError。
- 备份列出、候选检查和 restore 提交不再依赖活动库先初始化。活动库损坏时仍可看到并验证正常备份；差异数量返回 unknown。替换前保存带 SHA-256 的私有 raw 字节副本，替换后失败可精确恢复原字节，正常库仍使用 SQLite backup API。
- 旧 registry 来源与 ready 项目按 `source_root.current_path / project_relpath` 的规范化有效路径唯一匹配。集合中的嵌套子项目可以正确关联，pending alias 的 eligible_targets 继续只返回同项目 active-current 目标。
- 前端移除了 extend 选项和文案；历史异常 mode 在编辑器中回落为 inherit，服务端仍独立验证，不能靠隐藏按钮形成安全边界。

### J.2 最终验证

- 本轮三个新增/增强的 extend 失败关闭节点：`3 passed`。
- Python 3.14.5、pytest 9.1.1 全量：`537 passed, 83 subtests passed`。
- 独立 Python 3.11.15、pytest 9.1.1 全量：`537 passed, 83 subtests passed`。
- 按当前 `.github/workflows/ci.yml` 在本机等价执行：Node v24.18.0 下 `npm ci` 成功（8 packages、0 vulnerabilities），独立 Python 3.11 环境安装 `requirements-dev.txt` 后全量通过，public demo `--help` 和 Node 24 前端语法检查通过。
- Python 编译、Node 22/24 语法检查、`git diff --check` 和一次限定最终 diff 审阅通过。审阅中发现的旧 extend 读取遗漏已修复并复核为 solved；修复后限定范围没有剩余可复现 P0/P1。
- 未 push，因此以上是 macOS 本机对正式命令链的等价执行，不冒充 GitHub 托管 Ubuntu/Windows runner 已通过。

### J.3 阶段判断

- 阶段 1：`PASS`；损坏活动库的备份恢复闭环已补齐。
- 阶段 2：`PASS`；品牌决定绑定和旧 extend 读取失败关闭已补齐。
- 阶段 3：`PASS`；持久化旧 review 在所有发布分支前重新检查受支持品牌模式。
- 阶段 4：`PASS`；本轮七项原始复现及最终 extend 遗漏均已闭合。
- 阶段 5：`PASS`；本轮没有改变单仓、单组合器、正式生成或 manifest/usage 架构，全量回归通过。
- 整体迁移：`PARTIAL`，只因阶段 6 完整可见桌面端到端用户旅程和 GitHub 托管 Ubuntu/Windows CI 尚未完成。
- P0：无。P1：无。P2：托管双平台 CI 与阶段 6 完整用户旅程待后续授权执行。

本轮未创建 commit、未 push；本附录完成后停止继续扩张阶段 1–5 的独立审计。

## 附录 K：阶段 5 确定性、运行时契约与孤儿恢复最终修复记录

完成日期：2026-07-15。

本附录取代附录 I、J 中关于阶段 5 无剩余 P0/P1 的旧判断，但不改写当时的历史测试事实。本轮只闭合四个已稳定复现的问题：esbuild 临时路径泄漏、胶囊输入顺序、产品运行时 `data_contract.v1` 执行和孤儿产品验收回执重验；没有改变单仓、单组合器、正式版本内存输入、产品目录或 manifest/usage 架构。

### K.1 已闭合问题

- `compose_capsule_product()` 在任何 DOM、CSS、bundle、provenance 或 manifest 处理前，先按正式 `capability_key / role_key / variant_key / capability_kind / capsule_id / version_id` 固定排序。相同正式胶囊集合不再受调用方顺序影响，孤儿恢复使用当前仓库返回顺序也能得到相同组合结果。
- esbuild 仍只在随机私有临时目录中读写中间文件，但现在以稳定的 modules 根作为 `absWorkingDir`，并使用规范化相对 entry module。生成的 `app.js` 不包含 `reweave-formal-compose-*` 随机绝对路径；同一 task、product_id、generated_at 和正式胶囊集合连续组合得到逐字节相同的完整 composition。
- 固定可信 wiring adapter 内嵌与 Python `data_contract.v1` 对齐的封闭运行时校验，分别在 presentation input、interaction input、每个声明 emit、computation input 和 computation output 边界失败关闭。校验发生在 JSON clone 前；越界整数、错误类型、非有限数、循环引用、访问器、额外对象字段和不合法十进制不能先被 `JSON.stringify` 改写后放行。运行时仍不新增 schema 解释器依赖或第二执行路径。
- `retry_product_usage_registration()` 在任何确定性重组或 usage 写入前，重新执行当前静态产品检查和独立真实 QWebEngine 启动检查，并用生成时相同的 UTF-8、排序 key、两空格缩进、禁止非有限数和末尾 LF 编码逐字节核对 `quality_gate.json` 与 `runtime_validation.json`。文件名存在、manifest 自洽或攻击者同步更新文件哈希都不能替代可信重验；任一不一致返回 `product_validation_receipt_mismatch` 且不写 usage。
- 回归用例使用真实 `compose_capsule_product()` 和真实 QWeb worker 制造 usage 提交失败后的孤儿：未修改孤儿可重新验证、确定性重组并登记为 `registered`；篡改 runtime receipt 且同步更新 manifest 的第二个孤儿仍被拒绝。该用例不替换 composer 或验证器，仅模拟第一次 usage 数据库写失败及无法确认清理状态。

### K.2 最终验证

- 阶段 5 聚焦（含真实 composer、真实 QWeb 孤儿成功恢复与伪造回执拒绝）：Python 3.14.5 与独立 Python 3.11.15 均为 `10 passed, 7 subtests passed`。
- Python 3.14.5、pytest 9.1.1、Node v22.22.3 全量：`540 passed, 86 subtests passed`。
- 独立 Python 3.11.15、pytest 9.1.1、Node v24.18.0 全量：`540 passed, 86 subtests passed`。
- 按当前 `.github/workflows/ci.yml` 在本机等价执行：Node 24 下 `npm ci` 成功（added 7、audited 8、0 vulnerabilities），Python 3.11 全量通过，公开 demo `--help` 和 Node 24 前端语法检查通过。
- Python 编译、Node 22 前端语法检查和 `git diff --check` 通过。同一 composition 的正序与逆序输入逐字节相等；运行时探针分别拒绝字符串 total、运行时产生的非有限 total 和越界 quantity。
- `.venv-reweave` 中的 PySide6 完成真实 QWebEngine 孤儿恢复重验。本轮证明的是正式产品启动、回执可信性和恢复确定性，不把它表述为阶段 6 的完整可见交互旅程。
- 未 push，因此以上是 macOS 本机对正式命令链的等价执行，不冒充 GitHub 托管 Ubuntu/Windows runner 已通过。

### K.3 限定最终审阅与阶段判断

最终 diff 审阅只对照本附录列出的四项复现及其回归用例，不重新打开阶段 1–4，也不扩展新的独立对抗性审计。结果：随机路径不再进入输出，胶囊集合顺序已固定，五条数据端口边界执行正式契约，孤儿补登记同时要求可信回执重验和确定性重组；限定范围没有剩余可复现 P0/P1。

- 阶段 1–4：`PASS`；本轮未改变其架构和阶段门。
- 阶段 5：`PASS`；上述 2 个 P0、2 个 P1 已闭合。
- 阶段 6 进入判断：`READY`，但尚未完成。下一阶段仍必须在可见桌面流程中用真实来源项目完成“绑定→刷新→监督/复核→发布→生成→真实交互”，并证明来源项目零写入；本轮孤儿 QWeb 启动重验不能替代该验收。
- P0：无。P1：无。P2：GitHub 托管 Ubuntu/Windows CI 与阶段 6 完整桌面用户旅程待后续执行。

本轮未创建 commit、未 push；阶段 5 到此停止继续扩张独立审计。

## 附录 L：阶段 1–5 最终限定复核与阶段 6 桌面验收记录

完成日期：2026-07-15。

本附录取代附录 K 中“阶段 6 尚未完成”的当前状态判断，但不改写附录 A–K 形成时的历史事实。本轮没有重新设计架构，也没有恢复第二仓库、第二 composer、模板、fallback、preview/export/promote 或来源写入；阶段 1–5 的审阅在固定范围内结束，阶段 6 只验证已经封板的 V1 支持面。

### L.1 阶段 1–5 最终限定复核

- 阶段 1–2 聚焦在 schema 指纹、canonicalization、恢复、快照字节、原子边界、脱敏决定、品牌绑定和 data_contract.v1。Python 3.14 与独立 Python 3.11 均为 `70 passed, 40 subtests passed`；提取脚本语法和 Python 编译通过，未发现新的可复现 P0/P1。
- 阶段 3–4 聚焦在 DOM/Event provenance、三类子进程、资产闭包、发布 CAS、服务端决定授权、恢复期拒绝、品牌与旧仓嵌套项目。结果为 `61 passed, 29 subtests passed`；安全脚本、前端脚本和 Python 编译通过，未发现新的可复现 P0/P1。
- 阶段 5 聚焦在确定性组合、所有 data_contract.v1 端口、真实 QWebEngine 孤儿恢复和回执重验。结果为 `10 passed, 7 subtests passed`，真实 QWeb 用例未跳过；未发现新的可复现 P0/P1。
- 最后一次跨阶段限定 diff 审阅覆盖 Ollama 提示修复、阶段 4 管理桥、阶段 5 生成和发布面，结果为 `44 passed, 10 subtests passed`。阶段 1–5 判定保持 `PASS`，到此停止继续扩张独立审计。

### L.2 真实 Ollama 暴露的问题与最小修复

首次真实调用 `qwen2.5-coder:7b` 时，原提示只写“matching capsule_supervision.v1”，模型返回了不完整对象，严格监督 schema 正确地拒绝了它。这不是放宽校验的理由。

最小修复只在既有 Ollama prompt 中加入完整的 `capsule_supervision.v1` JSON 形状示例，并要求 verdict 使用既有枚举、capability_kind 保持不变。示例不包含源码、来源路径、原始 fixture、图片字节或敏感原文；实际 summary 仍是脱敏结构。loopback、显式选模、digest 复核、严格返回校验、只保存结构化结论及响应 SHA-256 的边界均未改变。因此 `supervision_rules.v1` 和持久化 schema 不升级。

新增回归断言验证提示包含 schema_version、当前 capability_kind 和 duplicate_suggestions。假服务聚焦用例通过；真实选择 `qwen2.5-coder:1.5b`（digest `d7372fd828518a4d38b1eb196c673c31a85f2ed302b3d1e406c4c2d1b64a0668`）后，三个原子候选均返回符合严格 schema 的监督结果。没有设置默认模型，也不把本轮结果扩大为所有本地模型均在固定超时内可用。

### L.3 受支持范围的真实桌面闭环

验收使用独立 `.venv-reweave` 的 Python 3.14.5、PySide6 6.11.1、系统 Node 22 和 loopback Ollama。来源是独立临时目录中的受控、单入口、无需构建的静态 ES module 项目，包含共享 `quote_calculation` 能力的 presentation、interaction、computation 三个可证明原子角色。它是对封板 V1 契约的正向端到端项目，不冒充现有 classic-script 旧项目。

自动验收创建并显示原 `create_reweave_window()` 桌面窗口，通过原前端按钮、QWebChannel 和唯一 `ReweaveAppService` 完成：

1. 打开 Capsule Warehouse，并通过 Source Root 按钮把受控目录交给现有文件夹选择桥。
2. 在原项目确认界面选择 `brand_mode=clear`，刷新项目。
3. 使用前端显式选择上述 Ollama 模型；没有前端硬编码或默认模型。
4. 得到三个 `review_required` 候选。computation 的验证范围为 `isolated_node_vm_computation`，interaction 为 `real_qwebengine_interaction`，presentation 为 `real_qwebengine_render`。
5. 在原风琴复核界面把三个候选发布为同一 `capability_key=quote_calculation`，role 分别为 `quote_summary`、`quote_input`、`total_price`，三个正式胶囊均为 active current。
6. 重新加载原前端，从正式 SQLite 查询看到三个胶囊，逐个加入任务并点击生成。
7. 最终产品状态为 `registered`，静态质量为 passed，提交内真实启动回执为 `real_qwebengine_runtime`。
8. 再用独立、off-the-record 的真实 QWebEngine 打开同一个已登记产品，把 quantity 设为 4、unit_price 设为 5，并在页面内触发真实 calculate click。页面显示 total=`20`、emission_count=`1`、runtime status=`passed`，阻断请求为 0。

第 8 步是 `real_qwebengine_product_interaction` 自动交互证据，不是 `synthetic_declared_interaction`；它也不声称做了人工视觉像素验收。产品内部的 `__reweave_result.acceptance_scope` 仍按正式协议标为启动契约 `real_qwebengine_product_bootstrap`，外部验收记录额外证明了实际点击后的业务结果，两个口径没有互相冒充。

本次登记产品为 `product_a57cc3e1240e44389abc07cc6587b7ca`，manifest digest 为 `ad9f7d097d4b5d6fba1f7a456a45b215d22a5f062f1aac5b13a3c08b5196b140`。manifest 精确绑定三个 version：

```text
ver_5bb98553a3194252925f08a66d38f4d3
ver_c14d17793ad24f53b9bdd6f13ddaf35f
ver_d908b55a48164b629c423ebc81b67729
```

SQLite 中六条 contribution usage 的 version 集合与 manifest 完全相同，全部使用同一个 manifest digest。来源目录的路径、mode、mtime_ns、size 和内容 SHA-256 组成的树摘要在验收前后均为 `c86672678ad4cb50b077b8145cce786245c0cd40e2a3bac35e4c1974eb9f4dd8`；`source_project_write=false` 不是由测试数量代替，而由这组前后证据和产品 provenance 同时证明。

### L.4 代表性旧项目范围检查

为避免把专门满足契约的正向项目冒充“所有旧项目”，本轮另外只读绑定仓库现有的 `examples/source_boxes/customer-quote-widget`。它能被发现为单入口静态项目，但其入口使用 classic `<script src="quote.js">` 和 document 全局执行；项目确认按 V1 固定返回 `classic_script_unsupported_v1`，不会进入 ready，不调用候选监督或验证，不产生 review item 或正式版本，来源摘要前后相同。

这个结果符合第 9 节“本地 ES module 闭包、无需构建”的封板边界，不是阶段 1–5 回归；但它证明阶段 6 的正向成功不能被描述为“仓库现有 classic-script 旧项目已经完成清洗入库”。如果产品要求这些既有样例成为 V1 正向输入，需要先由用户明确扩大产品范围，再回到设计契约定义确定性的 classic-script 边界和迁移规则；不得在阶段 6 用隐式 wrapper、模型改写、模板或 fallback 绕过当前门禁。

### L.5 最终测试与阶段判断

- Python 3.14.5、pytest 9.1.1 全量：`540 passed, 86 subtests passed`，0 failed；Python compileall 和 `git diff --check` 通过。
- 独立 Python 3.11.15、pytest 9.1.1、Node v24.18.0、npm 11.16.0 的本机 CI 等价链：`npm ci` 为 7 packages、0 vulnerabilities；全量 `540 passed, 86 subtests passed`；正式 CLI/产品产物聚焦 `6 passed`；public demo `--help`、前端 `node --check` 和旧 Stage4 demo inactive 负向断言通过。`package-lock.json` 前后 SHA-256 均为 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`。
- 本轮真实桌面闭环：`passed`；主窗口可见，原前端和真实 QWebChannel 在环，真实 Ollama、Node 子进程与 QWebEngine 均未替换。
- 来源零写入、正式 active-current 发布、manifest/usage 精确版本、静态质量、真实 QWeb 启动和真实产品点击均通过。
- 未 push，因此没有把本机结果表述为 GitHub 托管 Ubuntu/Windows runner 已通过。

阶段结论：

- 阶段 1–5：`PASS`；限定最终审阅无新增可复现 P0/P1，审计到此停止。
- 阶段 6：封板 V1 支持面内的自动真实桌面闭环为 `PASS`；若验收词“真实旧项目”要求覆盖仓库现有 classic-script 项目，则产品整体仍为 `PARTIAL`，不能用受控 ES module 正向项目替代该范围决定。
- P0：无。
- P1：无。
- P2：GitHub 托管 Ubuntu/Windows CI 尚未执行；是否把 classic-script 旧项目纳入 V1 需要用户明确拍板。前者是发布证据缺口，后者是产品范围决定，不在本轮擅自扩大。

本轮未创建 commit、未 push。阶段 6 证据形成后不再继续无边界重开阶段 1–5；下一步只能是获得范围决定、运行获准的托管 CI，或进入用户明确批准的后续产品工作。

## 附录 M：普通 ESM 提取、同会话状态与可复现阶段 6 最终收口

完成日期：2026-07-15。

本附录取代附录 L 的当前阶段状态和验证数字，但不改写其形成时的历史事实。本轮只闭合一个普通 ESM 提取缺口、两个管理状态缺口和阶段 6 证据不可复现问题；没有增加第二仓库、第二 composer、classic-script wrapper、模板、fallback 或新测试框架。

### M.1 已闭合问题

- `extraction_contract.v2` 保留 v1 的固定 `render` / `mount` / `compute` 入口，并对普通 ESM 入口模块的顶层具名函数执行同一组形参、原子符号闭包、DOM/Event、数据契约和输出证明。只有唯一原子角色全部通过时，才在候选模块副本末尾追加稳定的正式入口别名；不改来源字节，不使用 tree shaking，不允许模型决定边界。多角色歧义仍以 `non_atomic_role_closure_v1` 失败关闭，无法证明则仍为 `missing_supported_entrypoint_v1` 或对应固定拒绝码。
- 提取规则版本升级为 v2 后，应用服务在正式管理边界首次进入时检查 active-current 版本的六类规则证据。旧 v1 正式版本会在单一 SQLite 事务内转为 `pending_revalidation`，并追加不可变 `revalidation_required / rule_version_changed` 状态事件；不会被新规则精确重复短路。
- 管理刷新现在应用完整 `get_initial_state()`，同一桌面页面在发布、停用、恢复或新产品状态变化后，重新同步正式胶囊、历史、生成包、预览路径和派生控件。恢复到发布前备份时，旧胶囊选择、产品树、预览、响应和使用数均在同一 document token 内清除，不需要重载前端。
- `list_review_items({})` 默认只返回存在服务端可执行决定的待办状态；已发布、已拒绝和已合并历史不再混入默认队列，仍可通过显式 `status` 查询。
- 前端在 Ollama 模型列表旁明确显示：“已安装”不等于已通过监督验证，冷启动或较大模型可能在固定超时后进入 `waiting_model`。固定超时和失败关闭没有被放宽。

### M.2 可复现阶段 6 验收

仓库现在版本化一个受控、无构建、单入口 ESM 报价夹具和一条真实桌面用例。夹具使用 `showQuote` / `wireQuote` / `calculateTotal` 这类普通业务名称，不预先导出 `render` / `mount` / `compute`。用例不替换前端、应用服务、SQLite、intake、Stage 3 worker、composer、QWebChannel 或 QWebEngine；只用 loopback 的确定性 Ollama 协议替身隔离模型下载、冷启动和非确定输出，因此它证明的是产品通道和严格协议，不是任意真实模型的性能兼容性。

单一用例在不重载页面的同一 document token 内完成：

1. 打开真实 `create_reweave_window()` 窗口，从原前端绑定受控来源、确认项目、选择监督模型并刷新。
2. 通过原复核界面发布 presentation / interaction / computation 三个原子角色，随后立即在主胶囊列表看到三个 active-current 胶囊，无页面重载。
3. 通过原任务界面选择三个胶囊并生成正式产品，核对 canonical manifest 字节、digest、version 集合与 SQLite usage contribution。
4. 在独立 off-the-record 真实 QWebEngine 中输入 quantity=4、unit_price=5 并真实点击，页面得到 total=20、emission_count=1、runtime passed。这是 `real_qwebengine_product_interaction`，不是 `synthetic_declared_interaction`，也不声称像素级人工视觉验收。
5. 比较来源树的路径、mode、mtime_ns、size 和 SHA-256，并与产品 provenance 同时证明 `source_project_write=false`。
6. 恢复到发布前备份，同一页面刷新后证明正式胶囊、生成包、预览和历史产品派生状态全部回到备份时点。

### M.3 最终验证数字

- Python 3.14.5、pytest 9.1.1、Node v22.22.3、PySide6 6.11.1 全量：`544 passed, 86 subtests passed in 101.01s`。阶段 6 真实桌面用例实际运行并通过，没有 skip；单独重跑为 `1 passed in 15.87s`。
- 独立 Python 3.11.15、pytest 9.1.1、Node v24.18.0 的本机正式 CI 等价链：`543 passed, 1 skipped, 86 subtests passed in 59.34s`。唯一 skip 是该 Python 3.11 环境未安装 PySide6 而跳过真实桌面用例；它不会被表述为桌面验收通过的第二份证据。
- Node 24 下 `npm ci` 成功（added 7、audited 8、0 vulnerabilities），public demo `--help`、前端、提取、安全和计算分析脚本语法检查通过。Python 编译和 `git diff --check` 通过。
- 本轮没有 push，因此上述 Python 3.11 / Node 24 是 macOS 本机对 `.github/workflows/ci.yml` 命令链的等价执行，不冒充 GitHub 托管 Ubuntu / Windows runner 已通过。

### M.4 阶段判断与剩余边界

- 阶段 1：`PASS`。本轮没有改变 schema、canonicalization、不可变约束或备份恢复架构；规则版本升级对旧正式版本的处理在同一 SQLite 边界内失败关闭。
- 阶段 2：`PASS`。`extraction_contract.v2` 已闭合普通 ESM 顶层具名函数的确定性角色发现，同时保留原子闭包、快照字节、敏感与品牌失败关闭。
- 阶段 3：`PASS`。候选别名仍经过完整安全门、Ollama 监督和独立 Node / Image / QWeb 验证，没有绕过过期规则。
- 阶段 4：`PASS`。发布、停用、备份恢复后的同页面正式状态和默认待办复核队列已闭合。
- 阶段 5：`PASS`。本轮没有改变唯一 `module_native` 内存组合、data_contract.v1 端口、确定性 manifest / usage 和孤儿产品恢复结论。
- 阶段 6：Static Web V1 已封板支持面内的可复现真实桌面闭环为 `PASS`。它明确覆盖普通具名 ESM 角色，但不包括 classic script、需构建框架源码或多页面自动推断。
- 限定最终 diff 审阅范围内：P0 无，P1 无。P2 仅余 GitHub 托管 Ubuntu / Windows runner 未实际运行、classic-script 是否扩大为 Static Web V1 产品范围尚需用户决定，以及本地 checkpoint 尚未创建。

本轮未创建 commit、未 push。阶段 1–6 在已封板 Static Web V1 支持面内适合建立本地 checkpoint；按用户约束，必须等待明确确认后才能执行。到此停止继续扩张阶段 1–6 独立审计。

## 附录 N：品牌范围重验证、单事件契约与交付面最终修复记录

完成日期：2026-07-16。

本附录取代附录 M 的当前验证数字，但不改写其形成时的历史事实。本轮仅修复最后一次限定复核确认的四项问题：品牌 `usage_scope` 变化无法替换待重验证身份、交互事件数量契约不一致、正式胶囊选择不可纠错且未在前端预检，以及桌面管理任务回执无界增长。没有新增仓库、组合器、状态机、运行入口、模板、fallback 或兼容路径。

### N.1 已闭合问题

- 品牌配置变化仍先把该项目贡献过的 active-current 胶囊转为 `pending_revalidation`，并记录绑定当前 version 的 `revalidation_required / brand_profile_changed` 事件。新候选只有同时满足“同一项目贡献当前 version、同一 capability kind、activation/input/output/error/runtime allowlist/dom scope 全部相同、usage scope 确实变化、目标仍是 comparison 中的 exact current version”时，才形成 `scope_revalidation_match`。
- `replace_current` 的普通路径继续要求相同 `usage_scope`。品牌范围变化是唯一允许同一身份改变 scope 的 V1 例外；发布事务在复核决定 CAS 之后重新读取 current version、状态、项目来源和状态事件。任一证据在事务前失效均以 `replace_current_target_expired` 失败关闭，不会创建新身份、停用无关胶囊或覆盖旧决定。成功时只追加不可变 version，并原子切换同一 capsule 的 current version。
- `data_contract.v1` 的 `event_outputs.v1` 在共享规范化入口要求恰好一个静态事件；零事件和多个事件统一以 `event_outputs_contract_invalid` 拒绝。Stage 2 提取、Stage 3 验证和唯一 composer 不再对事件数量作互相矛盾的解释。
- 原前端的正式胶囊 dock 在提交前检查：最多三个、同一 capability、kind 不重复，且生成时至少包含 presentation 或 interaction。每个已选 chip 提供键盘可聚焦且带 `aria-label` 的移除按钮；用户可以直接纠正选择。服务端仍是最终权威，前端检查不构成安全边界；纯旧胶囊选择行为未改变。
- 桌面管理任务继续保留所有非终态任务，但每次任务完成时在既有锁内只保留最近 100 条终态 UI 回执。V1 不新增任务持久化、事件平台或后台清理服务。
- 最终真实桌面复跑暴露了桌面壳与前端可能同时构造 QWebChannel 的回调竞态。两端现在共用一个页面级 connecting 标记，任一端已连接或正在连接时另一端只等待既有 bridge；没有增加第二桥接实现。连续两次真实桌面闭环未再出现 `execCallbacks` JavaScript 异常。

### N.2 最终验证

- 原四项阶段 2–5 聚焦回归：`111 passed, 54 subtests passed in 80.87s`；新增 QWebChannel 单连接静态回归所在文件为 `11 passed`。
- Python 3.14.5、pytest 9.1.1、Node v22.22.3、PySide6 6.11.1 冻结版全量：`549 passed, 88 subtests passed in 113.78s`。
- 独立 Python 3.11、pytest 9.1.1 冻结版全量：`548 passed, 1 skipped, 88 subtests passed in 97.75s`。唯一 skip 是该临时 Python 3.11 环境没有 PySide6，不能作为第二份桌面验收证据。
- QWebChannel 竞态修复后，`.venv-reweave` 真实桌面用例连续单独重跑两次，分别为 `1 passed in 15.24s`、`1 passed in 15.35s`。独立 off-the-record QWebEngine 中真实输入 quantity=4、unit_price=5 并点击后得到 total=20、emission_count=1、runtime passed；验收口径为 `real_qwebengine_product_interaction`，同时再次证明 `source_project_write=false`。它不是 `synthetic_declared_interaction`，也不冒充像素级人工视觉验收。
- 提取、安全、行为和前端 JavaScript 的 Node 22 语法检查、Python compileall 与 `git diff --check` 通过。
- 按当前 `.github/workflows/ci.yml` 在本机补跑：`npm ci` 成功（added 7、audited 8、0 vulnerabilities），Node v24.18.0 对前端、提取、安全和行为脚本的语法检查通过，独立 Python 3.11 的 public demo `--help` 通过；`package-lock.json` 前后 SHA-256 均为 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`。
- 本轮没有 push；Python 3.11 是本机独立环境复验，真实 QWeb 是 macOS 本机证据，均不冒充 GitHub 托管 Ubuntu / Windows runner 已执行。

### N.3 限定最终审阅与阶段判断

最终 diff 审阅只覆盖本附录四项复现、对应回归、验收中直接出现的 QWebChannel 竞态和既有阶段门，不重新打开新的独立对抗性审计。结果：品牌范围变化不能绕过 exact-current 与事务内证据检查，事件数量在首个共享契约入口失败关闭，前端选择可以纠错且与服务端资格一致，终态任务回执有固定上限，桌面桥只建立一个 channel；限定范围无剩余可复现 P0/P1。

- 阶段 1：`PASS`；本轮未改变 SQLite schema、canonicalization、不可变约束或恢复语义。
- 阶段 2：`PASS`；单事件约束和品牌范围重验证来源绑定已闭合。
- 阶段 3：`PASS`；scope 变化仍必须经过完整监督、独立验证、人工决定和发布事务重检。
- 阶段 4：`PASS`；服务端决定资格、可纠错选择和有界任务回执已闭合。
- 阶段 5：`PASS`；唯一 `module_native`、正式内存对象、data contract 端口与 manifest/usage 结论保持不变。
- 阶段 6：封板 Static Web V1 支持面内的可复现真实桌面交互为 `PASS`。
- P0：无。P1：无。P2：GitHub 托管 Ubuntu / Windows CI 尚未实际运行；classic-script 是否扩大为 Static Web V1 产品范围仍是产品决定；本地 checkpoint 尚未创建。

本轮未创建 commit、未 push。冻结版本在已封板 Static Web V1 支持面内适合建立本地 checkpoint；必须等待用户明确确认后执行，并到此停止阶段 1–6 的循环式独立审计。

## 附录 O：恢复后诊断与管理交付面最终收口

完成日期：2026-07-16。

本附录取代附录 N 的当前验证数字，但不改写其历史事实。本轮只复核外部报告列出的 1 个 P0、3 个 P1、2 个 P2：品牌 scope-changing 重审、单事件 interaction、正式选择纠错和服务端任务上限在当前快照已经闭合；实际仍成立的范围只有恢复后历史产品不可见、前端 run 回执无界和 capability 展示名不可编辑。修复没有增加仓库、组合器、状态机、产品反向导入或任务持久化。

### O.1 已闭合问题

- `get_initial_state()` 继续把 `registered` 产品作为唯一正常 history，把 `usage_registration_incomplete` 作为唯一补登记队列；另以只读 `historicalProducts` 暴露恢复后缺失版本产品的 product_id、固定错误状态、manifest digest 和最近恢复前备份路径。历史产品不进入正常 history、不进入补登记、不从产品目录反向导入版本，也没有代码加载动作。
- 原前端在备份/恢复区域以原生 `details` 显示上述结构化诊断。用户展开时能看到 `historical_version_unavailable_after_restore`、digest 和恢复前备份路径；正常预览、产品树、选择和 registered history 仍回到备份时点。
- 前端 `ingestionManagement.runs` 与服务端采用同一最小策略：保留全部 queued/running，只保留最近 100 条终态 UI 回执。没有数据库任务表、清理线程或新状态层。
- 唯一应用服务新增 `rename_capability_group`：只接受合法稳定 key 和去首尾空白后 1–200 字符的展示名，只更新 `capability_groups.display_name/updated_at` 并增加仓库 revision。capability key、capsule identity、current version 和历史版本均不变。桌面桥只转发该 JSON 方法；前端使用原生修改按钮和 prompt，不增加编辑状态管理器。
- 外部报告中的品牌重审 P0 已由附录 N 的 exact-current、同项目贡献、`brand_profile_changed` 事件、完整角色契约和事务内重检关闭；不要求另建发布入口。单事件、正式选择纠错和服务端终态回执上限的既有回归也继续通过。

### O.2 最终验证

- 新增边界聚焦：阶段 4 管理、桌面桥和前端静态/可执行回归为 `38 passed, 4 subtests passed`。
- 阶段 4–5 与发布面扩大聚焦：`62 passed, 14 subtests passed in 27.93s`。
- 真实桌面恢复闭环：`1 passed in 16.48s`。同一页面在恢复后清除正式胶囊、预览和 registered history，同时可见历史产品 ID、`historical_version_unavailable_after_restore`、manifest digest 和准确恢复前备份路径；独立 off-the-record QWebEngine 的真实产品点击仍得到 total=20、emission_count=1、runtime passed，`source_project_write=false`。
- Python 3.14.5、pytest 9.1.1、PySide6 6.11.1 冻结版全量：`553 passed, 92 subtests passed in 116.14s`。
- 独立 Python 3.11、pytest 9.1.1 冻结版全量：`552 passed, 1 skipped, 92 subtests passed in 99.84s`。唯一 skip 仍是该环境没有 PySide6 的真实桌面用例。
- `npm ci` 成功（added 7、audited 8、0 vulnerabilities）；Node v24.18.0 的前端、提取、安全和行为脚本语法检查、Python 3.11 public demo `--help`、Python compileall 与 `git diff --check` 通过。`package-lock.json` 前后 SHA-256 均为 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`。
- 本轮没有 push；以上 CI 命令是 macOS 本机等价执行，不冒充 GitHub 托管 Ubuntu/Windows runner。

### O.3 阶段判断

- 阶段 1：`PASS`；schema、canonicalization、不可变约束和原子恢复未改变。
- 阶段 2：`PASS`；单事件与既有提取、快照、敏感和品牌边界继续通过。
- 阶段 3：`PASS`；品牌 scope-changing 新版本路径已有完整证据和事务内重检。
- 阶段 4：`PASS`；恢复后历史诊断、前后端任务上限和展示名编辑已闭合。
- 阶段 5：`PASS`；唯一 composer、data contract、manifest/usage 和孤儿恢复未改变。
- 阶段 6：封板 Static Web V1 支持面内真实桌面闭环为 `PASS`；恢复后正常状态清除与历史错误诊断已同时验证。
- 限定复核范围：P0 无、P1 无；外部报告中的两个 P2 均已关闭。剩余产品级 P2 仍只有 GitHub 托管 Ubuntu/Windows CI 未实际运行、classic-script 是否扩大产品范围尚需决定，以及本地 checkpoint 尚未创建。

本轮未创建 commit、未 push。当前冻结版本适合建立本地 checkpoint；必须等待用户明确确认后执行，并停止继续循环式重开阶段 1–6 审计。

## 附录 P：Static Web V1 发布收口记录

完成日期：2026-07-16。

本附录取代附录 O 的当前发布状态，但不改写附录 A–O 形成时的历史事实。本轮只完成已批准的发布收口：精确 checkpoint、独立远端 CI 分支、托管双平台 CI、真实桌面截图与交互复跑、现有来源只读试点、公开支持矩阵和限定最终 diff 审阅。没有新增仓库、组合器、状态机、classic-script wrapper、框架转换器、模板或 fallback。

### P.1 checkpoint 与远端边界

- 阶段 1–6 初始实现 checkpoint 为 `f27b5dc6c17fcf82d18a43911b55f8e36b464b66`，提交说明为 `feat(reweave): complete static web capsule pipeline`。
- 首次托管 Windows 运行暴露两个跨平台实现缺口：受限 Node/esbuild 子进程环境遗漏 Windows 必需运行时变量；SQLite 和产品文件使用只读描述符执行 `fsync` 时返回 `EBADF`。`bdec38b8b92f9f56df737568cf36c69f8f05fd28` 只补入固定 Windows 运行时白名单、排除 `NODE_OPTIONS`/`NODE_PATH` 等注入变量，并改用可同步的读写描述符；没有扩大候选运行权限或业务架构。
- 远端只创建 `codex/reweave-static-web-v1`。远端 `main` 未改变，本地 `main` 只保留已确认的本地 checkpoint；没有 push `main`，本轮也没有创建 PR。

### P.2 GitHub 托管 CI

首次 run `29437609516` 对 `f27b5dc` 的 Ubuntu job 通过，Windows pytest 以 `65 failed, 495 passed, 11 skipped, 49 subtests passed` 失败。该失败没有被隐藏或改写为通过。

修复后 run [29438141570](https://github.com/chenjinnan82-stack/Reweave-lite/actions/runs/29438141570) 对 `bdec38b` 的结果：

| runner | pytest | 其余门 | 结论 |
|---|---|---|---|
| Ubuntu latest，Python 3.11，Node 24 | `545 passed, 10 skipped, 92 subtests passed in 64.76s` | `npm ci`、公开 CLI `--help`、前端 `node --check` 通过 | `PASS` |
| Windows latest，Python 3.11，Node 24 | `544 passed, 11 skipped, 92 subtests passed in 117.15s` | `npm ci`、公开 CLI `--help`、前端 `node --check` 通过 | `PASS` |

托管 CI 没有安装 `requirements-desktop.txt`，因此不能替代 macOS 的 PySide6/QWebEngine 桌面门。不同 runner 的 skip 数也不能被表述为桌面验收通过。

最终本地回归：Python 3.14.5 + PySide6 为 `555 passed, 92 subtests passed in 119.03s`；`uv` 临时 Python 3.11 环境为 `554 passed, 1 skipped, 92 subtests passed in 96.80s`，唯一 skip 是该临时环境不含 PySide6。`npm ci` 为 7 packages、0 vulnerabilities；Node 22 的前端、提取、安全、行为和计算脚本语法检查、Python compileall、公开 CLI `--help` 与 `git diff --check` 通过。`package-lock.json` SHA-256 保持 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`。

### P.3 真实桌面与视觉证据

本地使用 Python 3.14.5、PySide6 6.11.1 和原 `create_reweave_window()` 复跑阶段 6。临时截图 harness 只增加 `QWebEngineView.grab()` 取证，不替换前端、QWebChannel、应用服务、SQLite、intake、Stage 3 worker、composer 或 QWebEngine；仓库文件没有因 harness 被修改。

- 最终复跑：`1 passed in 26.14s`。
- 独立 off-the-record QWebEngine 中输入 quantity=`4`、unit_price=`5` 并真实点击，得到 total=`20`、`emission_count=1`、runtime status=`passed`，验收标签为 `real_qwebengine_product_interaction`。
- `source_project_write=false`，来源树前后摘要相同。
- 同一可见会话展示三个 active 原子角色；恢复后正常仓库和 history 清空，同时展示 `historical_version_unavailable_after_restore`、manifest digest 和恢复前备份路径。
- 截图模型辅助检查没有发现 P0/P1。最初发现超长恢复路径导致仓库弹窗横向滚动；最终 CSS 仅增加弹窗横向裁切和 `.warehouse-meta` 任意长字符串换行，复跑截图确认路径在卡片内换行且纵向滚动正常。

该证据不是 `synthetic_declared_interaction`，也不是人工像素级或审美签字。生成报价页保持来源 fixture 自带的朴素样式，不能被描述为完整视觉设计验收。

### P.4 现有来源只读试点

仓库盘点没有发现 3–5 个可独立计数的既有 ESM 正样本。唯一符合封板条件的来源是 `tests/fixtures/reweave_phase6_quote`；同一项目的三个原子角色不能冒充三个试点项目。

| 来源组 | 数量 | 入口资格与结果 | 模型/子进程/正式路径 | 来源写入 |
|---|---:|---|---|---|
| `tests/fixtures/reweave_phase6_quote` | 1 | 单入口、三个本地 `type=module`；intake 为 `3 candidates / 3 extracted / 0 rejected` | 阶段 6 另经 loopback 协议监督、Node/QWeb、人工发布和正式产品生成 | before/after 均为 `4b13f640c4964e041d34a9e3d18220e4fb71ea6e834936af560b04349c52cfff` |
| `examples/source_boxes` classic script | 6 | 每项发现一个入口；确认返回 `classic_script_unsupported_v1` | 不调用候选监督或验证，不正式发布 | 全部前后一致 |
| `examples/source_boxes` HTML-only | 3 | 可确认；每项 `1 candidate / 0 extracted / 1 rejected`，`missing_supported_entrypoint_v1` | 不调用正式发布 | 全部前后一致 |
| `examples/source_boxes` 无 HTML | 5 | 每项目录发现数为 0 | 不进入 intake | 全部前后一致 |

14 个公开 example 的互斥汇总为 `6 + 3 + 5`。产品自身 `reweave_frontend` 不计作试点来源，且确认时以 `inline_script_unsupported_v1` 失败关闭。达到 3–5 个真实正向项目仍需要用户提供或选择额外只读 ESM 项目；本轮没有制造变体、复制 fixture 或扩大 classic/框架边界来凑数。

### P.5 最终支持矩阵

| V1 支持 | V1 明确不支持 |
|---|---|
| 一个已确认 HTML 入口 | classic `<script src>`、内联脚本、多页面自动推断 |
| UI 来源可按唯一显式 `data-capsule-root`、唯一 `main`、唯一 `form` 的固定顺序选择一个原子根 | 多个显式根或最终无法唯一选择 UI 根 |
| `.js` / `.mjs` 本地原生 ESM、静态相对 import | CommonJS、TypeScript、JSX、React/Vue/Svelte 组件源码、动态 import、bare specifier |
| 无需安装来源依赖、无需构建即可形成的自包含静态闭包 | `node_modules`、必须构建的来源、未单独批准的 `dist` / `build` 输出 |
| 可独立证明和验证的 presentation / interaction / computation 原子角色 | 无法证明原子角色或本地资产闭包的代码、SVG、字体 |

Vite 按是否已形成无需构建的原生静态闭包判断，不按名称判断。普通应用入口中的顶层启动语句、全局事件注册和不能静态证明为单一 `render` / `mount` / `compute` 角色的 bootstrap 属于 V1 不支持的提取边界，并以 `module_top_level_statement_unsupported`、`module_top_level_side_effect` 等现有细分原因失败关闭；V1 不自动改写，不让模型决定代码边界。classic script、React/JSX/TypeScript、需构建框架和多页面推断同样留在 V1 外；除非用户另行批准新的产品范围和设计契约，否则不进入实现。

### P.6 发布判断与停止条件

- 阶段 1–6：封板 Static Web V1 支持面内为 `PASS`。
- GitHub 托管 Ubuntu/Windows CI：`PASS`。
- 本地真实桌面和真实产品点击：`PASS`；模型辅助截图检查完成，人工主观视觉签字未冒充完成。
- 限定最终范围：P0 无、P1 无；本轮发现的 Windows 跨平台缺口和长路径视觉 P2 已关闭。
- 剩余非代码证据项：若发布门强制要求 3–5 个独立真实正向来源，尚需 2–4 个用户提供或批准的只读 ESM 项目；若要求人工审美或像素级验收，仍需用户本人签字。这两项不改变阶段 1–6 的契约结论。

当前实现适合作为 Static Web V1 release candidate。阶段 1–6 循环式独立审计到此停止；后续只能处理明确的新产品范围、用户提供的外部试点，或正常发布流程。

### P.7 外部真实 ESM 试点补充

补充完成日期：2026-07-16。本节是 P.4 与 P.6 之后的新证据，详细记录见 [真实公开 ESM 试点报告](reports/REWEAVE_STATIC_WEB_V1_REAL_PROJECT_PILOTS.md)。

本轮固定并只读运行四个额外公开项目：`MasiaAntoine/snake-js@894e7dc`、`nwakauc/ES6-Awesome-books@582758d`、`titusdmoore/wordle@2d01427` 和 `daria4783/hw10.js@c3b879c`。四项都只有一个 HTML 入口并加载本地 ESM，资格检查均为 `ready`；intake 合计 `4 candidates / 0 extracted / 4 rejected`，固定拒绝原因为顶层启动语句、顶层副作用或 V1 不支持的 import。四个来源的整树摘要、Git 空状态和 Reweave intake 快照前后完全一致；没有调用模型或 Stage 3 运行 worker，没有写入 capability group、capsule 或 version。

因此，“运行 2–4 个额外真实项目并取得只读证据”已经完成，但“取得额外真实正向项目”仍未完成，不能把安全拒绝记为正向验收。当前真实项目接受度应标为 `PARTIAL`，而不是改写 P.6 的历史测试数字。

试点同时发现一个失败关闭的 P1：阶段 2 的唯一 `<main>` / `<form>` 静态根推断没有与阶段 3 的唯一显式 `data-capsule-root` 及 HTML 标签白名单闭合。该问题的最小修复和复验证据见 P.8；本节保留发现时事实，不改写为试点正向成功。

### P.8 根契约修复与限定复验

完成日期：2026-07-16。

- 阶段 2 和阶段 3 现在统一按“唯一显式 `data-capsule-root` → 唯一 `<main>` → 唯一 `<form>`”选择 UI 原子根；多个显式标记或最终无法得到唯一根时，presentation/interaction 以 `html_capsule_root_invalid` 失败关闭，computation 不受 UI 根门禁影响。
- 阶段 3 HTML 白名单加入 `<main>`，清洗只输出选中子树并删除来源根标记；没有新增 helper 模块、仓库、组合器、模板、fallback 或来源写入。
- 新增回归覆盖显式根、唯一 main、唯一 form、多显式根、歧义根、嵌套显式根、纯计算隔离、根外资产排除，以及从无标记唯一 main 进入真实 QWebEngine interaction。阶段 2/3 聚焦为 `74 passed, 53 subtests passed`；无标记唯一 main 的真实 QWebEngine 用例单独为 `1 passed`。
- Python 3.14.5、pytest 9.1.1、PySide6 6.11.1 全量为 `557 passed, 98 subtests passed`，没有 skip；Python 3.11.15、Node 24.18.0 的本机 CI 等价链为 `556 passed, 1 skipped, 98 subtests passed`，唯一 skip 是临时 Python 3.11 环境没有 PySide6。
- Node 24 下 `npm ci` 为 7 packages、0 vulnerabilities，`package-lock.json` SHA-256 保持 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`；公开 CLI `--help`、前端及四个分析/验证脚本语法、Python compileall 和 `git diff --check` 均通过。本轮没有 push，因此不把本机等价链冒充为该修复的 GitHub 托管双平台重跑。
- 同四个固定公开项目在全新隔离仓库中重跑后仍为 `4 candidates / 0 extracted / 4 rejected`；四个来源树、Git 状态和 intake 快照前后相同，正式表为零。新证据位于 `/private/tmp/reweave-real-pilots-rootfix.Nu5J6C/evidence.json`，SHA-256 为 `3806be82b15423935b3d1d6f01cbc806a57dd91fe62c90bef1309c756ee8e32f`。

限定结论：该根契约 P1 已关闭，当前已知 P0/P1 为零。阶段 1–6 在封板支持面内保持 `PASS`；额外真实正向项目仍为 0，因此外部真实项目接受度保持 `PARTIAL`。普通应用 bootstrap 已明确在 V1 外，不继续随机寻找项目或设计自动转换器。

## 附录 Q：V1 外部真实项目扩面与 Bootstrap 决策封板

完成日期：2026-07-16。本附录执行 P.8 之后批准的限定扩面计划，不修改正文架构或阶段 1–6 契约。

### Q.1 冻结边界与交付物

本轮只增加三个证据层交付物：

- 固定样本清单：`docs/reports/REWEAVE_STATIC_WEB_V1_PILOT_CORPUS.json`。
- 无网络只读运行器：`scripts/run_reweave_v1_real_project_pilots.py`。
- 回归测试：`tests/test_reweave_real_project_pilots.py`。

运行器使用现有 `ReweaveAppService` 和每项目独立的 `CapsuleWarehouseStore`，不建立新 repository、仓库或组合器；不克隆、安装、构建、改写来源，也不自动发布或代替人工决定。失败族只在报告层派生，不写 SQLite。原始错误码、项目级最早终止门、candidate 级原因、规则版本、来源前后摘要、intake 快照和正式表增量均保留为结构化证据。

最终固定 manifest 文件 SHA-256 为 `dfd55804fe51b86311041c4863176571072bc910996c6c795d1bb79d7a1a5ebe`，规范 JSON SHA-256 为 `672a37a8e6bdb87a2bd175896dcad01475f977250a508550b3072f12a5d4f788`；运行器 SHA-256 为 `0f5e46947da5e38881afa6e6abec101da8608b7fbb01c958f4ee71b9a9fcf1ac`。运行器在任何写入前拒绝与来源 workspace 重叠的状态目录、位于来源内的输出文件和符号链接 checkout 根；服务失败仍执行来源后置检查，intake 快照不一致直接失败；duplicate 不冒充模型调用，所有 primary/secondary 未知码都使分类门失败。

### Q.2 正向轨道结论

presentation、interaction、computation 各检查固定上限 20 个公开搜索结果，总计 60 项。没有项目同时满足 V1 正向资格，因此没有为了取得成功而替换样本、改写源码或把 fixture 计作外部项目。搜索证据 SHA-256 分别为：

- presentation：`9edb8b1ed5884be12657c850762190869f9971feaae7cf1a00bdfd8eb6da24c0`。
- interaction：`113816c2392ea3ea7c523a2821eba595fb45a22f72bf600357fe0895e49a97e7`。
- computation：`5925000c328967e081d6a60b470e4857b98ecf1d492407bc04e075a82e0086ad`。

固定预算耗尽后的正式结论为：`eligible_projects_found=0`、`validated_positive=0`、正式角色覆盖为空、真实外部产品业务断言未执行。外部真实正向覆盖保持 `PARTIAL` 并停止搜索；它不改变阶段 1–6 在既定支持面内的 `PASS`，也不能由仓库 fixture 或全量绿色测试替代。

### Q.3 八项目失败观察

固定八项目漏斗为：

```text
screened=8
→ ready=4
→ extracted_any=0
→ stage3_pass_any=0
→ active=0
→ product_asserted=0（证据值为 null）
```

项目级最早失败族为：`bootstrap_top_level_not_declarative_v1=3`、`module_graph_unsupported_v1=1`、`qualification_closure_boundary=2`、`qualification_entry_unsupported_v1=2`。所有错误码均成功分类，没有 `unclassified`。八个来源前后摘要与 Git 状态一致，四个 intake 快照一致，所有正式表增量为零；没有模型或 worker 调用。

最终结构化证据为 `/private/tmp/reweave-v1-pilot-evidence-final5.json`，SHA-256 为 `d5453ae35d8cb2eb811ee9b5fe70437799702d59ca647ca29f1817bb0d9c01b0`。每个项目与 candidate 都显式记录最远门禁及最早失败，`unclassified_raw_error_codes=[]`；仓库只保存本附录与试点报告中的结构化摘要和 SHA-256，不保存第三方源码、绝对来源路径、控制台原文、模型 prompt 或 response。

### Q.4 Bootstrap v3 决策

机会探针固定复用八项目，只读检查预批准的“一个静态相对 named/default import → 一个最终直接调用 → 独立叶子角色”形态。观察结果为：匹配项目 1（门槛 3）、叶子原样通过 extraction v2 为 0、正式角色种类 0（门槛 2）、Stage 3 和 worker 运行均为 0。

唯一外层形态匹配项的叶子仍以 `unsupported_string_construction_v1` 被 v2 拒绝。证据 SHA-256 为 `e48044fe967957367f431cfd4b36fca86c8e68fe652e0582f672ff8544d65b60`。因此：

```text
decision = do_not_approve_extraction_contract_v3
extraction_contract_version = extraction_contract.v2
```

不实施 v3，不触发贡献项目重扫或 `pending_revalidation`，不修改 Stage 3、SQLite、composer、前端或产品运行契约。普通 bootstrap 继续在 V1 外；不新增 wrapper、模板、fallback、第二仓库或第二组合器。

### Q.5 验证与停止门

- Python 3.14.5、PySide6 6.11.1、Node 22.22.3 全量：`565 passed, 98 subtests passed`。
- Python 3.11、Node 24.18.0 本机 CI 等价链：`564 passed, 1 skipped, 98 subtests passed`；唯一 skip 是临时 Python 3.11 环境没有 PySide6。
- 试点工具聚焦：`8 passed`；`npm ci`、Node 语法、Python 编译和 `git diff --check` 通过。
- 本轮没有 push，未把本机等价链表述为该快照的 GitHub 托管 CI。

本轮停止条件已经触发：正向搜索预算耗尽，bootstrap v3 证据门没有满足。限定复核未发现新增可复现 P0/P1。阶段 1–6 的架构和支持面不变；外部真实正向覆盖保持 `PARTIAL`，后续只能在用户提供新的符合 V1 资格的固定项目时追加证据，不能通过扩大契约或自动转换不合格项目来改变本轮结论。

## 附录 R：普通旧项目纯计算函数回收契约

封板日期：2026-07-17。本附录定义并批准 `computation_adapter.v1`；它是 Static Web V1 之后的一个窄能力，不改变阶段 1–6 的单仓、单组合器架构，也不改变 `extraction_contract.v2`。

### R.1 目标、非目标与唯一数据流

唯一新增流程为：

```text
来源项目只读快照
→ 用户选择已导出的纯整数函数
→ 用户确认参数映射、闭区间、输出字段和业务样例
→ 固定规则生成 __reweave_adapter__/compute.js
→ 既有 AST / data_contract.v1 / Node / Ollama 门禁
→ 既有 SQLite 仓库
→ 既有 module_native
```

首版只证明“满足本节封闭规则的旧函数可以回收为 computation 胶囊”。它不支持 presentation、interaction、DOM、事件、匿名 handler、混合状态、tree-shaking、源码重写、Bootstrap v3、TypeScript、JSX、CommonJS、构建输出或来源依赖安装。Ollama 不生成 adapter、不决定函数边界，也不能直接发布。公开 CLI 不增加入口。

`adapter_contract_version` 固定为：

```text
computation_adapter.v1
```

### R.2 来源函数与整数证明

来源必须是快照内 `.js` / `.mjs` ESM 的 named export：`export function name(...)`，或函数声明后 `export { name }`。参数至少一个，且全部是无默认值、无 rest、无解构的普通标识符。函数及传递 helper 必须同步、非 generator、无递归，只包含不可变整数常量、局部 `const`、单一最终 return、整数参数、整数字面量、一元正负、`+`、`-`、`*` 和可唯一解析的静态纯 helper 调用。

区间分析逐个中间表达式计算闭区间；任一端点或中间值不能证明为 JavaScript safe integer 时，以 `adapter_interval_unproven` 失败关闭。分支、循环、try/catch、throw、赋值、可变模块状态、顶层调用、除法、取模、指数、动态调用、DOM、网络、storage、timer、random、动态执行及 Promise 均拒绝。

保存完整模块闭包，不裁剪符号。闭包只能包含选中函数、传递 helper、它们使用的不可变整数常量及静态相对 import/export。未进入调用图的声明、可执行导出、未使用 import、default/re-export、namespace/side-effect import、循环、符号链接或现有 `__reweave_adapter__/` 路径均拒绝。模块数、深度、路径和大小继续使用现有 V1 限制。

### R.3 用户映射、data contract 与样例

桌面只提交：

```json
{
  "project_id": "project-id",
  "offer_id": "opaque-offer-id",
  "arguments": [
    {
      "source_parameter": "quantity",
      "input_field": "quantity",
      "minimum": 0,
      "maximum": 10000
    },
    {
      "source_parameter": "price",
      "input_field": "unit_price",
      "minimum": 0,
      "maximum": 100000
    }
  ],
  "result_field": "total",
  "examples": [
    {"input": {"quantity": 4, "unit_price": 5}, "expected": 20}
  ]
}
```

每个来源参数必须且只能映射一次。输入/输出字段是互不重复的 snake_case；输入是必填顶层整数，范围端点是 safe integer 且形成闭区间；输出只有一个必填 safe-integer 字段，其最小/最大值由静态区间分析生成。至少一条、最多 64 条样例；样例输入必须符合映射范围，expected 必须符合推导输出范围。

样例只在当前管理任务内传给本地 Node 子进程。持久证据只保存样例数量、规范化 SHA-256 和通过标记，不保存样例原值。规则升级或人工敏感确认后不能从数据库伪造重放；用户必须重新提交至少一条样例。

固定 error contract 只有 `INPUT_CONTRACT_VIOLATION` 与 `OUTPUT_CONTRACT_VIOLATION`，两者 `field=null`、`details={}`。非对象、字段缺失/额外、非整数或越界输入返回前者；来源结果非整数或超出推导范围返回后者。来源异常不转换为业务错误，验证时记为 `adapter_source_exception`，产品运行时仍越过胶囊边界并导致运行失败。

### R.4 确定性生成与安全例外

生成器唯一保留逻辑路径是：

```text
__reweave_adapter__/compute.js
```

生成模块只包含：一个指向所选来源 named export 的静态相对 import；固定输入 shape/range guard；按来源参数顺序直接读取 `input.<field>` 的唯一调用；固定输出整数/range guard；正式 `{ok,value}` / `{ok,error}` envelope。相同来源字节、函数选择、映射和范围必须生成逐字节相同的模块。

通用 JavaScript 安全规则不放宽。唯一例外只在以下条件全部成立时授权：入口恰为保留路径；kind 为 computation；activation 为正式同步 compute；输入、输出和 error contract 与固定结构一致；模块源码逐 AST 结构匹配生成器规范；唯一来源调用是静态 named import，实参按映射顺序直接读取已声明整数输入字段。整个 `input`、别名、成员函数、动态目标、任意表达式或任一额外字节/语句均拒绝。Stage 3 和 `module_native` 调用同一安全分析器复检。

### R.5 Offer、候选和不可变证据

只读动作 `start_inspect_computation_adapters(project_id)` / `startInspectComputationAdapters` 基于完整一致性快照返回：

```json
{
  "schema": "computation_adapter_offers.v1",
  "project_id": "project-id",
  "snapshot_sha256": "...",
  "git_commit": null,
  "git_state": "dirty_or_non_git",
  "offers": [
    {
      "offer_id": "adapter_offer_...",
      "module_relpath": "src/calculate.js",
      "export_name": "calculate",
      "parameters": ["quantity", "price"],
      "function_sha256": "...",
      "closure": [{"logical_path": "src/calculate.js", "sha256": "..."}]
    }
  ],
  "rejection_summary": []
}
```

检查不调用模型/worker，不写 intake、review、capsule、version 或 product 表，不返回源码、绝对路径或字面量。`offer_id` 绑定 project、快照、Git 状态证据、模块、export、参数、函数哈希和闭包。创建动作只信任 `project_id + offer_id`；服务端重新快照、重新发现并匹配 offer，客户端提交的路径、函数名和 hash 均被丢弃。

成功 review 的 `sanitized_candidate_json` 保存：

```json
{
  "candidate_origin": "deterministic_computation_adapter",
  "adapter_contract_version": "computation_adapter.v1",
  "adapter_evidence": {
    "source": {
      "module_relpath": "src/calculate.js",
      "export_name": "calculate",
      "function_sha256": "...",
      "snapshot_sha256": "...",
      "git_commit": null,
      "git_state": "dirty_or_non_git"
    },
    "closure": [{"logical_path": "src/calculate.js", "sha256": "..."}],
    "mapping": {
      "arguments": [
        {
          "source_parameter": "quantity",
          "input_field": "quantity",
          "minimum": 0,
          "maximum": 10000
        },
        {
          "source_parameter": "price",
          "input_field": "unit_price",
          "minimum": 0,
          "maximum": 100000
        }
      ],
      "result_field": "total",
      "mapping_sha256": "..."
    },
    "generated_adapter": {
      "logical_path": "__reweave_adapter__/compute.js",
      "sha256": "..."
    },
    "examples": {"count": 1, "canonical_sha256": "...", "passed": true}
  }
}
```

正式发布时该摘要进入既有不可变 `extraction_summary_json`；来源闭包和完整 adapter 进入既有 `javascript_modules`，因此函数选择、映射和 adapter 字节参与 canonical hash。绝对路径、原始样例、完整模型 prompt/response、异常文本和堆栈不得持久化。非 Git 或 dirty Git 项目允许，但只记录快照与真实 git_state，不伪造 commit。

等待人工敏感/品牌确认或拒绝的行只保存 `candidate_origin`、规则版本和 `requires_reextract=true`，不保存源码、映射或样例。用户作出决定后必须重新创建；绑定决定仍按 project + source path + source hash + redaction/brand 证据规则复用。

### R.6 Stage 3、重复门和选择性重验证

Stage 3 不调用普通 `_extract()` 猜测 adapter。它读取脱敏证据，重新生成来源快照，重新证明同一 offer、映射和区间，逐字节重建 adapter，并核对 candidate/source/hash；任一变化返回 `candidate_boundary_changed`。之后继续执行现有敏感/品牌、固定安全、loopback Ollama、Node worker、重复/等价和人工发布流程。

精确重复只有当前候选与 active-current 正式版本都属于相同 origin，且 `computation_adapter.v1`、extraction/redaction/security/supervision/validation/canonicalization 证据全部当前时才能短路。历史版本或过期 adapter 只能作复核证据。adapter 规则升级只将 adapter 派生的 active-current 版本置为 `pending_revalidation`，不影响普通 extraction v2 胶囊；由于原始业务样例不持久化，重验证必须由用户重新提交样例。

固定失败码为：`adapter_offer_stale`、`adapter_source_unsupported_v1`、`adapter_mapping_invalid`、`adapter_interval_unproven`、`adapter_example_mismatch`、`adapter_source_exception`、`adapter_security_rejected`、`adapter_contract_version_expired`。未知内部结果失败关闭，不映射为成功或宽松尝试。

### R.7 桌面与验收门

桌面项目行新增“检查计算函数”，展示安全 offer 摘要；用户配置字段、范围、输出和业务样例并确认“仅证明映射与样例”。界面没有源码编辑器或自由 JavaScript 输入框。首版仍只接受已经登记且具有单一 HTML 入口的项目，包括普通 intake 标为 `unsupported_v1` 的项目；纯 JavaScript、无 HTML 的仓库发现不在本附录扩展范围内。

完成门要求：确定性 hash、stale/snapshot/dirty 变化、映射/区间/溢出、样例异常、同/跨模块 helper、全部拒绝语法、保留路径碰撞、安全例外、零正式表写入、Stage 3 重建、过期重复门和伪造客户端证据均有回归；随后通过 Python 3.14 + PySide6、Python 3.11 / Node 24 CI 等价门、Node syntax、Python compile 和 `git diff --check`。

公开真实验收最多冻结 12 个第三方项目，不安装依赖、不运行来源命令、不修改来源。第一个合格函数仍由用户在真实桌面确认映射/范围/样例，并只发布到 `/private/tmp` 的临时 SQLite。若耗尽仍无正样本，结论为 `computation_adapter.v1 = PARTIAL`，不得扩大语法、实施 Bootstrap v3 或使用自制样本冒充。

即使通过，产品声明也严格限定为：

```text
已证明：可从满足 computation_adapter.v1 的真实旧项目回收纯计算胶囊。
尚未证明：普通旧项目的 presentation、interaction 或混合代码可被自动拆分。
```

### R.8 当前实现与验收状态

实现快照：2026-07-17。`computation_adapter.v1` 的确定性发现、整数区间证明、adapter 生成、Stage 3 重建、精确重复证据、选择性重验证、应用服务、QWebChannel 和桌面映射表单已经落在同一主线上；没有新增 SQLite DDL、repository、composer、模板、fallback、Bootstrap v3 或公开 CLI 入口。

最终收口同时修复并锁定两项边界：成功的 Git 命令即使在 macOS stderr 输出临时目录警告，也能记录真实 clean commit；Stage 3 会同时复核快照、`git_state` 与 `git_commit`。普通胶囊不能把受保护输入通过直接别名、算术/转换表达式、一元表达式、模板插值、后续赋值、局部闭包、成员调用或动态目标转发给 imported function；该能力只属于逐字节匹配的保留 adapter。

冻结差异的验证结果：

- Python 3.14 / Node 22 全量：`577 passed, 1 skipped, 144 subtests passed`；skip 是不含 PySide6 的核心临时环境中的桌面 harness。
- 独立 PySide6 6.11.1 真实桌面 harness：`1 passed`，完成输入、点击和业务结果断言，不以窗口启动代替业务验收。
- Python 3.11.15 / Node 24.18.0 CI 等价全量：`577 passed, 1 skipped, 144 subtests passed`；公开 CLI help 与 Node 24 语法门通过。该本地等价门不冒充 GitHub 托管 CI。
- Python 编译、Node 22/24 语法和 `git diff --check` 通过。

公开真实项目验收仍为 `PARTIAL`。本轮在运行前冻结并排序了 12 个公开 GitHub 固定提交，随后只在 `/private/tmp` 克隆和只读检查；失败后没有替换项目，也没有安装依赖或运行来源命令。6 个项目没有可绑定的祖先 HTML 入口，2 个入口不唯一，2 个因 tracked symlink 不能形成冻结证据，1 个被现有 inline-script 门拒绝，1 个超过现有来源扫描限制；没有项目到达 adapter offer 分析门。12 个来源的整树摘要和 Git 状态前后相同，模型和 worker 调用均为 0，临时正式表增量为 0。

因此 12 项公开预算已经耗尽，当前只能证明实现和本地确定性样例闭合，不能声称已有第三方旧项目 adapter candidate、active-current 版本或 end-to-end 产品。是否让计算 adapter 接受没有单一 HTML 入口的 JS-only 旧项目属于后续独立产品范围决定；本阶段不放宽语法、不实施 Bootstrap v3，也不用自制样本替代第三方正向证据。

## 附录 S：真实旧 JavaScript 计算抓取能力阶段 0 封板契约

封板日期：2026-07-17。本附录是附录 R 之后的独立设计阶段，只定义如何从 JS-only 或普通旧网页项目中确定性抓取纯计算函数。它不修改附录 R 的历史实现记录，也不声称本能力已经进入业务路径。

### S.1 目标、非目标与单主线

当前 computation_adapter.v1 已能处理已经满足 Static Web 资格、且整个模块接近原子计算函数的来源；它不能处理没有 HTML 的 JavaScript 项目、大型仓库中的选定子目录，以及同时包含多个函数、helper、常量和无关导出的普通模块。本附录只补这三个准确缺口。

继续固定：

- 一个 SQLite 正式仓库。
- 一个 module_native 组合器。
- 一个 review、Stage 3 和发布主线。
- 不新增 repository 工厂、模板、fallback、第二 composer 或第二套 Stage 3。
- 不实施 Bootstrap V3。
- 不安装、构建、测试、执行或修改来源项目。
- Ollama 只命名、分组和监督；不决定函数边界、不生成 adapter、不放宽固定规则、不自动发布。

唯一架构为：

~~~mermaid
flowchart TD
    A["只读 static_web 或 javascript_computation_source"] --> B["解析唯一 JS owner"]
    B --> C["文件索引与一致性快照"]
    C --> D["source_graph.v1"]
    D --> E["用户选择函数、映射和样例"]
    E --> F["确定性依赖闭包"]
    F --> G["selected.js + 固定 adapter"]
    G --> H["执行前固定安全门"]
    H --> I["敏感、品牌、枚举决定"]
    I --> J["adapter_example_preflight"]
    J --> K["不可变 PreparedReview"]
    K --> L["唯一 shared_stage3_gate"]
    L --> M["现有 SQLite 正式仓库"]
    M --> N["唯一 module_native"]
~~~

正式数据流固定为：

~~~text
解析唯一 JS owner
→ 只读文件索引和一致性快照
→ source_graph.v1
→ 用户选择函数、映射和样例
→ 确定性闭包
→ 生成 selected.js 和固定 adapter
→ capture_static_gate：
   canonical JSON bytes 与候选结构
   → JavaScript 语法
   → 固定 adapter AST
   → DSL
   → node --check 与 execution bundle 统一 AST 安全
   → data_contract.v1
   → source freshness
   → 敏感、品牌、枚举与决定 binding
→ 必要时创建安全 waiting_user review 并停止
→ 用户决定后重新提交映射和样例
→ 从当前来源完整重建并重复上述门禁
→ adapter_example_preflight
→ 不可变 PreparedReview
→ shared_stage3_gate 再次执行正式门禁
→ exact duplicate
→ Ollama
→ 正式 runtime validation
→ 等价/变体比较
→ 一次事务持久化最终 outcome
→ 现有 SQLite 和 module_native
~~~

任何候选代码第一次执行前都必须通过 bundle 后统一 AST 安全分析。preflight 使用的模块字节必须与 PreparedReview 中的模块字节完全一致；preflight 不构成正式运行证据，Stage 3 也不得信任或跳过 preflight 已执行的安全检查。

### S.2 来源类型、范围与唯一 JS Owner

projects 的正式来源类型扩展为：

~~~text
static_web
javascript_computation_source
~~~

static_web 保留非空 HTML entry_relpath。javascript_computation_source 的 entry_relpath 必须为 NULL，不伪造 HTML 入口，也不复用 static 字段表达错误语义。project_relpath 等于 "." 表示整个来源根；其他规范 POSIX 相对路径表示用户明确选择的子目录。已登记范围不可原地修改；改选范围创建新 project_id。

clean Git、dirty Git 和 non-Git 均可登记：

- clean Git 保存真实完整 HEAD、clean_git 和选定范围的空 status digest。
- dirty Git 保存真实 HEAD（不存在则为 null）、dirty_git 和选定范围的结构化 status digest。
- non-Git 保存 non_git，commit 和 status digest 都为 null。
- 三者都以一致性快照为代码身份；不得伪造 commit。

范围自身或任一祖先为符号链接时拒绝。范围内无关符号链接只作为索引条目记录，不跟随、不读取，也不阻断扫描；只有 import 闭包依赖该符号链接或它的任一父级时才拒绝。来源枚举和读取必须锚定一次打开的范围根目录 descriptor，递归只允许使用 `scandir(fd)`、`openat/dir_fd`、`fstat` 和 `O_NOFOLLOW|O_DIRECTORY` 等价原语；普通文件还必须以 `O_NONBLOCK` 打开，随后用 `fstat` 证明仍是同一 regular file，防止 regular→FIFO 竞态在 deadline 检查前阻塞。不得在 `DirEntry.stat` 后按拼接路径重新打开子目录或文件。每个子对象都要把打开后的 dev/inode 与父 descriptor 下的 no-follow 观察值绑定，并在关闭前后复核，根路径最终身份也必须与根 descriptor 一致。

`javascript_computation_capture.v1` 的首版功能支持平台固定为 macOS 和 Linux。Windows 主应用、既有 Static Web V1、仓库管理和产品运行仍保留既定支持矩阵，但 Windows 不宣称具备本抓取能力；由于 Python/Windows 缺少本文要求的 descriptor-relative enumeration、relative open/stat、non-blocking open 与 no-follow 组合，抓取动作必须在读取任何来源模块字节和写 index 前结构化返回 `source_platform_unsupported_v1`。UI 应显示“当前平台不支持计算抓取”，项目和正式仓库状态保持不变。不得跳过测试、静默隐藏动作，或回退到 `lstat(path) → open(path) → lstat(path)` 路径遍历器。后续如需 Windows 抓取能力，必须先另行证明 handle-relative backend，不在 v1 预留第二实现或运行时 fallback。

javascript_computation_source 是计算索引、source graph、offer、扫描锁、run 和正式来源追溯的唯一 owner。从 static_web 行点击“扫描计算函数”时，服务端解析或创建同一物理范围的 JS owner；static 项目不保存第二份计算索引。

owner 创建顺序固定为：

1. 获取应用级 _javascript_owner_creation_lock。
2. 重新解析目标物理目录。
3. 进入 BEGIN IMMEDIATE。
4. 重新查询并解析全部既有 JS owner。
5. 0 个物理匹配则创建，1 个则复用，多于 1 个返回 duplicate_javascript_source_scope。
6. owner 确定后才获取 _project_guard(js_project_id)。

应用启动时执行同一重复 owner 检查；发现历史重复时禁止扫描，不自动选择、合并或删除。该单一应用锁是 V1 的有意上限：owner 创建不是热路径，未有测量证据前不引入 scope lock 表或锁工厂。

父 JS 范围扫描排除所有已独立登记的严格后代项目范围，不区分后代是 static 还是 JS。同一物理目录的 static/JS 共存不是后代，不排除。

### S.3 SQLite v2 目标与迁移边界

SCHEMA_VERSION 从 1 升到 2。v2 保留原 14 张表并只增加 project_file_index，共 15 张表；原 9 个显式索引保留，增加两个 projects partial unique index，共 11 个；原 31 个触发器完整保留或等价重建，增加三个来源身份/owner 触发器，共 34 个。

projects 的 v2 重建规则：

- 增加 source_type，值只能为 static_web 或 javascript_computation_source。
- entry_relpath 改为可空；static_web 必须非空，javascript_computation_source 必须为 NULL。
- 全部 v1 项目固定回填为 static_web。
- source_type、source_root_id、project_relpath 和 entry_relpath 发布后不可修改。
- 同一 source_root 内的 static entry 与 JS scope 分别使用以下索引：

~~~sql
CREATE UNIQUE INDEX idx_projects_static_entry
ON projects(source_root_id, project_relpath, entry_relpath)
WHERE source_type = 'static_web';

CREATE UNIQUE INDEX idx_projects_js_scope
ON projects(source_root_id, project_relpath)
WHERE source_type = 'javascript_computation_source';
~~~

跨 source_root 的物理唯一性由 S.2 的应用锁和事务内复核承担；不得假装上述索引能跨 root 证明物理路径唯一。

project_file_index 的 v2 DDL 固定为：

~~~sql
CREATE TABLE project_file_index (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    logical_path TEXT NOT NULL,
    entry_kind TEXT NOT NULL
        CHECK (entry_kind IN ('javascript_module', 'symlink')),
    size_bytes INTEGER,
    content_sha256 TEXT,
    PRIMARY KEY (project_id, logical_path),
    CHECK (
        (
            entry_kind = 'javascript_module'
            AND size_bytes IS NOT NULL
            AND typeof(size_bytes) = 'integer'
            AND size_bytes >= 0
            AND content_sha256 IS NOT NULL
            AND typeof(content_sha256) = 'text'
            AND length(content_sha256) = 64
            AND content_sha256 NOT GLOB '*[^0-9a-f]*'
        )
        OR
        (
            entry_kind = 'symlink'
            AND size_bytes IS NULL
            AND content_sha256 IS NULL
        )
    )
);
~~~

NULL size/hash、BLOB size/hash、空 hash、大写 hash、非十六进制 hash，以及携带 size/hash 的 symlink 行都必须被 SQLite 拒绝。

三个新增触发器的职责固定为：

- projects_source_identity_immutable：禁止修改 source_type、source_root_id、project_relpath 和 entry_relpath。
- project_file_index_owner_insert：project_id 不是 javascript_computation_source 时拒绝。
- project_file_index_owner_update：禁止更换 project_id，并再次确认 owner 类型。

intake_runs 的 run_kind CHECK 增加 javascript_computation_scan 和 javascript_computation_capture。review_items 增加 enum_decision、enum_decision_binding_sha256 和 enum_decided_at；enum_decision 只允许 confirm_selected_string_enumeration，三个字段必须同时为空或同时存在。enum_decision_binding_sha256 必须满足 64 位小写十六进制 CHECK，并纳入现有决定不可变触发器。

本文在 S.3.1—S.3.4 冻结 SCHEMA_SQL_V2 和 MIGRATE_V1_TO_V2 的完整组成；阶段 B 只能逐字实现这些组成，并冻结现有 SCHEMA_SQL_V1。fingerprint 比较全部非 sqlite_% 的 type、name、tbl_name、sql；未知对象、多一个、少一个或同名伪 SQL 均拒绝。

迁移只在同目录 candidate 数据库执行：

1. 停止新任务，结束或取消在途任务并关闭连接。
2. 验证 active v1 exact fingerprint、integrity_check、foreign_key_check 和数据不变量。
3. 记录 active 数据库 SHA-256。
4. 用 SQLite backup API 创建升级备份，并创建权限 0600 的原始字节 rollback 副本。
5. 在事务外设置 journal_mode=DELETE、foreign_keys=OFF 和 busy_timeout=5000；以 mode=ro URI 参数绑定 ATTACH rollback 副本，不 ATTACH active 数据库。
6. BEGIN IMMEDIATE 后只执行无 PRAGMA、无 seed、无索引、无触发器的 SCHEMA_TABLES_SQL_V2。
7. 按 S.3.4 的完整列清单复制原 14 张表；warehouse_state singleton 只从 v1 复制一次，projects 回填 static_web，review enum 字段回填 NULL，project_file_index 保持空。
8. 创建全部 11 个显式索引和 34 个触发器，设置 user_version=2，COMMIT 后 DETACH，并重新启用 foreign_keys。
9. 验证 integrity_check=ok、foreign_key_check 为空、exact v2 fingerprint、S.3.4 persistent invariants、原表主键集合和全部旧外键引用不变、正式 capsule/version/product/warehouse_state 逐值相同。
10. 再次确认 active SHA 未变化，fsync candidate 与目录后 os.replace。
11. 替换后重新验证；失败时用 rollback 副本原子恢复，恢复 SHA 必须与步骤 3 完全相同。

迁移失败不得改变活动库字节。阶段 B 未通过前不实施 owner/index 业务路径，也不迁移用户正式仓库。

#### S.3.1 SCHEMA_SQL_V2 的规范组成

SCHEMA_SQL_V1 固定为正文 18.3 当前 user_version=1 的完整 SQL，之后不得根据 v2 反推或改写。SCHEMA_SQL_V2 不通过运行时字符串替换生成，而是由以下四个冻结常量按顺序组成：

~~~text
SCHEMA_TABLES_SQL_V2
SCHEMA_SEED_SQL_V2
SCHEMA_INDEXES_SQL_V2
SCHEMA_TRIGGERS_SQL_V2
~~~

SCHEMA_TABLES_SQL_V2 逐字复用正文 18.3 的 11 个未变化表：warehouse_state、app_settings、source_roots、capability_groups、capsules、capsule_versions、capsule_sources、capsule_assets、capsule_status_events、product_capsule_usage、legacy_capsule_aliases；projects、intake_runs 和 review_items 使用本节完整 v2 定义，并在 projects 后创建 project_file_index。本段不含 PRAGMA、warehouse_state seed、索引或触发器。

SCHEMA_SEED_SQL_V2 只有：

~~~sql
INSERT INTO warehouse_state(singleton_id) VALUES (1);
~~~

新建空 v2 库固定执行：

~~~text
PRAGMA foreign_keys=ON
→ PRAGMA busy_timeout=5000
→ BEGIN IMMEDIATE
→ SCHEMA_TABLES_SQL_V2
→ SCHEMA_SEED_SQL_V2
→ SCHEMA_INDEXES_SQL_V2
→ SCHEMA_TRIGGERS_SQL_V2
→ PRAGMA user_version=2
→ COMMIT
~~~

迁移 candidate 只执行 TABLES，不能执行 SEED；warehouse_state 必须从 v1 精确复制，因此不存在 fresh seed 主键冲突，也禁止 INSERT OR IGNORE 或 UPSERT。

projects 的完整 v2 替换块为：

~~~sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    source_root_id TEXT NOT NULL REFERENCES source_roots(root_id),
    source_type TEXT NOT NULL CHECK (
        source_type IN ('static_web', 'javascript_computation_source')
    ),
    project_relpath TEXT NOT NULL,
    entry_relpath TEXT,
    display_name TEXT NOT NULL,
    project_state TEXT NOT NULL CHECK (
        project_state IN (
            'discovered_unconfirmed',
            'ready',
            'unsupported_v1',
            'source_missing'
        )
    ),
    discovery_signature TEXT NOT NULL,
    last_snapshot_hash TEXT,
    brand_mode TEXT NOT NULL DEFAULT 'inherit' CHECK (
        brand_mode IN ('inherit', 'extend', 'replace', 'clear')
    ),
    brand_profile_id TEXT,
    brand_profile_json TEXT,
    brand_profile_digest TEXT,
    brand_profile_version INTEGER NOT NULL DEFAULT 0 CHECK (
        brand_profile_version >= 0
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            source_type = 'static_web'
            AND entry_relpath IS NOT NULL
            AND length(entry_relpath) > 0
        )
        OR
        (
            source_type = 'javascript_computation_source'
            AND entry_relpath IS NULL
        )
    ),
    CHECK (
        (
            brand_profile_id IS NULL
            AND brand_profile_json IS NULL
            AND brand_profile_digest IS NULL
            AND brand_profile_version = 0
        )
        OR
        (
            brand_profile_id IS NOT NULL
            AND brand_profile_json IS NOT NULL
            AND brand_profile_digest IS NOT NULL
            AND brand_profile_version >= 1
        )
    )
);
~~~

project_file_index 使用 S.3 已给出的完整块，不能出现第二份变体。

intake_runs 的完整 v2 替换块为：

~~~sql
CREATE TABLE intake_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id),
    run_kind TEXT NOT NULL CHECK (
        run_kind IN (
            'refresh_project',
            'refresh_all_child',
            'legacy_import',
            'brand_revalidation',
            'javascript_computation_scan',
            'javascript_computation_capture'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'queued',
            'running',
            'no_change',
            'completed',
            'completed_with_pending',
            'failed',
            'cancelled',
            'interrupted'
        )
    ),
    snapshot_before TEXT,
    snapshot_after TEXT,
    extraction_contract_version TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    security_rules_version TEXT NOT NULL,
    supervision_rules_version TEXT NOT NULL,
    validation_contract_version TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    legacy_source_path_hash TEXT,
    legacy_source_file_hash TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);
~~~

review_items 的完整 v2 替换块为：

~~~sql
CREATE TABLE review_items (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES intake_runs(run_id),
    project_id TEXT REFERENCES projects(project_id),
    candidate_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL CHECK (
        candidate_status IN (
            'extracted',
            'waiting_user',
            'waiting_model',
            'waiting_validation',
            'review_required',
            'publishable',
            'published',
            'duplicate',
            'merged',
            'rejected'
        )
    ),
    source_relpath TEXT NOT NULL,
    source_location_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    redaction_rules_version TEXT NOT NULL,
    candidate_canonical_hash TEXT,
    sanitized_candidate_json TEXT NOT NULL,
    redaction_summary_json TEXT NOT NULL,
    supervision_result_json TEXT,
    supervision_response_hash TEXT,
    equivalence_comparison_json TEXT,
    sensitivity_decision TEXT CHECK (
        sensitivity_decision IS NULL OR sensitivity_decision IN (
            'confirm_fictional_fixture',
            'confirm_safe_redaction',
            'confirm_real_record_reject'
        )
    ),
    sensitivity_decided_at TEXT,
    brand_decision TEXT CHECK (
        brand_decision IS NULL OR brand_decision IN (
            'remove_brand',
            'retain_brand_limited'
        )
    ),
    brand_decided_at TEXT,
    asset_decision TEXT CHECK (
        asset_decision IS NULL
        OR asset_decision = 'confirm_assets_contain_no_real_records'
    ),
    asset_decided_at TEXT,
    enum_decision TEXT CHECK (
        enum_decision IS NULL
        OR enum_decision = 'confirm_selected_string_enumeration'
    ),
    enum_decision_binding_sha256 TEXT CHECK (
        enum_decision_binding_sha256 IS NULL
        OR (
            typeof(enum_decision_binding_sha256) = 'text'
            AND length(enum_decision_binding_sha256) = 64
            AND enum_decision_binding_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    enum_decided_at TEXT,
    decision TEXT CHECK (
        decision IS NULL OR decision IN (
            'merge_existing',
            'replace_current',
            'create_variant',
            'semantic_split',
            'publish_general',
            'publish_brand_limited',
            'reject'
        )
    ),
    retained_version_id TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (sensitivity_decision IS NULL AND sensitivity_decided_at IS NULL)
        OR
        (
            sensitivity_decision IS NOT NULL
            AND sensitivity_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    ),
    CHECK (
        (brand_decision IS NULL AND brand_decided_at IS NULL)
        OR
        (
            brand_decision IS NOT NULL
            AND brand_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    ),
    CHECK (
        (asset_decision IS NULL AND asset_decided_at IS NULL)
        OR
        (
            asset_decision IS NOT NULL
            AND asset_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    ),
    CHECK (
        (
            enum_decision IS NULL
            AND enum_decision_binding_sha256 IS NULL
            AND enum_decided_at IS NULL
        )
        OR
        (
            enum_decision = 'confirm_selected_string_enumeration'
            AND enum_decision_binding_sha256 IS NOT NULL
            AND enum_decided_at IS NOT NULL
            AND project_id IS NOT NULL
        )
    )
);
~~~

#### S.3.2 完整索引与触发器集合

SCHEMA_INDEXES_SQL_V2 精确包含以下 11 个显式索引；SQLite 自动索引不计入：

~~~sql
CREATE INDEX idx_projects_root ON projects(source_root_id);
CREATE UNIQUE INDEX idx_projects_static_entry
ON projects(source_root_id, project_relpath, entry_relpath)
WHERE source_type = 'static_web';
CREATE UNIQUE INDEX idx_projects_js_scope
ON projects(source_root_id, project_relpath)
WHERE source_type = 'javascript_computation_source';
CREATE INDEX idx_intake_runs_project ON intake_runs(project_id, created_at);
CREATE INDEX idx_review_items_status ON review_items(candidate_status, created_at);
CREATE INDEX idx_review_content_decision ON review_items(
    project_id, source_relpath, source_hash, redaction_rules_version
);
CREATE INDEX idx_capsules_group ON capsules(capability_key, role_key, variant_key);
CREATE INDEX idx_capsule_versions_hash ON capsule_versions(canonical_hash);
CREATE INDEX idx_capsule_versions_capsule
ON capsule_versions(capsule_id, version_number);
CREATE INDEX idx_capsule_sources_project ON capsule_sources(project_id);
CREATE INDEX idx_usage_product ON product_capsule_usage(product_id);
~~~

SCHEMA_TRIGGERS_SQL_V2 逐字复用正文 18.3 的以下 30 个触发器：

~~~text
warehouse_state_update_guard
warehouse_state_no_delete
review_items_source_binding_immutable
capability_groups_update_guard
capability_groups_no_delete
capsules_identity_immutable
capsules_no_delete
capsules_insert_not_active
capsules_active_requires_current_version
capsules_current_version_belongs_to_capsule
capsules_status_transition
capsule_versions_no_update
capsule_versions_no_delete
capsule_sources_no_update
capsule_sources_no_delete
capsule_sources_canonical_relationship
capsule_assets_no_update
capsule_assets_no_delete
capsule_status_events_no_update
capsule_status_events_no_delete
capsule_status_events_version_belongs_to_capsule
capsule_status_events_match_state
product_capsule_usage_matches_version
product_capsule_usage_manifest_consistent
product_capsule_usage_no_update
product_capsule_usage_no_delete
legacy_capsule_aliases_no_update
legacy_capsule_aliases_no_delete
legacy_capsule_aliases_target_matches
legacy_capsule_aliases_contract
~~~

第 31 个触发器使用以下 v2 定义：

~~~sql
CREATE TRIGGER review_items_content_decision_once
BEFORE UPDATE ON review_items
WHEN (OLD.sensitivity_decision IS NOT NULL
      AND NEW.sensitivity_decision IS NOT OLD.sensitivity_decision)
  OR (OLD.sensitivity_decided_at IS NOT NULL
      AND NEW.sensitivity_decided_at IS NOT OLD.sensitivity_decided_at)
  OR (OLD.brand_decision IS NOT NULL
      AND NEW.brand_decision IS NOT OLD.brand_decision)
  OR (OLD.brand_decided_at IS NOT NULL
      AND NEW.brand_decided_at IS NOT OLD.brand_decided_at)
  OR (OLD.asset_decision IS NOT NULL
      AND NEW.asset_decision IS NOT OLD.asset_decision)
  OR (OLD.asset_decided_at IS NOT NULL
      AND NEW.asset_decided_at IS NOT OLD.asset_decided_at)
  OR (OLD.enum_decision IS NOT NULL
      AND NEW.enum_decision IS NOT OLD.enum_decision)
  OR (OLD.enum_decision_binding_sha256 IS NOT NULL
      AND NEW.enum_decision_binding_sha256
          IS NOT OLD.enum_decision_binding_sha256)
  OR (OLD.enum_decided_at IS NOT NULL
      AND NEW.enum_decided_at IS NOT OLD.enum_decided_at)
BEGIN
    SELECT RAISE(ABORT, 'review_content_decision_immutable');
END;
~~~

新增的三个触发器为：

~~~sql
CREATE TRIGGER projects_source_identity_immutable
BEFORE UPDATE ON projects
WHEN NEW.project_id <> OLD.project_id
  OR NEW.source_root_id <> OLD.source_root_id
  OR NEW.source_type <> OLD.source_type
  OR NEW.project_relpath <> OLD.project_relpath
  OR NEW.entry_relpath IS NOT OLD.entry_relpath
BEGIN
    SELECT RAISE(ABORT, 'project_source_identity_immutable');
END;

CREATE TRIGGER project_file_index_owner_insert
BEFORE INSERT ON project_file_index
WHEN NOT EXISTS (
    SELECT 1
    FROM projects p
    WHERE p.project_id = NEW.project_id
      AND p.source_type = 'javascript_computation_source'
)
BEGIN
    SELECT RAISE(ABORT, 'project_file_index_owner_mismatch');
END;

CREATE TRIGGER project_file_index_owner_update
BEFORE UPDATE ON project_file_index
WHEN NEW.project_id <> OLD.project_id
   OR NOT EXISTS (
       SELECT 1
       FROM projects p
       WHERE p.project_id = NEW.project_id
         AND p.source_type = 'javascript_computation_source'
   )
BEGIN
    SELECT RAISE(ABORT, 'project_file_index_owner_mismatch');
END;
~~~

#### S.3.3 MIGRATE_V1_TO_V2 的显式复制契约

迁移只 ATTACH 权限 0600、SHA 与 active 开始值相同的 rollback/source 副本。URI 固定为 file:<percent-encoded-path>?mode=ro，并通过参数绑定执行 ATTACH DATABASE ? AS v1。

复制顺序和列清单固定为：

~~~text
warehouse_state:
  singleton_id, warehouse_revision, last_backed_up_revision
app_settings:
  setting_key, value_json, updated_at
source_roots:
  root_id, root_kind, current_path, status, brand_profile_id,
  brand_profile_json, brand_profile_digest, brand_profile_version,
  created_at, updated_at
projects:
  project_id, source_root_id, 'static_web' AS source_type,
  project_relpath, entry_relpath, display_name, project_state,
  discovery_signature, last_snapshot_hash, brand_mode, brand_profile_id,
  brand_profile_json, brand_profile_digest, brand_profile_version,
  created_at, updated_at
intake_runs:
  run_id, project_id, run_kind, status, snapshot_before, snapshot_after,
  extraction_contract_version, redaction_rules_version,
  security_rules_version, supervision_rules_version,
  validation_contract_version, canonicalization_version, counts_json,
  error_code, legacy_source_path_hash, legacy_source_file_hash,
  started_at, completed_at, created_at
review_items:
  review_id, run_id, project_id, candidate_id, candidate_status,
  source_relpath, source_location_json, source_hash,
  redaction_rules_version, candidate_canonical_hash,
  sanitized_candidate_json, redaction_summary_json,
  supervision_result_json, supervision_response_hash,
  equivalence_comparison_json, sensitivity_decision,
  sensitivity_decided_at, brand_decision, brand_decided_at,
  asset_decision, asset_decided_at,
  NULL AS enum_decision, NULL AS enum_decision_binding_sha256,
  NULL AS enum_decided_at,
  decision, retained_version_id, decided_at, created_at, updated_at
capability_groups:
  capability_key, display_name, created_at, updated_at
capsules:
  capsule_id, capability_key, role_key, variant_key, capability_kind,
  status, current_version_id, created_at
capsule_versions:
  version_id, capsule_id, version_number, extraction_contract_version,
  extraction_summary_json, redaction_rules_version,
  canonicalization_version, canonical_hash, activation_json,
  input_contract_json, output_contract_json, error_contract_json,
  runtime_allowlist_json, dom_scope_json, usage_scope_json, html_text,
  css_text, javascript_modules_json, cleaning_summary_json,
  security_rules_version, supervision_rules_version,
  supervision_model_name, supervision_model_digest, supervised_at,
  supervision_result_json, supervision_response_hash,
  validation_contract_version, validation_result_json, created_at
capsule_sources:
  source_link_id, version_id, project_id, source_identity, source_kind,
  source_relpath, source_hash, candidate_canonical_hash, relationship,
  read_at
capsule_assets:
  asset_id, version_id, logical_path, media_type, sha256, size_bytes,
  width, height, content
capsule_status_events:
  event_id, capsule_id, event_type, from_status, to_status, version_id,
  reason_code, created_at
product_capsule_usage:
  usage_id, product_id, manifest_digest, capsule_id, version_id,
  capability_key, role_key, variant_key, usage_scope_json,
  contribution_role, generated_at
legacy_capsule_aliases:
  alias_id, import_run_id, legacy_file_hash, legacy_capsule_id,
  relationship, new_capsule_id, new_version_id, reason_code, created_at
~~~

每次 INSERT 必须在目标和 SELECT 两侧写出对应列名，禁止 SELECT *。warehouse_state 的 v1 行数必须精确为 1 且 singleton_id=1；candidate 在复制前必须为 0 行。project_file_index 不复制，保持空。

迁移后用双向 EXCEPT 或类型保持的逐行比较证明原 14 表主键集合与所有旧字段值不变；不能用 count(*) 代替。唯一新增值是 projects.source_type='static_web'、三个 enum 字段为 NULL 和空 project_file_index。

#### S.3.4 v2 持久不变量

初始化、打开、备份、inspect_restore、restore 和迁移后都在 Python 层执行：

- 每个 project_file_index.project_id 必须对应 javascript_computation_source。
- logical_path 必须通过 S.4 的统一 POSIX 相对路径校验；同一 project 内拒绝 exact、casefold、NFC 和 casefold(NFC) 碰撞。
- javascript_module 的 size/hash 与字段约束一致；symlink 不保存目标内容、size 或 hash。
- 对存在 index 行的 JS project，按排序行重建 javascript_scope_snapshot.v1，projects.last_snapshot_hash 必须非 NULL 且等于 scope_snapshot_sha256。
- 没有 index 行的 JS project 必须 last_snapshot_hash IS NULL；static_web 不使用该摘要比较。
- 恢复验证不读取来源项目；module 的真实字节数和 SHA 只在索引写入前由一致性快照验证。
- v1 verifier 不认识 v2 对象；v2 verifier 拒绝未知对象、多/少对象或同名伪 SQL。

这些规则由统一 _assert_persistent_data_invariants 语义承担，不增加 header 表、仓库接口或事件系统。

### S.4 文件索引、摘要与固定资源门

索引扫描先建立轻量目录清单，只读取选定范围中的 .js/.mjs 字节；source graph 只解析用户选中的 offer 所需模块。固定剪枝目录为：

~~~text
.git
node_modules
dist
build
coverage
.venv
venv
__pycache__
~~~

固定资源上限：

~~~text
选定范围：
50,000 个目录项
2,000 个 .js/.mjs
64 MiB JavaScript 总字节
单文件 1 MiB
目录深度 32
文件索引 60 秒

目标闭包：
32 个模块
import 深度 8
闭包源码 4 MiB
单 offer 分析 15 秒

selected bundle：
1 MiB
bundle 30 秒
~~~

超限使整次任务失败，不返回截断索引或部分 offer。取消先终止 worker，2 秒内未退出再 kill；取消、崩溃、超时或来源变化都不替换旧索引。source graph/esbuild worker 使用 --max-old-space-size=512；adapter preflight 和正式 computation worker保持 --max-old-space-size=64。

所有摘要使用本文 Canonicalization V1 的 canonical JSON UTF-8 bytes。

~~~text
file_index_digest =
SHA-256({
  "version": "project_file_index.v1",
  "entries": [
    {"path", "kind", "size", "sha256"}
  ]
})
~~~

symlink 的 size 和 sha256 显式为 null；条目按逻辑路径 UTF-8 字节序排序。

~~~text
scope_snapshot_sha256 =
SHA-256({
  "version": "javascript_scope_snapshot.v1",
  "javascript_modules": [
    {"path", "size", "sha256"}
  ],
  "symlinks": [
    {"path"}
  ]
})
~~~

~~~text
source_identity_sha256 =
SHA-256({
  "version": "javascript_source_identity.v1",
  "scope_snapshot_sha256": "...",
  "git_state": "clean_git | dirty_git | non_git",
  "commit": "... | null",
  "status_sha256": "... | null"
})
~~~

git_status_contract.v1 只读取选定 scope，使用 NUL 分隔 porcelain 记录，应用与索引相同的剪枝规则；解析成受控 status/path 元组后按规范逻辑路径排序，再计算摘要。Git 只能由来源仓库范围外的可信绝对可执行文件启动，子进程 PATH 收窄到该可执行文件目录。status 必须使用系统临时目录中的无本地配置、无 `info/attributes`、无 hooks 的惰性 Git metadata 目录，只以只读方式引用来源 index 和 object store，并将 work tree 显式绑定到已验证的来源根；同时使用临时空 attribute tree、禁用系统与全局 attributes、忽略 submodule 递归。不得让来源 `.git/config`、`.git/info/attributes`、worktree `.gitattributes` 或 clean/process filter 影响 status 或执行命令；所有临时 metadata/object 只写系统临时目录，不写来源 `.git`。scope 和已发现的剪枝目录使用显式 literal include/exclude pathspec，解析器仍执行同一剪枝作为第二道门。不得保存原始 status 文本。malformed、越界路径、大小写碰撞或 NFC/NFD 碰撞失败关闭。mtime_ns 不持久化、不参与摘要或身份。

逻辑路径禁止绝对路径、反斜杠、空段、"."、".."、控制字符和尾斜杠。路径不自动修复或 Unicode 规范化。import 必须精确命中原始拼写；只有大小写或 Unicode 规范化近似匹配时返回 import_path_spelling_mismatch。

### S.5 source_graph.v1 正式契约

分析器只接收 Python 一致性快照中的严格 UTF-8 模块字节和 SHA-256，不接收来源绝对路径，也不重新读取实时目录。无效 UTF-8 返回 source_utf8_invalid，禁止 replacement character。

正式进程内示例：

~~~json
{
  "schema": "source_graph.v1",
  "project_id": "js-owner-id",
  "scope_snapshot_sha256": "...",
  "source_identity_sha256": "...",
  "modules": [
    {
      "logical_path": "src/quote.js",
      "sha256": "...",
      "imports": [],
      "exports": [
        {
          "public_name": "calculate",
          "binding_id": "binding-1"
        }
      ],
      "bindings": [
        {
          "binding_id": "binding-1",
          "kind": "function",
          "parameters": [
            {"binding_id": "parameter-1", "display_name": "quantity"}
          ],
          "start_utf16": 42,
          "end_utf16": 115,
          "start_byte": 48,
          "end_byte": 121,
          "line": 3,
          "column": 1,
          "declaration_sha256": "...",
          "calls": [],
          "reads": [],
          "writes": [],
          "captures": []
        }
      ],
      "top_level_execution": [],
      "dynamic_dependencies": []
    }
  ]
}
~~~

阶段 D 的独立分析器 stdin 固定为 `source_graph_request.v1`，只接受快照字节，不接受来源目录：

~~~json
{
  "schema": "source_graph_request.v1",
  "mode": "graph",
  "project_id": "js-owner-id",
  "scope_snapshot_sha256": "...",
  "source_identity_sha256": "...",
  "entry_modules": ["src/quote.js"],
  "module_snapshot": [
    {
      "path": "src/quote.js",
      "source_base64": "...",
      "sha256": "..."
    }
  ],
  "symlinks": []
}
~~~

`mode=prove` 额外要求唯一 `target` 与按目标参数源码顺序绑定的 `parameter_domains`。证明成功时，`proof` 的最小正式形状固定为：

~~~json
{
  "target_binding_id": "...",
  "parameter_domains": [
    {
      "parameter_binding_id": "...",
      "domain": {"kind": "integer", "intervals": [[0, 100]]}
    }
  ],
  "result_domain": {"kind": "integer", "intervals": [[0, 500]]},
  "closure": {
    "module_paths": ["src/quote.js"],
    "binding_ids": ["..."]
  },
  "closure_sha256": "..."
}
~~~

整数区间先按端点排序再合并重叠或相邻段；布尔值排序为 `false,true`；枚举按精确 UTF-8 字节序排序；闭包路径和 binding ID 分别确定性排序。拒绝结果精确为 `schema/status/error_code/logical_path`，不得包含源码、base64、绝对路径、异常文本或堆栈。分析器由父进程以 `node --max-old-space-size=512` 启动；父进程执行 15 秒单 offer 超时、取消和强制终止。分析器本身不读取文件系统，也不把超时当作可在同步 JavaScript 内自证的安全边界。

图按 TypeScript lexical symbol 建模，不能按变量名字符串匹配。必须显式覆盖 module、export/import/re-export binding、function、parameter、local const、module const、call、read、write、capture、top-level execution 和 dynamic/unknown dependency。

TypeScript span 使用半开区间 start_utf16/end_utf16。每个模块从同一份快照预先建立 UTF-16 code-unit 到 UTF-8 byte offset 的边界映射；代理对中点不是合法切片边界。binding/declaration hash 只覆盖映射后的准确原始 UTF-8 字节。行列使用 TypeScript line map 并对外转为 1-based。测试覆盖中文、emoji、重音字符、CRLF、非 ASCII 声明和非法代理对中点。

稳定 binding_id 固定为以下 canonical JSON 的 SHA-256：

~~~json
{
  "source_graph_version": "source_graph.v1",
  "logical_path": "src/quote.js",
  "binding_kind": "function",
  "start_byte": 48,
  "end_byte": 121,
  "declaration_sha256": "...",
  "lexical_parent_binding_id": null
}
~~~

lexical_parent_binding_id 递归使用同一公式。参数 binding 额外加入源码顺序 ordinal；import/export alias binding 额外加入 target_binding_id 和原始 export token 的 UTF-8 byte hash。UTF-16 offset、遍历顺序、绝对路径和显示名不参与身份。leaf_binding_hash 就是最终 leaf binding_id；offer_id 绑定 source identity、public export token hash、leaf_binding_hash、参数 binding_id 顺序和闭包证据 hash。

UI 对 Unicode 导出名显示原名和 “U+ 加至少四位大写十六进制”的码点序列，例如 U+00E9、U+8BA1、U+1D49C。不做 NFC/NFD 转换。capture entry 只由 TypeScript AST Factory + Printer 生成，不用字符串拼接改写来源。

source graph 和 offer 只驻留当前进程；应用重启、任务取消或来源变化后丢弃。

### S.6 模块解析、目标函数与依赖闭包

允许的模块引用：

- 显式 ./x.js 和 ./x.mjs。
- extensionless ./x，但只能唯一命中 ./x.js 或 ./x.mjs；两者同时存在时拒绝。
- named/default import、alias 和受限静态 re-export。
- export { value }、export { value as alias }、export { default }、export { default as alias } from "./x.js"。

拒绝 directory index、package exports、bare package、URL、query、fragment、import map、namespace import/export、side-effect import、dynamic import、CommonJS、TypeScript、JSX、export *、字符串形式导出名、export default factory() 和成员目标。source graph resolver 与 esbuild resolver 必须使用同一个只读 snapshot resolution map。

可选择的目标包括 named function export、具名或匿名 default function，以及 const function/arrow 经 named/default export 或受限 re-export 唯一解析到 leaf binding 的形式。let/var 函数 binding、成员目标和多义 re-export 拒绝。

用户选择目标函数后，分析器按 lexical binding 递归纳入：

- 目标函数。
- 唯一解析的传递 helper。
- 不可变 local/module const。
- 静态相对 import/re-export。
- 可证明不可变的 capture。
- 相关模块全部顶层初始化证据。

mutable capture、动态调用、未知 binding、alias cycle、递归、循环、对象共享状态、范围外 import、闭包内 symlink 或无法证明的顶层执行都返回 closure_unproven 或更具体失败码。

V1 允许机械 tree-shaking，但边界固定：

- 未进入目标调用图的普通函数体可以从最终 selected bundle 移除。
- 目标函数和全部传递 helper 的所有 AST 节点都要检查，包括不可达代码；return 后隐藏的危险语句同样拒绝。
- 参与 module-evaluation closure 的每个模块，其全部顶层语句都必须正向证明；不能因为预计未被调用而忽略顶层副作用。
- esbuild 只做固定 bundle/tree-shaking，不承担安全证明。

顶层白名单只有 import/export declaration、function declaration、固定函数 const binding、可静态求值的不可变 const，以及已证明的纯 helper 初始化 const。

顶层 helper 初始化必须同时满足：

- helper 属于同一 source graph。
- 同步、无循环、无递归、无可变 capture。
- 参数只来自字面量或此前已证明的 const。
- helper 闭包全部属于计算 DSL。
- 返回值可静态求值为一个确定的 safe integer、boolean 或已确认枚举字符串。
- 分析器不执行来源代码。

无法得到确定单值时返回 top_level_initializer_unproven。顶层独立调用、IIFE、assignment、let/var、class、new 和未知初始化均失败关闭。

### S.7 首版计算 DSL 与静态区间证明

允许：

- safe integer、boolean 和已确认字符串枚举。
- +、-、*、%，一元 +、-、!。
- <、<=、>、>=、===、!==。
- &&、||。
- if/else、三元和有 default、无 fallthrough 的字面量 switch。
- Math.min、Math.max、Math.abs。
- local const。
- 初始化后再无写入的 local let。
- 唯一解析的纯 helper。

拒绝：

- /、**、浮点、BigInt 和 bitwise。
- Math.round/floor/ceil/trunc。
- 循环、递归、try/catch、throw 和任意异常文本传出。
- 默认参数、rest、解构、动态调用和未知作用域。
- 对象共享状态、DOM、事件、network、storage、timer、random 和动态执行。
- 未列出的任何 AST 节点。

TypeScript Program 只包含快照模块和 Reweave 固定的最小 intrinsic；不读取来源 tsconfig、package、node_modules 或 @types。Math 必须解析到固定 intrinsic symbol；被参数、局部声明或 import 遮蔽时拒绝。

静态抽象域固定为 Bottom、BoolSet、EnumSet 和最多 16 个互不重叠闭区间的 IntSet。所有端点必须是 JavaScript safe integer；超过 16 段、无法证明中间值或需要依赖运行样例补证明时返回 interval_unproven。每个 IntSet 二元运算对左右全部区间做笛卡尔 transfer，按端点排序并合并重叠或相邻区间；禁止先取整体凸包来代替分段证明。

固定 transfer rule：

- a+b 为 [amin+bmin, amax+bmax]。
- a-b 为 [amin-bmax, amax-bmin]。
- a*b 取四个端点乘积的最小和最大值。
- Math.abs 跨 0 时为 [0, max(abs(min), abs(max))]。
- Math.min 为 [min(各输入最小值), min(各输入最大值)]。
- Math.max 为 [max(各输入最小值), max(各输入最大值)]。
- 比较生成 BoolSet，并只对 identifier 与字面量的固定比较做区间细化。
- if、三元、switch 使用 union；条件必须是 BoolSet。&&/|| 两侧均为 BoolSet，并按 JavaScript 短路顺序及当前分支 refinement 分析。
- helper 按 symbol identity 绑定实参抽象值；直接或互相递归均拒绝。

% 严格使用 JavaScript remainder 语义：除数域包含 0 时拒绝；对每个被除数/除数区间对，令 K=max(abs(除数端点))-1，正被除数结果为 [0,min(maxDividend,K)]，负被除数结果为 [-min(abs(minDividend),K),0]，跨 0 时取两部分 union；JavaScript -0 在正式 JSON integer 契约中规范为 0。

字符串枚举最多 32 个精确 UTF-8 值，只可用于严格比较、helper 参数和 switch，不参与算术、输出或直接 truthiness 条件；必须先通过严格比较产生 BoolSet。switch 最多 16 个唯一 case，必须有 default，每个 case 终止返回，不允许 fallthrough。

### S.8 固定 bundle、adapter 与确定性证据

capture entry 固定导出唯一 ASCII binding __selected。esbuild 配置逐字段固定为：

~~~json
{
  "bundle": true,
  "treeShaking": true,
  "format": "esm",
  "platform": "neutral",
  "target": "es2022",
  "write": false,
  "minify": false,
  "metafile": true,
  "sourcemap": false,
  "legalComments": "none",
  "external": [],
  "charset": "utf8",
  "logLevel": "silent",
  "resolveExtensions": [],
  "mainFields": [],
  "conditions": [],
  "packages": "bundle",
  "tsconfigRaw": {"compilerOptions": {}}
}
~~~

absWorkingDir 必须显式设置为本次 0700 隔离临时根，entryPoints 精确为相对路径 __reweave_capture_entry__.js。自定义 snapshot resolver 是唯一 resolver：只查 S.6 已冻结的 resolution map；自定义 loader 只返回与登记 SHA 匹配的快照 bytes；bare package、默认 extension、main field、conditions、node_modules 和任何 fallback filesystem read 都失败。packages 虽固定为 bundle，但没有 bare specifier 可以到达 esbuild 默认 package resolver。

warning 数组或 stderr 非空即失败；只能产生一个 JavaScript output；output imports 必须为空；metafile input 不得越过已证明的 module-evaluation closure，且必须覆盖 selected symbol closure；metafile.outputs[output].exports 必须精确等于 ["__selected"]。bundle 后 AST 再确认只有一个名为 __selected 的 named export，没有 default、额外 export 或 re-export。

esbuild 只能从 snapshot resolution map 读取模块。随机临时路径不得进入输出；相同快照、选择、工具版本和选项必须生成逐字节相同的 selected.js。selected.js 最大 1 MiB。

需要区分两种 bundle：

- selected bundle 是 source graph capture 产生并作为 __reweave_capture__/selected.js 保存的字节，摘要名为 selected_bundle_sha256。
- execution bundle 是从精确 selected.js 与固定 adapter 再机械生成、实际交给 Node 的最终执行字节，摘要名为 execution_bundle_sha256。

execution bundle 使用同样的固定 resolver/无 external 配置，对其精确字节运行 node --check 和统一 bundle AST 安全分析。preflight 与正式 runtime 都从 candidate_payload_json 解析两模块，重新生成 execution bundle，核对 execution_bundle_sha256 后把同一字节写入 worker 临时文件；写后重读 hash 不同即拒绝。execution bundle 是确定性派生证据，不替代 selected.js 和 adapter 参与 canonical hash。

execution bundle 的机械 profile 固定为 `bundle=true`、`treeShaking=true`、`format=iife`、`globalName=ReweaveCandidate`、`platform=neutral`、`target=es2022`、`write=false`、`minify=false`、`metafile=true`、`sourcemap=false`、`legalComments=none`、`external=[]`、`charset=utf8`，并把 `resolveExtensions/mainFields/conditions` 固定为空、`packages=bundle`、`tsconfigRaw.compilerOptions={}`。它使用另一个 0700 临时 `absWorkingDir` 和只识别上述两模块的内存 resolver；不得读取默认文件系统、package 或来源目录。warning、额外 output、output import、非两模块 metafile input、超过 1 MiB、随机临时路径进入输出或二次生成 hash 不同均失败关闭。

正式 adapter v2 精确包含：

~~~text
__reweave_capture__/selected.js
__reweave_adapter__/compute.js
~~~

两模块限制只适用于 candidate_origin=deterministic_computation_adapter 且 adapter_contract_version=computation_adapter.v2。普通 computation 继续使用原有模块契约。

安全 offer 示例：

~~~json
{
  "schema": "computation_adapter_offers.v2",
  "project_id": "js-owner-id",
  "source_graph_version": "source_graph.v1",
  "scope_snapshot_sha256": "...",
  "source_identity_sha256": "...",
  "offers": [
    {
      "offer_id": "...",
      "module_relpath": "src/quote.js",
      "export_name": "calculate",
      "export_name_codepoints": "U+0063 U+0061 U+006C U+0063 U+0075 U+006C U+0061 U+0074 U+0065",
      "leaf_binding_hash": "...",
      "parameters": [
        {"parameter_binding_id": "...", "display_name": "quantity"}
      ],
      "dependency_summary": {
        "module_count": 2,
        "helper_count": 1,
        "constant_count": 1
      },
      "status": "needs_configuration",
      "blockers": []
    }
  ]
}
~~~

不向前端返回源码、绝对路径、字符串枚举原值或业务字面量。客户端提交 offer_id 和 parameter_binding_id；路径、函数名、hash、模块列表、规则版本和 canonical hash 均不具权威性。

发布版本 extraction_summary_json 至少保存：

~~~json
{
  "candidate_origin": "deterministic_computation_adapter",
  "source_graph_version": "source_graph.v1",
  "adapter_contract_version": "computation_adapter.v2",
  "bundle_contract_version": "reweave_capture_bundle.v1",
  "bundle_tool": {"name": "esbuild", "version": "..."},
  "source": {
    "project_id": "...",
    "git_state": "dirty_git",
    "commit": "...",
    "scope_snapshot_sha256": "...",
    "source_identity_sha256": "..."
  },
  "selected_function": {
    "module_relpath": "src/quote.js",
    "public_export_name": "calculate",
    "export_token_sha256": "...",
    "leaf_binding_hash": "..."
  },
  "dependency_closure": {
    "module_count": 2,
    "binding_count": 4,
    "evidence_sha256": "...",
    "top_level_evidence_sha256": "..."
  },
  "mapping_sha256": "...",
  "generated_modules": {
    "selected_sha256": "...",
    "adapter_sha256": "..."
  },
  "examples": {
    "count": 1,
    "canonical_sha256": "...",
    "passed": true
  },
  "worker": {
    "contract_version": "...",
    "result_sha256": "...",
    "passed": true
  }
}
~~~

selected.js 和 adapter 的精确字节、activation、input/output/error contract、runtime allowlist 和既有 scope 直接参与 canonical hash。来源路径、commit、source graph、闭包证据、用户决定、样例 hash、worker 时间和工具版本只用于追溯与 freshness；它们不直接改变内容 hash。

### S.9 敏感、品牌与枚举确认的持久化边界

生成产物的固定顺序为：

~~~text
内存 source graph
→ 临时目录生成 selected.js 和 adapter
→ canonical 结构、语法、adapter AST、DSL、execution bundle 统一 AST 安全、
  data contract 和 source freshness
→ 固定敏感、品牌和枚举扫描
→ 需要确认时只保存 hash、计数和安全摘要
→ 用户决定绑定当前来源和工具证据
→ 用户重新提交映射和样例
→ 重新快照、建图、生成和复跑门禁
→ 全部门禁通过后才允许写入候选模块
~~~

在敏感门通过前，selected.js、adapter、枚举原值和业务样例不得进入 SQLite、日志或模型 prompt。waiting/rejected 行不保存映射原值、枚举原值、样例原值或模块源码。

固定扫描语料精确为 selected.js、固定 adapter、规范化 input/output/error contract 和本次仍驻留内存的业务样例；不扫描来源范围内未进入 selected symbol closure 的无关源码，也不把上述语料发送给 Ollama。secret 直接拒绝。computation_adapter.v2 不允许重写来源或生成产物，因此模糊敏感内容只允许 `confirm_fictional_fixture` 或 `confirm_real_record_reject`，不允许 `confirm_safe_redaction`；品牌命中只允许 `retain_brand_limited`，不允许 `remove_brand`；字符串枚举只允许 `confirm_selected_string_enumeration`。确认真实记录后返回安全的 terminal rejected outcome，且绝不运行 preflight。

包含 selected.js、adapter 或 execution bundle 的临时目录只能创建在应用私有临时根，目录权限为 0700、文件为 0600，不得位于 state_dir、backup 目录或来源目录。waiting、rejected、cancelled、failed、timeout、异常和正常完成都在 finally 中删除；应用启动时只清理由本应用固定 marker、当前用户 owner 和路径边界共同证明的陈旧 capture 目录，不能遍历或删除其他临时目录。

服务端 offer 状态只有 needs_configuration、unsupported、stale、consumed。capturable 只是前端派生展示，needs_confirmation 属于 linked waiting_user review，不属于 offer 状态。

枚举确认流程固定为：

~~~text
offer needs_configuration
→ 用户提交映射和样例
→ 需要确认时创建安全 waiting_user review
→ offer consumed
→ 未重启时用户查看当前本机临时枚举并通过 review_id 作决定
→ 若决定前已重启，先重新扫描、重建并重新展示当前精确枚举
→ 绑定一致后才允许通过 review_id 作决定
→ 重新提交映射和样例，同时携带 review_id
→ 服务端从当前来源完整重建
→ 决定 binding 完全一致才继续
~~~

全部枚举参数一次确认，摘要为：

~~~text
enumerations_digest =
SHA-256(canonical JSON [
  {
    "parameter_binding_id": "...",
    "values": ["..."]
  }
])
~~~

外层按 parameter_binding_id 排序，values 按精确 UTF-8 字节序排序。waiting 阶段只保存枚举数量和 digest；确认后仍从当前快照重新推导精确值，不能从 SQLite 恢复原值。

parameter_binding_id 使用 S.5 的稳定 binding_id：函数 leaf_binding_hash + 参数源码 ordinal + 参数 declaration binding hash。重扫后身份相同才可能复用决定；决定前重启时只凭 count/digest 不能确认。

enum_decision_binding_sha256 覆盖 source identity、selected function、selected bundle、mapping、业务样例 digest、enumerations、source graph/adapter/bundle contract、TypeScript 版本、esbuild 版本、selected/execution bundle options digest、redaction rules、brand profile id/digest。来源、映射、样例、枚举、工具或品牌证据任一变化都使旧决定失效。

capture v2 的决定写入还必须经过两层仅驻留进程内存的随机授权：Stage E 在当前完整重建后把 `review_id + decision_binding_sha256` 绑定到一次性 token，通用 intake 决定入口必须同时核对当前 binding 与 token，成功后立即消费。token 不进入 SQLite、日志或 QWebChannel。应用重启后 token 必然消失；用户必须携带 review_id 重新扫描、重新提交映射和样例并完成当前证据重建，服务端才会签发新的单次授权。客户端只持有 binding 不能直接调用通用决定入口绕过重建。

### S.10 首次执行前安全门与 adapter preflight

两份模块生成后，第一次执行前必须调用与 shared_stage3_gate 共用的 capture_static_gate 纯函数，顺序唯一固定为：

1. canonical JSON bytes 与候选结构检查。
2. selected.js、adapter 和生成后 execution bundle 的 JavaScript 语法检查。
3. 固定 adapter AST 结构检查。
4. source graph、selected bundle 和传递 helper 的 DSL 证明。
5. 对精确 execution bundle 做 node --check 与统一 AST 安全分析。
6. data_contract.v1 规范化和兼容检查。
7. 重验当前 source_identity freshness。
8. 重新运行敏感、品牌和字符串枚举扫描。
9. 若当前证据需要决定，重新计算 decision binding 并与持久决定比较；null 只有在当前扫描明确无需决定时才合法。
10. 需要人工决定时立即创建安全 waiting review 并停止。
11. 决定有效时才运行 adapter_example_preflight。

任何失败都不得执行候选代码。

`capture_static_gate` 必须接收服务端当前的不可变 `JavascriptScopeSnapshot`，并验证 payload 的 project、source identity 与 scope snapshot 全部精确相等。门内必须从 mapping 重建 parameter domain，再以同一快照重新运行 source graph、DSL proof 和固定 capture；target binding、参数顺序、结果区间、symbol/module/top-level evidence、selected 字节、capture entry、工具/options、module-evaluation/symbol/metafile 路径必须逐项相等。仅仅让 payload 内部 hash 自洽不能通过该门。

preflight receipt 固定为：

~~~json
{
  "validation_scope": "adapter_example_preflight",
  "formal_runtime_evidence": false,
  "candidate_payload_sha256": "...",
  "execution_bundle_sha256": "...",
  "examples_sha256": "...",
  "worker_contract_version": "...",
  "passed": true
}
~~~

preflight 从最终 candidate_payload_json 解析精确模块字节，不接受第二份模块副本。它只检查用户参数映射、业务样例、来源函数异常和输出整数范围；不写正式 runtime_validation_json，不能满足 exact duplicate、发布或正式 runtime evidence。

preflight 使用现有 computation worker，worker stdout 必须精确符合 `compute_validation.v1`：顶层键只能是 `schema_version`、`status` 和 `cases`。preflight receipt 的 `worker_contract_version` 必须精确记录该值；`runtime_validation.v1` 或其他看似 passed 的 schema 不能冒充 worker 结果。

preflight 返回后、构造 PreparedReview 前必须再次从 JS owner 执行完整 scope scan，并逐字段核对 source identity、scope snapshot、Git evidence、symlink 集合和全部模块摘要。worker 运行期间发生任何来源变化都返回 `source_changed`；不得以 preflight 已通过为由接受旧字节。

### S.11 真正不可变的 PreparedReview

唯一内部对象固定为：

~~~python
@dataclass(frozen=True)
class PreparedReview:
    run_id: str
    review_id: str | None
    candidate_id: str
    project_id: str
    source_identity_sha256: str
    decision_binding_sha256: str | None
    candidate_payload_json: bytes
    rule_versions_json: bytes
    preflight_receipt_json: bytes
~~~

三个 JSON 字段必须是 canonical JSON UTF-8 bytes。bytes 不包含可被原地修改的 dict/list/Mapping，只能由服务端工厂创建。工厂 parse 后重新 canonicalize；输入字节不一致时拒绝。客户端不能提交模块、规则版本、canonical hash 或 preflight receipt。

工厂还必须交叉核验：`project_id` 与 payload 一致；`candidate_id` 等于 payload SHA-256 的固定派生值；rule_versions_json 与 payload 中唯一的 rule_versions 对象逐字段相等；receipt 只含正式列出的七个字段，且 candidate、execution bundle、examples digest 和 worker contract 全部与 payload/当前规则一致。工厂再次运行不执行代码的 capture_static_gate 并核对 execution bundle；伪造 source graph、closure、selected bundle、tool/options、brand evidence 或 receipt 均失败关闭。

`preflight_receipt_json` 的 origin 语义固定：`candidate_origin=deterministic_computation_adapter` 且 `adapter_contract_version=computation_adapter.v2` 时必须是第 S.10 节完整、合法且 `formal_runtime_evidence=false` 的 receipt；所有普通 presentation/interaction/computation 候选必须精确使用 canonical JSON `null`，即字节 `b"null"`。`process_review` 不得为普通候选合成 passed receipt，`shared_stage3_gate` 必须按 origin 交叉验证并拒绝相反形态。

candidate origin、source identity、selected binding/export token hash、dependency closure/top-level evidence hash和 selected/adapter/execution module hash保存在 candidate_payload_json 的既有追溯结构中；source graph/adapter/bundle contract、TypeScript/esbuild 版本和 bundle options hash保存在 rule_versions_json。不得为这些字段增加第四组 bytes 接口；shared gate 必须将两组内容与当前来源证据交叉核对。

preflight 从 candidate_payload_json 解析模块；shared_stage3_gate 每次也从这些 bytes 解析全新对象，并重新计算 canonical hash。任何 preparation 或客户端 hash 都不具权威性。

PreparedReview 不序列化到 SQLite、日志、QWebChannel 或模型 prompt。等待、失败、取消、进程退出或来源变化后直接丢弃。

### S.12 唯一 shared Stage 3 核心

现有 Stage 3 必须提取一个共用核心：

~~~text
process_review(review_id)
→ 从 SQLite 加载已有完整候选
→ 构造 PreparedReview
→ shared_stage3_gate(prepared)

process_ephemeral_capture(prepared)
→ shared_stage3_gate(prepared)
~~~

禁止复制第二套 security、canonicalization、supervision、runtime 或 equivalence 逻辑。

shared_stage3_gate 固定顺序：

1. 从三组 canonical bytes 解析全新对象并重验结构。
2. 调用 S.10 同一个 capture_static_gate，依次重复语法、adapter AST、DSL、execution bundle 统一 AST 安全、data contract 和 source identity freshness。
3. 重新运行敏感、品牌、枚举扫描；重新计算 decision binding，确认 null/已决定与当前证据完全一致。
4. 重新计算 canonical hash。
5. 查询 origin 兼容且证据当前的 exact duplicate。
6. 未重复时调用 loopback Ollama。
7. Ollama 通过后用精确 execution bundle 运行正式 runtime validation。
8. 运行等价/变体比较。
9. 返回结构化 outcome。

正式顺序始终是 exact duplicate → Ollama → runtime validation；preflight 不属于这条正式证据链。

rejected、waiting_user、waiting_model、waiting_validation 和 preflight failure 只写安全摘要，并写：

~~~text
resume_contract = resubmit_ephemeral_capture.v1
~~~

这些状态不保存模块。应用重启后对该行调用 process_review 返回 capture_resubmission_required，用户必须重新扫描并重新提交映射和样例。

只有全部确定性门禁通过、Ollama 通过或 exact duplicate 合法短路、正式 runtime validation 通过或 duplicate 合法免跑，以及最终来源身份一致时，才能持久化模块。模块、证据和最终 candidate status 在一个事务中写入。review_required 可以保存模块，因为此时仅剩人工身份、等价或变体决定；正式 capsule/version 仍由后续现有发布事务创建。

### S.13 Exact Duplicate 的事务内复核

事务外 duplicate outcome 必须携带：

~~~json
{
  "target_capsule_id": "...",
  "target_version_id": "...",
  "target_canonical_hash": "...",
  "target_evidence_fingerprint": "..."
}
~~~

target_evidence_fingerprint 覆盖 candidate origin、extraction contract、redaction rules、adapter/source graph/bundle contract（不适用时显式 null）、TypeScript/esbuild/bundle options（不适用时显式 null）、security rules、supervision rules和模型 digest、validation contract、canonicalization version、当前 decision binding/brand profile 证据、version ID 和 canonical hash。

持久化 duplicate 时：

1. BEGIN IMMEDIATE。
2. 按 target_capsule_id + target_version_id 重新读取。
3. 确认 capsule status=active。
4. 确认 current_version_id=target_version_id。
5. 确认 canonical hash 相同。
6. 确认 prepared.candidate_origin 与 target candidate origin 精确相同。
7. 重新运行 redaction/brand/enumeration freshness，确认 prepared decision binding 仍有效。
8. 重新计算 evidence fingerprint。
9. 确认 extraction、source graph、adapter、bundle/tool/options、redaction、security、supervision/model digest、validation 和 canonicalization 全部仍为当前版本；不适用字段必须显式 null。
10. 全部满足后才追加 capsule_sources 和 duplicate review outcome。

任一不符返回 exact_duplicate_target_expired；不得追加 capsule_sources、不得写 duplicate 状态，也不得在同一事务中寻找或改选另一个目标。调用方只能重新运行完整 Stage 3。

extraction、source graph、adapter、bundle/tool/options、redaction、security、supervision/model digest、validation、canonicalization、decision binding 或 brand profile 任一过期时都禁止 exact duplicate。

### S.14 状态机、失败码与重启语义

项目状态沿用：

~~~text
discovered_unconfirmed → ready
ready → source_missing | unsupported_v1
source_missing → ready
~~~

JS 扫描任务沿用 intake run 状态：

~~~text
queued → running
running → completed | completed_with_pending | no_change
running → failed | cancelled | interrupted
~~~

应用重启时 queued/running 统一转 interrupted；未提交的索引不发布，source graph、offer 和 PreparedReview 全部丢弃。

offer 进程内状态只有：

~~~text
needs_configuration → consumed
needs_configuration → stale
needs_configuration → unsupported
~~~

linked waiting review 是候选主线状态，不增加 offer 的 needs_confirmation。候选和正式胶囊继续使用正文既有状态机，不建立第五套状态引擎。

固定失败码至少包括：

- 来源/索引：source_changed、source_unavailable、source_platform_unsupported_v1、source_scope_limit_exceeded、source_scope_symlink_forbidden、source_path_normalization_conflict、import_path_spelling_mismatch、duplicate_javascript_source_scope、scan_cancelled。
- 图/闭包：offer_stale、source_utf8_invalid、source_span_invalid、closure_unproven、closure_symlink_forbidden、mutable_capture、top_level_side_effect、top_level_initializer_unproven、dynamic_dependency、unsupported_control_flow、invalid_export_identifier、interval_unproven。
- 生成/门禁：adapter_mapping_invalid、adapter_example_mismatch、adapter_source_exception、sensitive_content_confirmation_required、string_enumeration_confirmation_required、brand_confirmation_required、bundle_nondeterministic、bundle_security_rejected、worker_timeout、worker_failed、adapter_contract_version_expired。
- 恢复/竞态：capture_resubmission_required、exact_duplicate_target_expired。

未知结果统一为 unclassified_internal_result 并失败关闭。环境失败和来源不支持必须分开统计。

### S.15 桌面流程、服务接口与源码查看

应用服务新增：

~~~text
register_javascript_computation_source(payload)
start_scan_javascript_computations(project_id)
start_create_computation_adapter(payload)
~~~

桌面 QWebChannel bridge 沿用现有 Python `snake_case` slot，不建立第二套 camelCase 别名：

~~~text
register_javascript_computation_source
start_scan_javascript_computations
start_create_computation_adapter
~~~

project_id 可以来自 static 或 JS 行，服务端始终解析为唯一 JS owner。客户端提交的路径、函数名、hash、模块列表、source graph 或规则版本不作为权威证据。

JS-only/子目录登记只接受：

~~~json
{
  "source_root_id": "root-id",
  "project_relpath": "packages/pricing",
  "display_name": "Pricing computation"
}
~~~

source_root_id 必须来自现有只读绑定根；project_relpath 使用 S.4 路径规则，"." 表示整个根。服务端重新 resolve、执行父子排除和唯一 owner 创建；前端不能提交 source_type、entry_relpath、resolved path 或 project_id。返回唯一 JS owner 的 project_id。static 行直接扫描时不经过该公开 payload，而由服务端解析同物理范围 owner。

创建/重提交 payload 精确为：

~~~json
{
  "project_id": "js-owner-id",
  "offer_id": "opaque-offer-id",
  "review_id": null,
  "arguments": [
    {
      "parameter_binding_id": "...",
      "input_field": "quantity",
      "kind": "integer",
      "minimum": 0,
      "maximum": 10000
    }
  ],
  "result_field": "total",
  "examples": [
    {"input": {"quantity": 4}, "expected": 20}
  ]
}
~~~

首次提交 review_id 必须为 null；重启恢复时必须提供当前重扫得到的新 offer_id 和既有 waiting review_id。服务端只从当前 offer 解析参数、闭包和枚举。需要决定时返回 offer_status=consumed、candidate_status=waiting_user、review_id 和 resume_contract=resubmit_ephemeral_capture.v1；决定接口继续使用现有 decide_review_item，但服务端必须从当前临时重建证据计算 allowed_decisions，枚举决定不在列表时拒绝。成功只返回候选安全摘要，不返回模块。

桌面流程固定为：

~~~text
项目或子目录
→ 扫描计算函数
→ 查看可抓取、需配置、需确认、暂不支持
→ 查看函数参数、helper、常量、模块数和阻断原因
→ 选择目标函数
→ 配置整数、boolean 或已确认枚举输入
→ 配置范围、输出字段和业务样例
→ 查看将抓取的依赖摘要
→ 必要时完成枚举/敏感/品牌确认
→ 创建候选
→ 现有监督、验证、复核和发布
~~~

不提供自由 JavaScript 编辑器。“查看源码位置”只由 native bridge 根据当前 offer/node identity 临时解析本地文件和行列；源码不进入 SQLite、不缓存到前端、不发送未经确认的原文给 Ollama。来源变化时显示 offer_stale。

### S.16 兼容、v1 退役与恢复

static_web、普通 extraction_contract.v2 和普通 computation 保持原路径。新 JS 抓取路径在 SQLite v2、owner/index、source graph、安全、ephemeral Stage 3、桌面和第三方验收全部通过前，不进入用户正式生成活跃路径。

computation_adapter.v1 在 v2 第三方验收通过前继续是唯一活跃 adapter 路径，不建立长期双路径开关。验收通过并由用户确认硬切换后：

1. 创建并验证完整仓库备份。
2. 禁止创建新的 v1 offer/candidate；旧入口返回 adapter_creation_path_retired。
3. 未发布 v1 候选保持原 candidate_status 和不可变历史内容；服务端读取 candidate_origin/adapter_contract_version 时派生 adapter_contract_version_expired，禁止继续 process 或 publish，UI 显示需要重新扫描。不得增加 expired 状态或改写历史行。
4. 只将 current evidence 明确为 computation_adapter.v1 的 active-current 置为 pending_revalidation。

事务内使用：

~~~sql
UPDATE capsules
SET status = 'pending_revalidation'
WHERE capsule_id = ?
  AND current_version_id = ?
  AND status = 'active';
~~~

仅 rowcount=1 时写绑定该 version 的 revalidation_required。普通 computation、历史版本、disabled、已 pending 和 adapter v2 不受影响。旧产品与 manifest 不改写。恢复旧备份后先在 candidate 上执行已测试迁移，恢复完成后重新执行同一 v1 退役门。

### S.17 文件级实施范围与阶段门

阶段 0 唯一仓库文件：

- docs/REWEAVE_CAPSULE_INGESTION_DESIGN.md。

后续批准后的最小实施范围：

- pimos_lite/reweave_capsule_store.py：SQLite v2、迁移、fingerprint、备份恢复。
- 新增 pimos_lite/reweave_javascript_source.py：唯一 JS owner、索引、摘要、快照和资源门。
- 新增 scripts/analyze_reweave_source_graph.mjs：lexical graph、UTF span、闭包、DSL 和区间证明。
- pimos_lite/reweave_capsule_intake.py：offer、映射、bundle、adapter 和敏感顺序。
- scripts/analyze_reweave_security.mjs 与 pimos_lite/reweave_capsule_stage3.py：固定 adapter 检查、PreparedReview、共享 Stage 3、重建和 freshness。
- pimos_lite/reweave_app_service.py、pimos_lite/desktop_reweave_static.py、reweave_frontend/app.js：服务端动作、桥接和管理 UI。
- pimos_lite/composer/module_native.py：仅增加 adapter v2 的条件式两模块复检。

不新增依赖、公开 CLI、repository、composer、worker 框架或运行时 fallback。

实施阶段固定为：

1. 阶段 0：只修订本文、运行三个 /private/tmp 探针、做限定 diff 复核。
2. 阶段 B：只实现 SQLite v2、迁移、exact fingerprint、备份恢复和失败注入；不迁移用户正式仓库。
3. 阶段 C：唯一 JS owner、文件索引、摘要和来源锁；功能门只要求 macOS/Linux 正向工作，Windows 要求结构化 `source_platform_unsupported_v1` 且零来源读取、零索引写入。
4. 阶段 D：source graph、UTF span、闭包、DSL 和静态区间证明；不生成候选。
5. 阶段 E：固定 capture、bundle、adapter、执行前安全门、敏感/品牌/枚举和 preflight。
6. 阶段 F：唯一 shared Stage 3、应用服务、桌面和条件式 composer 复检。
7. 阶段 G：固定第三方验收与 v1 硬切换决定。

每阶段失败都保持上一条活跃路径不变，不通过运行时双路径开关绕过阶段门。

### S.18 阶段 0 探针、自动测试与第三方验收门

三个阶段 0 探针只使用 Python 标准库、本地 stub outcome 和 /private/tmp；不导入、模拟通过或声称验证尚未实现的生产 shared_stage3_gate。

探针 1：逐字使用 S.3 的 project_file_index DDL 与 owner insert trigger（只以最小 projects 父表承载外键），断言合法 module 行通过，NULL size/hash、BLOB size/hash、空 hash、大写 hash、非十六进制 hash、非法 symlink 字段和 static owner 均被 SQLite 拒绝。完整 schema 的 15/11/34 与 fingerprint 探针属于阶段 B，不由本最小探针冒充。

探针 2：

1. 首次提交产生安全 waiting_user review。
2. 用唯一 sentinel 表示源码、枚举和样例；关闭连接后检查 review JSON、数据库原始字节、journal/WAL/SHM sidecar、备份和探针日志都不含 sentinel。
3. waiting 阶段模型和 worker stub 调用计数必须均为 0。
4. waiting、cancel 和异常路径都断言私有 capture 临时目录已清除。
5. 清空内存 offer、graph 和 PreparedReview 模拟重启。
6. 重新扫描、重建并在本地临时视图重新展示当前精确枚举；不能只凭 count/digest 决定。
7. 用户通过 review_id 保存决定，再重新提交相同映射和样例。
8. binding 完全一致才生成 canonical JSON byte payload。
9. 仅本地 stub success outcome 后允许一个事务写入模块。
10. 修改源码、映射、枚举或 TypeScript/esbuild/bundle options 版本都必须拒绝。

探针 3：两个 source root 并发指向同一物理目录，最终只能产生一个 JS owner并返回同一 project_id；注入历史重复 owner 后，启动检查必须禁止扫描。

真正的 production 测试放在阶段 F，必须证明 process_review 和 process_ephemeral_capture 调用同一个 shared_stage3_gate，并覆盖正式门序、preflight 非正式证据、duplicate 事务竞态和模块延迟持久化。

后续自动测试还必须覆盖 JS-only、大仓库和子目录、多函数同模块、同/跨模块 helper、不可变常量、Unicode/CRLF span、无关危险函数被 tree-shake、顶层副作用仍拒绝、mutable capture、分支/Math 白名单、动态调用/递归/循环/DOM/network/storage、无关/闭包 symlink、source changed、stale offer、bundle 确定性、dirty/non-Git identity、canonical hash、来源零写入和用户正式仓库零写入。

第三方验收最多冻结 12 个新项目，并只在受支持的 macOS/Linux 抓取平台执行。运行前按 repository URL 和完整 commit 排序并冻结 manifest；每项记录 URL、full commit、许可证、选定 scope、clean Git 和来源整树 SHA-256。失败后不替换项目；不安装、不构建、不运行来源项目命令或入口、不修改来源。候选 bundle 只能在本文隔离 worker 中执行，这不等同于执行来源项目。Windows CI 只验证结构化不支持结果、零来源读取和零索引写入，不计作第三方正向验收。

全部 checkout、临时 SQLite、产品和原始证据只能位于 /private/tmp；验收前后记录每个来源树摘要/Git 状态以及用户正式 state_dir 的摘要，二者必须分别不变。mapping、枚举/敏感决定和至少一个发布决定必须通过真实桌面管理流程完成，脚本不能代替人工确认。

至少三个独立项目必须达到 validated_positive，即分别通过 source graph、bundle、敏感/品牌/枚举确认、data contract、AST 安全、Ollama 和正式 Node runtime validation。至少一个还要成为临时仓库 active-current，与现有 presentation/interaction 组合，并在真实 QWebEngine 完成输入、点击、业务结果、事件一次、无网络和无根外 mutation 断言。只形成 candidate 不算成功。

12 项耗尽仍未满足时：

~~~text
javascript_computation_capture = PARTIAL
do_not_cut_over_computation_adapter_v1
~~~

不得扩大 DSL、实施 Bootstrap V3、加入 wrapper/template/fallback 或用自制项目冒充外部能力。

阶段 0 完成门：

- 本附录全部契约进入正式文档。
- 三个 /private/tmp 探针通过。
- 限定 diff 只包含本附录，没有业务代码新增修改。
- 未发现新增可复现 P0/P1。
- 不 commit、不 push。

阶段 0 执行记录（2026-07-17）：

- 开始修改前的完整工作树 patch 已保存为 `/private/tmp/reweave-stage0-before.patch`，SHA-256 为 `e3fd0f822b70a8fbc5221d0b32028ca55d2eb5dcb73a757a14e6680243cceca7`。
- 契约探针脚本位于 `/private/tmp/reweave-stage0-contract-probes.py`，SHA-256 为 `74a80746d76bed5253a7ec7b8cd33de6b807a5e76e7c2cd3c2b9d1f8819b7117`；它只使用 Python 标准库、本地 stub outcome 和 `/private/tmp`，未导入或声称验证生产 `shared_stage3_gate`。探针中的 `PreparedReview.rule_versions_json` 同时冻结 source graph、adapter、bundle contract、TypeScript、esbuild 和 bundle options 证据，并断言三类工具证据任一变化都会改变该 canonical bytes。
- 探针 1 通过：接受 2 条合法索引记录，拒绝 7 条 NULL、空、大写、非十六进制、非法 symlink 或错误 owner 记录。
- 探针 2 通过：完成 waiting review、重启后重新提交、binding 复核、延迟模块持久化和 6 类证据变更拒绝；`production_stage3_called=false`，waiting 阶段模型和 worker 调用均为 0，并验证 4 类临时捕获清理路径。
- 探针 3 通过：两个并发 source root 返回同一个 JS owner，建立 owner 前只有 1 个物理范围 owner；注入历史重复 owner 后扫描被阻断。
- 三项限定审阅分别覆盖 SQLite/迁移、source graph/安全/Stage 3、桌面/重启/临时文件边界，结论均为 `CLOSED`；在本阶段冻结范围内没有剩余可复现 P0/P1。
- 机械复核通过：`git diff --check` 无输出，附录 S Markdown fence 成对；本轮只修改本文，没有修改业务代码、测试、Git 分支或既有未提交文件集合。
- 本轮没有 commit 或 push。生产 `shared_stage3_gate`、SQLite v2 迁移和真实第三方验收仍属于后续阶段，不能由阶段 0 探针替代。

阶段 0 当前执行状态：

~~~text
PASS
STAGE_B_ELIGIBLE_NOT_STARTED
~~~

### S.19 阶段 A–C 最新修复与复核记录（2026-07-17）

本节只更新阶段 A–C 的当前实现事实和阶段 D 进入门，不实施阶段 D，也不改写 S.18 形成时的历史状态。

- 阶段 A：`PASS`。三项阶段 0 契约探针在 Python 3.11/3.14 均通过；最新探针 SHA-256 见 S.18。
- 阶段 B：`PASS`。`enum_decision_binding_sha256` 与 `project_file_index.content_sha256` 现由 DDL 的 `typeof='text'`、64 位小写十六进制 CHECK 与永久不变量共同约束，`project_file_index.size_bytes` 由 `typeof='integer'` 约束；BLOB 类型在写入和恢复验证两处均被拒绝。活动 v2 数据库损坏时恢复 v1 备份会在私有 candidate 上迁移到当前应用目标 schema v2，不再降级。v2 exact schema fingerprint 更新为 `2f5c245eee172d57abc065d1c63ad76e11925aec6a021d586a9384c4cbde2ada`。
- 阶段 C 安全边界：在具备 descriptor-relative 原语的平台上为 `PASS`。来源根一次打开后，所有递归枚举和读取都锚定 descriptor；最终 JS snapshot 后再次取得 Git evidence，并要求与前一份完全一致后才写索引和形成 source identity。根/父目录 symlink ABA、regular→FIFO 阻塞竞态、最终 Git/快照窗口、来源 PATH Git、worktree/info attributes clean filter、Git 输出剪枝和来源字节 repr 泄漏均有回归并通过。
- 阶段 C 产品范围：`PASS`。用户已批准 `javascript_computation_capture.v1` 首版只支持 macOS/Linux；Windows 主应用继续受支持，但抓取动作必须在来源读取和索引写入前结构化返回 `source_platform_unsupported_v1`。这不是跳过 Windows 测试：Windows CI 必须验证固定错误码、零来源读取、零索引写入和主应用既有能力不回归；不得恢复 path-based walker。

最终字节快照验证：

- Python 3.11 全量：`625 passed, 1 skipped, 180 subtests passed`；skip 是不安装 PySide6 的 CI 桌面门。
- Python 3.14.5 + PySide6 6.11.1 全量：`626 passed, 180 subtests passed`。
- 本轮修复后的阶段 B/C 聚焦门在 Python 3.11 和 3.14 均为：`72 passed, 57 subtests passed`。
- 本轮 Node 22.22.3 对前端和两个分析脚本的 `node --check`、Python 3.14 compileall、公开 CLI help 与 `git diff --check` 均通过；本轮未修改这些 JavaScript 字节，既有 Node 24.14.0 语法证据仍对应同一内容。
- 当前修复未 push，因此没有触发这组字节的 GitHub 托管 Windows runner；该项保留为 checkpoint/发布前 P2，不冒充远端 Windows 已执行，也不阻断只实现 source graph 的阶段 D。
- 本轮没有运行来源项目命令、没有修改来源项目、没有写用户正式仓库、没有 commit 或 push。

当前阶段门：

~~~text
STAGE_A_PASS
STAGE_B_PASS
STAGE_C_PASS_POSIX_CAPTURE_WINDOWS_STRUCTURED_UNSUPPORTED
STAGE_D_ELIGIBLE_NOT_STARTED
~~~

### S.20 阶段 D 实现与封板记录（2026-07-17）

阶段 D 只实现独立的 `source_graph.v1` 分析与证明 worker，没有生成 capture、bundle、adapter 或候选，也没有接入 SQLite、Stage 3、应用服务、前端或 `module_native`。阶段 E 尚未开始。

实现范围：

- `scripts/analyze_reweave_source_graph.mjs`：只消费 stdin 中的一致性快照字节，建立 TypeScript lexical symbol graph，完成严格模块解析、UTF-16/UTF-8 span、依赖闭包、计算 DSL 和静态区间证明。
- `tests/test_reweave_source_graph.py`：覆盖合法闭包、失败关闭、Unicode/BOM/CRLF、路径冲突、symlink、alias、TDZ、顶层初始化证据、分支、Math 白名单、溢出、递归、循环和动态依赖。
- 发布面审计只登记上述 worker 和测试；没有新增依赖、仓库、组合器、模板、fallback 或运行时双路径。

最终限定审阅修复并锁定：

- 未进入当前执行环境的局部 `const` 和后声明的顶层 const-bound helper 均按 TDZ 失败关闭。
- 重复或多义 public export/re-export 一律拒绝。
- import/export alias 保留真实词法边；动态依赖分类单独解析 semantic leaf，不把合法 helper 误报为 unknown call。
- 未知或不在顶层白名单的 initializer 必须记录 `top_level_execution`。只有固定函数 binding、直接标量字面量和类型正确的一元字面量免除；object、class、除法、零除、溢出和类型错误表达式都保留 `VariableStatement` 证据。

最终冻结字节：

~~~text
scripts/analyze_reweave_source_graph.mjs
SHA-256 8c332705f4536401508ffd20e4efdd018e56c9fa769ae304c8ac98503679514b

tests/test_reweave_source_graph.py
SHA-256 d31769834095b7f5044393a94237f2e7da89d41a9a7974a34c18fcf885854ca5
~~~

验证结果：

- 阶段 D 与发布面聚焦：`76 passed`。
- Python 3.14.5 + PySide6 6.11.1 全量：`697 passed, 180 subtests passed`。
- 隔离副本 Python 3.11.15 + Node 24.18.0 CI 等价全量：`687 passed, 10 skipped, 180 subtests passed`；skip 为显式环境/平台门，不是失败。
- 隔离副本重新执行 `npm ci`；公开 CLI `--help`、前端与 source graph worker 的 Node 24 `node --check`、Python 编译和 `git diff --check` 均通过。
- 最终冻结字节上的限定只读审阅未发现新的可复现 P0/P1。
- 当前字节未 push，未触发 GitHub 托管 Ubuntu/Windows runner；不得把本地 CI 等价结果表述为远端 CI 已运行。

阶段 D 当前状态：

~~~text
STAGE_D_PASS
STAGE_E_ELIGIBLE_NOT_STARTED
P0=0
P1=0
P2=1 hosted Ubuntu/Windows CI pending checkpoint/push
~~~

本阶段没有运行来源项目命令、没有修改来源项目、没有写用户正式状态目录、没有 commit 或 push。

### S.21 阶段 E 实现与封板记录（2026-07-18）

阶段 E 已完成固定 capture、bundle、adapter、首次执行前安全门、敏感/品牌/枚举决定边界与非正式业务样例 preflight。它只产生进程内不可变 `PreparedReview`；唯一 shared Stage 3、Ollama 正式监督、正式 runtime evidence、模块延迟持久化、应用服务和桌面流程仍属于阶段 F。阶段 E 没有把新路径接入生成活跃面，也没有写正式 capsule/version/product 表。

实现范围：

- `scripts/analyze_reweave_source_graph.mjs`：在阶段 D graph/proof 上增加固定 capture mode；使用快照唯一 resolver、固定 TypeScript Factory/Printer entry 与 esbuild profile，输出唯一 `__selected`、完整闭包证据和确定性 selected bundle。
- `scripts/analyze_reweave_security.mjs`：增加 computation adapter v2 的精确两模块 AST 契约、固定 execution bundle profile与 bundle 后统一 AST 复检；普通胶囊不能借用保留路径或 adapter 例外。
- `pimos_lite/reweave_capsule_stage3.py`：增加确定性 adapter、当前快照绑定的 `capture_static_gate`、私有临时根、非正式 preflight、真正不可变的 canonical-bytes `PreparedReview` 和完整 freshness 检查。
- `pimos_lite/reweave_capsule_intake.py`：只为 capture v2 增加 waiting review 的一次性进程内随机授权；既有通用 review 主线和数据库结构不变。
- `tests/test_reweave_source_graph.py` 与 `tests/test_reweave_capsule_stage3.py`：覆盖确定性、跨模块 helper、boolean/enum、经证明的顶层纯 helper initializer、无关危险函数 tree-shaking、当前 snapshot/closure/tool/receipt 防伪、决定重启重建、敏感零持久化、来源变化、首次执行前门序、worker schema、私有临时目录正常/崩溃清理和来源零写入。

限定复核完成并锁定：

- payload 内部自洽不足以通过：静态门会用当前 frozen snapshot 重建 source graph、DSL、closure 和 selected bundle，再逐字段比较证据。
- 任何候选代码首次执行前均已通过语法、固定 adapter AST、DSL、统一 AST 安全和 data contract 门；preflight 使用同一 payload 精确字节，且不能冒充正式 runtime evidence。
- waiting/rejected 仅保存计数、digest 和安全摘要；selected、adapter、枚举值、mapping 与样例不进入 SQLite。重启后必须完整重建才能获得新的单次决定授权。
- capture 临时内容只存在于当前用户私有、带固定 marker 的目录；正常、异常和 timeout 均清理，启动清理只删除 owner、名称、marker、PID 与路径边界全部匹配的遗留目录。
- Stage E 当前没有模块持久化入口；`PreparedReview` 的模块字节仅驻留进程内，正式持久化必须等阶段 F 的唯一 shared gate 完成。

最终冻结验证：

- 进入阶段 F 前的限定复核发现并修复一个品牌配置竞态：preflight 期间有效 brand profile 变化时，所有成功、等待和拒绝 outcome 都必须返回 `brand_profile_changed`，waiting review 写事务内再次核对 profile ID 与 digest，不能把过期的 `general` 结论交给 Stage 3。
- Stage E 聚焦：`85 passed`。
- 阶段 D/E 关联面：`205 passed, 99 subtests passed`。
- Python 3.14.5 + PySide6 6.11.1 全量：`710 passed, 180 subtests passed`。
- 前端与 extraction/security/source_graph 三个分析脚本的 Node 22 `node --check`、Python 3.14 编译、公开 CLI `--help` 和 `git diff --check` 通过。
- 修复上述竞态后的冻结字节通过限定只读复核；没有剩余可复现 P0/P1。
- Python 3.11.15 + Node 24.18.0 隔离 CI 等价全量：`700 passed, 10 skipped, 180 subtests passed`；10 个 skip 均因该 CI 环境不安装 PySide6：8 个 Stage 3 桌面/QWeb 用例、1 个 Phase 5 真实 QWeb 恢复用例和 1 个 Phase 6 桌面端到端用例，不是业务失败。
- 隔离副本执行缓存内 `npm ci --offline`，结果为 added 7、audited 8、0 vulnerabilities；Node 24 对前端和三个分析脚本的 `node --check`、Python compileall、公开 CLI `--help` 与 `git diff --check` 全部通过。共享冻结源与隔离副本的受测文件 checksum 一致。
- 当前字节未 push，未触发 GitHub 托管 Ubuntu/Windows runner；不得把本地 CI 等价结果表述为远端 CI 已执行。

当前阶段门：

~~~text
STAGE_D_PASS
STAGE_E_PASS
STAGE_F_ELIGIBLE_NOT_STARTED
P0=0
P1=0
P2=1 hosted Ubuntu/Windows CI pending checkpoint/push
~~~

本阶段没有运行来源项目命令、没有修改来源项目、没有写用户正式状态目录、没有 commit 或 push。

### S.22 阶段 F 实现与封板记录（2026-07-18）

阶段 F 已把阶段 E 的内存态 `PreparedReview` 接入唯一 Stage 3、现有应用服务、桌面管理界面和唯一 `module_native`。没有复制 security、canonicalization、supervision、runtime 或 equivalence 逻辑；没有新增仓库、repository 工厂、composer、模板、fallback、公开 CLI 或 SQLite DDL。`computation_adapter.v1` 没有在本阶段退役，是否硬切换只由阶段 G 的固定第三方验收决定。

实现范围：

- `pimos_lite/reweave_capsule_stage3.py`：`process_review` 与 `process_ephemeral_capture` 共用唯一 `shared_stage3_gate`；正式门序保持 exact duplicate → Ollama → runtime validation → equivalence。waiting、失败与 preflight 只持久化安全摘要，`review_required` 或合法 duplicate 才在事务内写最终 outcome。
- `pimos_lite/reweave_app_service.py`、`pimos_lite/desktop_reweave_static.py` 与 `reweave_frontend/app.js`：增加 JS source 登记、计算函数扫描、进程内 offer session、服务端权威重建、重启后显式 review ID 重提交和 integer/boolean/enum 映射 UI。前端不能提交来源路径、函数名、hash、模块、规则版本或自由 JavaScript。
- `pimos_lite/composer/module_native.py`：只对 `deterministic_computation_adapter + computation_adapter.v2` 强制精确两模块与正式契约复检；普通 computation 保持原契约。
- 关联测试覆盖 shared gate 调用、模块延迟持久化、preflight 非正式证据、duplicate 事务竞态、重启发布、桌面桥接、前端管理流程和 composer 条件式复检。

最终限定复核修复并锁定：

- selected 与 execution bundle options 都有固定 digest；任一工具或 options 证据过期时，v2 版本不能用于 exact duplicate 或生成。管理服务只把证据过期的 active-current v2 adapter 以 `capsule_id + current_version_id + active` CAS 转为 `pending_revalidation`，不影响 v1 或普通 computation。
- exact duplicate 持久化事务重新核对 active、current version、canonical hash、当前规则、当前监督模型和 evidence fingerprint；目标变化返回 `exact_duplicate_target_expired`，不追加 source、不改选目标。
- v2 duplicate 仍不持久化模块，但事务绑定 retained version、候选 canonical hash、重复来源 snapshot 与 brand profile。用户选择 `semantic_split` 时只复用仍 eligible 的 active-current retained version 正式字节与证据，并再次核对当前模型、来源快照和品牌配置；旧 capsule 原子停用，新 identity 成为 active-current，新的 `published_implementation` source provenance 指向重复来源。
- 进入阶段 F 前发现的 brand profile preflight 竞态、最终 evidence freshness P1 与 duplicate semantic split P1 均有直接回归；同一限定审阅者确认最后一个 finding 为 `CLOSED`，审计到此停止，不扩大到阶段 G。

冻结验证：

- 阶段 F 统一聚焦（semantic split 修复前的完整集成面）：`118 passed, 55 subtests passed`；最终 semantic split 与两项关联 CAS 回归：`3 passed`。
- 显式固定 `/opt/homebrew/opt/python@3.14/bin/python3.14` 的 Python 3.14.5 + pytest 9.1.1 + PySide6 6.11.1 全量：`728 passed, 182 subtests passed`，无失败、无 skip。
- 带真实 Git metadata 的隔离副本、Python 3.11.15 + Node 24.18.0 CI 等价全量：`718 passed, 10 skipped, 182 subtests passed`。10 个 skip 全部来自 CI 环境未安装 PySide6：8 个 Stage 3 QWeb/图片用例、1 个 Phase 5 真实 QWeb 恢复用例和 1 个 Phase 6 桌面端到端用例；没有失败。
- 隔离副本执行 `npm ci --offline`：added 7、audited 8、0 vulnerabilities。Node 24 对前端及五个 JavaScript 分析/验证脚本的 `node --check`、Python 3.11 compileall、公开 CLI `--help`、`git diff --check` 和共享源/隔离副本字节比较均通过；`package-lock.json` SHA-256 保持 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`。
- 一次未显式指定 Python 的本地探测被 `uv` 解析为托管 Python 3.11，并因没有 PySide6 得到 `727 passed, 1 skipped`；该结果没有被当作 Python 3.14 发布门。首次 CI 等价副本又因人为漏拷 `.git` 导致 6 个试点工具测试无法执行 `git rev-parse HEAD`；补齐只读 Git metadata 后同一完整命令全绿。两项均为环境构造问题，不计作产品回归。
- 当前工作树未 commit、未 push，因此没有触发本次字节的 GitHub 托管 Ubuntu/Windows runner；本机 Python 3.11 + Node 24 结果不得表述为远端 CI 已运行。

当前阶段门：

~~~text
STAGE_D_PASS
STAGE_E_PASS
STAGE_F_PASS
STAGE_G_ELIGIBLE_NOT_STARTED
P0=0
P1=0
P2=1 hosted Ubuntu/Windows CI pending checkpoint/push
~~~

阶段 F 没有运行来源项目安装、构建、测试或入口命令，没有修改来源项目，没有 commit 或 push。第三方 `validated_positive` 与真实外部 computation 产品验收尚未发生，不能用本阶段自动测试数字替代阶段 G 的真实能力结论。

### S.23 阶段 A–E 跨阶段兼容重新封板（2026-07-18）

本节取代 S.19–S.21 中与当前测试数字和阶段门有关的旧快照，不改写当时的历史实施记录。一次限定的跨阶段复核确认并修复了两个 P0 和三个 P1；没有改变单仓、单组合器、唯一 review/Stage 3/发布主线或抓取契约。

修复事实：

- Static Web discovery 在 schema v1/v2 均使用显式列名；v2 新记录显式写入 `source_type='static_web'`。v2 的查找、更新和 `source_missing` 收尾只处理 Static Web 行，同目录 `javascript_computation_source` owner 不会被重发现误停用。
- `project_file_index` 的 JavaScript 行同时要求 `typeof(size_bytes)='integer'` 和 `typeof(content_sha256)='text'`；NULL、BLOB、空值、大写或非十六进制 hash 均由 SQLite 失败关闭。v2 exact schema fingerprint 为 `2f5c245eee172d57abc065d1c63ad76e11925aec6a021d586a9384c4cbde2ada`。
- Stage E 枚举字符串长度复用 `data_contract.v1` 的 UTF-16 code-unit 语义；BMP 外字符不再被错误缩短。lone surrogate 在客户端映射边界被结构化拒绝为 `adapter_mapping_invalid`，不泄漏原始 `UnicodeEncodeError`。
- 当前字节保留并通过 brand profile 并发回归：preflight 期间有效 profile 变化固定返回 `brand_profile_changed`，不能形成带旧 digest 的 `PreparedReview`。
- `CapsuleWarehouseStore` 的进程级重入锁继续作为低频迁移/恢复的最小串行屏障保留；在没有可复现吞吐问题前不引入锁注册表。阶段封板改用 checkpoint、限定测试节点和完整命令证据，不再用 `reweave_capsule_stage3.py` 单个大文件 SHA 代表阶段 E 的全部有效性。

当前字节验证：

- 五项修复与品牌竞态的直接回归：`6 passed, 18 subtests passed`。
- 阶段 A–E 冻结范围（store、Static intake、JS source/index、source graph、Stage E capture）：`220 passed, 114 subtests passed`。
- 显式 Python 3.14.5 + pytest 9.1.1 + PySide6 6.11.1 全量：`731 passed, 182 subtests passed`，无失败、无 skip；真实 QWebEngine 用例随全量执行，不能把它们扩大表述为尚未进行的第三方阶段 G 验收。
- 带 Git metadata 的隔离副本、Python 3.11 + Node 24.18.0 CI 等价全量：`721 passed, 10 skipped, 182 subtests passed`。10 个 skip 全部是该环境未安装 PySide6 的既定图片/QWeb/桌面门，不是业务失败。
- 隔离副本执行 `npm ci --offline`：added 7、audited 8、0 vulnerabilities。Node 22.22.3 与 Node 24.18.0 对前端和全部五个 `.mjs` 分析/验证脚本的 `node --check`、Python 3.14/3.11 compileall、公开 CLI `--help` 与 `git diff --check` 均通过；`package-lock.json` SHA-256 保持 `ec01145e8e4afc19ea1f93613a83d2e912dc989710d2f2e5c85ca9b8aa8c7c4f`。
- 当前字节未 push，未触发 GitHub 托管 Ubuntu/Windows runner；本机隔离结果不冒充托管 CI。

当前阶段门：

~~~text
STAGE_A_PASS
STAGE_B_PASS
STAGE_C_PASS_POSIX_CAPTURE_WINDOWS_STRUCTURED_UNSUPPORTED
STAGE_D_PASS
STAGE_E_PASS
STAGE_F_PASS
STAGE_G_ELIGIBLE_NOT_STARTED
P0=0
P1=0
P2=1 hosted Ubuntu/Windows CI pending checkpoint/push
~~~

本次收口没有运行来源项目命令，没有修改来源项目或用户正式状态目录，没有 commit 或 push。

### S.24 阶段 G 第三方验收、真实产品与 v1 退役封板（2026-07-19）

阶段 G 按固定预算完成并判定为 `PASS`。本轮在运行 Reweave 前冻结 12 个第三方项目的 URL、完整 commit、许可证文件、Git 状态、目标函数和来源摘要；达到三个独立项目 `validated_positive` 后依约停止，没有用运行结果替换样本，也没有继续检查剩余九项。来源项目没有安装、构建、运行、修改或回写，全部 SQLite、产品与原始证据只存在于 `/private/tmp/reweave-stage-g-final`。

三个 `validated_positive` 为：

- Grapheme（GPL-3.0），commit `c84ff5386bee8f47d686bf9d757ad48654f4f5eb`，目标 `basic_arithmetic.js / Multiply`，正式验证 canonical hash `0f82dc743f08b2704b49a0dae6ec3b95fbbcdc9a4c5fb5bf6eb1fb274e53e61a`，证据 SHA-256 `00b781e40b9568a2137a9d39939f51dee461860230707e5abdbcbebebde7cc0c`。
- betocostadev/build-tools-code-quality（MIT），commit `9d462676c6c8a6cb785c79e58b1f6308a3a3ff2b`，目标 `basic-math.js / multiply`，canonical hash `ba3915945cc82189e52f56e38c892c4d65da4790b8848026119029293f66eda7`，证据 SHA-256 `bedd26145895087b4ff8b78fbf58b5477f4148b52154044b0d1e8acc49a2bf97`。
- Color.js（MIT），commit `9ab13a94ae9170b551c4292f6624995900f78711`，目标 `util.js / clamp`，canonical hash `251912275eda0c8e4cbd97a095a77b5c7100277b1c9cfb0db7e31555a7cdbdd0`，证据 SHA-256 `42238eac406522a12e2dbe3fbb5b3efc281962ceb7c4c0692a1fb0622c942cf8`。

三项均通过 source graph、确定性 bundle、敏感/品牌/枚举门、`data_contract.v1`、bundle 后 AST 安全检查、真实 loopback Ollama 监督和真实 Node computation worker。三项验证运行前后正式 `capsules`、`capsule_versions`、`product_capsule_usage` 行数均为零；仅 Grapheme 随后的端到端流程执行了人工发布。Grapheme 第一次硬切后复验因冷模型未能在固定时间内响应而停在 `ollama_unavailable`，没有执行 worker 或写正式表；使用不含来源内容的提示预热同一个固定模型后，对同一冻结来源重跑通过。该次失败只记录为监督环境观察，不计作来源项目不支持。

Grapheme 通过现有 `computation_adapter.v2` 生成新映射 `x → quantity`、`y → unit_price`、`result → total`，业务样例为 `4 × 5 = 20`。新版本 canonical hash 为 `0f82dc743f08b2704b49a0dae6ec3b95fbbcdc9a4c5fb5bf6eb1fb274e53e61a`，最终验收 version ID 为 `ver_61de5d83f63445b9ae3faaf93a980047`；它与旧临时 v1 `x/y → result` 的 canonical hash `08266b91ff72162b5f9037f9e7d519b18dde540f8eae6677fd2301e51520a288` 不同，旧版本未被修改、覆盖或冒充复用，`module_native` 没有增加运行时字段改名。

真实产品由以下三个 active-current 精确版本组成：

- presentation：`ver_2e9ba6869e334227a04df87891d90173`，canonical hash `97103a0e56518064c7fb0e324846723772dd27f563b1e2c0b14092537d9373ef`。
- interaction：`ver_13853a3a1a8140c7be5e35c481e431d4`，canonical hash `2ecd6d79c2c3adfcce7b6a6ec24fda0b50d3f1137b4c808cdd9495c04fddf568`。
- computation：`ver_61de5d83f63445b9ae3faaf93a980047`，canonical hash `0f82dc743f08b2704b49a0dae6ec3b95fbbcdc9a4c5fb5bf6eb1fb274e53e61a`。

manifest digest 为 `a0f8fb5f58bb0989d1d26c4b94f99fed7ff81db0e72d9bfb3da13cf62dd2cc00`，六条 `product_capsule_usage` 贡献记录与 manifest 的三个精确 version ID 和 canonical hash 一致。真实 QWebEngine 业务验收范围为 `real_qwebengine_product_interaction`：输入数量 `4`、单价 `5`，点击 Calculate 后得到 `20`；事件发出一次、runtime 为 `passed`、阻断请求为空、控制台错误为空、根外 mutation 为空。最终字节证据 SHA-256 为 `bdf441ba6bb766cdf00ae9074e564b368888676a0f797bf943f4fef18cf53f91`。这不是启动探针或 synthetic interaction。

阶段 G 成功后执行精确硬切：新的 v1 inspect/create 固定返回 `adapter_creation_path_retired`；旧 v1 waiting/review 的处理、决定和发布固定返回 `adapter_contract_version_expired`。只有证据明确属于 `computation_adapter.v1` 的 active-current 版本，在验证完整备份且 warehouse revision 未变化后，才通过 current version + active CAS 转为 `pending_revalidation`；普通 computation、adapter v2、历史版本、disabled、旧产品和只读 `capsules.json` 开发者迁移入口均不受影响。恢复旧备份后会重新运行同一退役门。

最终冻结验证：

- Python 3.14.5、pytest 9.1.1、PySide6 6.11.1 全量：`756 passed, 183 subtests passed`。
- Python 3.11.15、Node 24.14.0 隔离 CI 等价全量：`745 passed, 11 skipped, 183 subtests passed`；11 个 skip 均为隔离环境未包含 PySide6 的既定图片/QWeb/桌面门。隔离副本 `npm ci --offline`、公开 demo `--help`、Node 24 前端语法和 `git diff --check` 均通过；源仓与隔离副本受控文件聚合 SHA-256 均为 `2c3a5cbbe2afa756a0cf251c260b32633acc76895814b27955c502c229b3a794`。
- computation 真实 Node worker 与产品真实 QWebEngine 业务断言均通过；来源摘要、用户正式状态、旧 v1 数据库和 Reweave 受测工作树摘要前后相同。
- 一次与 CI 全量并行运行的 Python 3.14 全量中，一个 source graph worker 用例出现非确定性失败；该用例单独重跑通过，Stage 3 整文件 `55 passed, 42 subtests passed`，取消并行重任务后的正式全量全绿。没有据此修改安全或超时契约。
- 最终限定 diff 复核发现并修复一个退役竞态：预查时无 v1、随后旧进程发布 v1 的 `0 → 1` 时序，第二事务现在也必须通过 warehouse revision 复核；不匹配时事务失败并重试，下一次看到 v1 后先做验证备份，再允许 CAS 退役。四条精确退役回归及管理/生成/桌面关联组通过。
- 当前最终字节尚未 push，未触发 GitHub 托管 Ubuntu/Windows runner；本机 CI 等价结果不冒充托管 CI。

当前阶段门：

~~~text
STAGE_A_PASS
STAGE_B_PASS
STAGE_C_PASS_POSIX_CAPTURE_WINDOWS_STRUCTURED_UNSUPPORTED
STAGE_D_PASS
STAGE_E_PASS
STAGE_F_PASS
STAGE_G_PASS
P0=0
P1=0
P2=1 hosted final-byte CI and demo publication pending explicit push/release approval
~~~

结构化摘要见 `docs/reports/REWEAVE_STAGE_G_ACCEPTANCE.json`。Stage G 到此停止，不实施 Bootstrap V3，不扩大 DSL，不创建模板、fallback、第二仓库或第二 composer；外部旧项目的 presentation/interaction 自动拆分仍未证明。

若后续建立公开 `Reweave-demo`，必须在独立发布动作中按 Grapheme 的 GPL-3.0 许可完成衍生输出的许可证、源代码提供方式和归属核对；Stage G 的本地临时验收本身不构成公开分发批准。
