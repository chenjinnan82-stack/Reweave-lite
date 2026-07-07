<div align="center">

<img src="assets/logo.svg" alt="Reweave" width="420">

# 再织 Reweave

**把旧项目清洗成可复用的胶囊，再织成新的 Web 任务包。**

旧项目 -> Source Box -> Capsules -> Task Pack -> New Web

[English](README.md)

![Local first](https://img.shields.io/badge/local--first-yes-2f855a)
![CI](https://github.com/chenjinnan82-stack/Reweave-lite/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Source writes](https://img.shields.io/badge/source%20writes-off-1f2937)
![Task Pack](https://img.shields.io/badge/task%20pack-preview-f59e0b)
![Desktop](https://img.shields.io/badge/app-desktop-334155)

</div>

## 为什么做

小模型不是完全不会写代码。它真正吃亏的地方，是很难稳定记住一个旧项目里的命名、布局、样式、业务词和细节规则。

再织把旧项目文件夹当作 **Source Box**，只读扫描后清洗成 **Capsule**，再让新任务按需调用这些胶囊，生成带来源痕迹的 **Task Pack Preview**。

它的灵感来自蜘蛛吐丝：旧项目里的线索不是被复制粘贴，而是被清洗、连接，再织成新的结构。

## 现在能做什么

- 绑定旧项目文件夹为 Source Box。
- 只读扫描，不写源项目。
- 生成 capsule candidate。
- 人工 Store 到本地 Capsule Warehouse。
- 在桌面工作台选择胶囊进入任务。
- 生成 Task Pack preview，包含：
  - `task_pack.json`
  - `capsules_used.json`
  - `provenance.json`
- 默认关闭真实源项目写入。

## 截图

### Source Box

绑定旧项目文件夹。它是胶囊来源，不是写入目标。

![再织 Source Box 开屏](assets/reweave-source-box.png)

### Capsule Workbench

选择本地胶囊，规划新的 Web 任务，同时保留 trace 和 source-write 状态。

![再织桌面工作台](assets/reweave-workbench.png)

## 快速开始

```bash
./start_reweave_static.sh
```

运行公开仓库自带检查：

```bash
python3 -m pip install pytest
python3 -m pytest tests/test_reweave*.py -q
node --check reweave_frontend/app.js
```

可选：把桌面桥接到你自己的 Lumo Lite runtime state：

```bash
REWEAVE_LUMO_LITE_STATE_PATH=/path/to/frontend_runtime_state.json \
./start_reweave_static.sh
```

## 公开可复现性

- GitHub Actions 会运行 Reweave 测试和前端语法检查。
- 默认启动不依赖私有工作区路径。
- Source project writes 默认保持关闭。

早期 Lumo Lite 工作台里的内部能力测试记录，不作为这个公开仓库的运行前提。

## 安全边界

再织现在不是全自动生产级 IDE。

它当前不承诺任意项目自动生成、不自动多文件写入、不覆盖文件、不删除文件，也不在前端开放真实写入按钮。

未来真实写入只保留一条安全路线：人工确认、单文件、新建、不覆盖、可回滚。

## 项目结构

```text
reweave_frontend/                  桌面界面
pimos_lite/reweave_engine/         Local 和 Lumo Lite 引擎
pimos_lite/reweave_*               Source Box、胶囊、预览、桥接逻辑
tests/test_reweave*.py             release 和 bridge 测试
```

## 后续方向

- Source Box 入口继续打磨。
- 胶囊 review 和选择更顺手。
- Task Pack 计划能力增强。
- 准备更多公开 demo Source Box。
- 真实写入只做人工确认的单文件新建和 rollback receipt。

## 开源协议

MIT
