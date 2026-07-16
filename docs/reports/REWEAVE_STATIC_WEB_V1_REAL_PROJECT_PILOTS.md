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
