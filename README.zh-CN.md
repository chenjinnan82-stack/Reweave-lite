<div align="center">

<img src="assets/logo.svg" alt="Reweave" width="420">

# 再织 Reweave

**把旧项目清洗成可复用的胶囊，再织成新的 Web 任务包。**

旧项目 -> Source Box -> Capsules -> Small Project Pack -> New Web

[English](README.md)

![Local first](https://img.shields.io/badge/local--first-yes-2f855a)
![CI](https://github.com/chenjinnan82-stack/Reweave-lite/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Source writes](https://img.shields.io/badge/source%20writes-off-1f2937)
![Small Project Pack](https://img.shields.io/badge/small%20project%20pack-preview-f59e0b)
![Desktop](https://img.shields.io/badge/app-desktop-334155)

</div>

## 30 秒开始

先在桌面 Capsule Warehouse 中绑定 Source Box、刷新、复核清洗后的候选，并把所需胶囊发布到正式 SQLite 仓库。然后用明确的 active 胶囊 ID 生成产品：

```bash
python3 scripts/run_public_reweave_demo.py \
  --task "Build a quote summary card" \
  --capsule-id cap_11111111111111111111111111111111 \
  --capsule-id cap_22222222222222222222222222222222 \
  --capsule-id cap_33333333333333333333333333333333
```

请把示例 ID 替换为桌面仓库中显示的正式 ID。只有仓库不在默认应用状态目录时才需要 `--state-dir /path/to/reweave-state`。输出 JSON 是 `ReweaveAppService` 的原始产品结果，包含产品 ID、manifest digest、产品路径、精确胶囊版本、质量结果和运行验收。

CLI 不扫描来源、不 promote、不选择模型，也不隐式选择胶囊。没有胶囊 ID 就不会生成。

桌面应用现已把 Static Web 目标 Patch 契约接成 review-only 交互闭环；公开 CLI 仍没有目标接入入口。

**边界：** Source Box 和选定的目标项目始终只读。生成产品保存在 Reweave 应用状态目录；目标接入只返回可审查 Patch 数据，绝不直接应用。

## 当前主线

```text
Source Box -> 只读快照 -> 原子提取 -> 人工复核
-> 一个正式 SQLite 仓库 -> 一个 module_native 组合器
-> index.html / styles.css / app.js -> 质量与运行门
-> 不可变 manifest 和产品使用记录
```

同一个正式仓库和组合器还提供一条独立的 review-only 目标支线：

```text
满足资格的正式胶囊 + 已授权的 Static Web 目标快照
-> 路径、HTML 直接资源引用和 JavaScript module 校验
-> 唯一 module_native 结果 -> static_web_iframe_embed.v1
-> 结构化 review-only Patch + 文本 Diff + 证据
-> 目标、产品仓和 usage 零写入
```

桌面端把独立产品生成和目标接入保持为清楚分离的双入口。目标页面提供简单/开发者模式、满足资格的胶囊卡片、文本 Diff、二进制元数据、验证或拒绝证据，以及绑定 `plan_id` 和目标快照的内存态最终确认。该确认不会发起 bridge call，也不授予 write、apply 或 commit 权限。

监督模型只在桌面仓库流程中显式选择，CLI 没有硬编码默认模型。生成只使用满足资格的 active/current 正式版本。

### Static Web V1 支持范围

| 支持 | V1 不支持 |
| --- | --- |
| 一个已确认的 HTML 入口 | classic `<script src>`、内联脚本、多页面自动推断 |
| 由 `.js` / `.mjs` 和静态相对 import 组成的自包含本地 ES module 闭包 | CommonJS、TypeScript、JSX、React/Vue/Svelte 组件源码、动态 import、裸包导入 |
| 不需要安装来源依赖、不需要构建即可运行的来源 | `node_modules`、必须构建的项目、未单独批准的 `dist` / `build` 输出 |
| 能独立证明的 presentation、interaction、computation 原子角色 | SVG、字体，以及无法证明原子角色或本地资产闭包的代码 |

Vite 不按名称一刀切：已经形成自包含原生 module 入口的静态来源可以符合条件；必须运行 Vite 或安装依赖的项目不属于 V1。

## 为什么做

小模型不是完全不会写代码。它真正吃亏的地方，是很难稳定记住一个旧项目里的命名、布局、样式、业务词和细节规则。

再织把旧项目文件夹当作 **Source Box**，只读扫描后清洗成 **Capsule**，再让新任务按需调用这些胶囊，生成带来源痕迹的 **Small Project Pack**。

它的灵感来自蜘蛛吐丝：旧项目里的线索不是被复制粘贴，而是被清洗、连接，再织成新的结构。

## 现在能做什么

- 绑定旧项目文件夹为 Source Box。
- 对符合 Static Web V1 支持条件的来源，通过只读快照提取可独立验证的 presentation、interaction 和 computation 胶囊。
- 在桌面流程中完成复核、模型监督、验证、发布、备份和恢复。
- 把正式不可变版本保存在唯一的本地 SQLite Capsule Warehouse。
- 由唯一 `module_native` 组合器接收内存态正式胶囊。
- CLI 只经 `ReweaveAppService` 使用明确选择的正式胶囊 ID 生成。
- 生成可运行的 `index.html`、`styles.css`、`app.js`、manifest、provenance、质量证据和精确产品使用记录。
- 通过独立的桌面目标接入页面分析一个显式选择的 Static Web 目标入口，并审阅 `ReweaveAppService` 返回的确定性、绑定目标快照的 Weave Plan 和完整 review-only Patch。
- 默认关闭真实源项目写入。

## 截图

下列仓库图片仅作界面示意。发布验收以设计文档单独记录的真实 QWeb 交互和模型辅助截图证据为准；这些图片不是像素级签字。

### Source Box

绑定旧项目文件夹。它是胶囊来源，不是写入目标。

![再织 Source Box 开屏](assets/reweave-source-box.png)

### Capsule Workbench

选择本地胶囊，规划新的 Web 任务，同时保留 trace 和 source-write 状态。

![再织桌面工作台](assets/reweave-workbench.png)

## 快速开始

在桌面仓库发布胶囊后，运行公开 CLI：

```bash
python3 scripts/run_public_reweave_demo.py \
  --task "Build a quote summary card" \
  --capsule-id cap_11111111111111111111111111111111 \
  --capsule-id cap_22222222222222222222222222222222
```

Windows PowerShell：

```powershell
py -3 scripts\run_public_reweave_demo.py `
  --task "Build a quote summary card" `
  --capsule-id cap_11111111111111111111111111111111 `
  --capsule-id cap_22222222222222222222222222222222
```

返回值中的 `previewPath` 指向生成产品；`productId`、`manifestDigest` 和 `capsulesUsed` 提供精确本地追溯。

当前正向流程使用仓库内版本化的 ESM 开发者夹具：

```text
tests/fixtures/reweave_phase6_quote
```

公开的 `customer-quote-widget` 和 `ops-status-card` 使用 classic script。它们保留为 V1 范围负向样例，预期停在 `classic_script_unsupported_v1`，不会完成正向入库。

桌面闭环：

```text
Bind Source Box -> 发现并确认 -> Refresh -> 复核并发布 -> Generate -> 查看 provenance
```

桌面管理把 Source Box 入库、复核、发布、备份和恢复保持在同一条 SQLite 主线上；CLI 通过同一个应用服务生成。

见 [Desktop User Flow](docs/DESKTOP_USER_FLOW.md)。

运行公开仓库自带检查：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
python -m pytest tests -q
node --check reweave_frontend/app.js
```

macOS/Linux 可选桌面壳：

```bash
npm ci
python3 -m venv .venv-reweave
. .venv-reweave/bin/activate
python -m pip install -r pimos_lite/requirements-desktop.txt
./start_reweave_static.sh
```

PySide6 只安装在独立 `.venv-reweave`，不进入核心依赖。启动脚本不会自动安装依赖，也不会自动连接软件包仓库。Ollama 监督只允许 loopback，并要求用户显式选择本机已安装模型；Reweave 没有硬编码默认模型。

### 已退役的 Stage 4 demo

旧 Stage 4 公开 demo 入口在证明不属于正式产品、桌面、发布和 CI 调用图后已经删除。基于应用服务的正式 CLI 是唯一公开 CLI 入口。Windows 桌面壳仍是 experimental；CLI 帮助入口和测试套件已纳入 Windows CI。

可选 runtime bridge：

```bash
REWEAVE_RUNTIME_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## 公开可复现性

- GitHub Actions 会运行 Reweave 测试。
- GitHub Actions 会在 Ubuntu 和 Windows 上检查 service-backed 公开 CLI 的帮助入口。
- GitHub Actions 会检查前端 JavaScript 语法。
- CI 只检查基于应用服务的唯一正式公开 CLI 入口。
- 默认启动不依赖私有工作区路径。
- Source project writes 默认保持关闭。

运行证据标签严格区分：

| 标签 | 能证明什么 |
| --- | --- |
| `synthetic_declared_interaction` | 只证明声明交互模拟，不是浏览器验收。 |
| `real_qwebengine_render` / `real_qwebengine_interaction` | 候选在隔离的真实 QWebEngine 中完成渲染或交互。 |
| `real_qwebengine_product_bootstrap` | 生成产品能在真实 QWebEngine 启动，不等于完整业务点击。 |
| `real_qwebengine_product_interaction` | 外部输入和真实点击得到预期产品结果，不等于像素级或人工视觉签字。 |

托管 CI 在 Ubuntu 和 Windows 上使用 Python 3.11、Node 24；它不安装 PySide6，也不能替代 macOS 本地真实 QWeb 桌面门。Windows 桌面打包仍为 experimental。

历史内部工作台笔记，不作为这个公开仓库的运行前提。

## 安全边界

再织现在不是全自动生产级 IDE。

它当前不承诺任意项目自动生成、不自动多文件写入、不覆盖文件、不删除文件，也不在前端开放真实写入按钮。

Static Web 桌面目标流程只审阅 Patch 数据，不应用 Patch、不 commit、不写选定目标，也不宣称自动完成法律许可证授权判断。最终确认只是内存态审阅回执，不是目标写入授权；公开 CLI 仍没有目标接入入口。

这个仓库公开的是一条安全的 Reweave-lite 路线：从旧项目上下文生成可检查的 Small Project Pack，而不是替你自动编辑原项目的 IDE。

生成写入只发生在应用状态目录中新建的产品目录；Source Box 始终只读。

## 项目结构

```text
桌面界面                          reweave_frontend/
应用服务                          pimos_lite/reweave_app_service.py
正式 SQLite 仓库                  pimos_lite/reweave_capsule_store.py
只读入库                          pimos_lite/reweave_capsule_intake.py
Static Web 目标 Patch 规划          pimos_lite/reweave_static_web_target.py
安全与验证                        pimos_lite/reweave_capsule_stage3.py
唯一组合器                        pimos_lite/composer/module_native.py
公开样例                          examples/source_boxes/
公开 CLI                          scripts/run_public_reweave_demo.py
测试                              tests/
```

Source Box -> Capsule -> Task Pack 的主链见 [Architecture](docs/ARCHITECTURE.md)。

## 后续方向

唯一权威产品路线图是 [Reweave 产品北极星](docs/REWEAVE_PRODUCT_NORTH_STAR.md)。其中四个可独立验收的计划均已完成；后续目标类型仍按独立顺序推进。

## 开源协议

MIT
