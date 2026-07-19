# Reweave Static Web V1 真实公开 ESM 试点

完成日期：2026-07-16。

当前判断：试点执行与只读证据采集已完成；外部真实项目正向覆盖仍为 `PARTIAL`。

## 1. 范围与方法

本轮从 GitHub 克隆四个公开项目的固定提交到 `/private/tmp` 隔离目录。每个项目都只有一个 HTML 入口、从 HTML 加载本地 `.js` ESM，且试点没有安装来源依赖、运行来源构建器或修改来源代码。

每个项目使用独立的临时 SQLite 仓库执行：

```text
bind_source_root(single_project)
→ discover_projects
→ confirm_project
→ run_intake
```

运行环境为 Python 3.14.5 和 Node 22.22.3。Node AST 提取器按正常 intake 路径运行；因为没有候选达到 `extracted`，所以没有调用 Ollama、Node computation worker、Image worker、QWeb worker 或正式发布事务。

来源只读证据包括：

- 排除 `.git` 后，对目录、普通文件和符号链接按 POSIX 相对路径排序；记录类型、mode、mtime、大小、文件 SHA-256 或链接目标，再计算整树 SHA-256。
- 使用 `GIT_OPTIONAL_LOCKS=0 git status --porcelain=v1 -z --untracked-files=all` 比较前后状态。
- 比较 `intake_runs.snapshot_before` 与 `snapshot_after`。
- 检查 `capability_groups`、`capsules` 和 `capsule_versions` 行数。

本次原始本地证据文件 SHA-256 为 `4b599681a435c8af5f33c99c3d20ac40fcf8f13f9a43b4ad198c97dc16cb45bf`。报告只保存结构化结果和摘要，不复制第三方源码。

## 2. 固定项目与结果

