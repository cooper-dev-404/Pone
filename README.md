# P一下

P一下是基于 PhotoCraft 0.23.1 的 Mac 位图编辑工作台。仓库包含工作台源码、可编辑练习稿、回归测试和逐项验收清单。 [工作台说明](layerlight-workbench/README.md) · [开发清单](bitmap-editor-research/photoshop-coverage.md)

## 在 Mac 上打开

在 Codex 中选择这个目录作为本地工作区。进入工作台目录后，可分别运行练习稿的启动命令。

```sh
cd layerlight-workbench
bash P一下.command --fill
bash P一下.command --remove
```

首次启动会下载并校验 PhotoCraft 官方运行时，也可使用已下载的同版 DMG。用户配置和可编辑练习副本保存在 `~/Library/Application Support/Layerlight Workbench`。

## 云端与本地协作

把工作区连接到同一个私有 Git 仓库。每次从 `main` 为清单中的一项功能创建分支。云端用 `layerlight-workbench/verify.py` 跑引擎回归，Mac 用同一提交验收画布交互。将测试结果与样稿一起提交，通过后合并，再进入下一项。

当前验收结果及第 03 项「内容识别移动」的启动条件见 [开发清单](bitmap-editor-research/photoshop-coverage.md)。 [Linux 回归记录](layerlight-workbench/verification/cli-results.json)
