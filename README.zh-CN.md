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

## 30 秒 demo

```bash
python3 scripts/run_public_reweave_demo.py
```

输出 JSON 会打印产物目录和文件列表。预期输出包含可运行的 `index.html`、`styles.css`、`app.js`，以及 `task_intent.json`、`task_plan.json`、`quality_gate.json`、`task_pack.json`、`capsules_used.json`、`provenance.json` 和 `snippets_used.json`。

**边界：** 源项目默认只读。Reweave-lite 生成小项目包 preview，不自动写入或覆盖你的项目。

可直接复制的公开 demo 流程：

```bash
python3 scripts/run_public_reweave_demo.py --list-capsules
python3 scripts/run_public_reweave_demo.py --select-capsule "Style Sheet" --select-capsule "Script Module"
python3 scripts/run_public_reweave_demo.py --source examples/source_boxes/support-ticket-triage --task "Build a support dashboard"
```

第一条列出可选胶囊。第二条用手动选择的胶囊生成 Small Project Pack。第三条换一个公开 Source Box 跑同一条链路。

5 个公开模板案例：

```bash
python3 scripts/run_public_reweave_demo.py --list-template-cases
python3 scripts/run_public_reweave_demo.py --template-case dashboard
python3 scripts/run_public_reweave_demo.py --template-case landing-page
python3 scripts/run_public_reweave_demo.py --template-case form-tool
python3 scripts/run_public_reweave_demo.py --template-case admin-panel
python3 scripts/run_public_reweave_demo.py --template-case data-viewer
```

每个案例都会生成可打开的 Small Project Pack，并保持 source project writes 为 `0`。

用你自己的旧项目跑一句真实任务：

```bash
python3 scripts/run_public_reweave_demo.py \
  --source /path/to/your/old-project \
  --task "Build a customer quote dashboard from this old project"
```

`--task-template` 仍保留为 demo 捷径，但主线是 `--task`。

## 本地小模型

不使用 Ollama 时，Reweave 会跑 deterministic demo：

```bash
python3 scripts/run_public_reweave_demo.py
```

使用 Ollama 时，Reweave 会让本地小模型优化同一个 Small Project Pack：

```bash
ollama pull qwen2.5-coder:1.5b
python3 scripts/run_public_reweave_demo.py \
  --source examples/source_boxes/customer-quote-widget \
  --task "Build a styled quote interaction" \
  --select-capsule "Style Sheet" \
  --select-capsule "Script Module" \
  --llm ollama \
  --model qwen2.5-coder:1.5b
```

如果你要严格证明模型真的参与了，增加 `--require-llm`：

```bash
python3 scripts/run_public_reweave_demo.py \
  --source examples/source_boxes/customer-quote-widget \
  --task "Build a styled quote interaction" \
  --select-capsule "Style Sheet" \
  --select-capsule "Script Module" \
  --llm ollama \
  --model qwen2.5-coder:1.5b \
  --require-llm
```

JSON / provenance 里预期能看到：

```json
{
  "llm": {
    "provider": "ollama",
    "model": "qwen2.5-coder:1.5b",
    "applied": true,
    "source_project_write": false
  }
}
```

`qwen2.5-coder:1.5b` 已在 5 个公开 Source Box 上复现通过。见 [P7 Local Ollama Reproduction](docs/reports/P7_LOCAL_OLLAMA_REPRODUCTION.md)。

如果 Ollama 没有运行，Reweave 会回退到稳定的 deterministic Small Project Pack；除非你显式加 `--require-llm`。provenance 会记录本地模型是否真的参与生成。

## 为什么做

小模型不是完全不会写代码。它真正吃亏的地方，是很难稳定记住一个旧项目里的命名、布局、样式、业务词和细节规则。

再织把旧项目文件夹当作 **Source Box**，只读扫描后清洗成 **Capsule**，再让新任务按需调用这些胶囊，生成带来源痕迹的 **Small Project Pack**。

它的灵感来自蜘蛛吐丝：旧项目里的线索不是被复制粘贴，而是被清洗、连接，再织成新的结构。

## 现在能做什么