| 项目固定提交 | 入口 | 资格 | Intake | 固定拒绝原因 |
|---|---|---|---|---|
| [MasiaAntoine/snake-js@894e7dc](https://github.com/MasiaAntoine/snake-js/tree/894e7dc8549b0aa347ecbe985704a3c32fbbc767) | `index.html` → `main.js` | `ready` | `1 candidate / 0 extracted / 1 rejected` | `module_top_level_statement_unsupported` |
| [nwakauc/ES6-Awesome-books@582758d](https://github.com/nwakauc/ES6-Awesome-books/tree/582758d79513c5447324f8ea360bfe88a5bf0148) | `index.html` → `modules/index.js` | `ready` | `1 candidate / 0 extracted / 1 rejected` | `module_import_unsupported` |
| [titusdmoore/wordle@2d01427](https://github.com/titusdmoore/wordle/tree/2d01427ccac3324dafadd31c0bb128d6039442b1) | `index.html` → `app.js` | `ready` | `1 candidate / 0 extracted / 1 rejected` | `module_top_level_side_effect` |
| [daria4783/hw10.js@c3b879c](https://github.com/daria4783/hw10.js/tree/c3b879cc81b27c716c27fc03e0c9c733663750dc) | `js.html` → `js.js` | `ready` | `1 candidate / 0 extracted / 1 rejected` | `module_top_level_statement_unsupported` |

| 项目 | Reweave intake 快照前后 | 来源整树前后 |
|---|---|---|
| `MasiaAntoine/snake-js` | `0a7ccae7f0f7f6ffec27da12777d6fc3e5f3e32d3c7ff642644ca2c267badbaf` | `b5d10cd01962f6f6de0372f912286afb5872b9aeffdf613afa2809e72e5b091b` |
| `nwakauc/ES6-Awesome-books` | `d815bf2a9b0ed73287715b66c8ac7732e540ab60578ba280dc7ff2c3a9d52cfa` | `ae11b3829a1cddc820266c1d86f9b5df62bfc999b24c12412f588852775f32e2` |
| `titusdmoore/wordle` | `9194b110545ca45b52e89f4eff1e5366cfc84ff853cf5f4d3449e061059691f7` | `cbeff4cf45e99b6a743763de6d72bedbe2131798ed8efa229f5ba653340763b7` |
| `daria4783/hw10.js` | `a41a110bd3aab7d099cc7beb78f201c51efb63465980f10c3d554d8dbe63e1a8` | `04fe64f27e06df11fa986bc6245149b815bcb9987edfddc5294186124ddef439` |

上述八个摘要均为 before 与 after 的共同值。四个 Git 工作树前后均为空状态，空状态字节的 SHA-256 均为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。每个隔离仓库的三个正式表行数都为 0。

## 3. 能力判断

四个项目证明当前路径能在真实来源上保持只读、稳定快照和失败关闭，但没有证明能从普通 ESM 应用入口提取正式原子胶囊。它们的入口普遍直接执行启动语句、注册全局事件或使用 V1 禁止的 import 形式，而不是暴露可独立验证的 `render`、`mount`、`compute` 角色闭包。

因此不能把“资格为 `ready`”表述为“能力已提取”，也不能把四个安全拒绝表述为四个正向验收。当前正向证据仍只有仓库内契约化 fixture `tests/fixtures/reweave_phase6_quote`。

本轮曾确认一个失败关闭的 P1 契约缺口：阶段 2 会把唯一 `<main>` 或 `<form>` 推断为静态根，但阶段 3 的 UI 清洗只接受唯一显式 `data-capsule-root`，并且当时的 HTML 安全标签集合不接受 `<main>`。试点没有通过改写来源规避；随后实现按同一固定顺序统一了阶段 2/3 根选择，并完成真实 QWebEngine 回归，详见第 5 节。

## 4. 收口结论

- 额外四个真实公开项目的只读资格与 intake 试点：`DONE`。
- 来源项目无写入、快照一致、正式仓库无发布：`PASS`。
- 安全失败关闭：`PASS`。
- 额外真实正向项目数量：`0`，目标仍为 `PARTIAL`。
- 当前已知问题：P0 无；根推断 P1 已关闭，P1 无。
- 普通应用顶层启动代码属于 V1 不支持的提取边界，具体使用 `module_top_level_statement_unsupported`、`module_top_level_side_effect` 等细分原因失败关闭；它不是待实现的隐含范围，也不把当前结果用于宣称任意 ESM 旧项目可自动入库。

## 5. 根契约修复复验

修复后使用同四个固定提交和四个全新隔离 SQLite 仓库重新运行。结果仍为 `4 candidates / 0 extracted / 4 rejected`，拒绝原因逐项未变；四个来源树、Git 状态及 intake 快照前后完全一致，`capability_groups`、`capsules`、`capsule_versions` 仍全部为 0。

复验原始证据：

- 路径：`/private/tmp/reweave-real-pilots-rootfix.Nu5J6C/evidence.json`
- SHA-256：`3806be82b15423935b3d1d6f01cbc806a57dd91fe62c90bef1309c756ee8e32f`
- 环境：Python 3.14.5、Node 22.22.3

根契约回归覆盖唯一显式标记、唯一 `<main>`、唯一 `<form>`、多显式根、歧义根、嵌套显式根及 computation 隔离；阶段 2/3 聚焦为 `74 passed, 53 subtests passed`。无显式标记的唯一 `<main>` interaction 已在真实 QWebEngine 中运行，单独结果为 `1 passed`。完整验证及 CI 等价数字记录在设计文档 P.8。

本次修复只消除了合法 UI 根在阶段 2/3 之间的不一致，没有改写四个项目的顶层 JavaScript，也没有新增自动转换器。额外真实正向项目仍为 0，所以本报告的外部正向覆盖结论继续保持 `PARTIAL`。

## 6. 冻结扩面清单与可复现工具

本节及后续章节记录“V1 真实项目扩面与 Bootstrap 决策方案”的最终执行结果；第 1–5 节保留此前四项目试点的历史证据。最终固定清单位于 `docs/reports/REWEAVE_STATIC_WEB_V1_PILOT_CORPUS.json`，文件 SHA-256 为 `dfd55804fe51b86311041c4863176571072bc910996c6c795d1bb79d7a1a5ebe`，规范 JSON SHA-256 为 `672a37a8e6bdb87a2bd175896dcad01475f977250a508550b3072f12a5d4f788`。

新增无网络试点脚本为 `scripts/run_reweave_v1_real_project_pilots.py`，只接受：

```text
--manifest
--workspace
--state-root
--output
```

脚本不克隆项目、不安装来源依赖、不运行来源构建器、不写来源目录，也不自动形成任何人工复核决定。它只处理已检出的固定提交，并在执行前校验 Reweave HEAD 与规则版本、来源 HEAD、Git clean 状态、origin、入口和许可证路径；每个项目使用独立 SQLite 状态目录。`--state-root` 与来源 workspace 必须完全分离，`--output` 不得位于来源 workspace 内，checkout 根或整树出现符号链接均失败关闭。服务中途失败也必须执行来源后置检查，intake 快照不一致使整份证据失败；同批 duplicate 不冒充模型调用，任何 secondary 未知错误码同样使分类门失败。最终脚本 SHA-256 为 `0f5e46947da5e38881afa6e6abec101da8608b7fbb01c958f4ee71b9a9fcf1ac`。

报告层保留原始错误码，另外派生固定 `failure_family`；未知错误码为 `unclassified` 并使整份证据失败。模型和三个 worker 使用 `true`、`false`、`null` 三态记录，`product_asserted` 只有真实业务断言才能取布尔值，不能从正式表、manifest 或浏览器启动成功推断。

## 7. 真实正向覆盖轨道

按 presentation、interaction、computation 三类分别检查前 20 个公开搜索结果，共检查 60 项后停止。没有项目同时满足许可证、单入口本地 ESM、自包含静态闭包、无构建、无远程资源/品牌/位图，以及可静态预筛为单一原子角色等全部条件，因此固定正向清单为空，未在运行结果之后替换或制造样本。

| 搜索轨道 | 检查数 | 合格数 | 原始搜索证据 SHA-256 |
|---|---:|---:|---|
| presentation | 20 | 0 | `9edb8b1ed5884be12657c850762190869f9971feaae7cf1a00bdfd8eb6da24c0` |
| interaction | 20 | 0 | `113816c2392ea3ea7c523a2821eba595fb45a22f72bf600357fe0895e49a97e7` |
| computation | 20 | 0 | `5925000c328967e081d6a60b470e4857b98ecf1d492407bc04e075a82e0086ad` |

原始搜索证据位于 `/private/tmp/reweave-v1-positive-scout/`，仓库只保存数量和 SHA-256，不保存搜索结果正文。由于样本预算已经耗尽，本轮正向完成门没有满足：`validated_positive=0`，覆盖角色为空，真实外部项目 `end_to_end_positive` 未执行。该结果必须保持 `PARTIAL`，不能用仓库 fixture、现有全量测试或安全拒绝替代外部真实正向证据。

## 8. 固定八项目失败观察轨道

八项目清单由此前四个固定项目和四个新增普通 ESM 项目构成，运行前已经冻结。最终漏斗为：

```text
screened=8
→ ready=4
→ extracted_any=0
→ stage3_pass_any=0
→ active=0
→ product_asserted=0（真实值为 null，未执行）
```

| 固定项目 | 最早终止门 | `raw_error_code` | `failure_family` |
|---|---|---|---|
| `MasiaAntoine/snake-js@894e7dc` | intake | `module_top_level_statement_unsupported` | `bootstrap_top_level_not_declarative_v1` |
| `nwakauc/ES6-Awesome-books@582758d` | intake | `module_import_unsupported` | `module_graph_unsupported_v1` |
| `titusdmoore/wordle@2d01427` | intake | `module_top_level_side_effect` | `bootstrap_top_level_not_declarative_v1` |
| `daria4783/hw10.js@c3b879c` | intake | `module_top_level_statement_unsupported` | `bootstrap_top_level_not_declarative_v1` |
| `jrletner/vanilla_js_todo@cd61d97` | 资格入口 | `classic_script_unsupported_v1` | `qualification_entry_unsupported_v1` |
| `AdityaKumar1511/cipher-lab@0ee47a8` | 资格闭包 | `static_closure_external_reference` | `qualification_closure_boundary` |
| `DaveHomeAssist/noteforge@ba380b9` | 资格闭包 | `static_closure_external_reference` | `qualification_closure_boundary` |
| `inorganik/countUp.js@2346e49` | 资格入口 | `inline_script_unsupported_v1` | `qualification_entry_unsupported_v1` |

项目级失败族分别为：bootstrap 顶层非声明式 3、模块图 1、资格闭包 2、资格入口 2。候选级仅统计四个实际形成的 rejected candidate：bootstrap 顶层非声明式 3、模块图 1。项目数和 candidate 数没有混用分母。

最终证据位于 `/private/tmp/reweave-v1-pilot-evidence-final5.json`，SHA-256 为 `d5453ae35d8cb2eb811ee9b5fe70437799702d59ca647ca29f1817bb0d9c01b0`。证据门和未知分类门均为 `passed`，`unclassified_raw_error_codes=[]`。八个项目都记录了显式 `farthest_gate` 与项目级 `primary_failure`。八个来源的整树摘要与 Git 状态前后分别相同，四个 intake 快照前后相同，八个隔离仓库的全部正式表增量均为 0；没有调用 Ollama、Node computation worker、Image worker 或 QWeb worker。

## 9. Bootstrap 机会探针与 v3 决定

只读机会探针对固定八项目沿 import 证据检查预批准形态，不创建候选、不写正式仓库、不运行 Stage 3 或 worker，也没有 wrapper、源码改写、tree-shaking 或模型边界判断。

只有 `jrletner/vanilla_js_todo` 出现“一个静态相对 named import → 一个最终直接调用”的外层形态；它的叶子模块仍以 `unsupported_string_construction_v1` 被 extraction v2 拒绝，且没有形成可验证的正式原子角色。其余七项分别包含 `window.onload`、多 import/调用、全局事件、无 import、动态 import、`DOMContentLoaded`、`new`、生成输出或多执行语句等拒绝形态。

| 决策指标 | 门槛 | 观察值 |
|---|---:|---:|
| 相同预批准形态的独立项目 | 3 | 1 |
| 覆盖正式原子角色种类 | 2 | 0 |
| 叶子模块原样通过 v2 | 必须通过 | 0 |
| Stage 3 / worker 通过 | 必须通过 | 0 / 0 |

机会探针证据位于 `/private/tmp/reweave-bootstrap-opportunity-evidence.json`，SHA-256 为 `e48044fe967957367f431cfd4b36fca86c8e68fe652e0582f672ff8544d65b60`。门槛没有满足，正式决定为 `do_not_approve_extraction_contract_v3`：继续使用 `extraction_contract.v2`，普通 bootstrap 保持 V1 不支持，不新增 wrapper、模板、fallback、仓库、组合器或运行时兼容路径。

## 10. 最终验证与停止结论

- Python 3.14.5、PySide6 6.11.1、Node 22.22.3 全量：`565 passed, 98 subtests passed`。
- Python 3.11、Node 24.18.0 本机 CI 等价链：`564 passed, 1 skipped, 98 subtests passed`；唯一 skip 是临时 Python 3.11 环境没有 PySide6。
- 新试点工具聚焦：`8 passed`。
- `npm ci`：7 packages、0 vulnerabilities。
- Node 22/24 语法、Python 编译和 `git diff --check`：通过。
- 本轮未 push，因此没有把本机等价链描述为该未提交快照的 GitHub 托管 CI。

最终判断：阶段 1–6 在已经封板的 Static Web V1 契约内保持 `PASS`；新增证据工具没有改变 SQLite、提取、Stage 3、组合器、前端或产品运行路径。外部真实正向覆盖因固定预算内没有合格项目而保持 `PARTIAL`，普通 bootstrap 的 v3 门未通过且停止扩围。当前没有由本轮引入或复现的 P0/P1；剩余项是外部正向证据不足，不是把不符合 V1 的项目自动转换为可接受项目的代码缺陷。
