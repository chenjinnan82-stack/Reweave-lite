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

**边界：** Source Box 始终只读。生成产品保存在 Reweave 应用状态目录，不覆盖源项目。

## 当前主线

```text
Source Box -> 只读快照 -> 原子提取 -> 人工复核
-> 一个正式 SQLite 仓库 -> 一个 module_native 组合器
-> index.html / styles.css / app.js -> 质量与运行门
-> 不可变 manifest 和产品使用记录
```

监督模型只在桌面仓库流程中显式选择，CLI 没有硬编码默认模型。生成只使用满足资格的 active/current 正式版本。

## 为什么做

小模型不是完全不会写代码。它真正吃亏的地方，是很难稳定记住一个旧项目里的命名、布局、样式、业务词和细节规则。

再织把旧项目文件夹当作 **Source Box**，只读扫描后清洗成 **Capsule**，再让新任务按需调用这些胶囊，生成带来源痕迹的 **Small Project Pack**。

它的灵感来自蜘蛛吐丝：旧项目里的线索不是被复制粘贴，而是被清洗、连接，再织成新的结构。

## 现在能做什么

- 绑定旧项目文件夹为 Source Box。
- 通过只读快照提取可独立验证的 presentation、interaction 和 computation 胶囊。
- 在桌面流程中完成复核、模型监督、验证、发布、备份和恢复。
- 把正式不可变版本保存在唯一的本地 SQLite Capsule Warehouse。
- 由唯一 `module_native` 组合器接收内存态正式胶囊。
- CLI 只经 `ReweaveAppService` 使用明确选择的正式胶囊 ID 生成。
- 生成可运行的 `index.html`、`styles.css`、`app.js`、manifest、provenance、质量证据和精确产品使用记录。
- 默认关闭真实源项目写入。

## 截图

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

在桌面程序里试用公开 Source Box：

```text
examples/source_boxes/customer-quote-widget
examples/source_boxes/ops-status-card
```

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
python3 -m venv .venv-reweave
. .venv-reweave/bin/activate
python -m pip install -r pimos_lite/requirements-desktop.txt
./start_reweave_static.sh
```

启动脚本不会自动安装依赖，也不会自动连接软件包仓库。

### 历史 demo

以下脚本仅保留为非活跃迁移历史，不是当前产品生成路径，也不是 CI 直接入口：

```bash
python scripts/run_public_stage4_demo.py
python scripts/run_public_stage4_demo.py --case data
```

它们不读取正式 SQLite 生成路径。Windows 桌面壳仍是 experimental；CLI 帮助入口和测试套件已纳入 Windows CI。

可选 runtime bridge：

```bash
REWEAVE_RUNTIME_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## 公开可复现性

- GitHub Actions 会运行 Reweave 测试。
- GitHub Actions 会在 Ubuntu 和 Windows 上检查 service-backed 公开 CLI 的帮助入口。
- GitHub Actions 会检查前端 JavaScript 语法。
- 历史 demo 脚本不是 CI 直接入口。
- 默认启动不依赖私有工作区路径。
- Source project writes 默认保持关闭。

历史内部工作台笔记，不作为这个公开仓库的运行前提。

## 安全边界

再织现在不是全自动生产级 IDE。

它当前不承诺任意项目自动生成、不自动多文件写入、不覆盖文件、不删除文件，也不在前端开放真实写入按钮。

这个仓库公开的是一条安全的 Reweave-lite 路线：从旧项目上下文生成可检查的 Small Project Pack，而不是替你自动编辑原项目的 IDE。

生成写入只发生在应用状态目录中新建的产品目录；Source Box 始终只读。

## 项目结构

```text
桌面界面                          reweave_frontend/
应用服务                          pimos_lite/reweave_app_service.py
正式 SQLite 仓库                  pimos_lite/reweave_capsule_store.py
只读入库                          pimos_lite/reweave_capsule_intake.py
安全与验证                        pimos_lite/reweave_capsule_stage3.py
唯一组合器                        pimos_lite/composer/module_native.py
公开样例                          examples/source_boxes/
公开 CLI                          scripts/run_public_reweave_demo.py
测试                              tests/
```

Source Box -> Capsule -> Task Pack 的主链见 [Architecture](docs/ARCHITECTURE.md)。

## 后续方向

- 更多公开 Source Box demo。
- 更好的桌面打包。
- 更稳定的 Task Pack preview。

见 [Roadmap](ROADMAP.md)。

## 开源协议

MIT