- 绑定旧项目文件夹为 Source Box。
- 只读扫描，不写源项目。
- 生成 capsule candidate。
- 人工 Store 到本地 Capsule Warehouse。
- 在桌面工作台选择胶囊进入任务。
- 在 CLI 中列出胶囊，并手动选择要复用的胶囊。
- 可选使用本地 Ollama 小模型优化 Small Project Pack。
- 生成 Small Project Pack preview，包含：
  - `task_intent.json`
  - `task_plan.json`
  - `quality_gate.json`
  - 可运行的 `index.html`、`styles.css`、`app.js`
  - `task_pack.json`
  - `capsules_used.json`
  - `provenance.json`
  - `snippets_used.json`
- 默认关闭真实源项目写入。

## 截图

### Source Box

绑定旧项目文件夹。它是胶囊来源，不是写入目标。

![再织 Source Box 开屏](assets/reweave-source-box.png)

### Capsule Workbench

选择本地胶囊，规划新的 Web 任务，同时保留 trace 和 source-write 状态。

![再织桌面工作台](assets/reweave-workbench.png)

## 快速开始

运行公开 Task Pack demo：

```bash
python3 scripts/run_public_reweave_demo.py \
  --source examples/source_boxes/customer-quote-widget \
  --task "Build a quote summary card"
```

Windows PowerShell：

```powershell
py -3 scripts\run_public_reweave_demo.py `
  --source examples\source_boxes\customer-quote-widget `
  --task "Build a quote summary card"
```

脚本默认写入系统临时目录，例如 macOS/Linux 上的 `/tmp/reweave_public_demo`，或 Windows 上的 `%TEMP%\reweave_public_demo`。

在桌面程序里试用公开 Source Box：

```text
examples/source_boxes/customer-quote-widget
examples/source_boxes/ops-status-card
```

桌面闭环：

```text
Bind Source Box -> Scan -> Prepare -> Store -> 选择胶囊 -> Build Small Project Pack -> 查看 provenance
```

macOS 桌面 smoke 已验证：程序打开后先进入 Source Box 开屏，Generate / Export / Open Folder 在未满足条件前保持隐藏，bridge 主流程可以生成 Task Pack preview，且不写源项目。

见 [Desktop User Flow](docs/DESKTOP_USER_FLOW.md)。

运行公开仓库自带检查：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node --check reweave_frontend/app.js
```

macOS/Linux 可选桌面壳：

```bash
./start_reweave_static.sh
```

Windows 桌面壳仍是 experimental；CLI demo 和测试已纳入 Windows CI。

可选 runtime bridge：

```bash
REWEAVE_RUNTIME_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## 公开可复现性

- GitHub Actions 会运行 Reweave 测试。
- GitHub Actions 会在 Ubuntu 和 Windows 上运行公开 Task Pack demo。
- GitHub Actions 会检查 `task_intent.json`、`task_plan.json`、`quality_gate.json`、`task_pack.json`、`capsules_used.json` 和 `provenance.json`。
- GitHub Actions 会检查前端 JavaScript 语法。
- 默认启动不依赖私有工作区路径。
- Source project writes 默认保持关闭。

历史内部工作台笔记，不作为这个公开仓库的运行前提。

## 安全边界

再织现在不是全自动生产级 IDE。

它当前不承诺任意项目自动生成、不自动多文件写入、不覆盖文件、不删除文件，也不在前端开放真实写入按钮。

这个仓库公开的是旧项目复用链条里的 Reweave-lite 安全 release surface，不是全自动 IDE。

未来真实写入只保留一条安全路线：人工确认、单文件、新建、不覆盖、可回滚。

## 项目结构

```text
桌面界面                          reweave_frontend/
运行时桥接                        pimos_lite/reweave_engine/lumo_lite.py
Source Box 入口                   pimos_lite/reweave_source_registry.py
Source Box 扫描                   pimos_lite/reweave_source_scanner.py
胶囊草稿                          pimos_lite/reweave_capsule_draft.py
胶囊仓库                          pimos_lite/reweave_capsule_warehouse.py
Task Pack / provenance            pimos_lite/reweave_preview_pack.py
公开样例                          examples/source_boxes/
公开 demo                         scripts/run_public_reweave_demo.py
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
