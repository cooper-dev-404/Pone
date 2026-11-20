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

要从访达的「应用程序」打开改版后的「P一下」，在工作台目录运行 `bash editor-ui/build-macos.sh --install`。安装结果为 `/Applications/P一下.app`，沿用已有的界面预览设置和练习副本。 [构建要求](layerlight-workbench/README.md#编辑器界面预览)

## 云端与本地协作

云端从私有仓库 `cooper-dev-404/p-yixia` 的 `codex/editor-ui` 分支接续当前改版。分支包含固定版本的编辑器补丁、去外框的像素狸花猫图标、Mac 安装入口与实机验收记录。

先读 [AGENTS.md](AGENTS.md) 和 [编辑器界面改版记录](bitmap-editor-research/photoshop-coverage.md#编辑器界面改版记录)。云端可用 PhotoCraft 0.23.1 的同平台 CLI 运行 `python3 layerlight-workbench/verify.py /路径/photocraft-cli`，Mac 使用同一提交构建和实测。界面改版仍需补验窄窗口、长时间编辑和专项设置弹窗。完成开发清单列出的必需验收并合并至 `main` 后，再开第 03 项「内容识别移动」。 [开发清单](bitmap-editor-research/photoshop-coverage.md) · [Linux 回归记录](layerlight-workbench/verification/cli-results.json)
