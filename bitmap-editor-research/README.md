# 专业位图编辑器需求与开源底座对比

产品能力现已细化为 [Photoshop 位图能力验收矩阵](photoshop-coverage.md) 和 [带候选命令的 CSV](photoshop-coverage.csv)。

目标是一款面向平面设计师的 Mac 数字位图工作台。典型工作是素材修图、多图合成、数字海报和电商活动图、系列尺寸出图，以及保存可编辑源文件。用户已明确要求完整的专业位图能力，主界面也应提供能直接找到的工具入口。以下场景是根据这个目标拟出的验收样本，具体分辨率和设计稿用于验证操作。

## 选择哪个开源底座

**PhotoCraft 的功能覆盖面更大，建议作为编辑引擎首选。** Compositor 很适合做 Mac 原生体验的对照，尤其是画布交互、笔刷响应和蒙版修边。GIMP 提供另一份真实渲染对照，也值得参考修复和滤镜。三者的文档、代码和实测范围如下。

| 维度 | PhotoCraft | Compositor |
|---|---|---|
| 修图、选区和合成 | 有选区、蒙版、剪贴、混合模式、调整图层、智能对象、图层样式、画板及滤镜。项目路线图说明，发丝修边和部分画笔手感仍有差距。 | 有魔棒、主体选择、蒙版、剪贴、曲线、色阶、色相饱和度、跨可见图层采样的仿制图章、污点修复和内容识别填充；源码中也有沿原图边缘细化蒙版的实现。 |
| 给位图配字并反复改稿 | 有点文字和段落文字、字形与段落属性及画板；本次实测中文标题存入 PSD 后可重开继续改字。 | 本地文档可编辑文字；PSD 写入代码会提示文字转为像素。 |
| PSD 交接 | 支持分层 PSD/PSB，并尝试保留内核尚未建模的部分数据。本次四层样本往返一致。上游报告的 Photoshop 原作渲染对照为 133/256，实际客户稿仍需验证。 | 支持分层导入导出。原生项目支持可编辑调整；当前 PSD 写入代码会列出栅格化的部分效果，以及无法写入的调整图层。 |
| Mac 形态 | Rust 引擎可脱离界面运行，有 Apple 芯片和 Intel 的通用 Mac 安装包。最低系统和原生体验需实机核对。 | 以 AppKit/SwiftUI 为主，包含 Core Graphics 和 Metal 实现。上游要求 Apple 芯片和 macOS 26+，并提供 4000 × 4000 文档的笔刷基准。 |
| 许可证和可借用部分 | MIT 或 Apache-2.0。优先评估文档、合成、命令和 PSD 编解码，随包素材的授权独立核对。 | MIT。优先参考笔刷分块、选区与蒙版、Mac 工具操作和 PSD 降级提示。 |

资料：[PhotoCraft 架构](https://github.com/storytold/photocraft/blob/856f865cf98d7e4817f6f955980f47fb4ead8c32/docs/architecture.md) · [PhotoCraft 兼容路线图](https://github.com/storytold/photocraft/blob/856f865cf98d7e4817f6f955980f47fb4ead8c32/docs/roadmap.md) · [PhotoCraft v0.23.1](https://github.com/storytold/photocraft/releases/tag/v0.23.1) · [Compositor 功能与系统要求](https://github.com/robbietilton/Compositor) · [PSD 写入源码](https://github.com/robbietilton/Compositor/blob/1910aeabf73b9baf471548b4e23c27a3dd1a0b60/Compositor/IO/PSD/PSDWriter.swift) · [笔刷基准](https://github.com/robbietilton/Compositor/blob/1910aeabf73b9baf471548b4e23c27a3dd1a0b60/docs/brush-performance.md) · [蒙版修边源码](https://github.com/robbietilton/Compositor/blob/1910aeabf73b9baf471548b4e23c27a3dd1a0b60/Compositor/Document/GuidedMatte.swift)

**GIMP 的实测价值**。上一轮在 GIMP 3.0.4 中验证了选区转蒙版、修边、XCF 重开和 PSD 保留图层。GIMP 3.2 的文档还说明链接图层、可编辑文字与非破坏式滤镜的工作方式。GIMP 使用 GPLv3 或更新版本，可用于参考操作和做独立渲染对照。 [GIMP 3.2 发布说明](https://www.gimp.org/release-notes/gimp-3.2.html) · [GIMP 许可证](https://www.gimp.org/docs/userfaq.html)

## 本次实测

在 Linux 上用 PhotoCraft v0.23.1 的官方 CLI 打开上一轮由 GIMP 生成的 960 × 720 RGB PSD，保留了原图、背景和图层蒙版。新增剪贴曲线后，参考蒙版外的像素保持一致。再加入中文标题「新品发布」，存为 PSD 后重新打开，四层仍分别是文字、剪贴曲线、带蒙版的原图和背景。重开前后渲染逐像素一致。重开后还实际把标题改成了「周末上新」，导出了 480 × 360 的 PNG。原尺寸无损 WebP 和同一版 PNG 的像素也一致。

这组结果来自同一份合成样本。实测方式是 PhotoCraft CLI 对文件读取、编辑、保存和重新渲染。Photoshop 打开结果、Mac 图形界面、其他字体、多画板 PSD 和复杂智能对象需要用新的样本验证。PhotoCraft 上游的 Photoshop 原作兼容统计和单样本自我往返是不同测试。 [原尺寸渲染](example.png) · [可编辑 PSD](example.psd) · [重开后的图层属性](example-layers.json) · [改字与缩尺寸后的输出](example-480.png)

## 功能按照设计任务验收

| 设计任务 | 需要的功能 | 怎样算够用 |
|---|---|---|
| 做商品精修图 | 选框、套索、魔棒、快速选择、主体选择、选区加减反选、羽化、边缘修整、保存与载入选区、图层蒙版黑白画笔 | 抠出浅色或带细边的商品，换两种反差背景复查，重开项目还能继续修边。 |
| 修掉尘点、瑕疵与杂物 | 画笔和橡皮、仿制图章、污点修复、修复画笔、修补、内容识别填充、当前层或可见层采样 | 在独立修复层处理瑕疵。关掉修复层能查看原图，恢复后无明显接缝，回退和重做能恢复笔划。 |
| 做合成海报、主图或封面 | 图层、组、排序、多选、剪贴蒙版、透明度、正片叠底／滤色／叠加、保留源像素的变换、嵌入与链接素材、替换内容、裁剪拉直、透视、辅助线、对齐吸附 | 用多张图组成海报。替换主素材后保持版面位置和样式。缩小后恢复原尺寸时，仍能使用源图像细节。 |
| 局部或全局调色 | 曝光、色阶、曲线、色相／饱和度、色彩平衡、可选颜色、直方图、带蒙版的调整图层、高斯模糊、锐化、降噪、可回编辑的滤镜 | 只改商品色调、不改背景；保存重开后还能调整参数、换蒙版和切换前后对比。 |
| 给数字图加可编辑版面 | 点文字、段落框、字体和字重、字号、行距与字距、中英混排、标点与换行、基础色块和渐变、描边投影、对齐分布 | 修改一段较长标题，检查行距、换行、边距和对齐。文字保持可编辑，可定位缺失字体，成品输出为位图。 |
| 一套设计出多个版本 | 同项目多画板、复用素材、版本及图层组合、按画板或图层导出、尺寸与命名预设、批量导出 | 同一套设计生成横版、竖版、方版和透明素材。换图或改字后按预设重导，检查实际像素尺寸、透明度、色彩配置与文件名。 |
| 与 Photoshop 交接与迭代 | PSD/PSB、原生项目、缺字体／缺链图提示、导入与导出保真说明、历史、自动保存和恢复；PNG、JPEG、WebP、TIFF 等按需要输出 | 用带分组、文字、曲线、剪贴、混合、蒙版和智能对象的 PSD 样本验证画面、结构和可编辑性。对无法保留的数据在保存前有具体提示。 |

功能对照：[Photoshop 非破坏编辑](https://helpx.adobe.com/photoshop/desktop/create-manage-layers/create-layer-compositions/non-destructive-editing-techniques.html) · [选区工具](https://helpx.adobe.com/photoshop/desktop/make-selections/get-started-selections/selection-tools-overview.html) · [跨层采样](https://helpx.adobe.com/photoshop/desktop/create-manage-layers/get-started-layers/sample-from-all-visible-layers.html) · [调整图层](https://helpx.adobe.com/photoshop/desktop/create-manage-layers/color-adjustment-fill-layers/adjustment-layers-options.html) · [中文及东亚字符](https://helpx.adobe.com/photoshop/desktop/text-typography/international-text-languages/format-asian-type-characters.html) · [多画板](https://helpx.adobe.com/photoshop/desktop/create-manage-layers/get-started-layers/use-artboards-to-lay-out-designs.html) · [多尺寸导出](https://helpx.adobe.com/photoshop/desktop/save-and-export/export-files-to-different-formats/export-files-in-different-sizes.html)

## 对下一版工作台的要求

截图里的工具入口应和真实能力对上。主工具栏要能找到移动变换、选区、裁剪、画笔修复、文字与渐变。画布上方显示当前工具的选项，右侧常驻图层与混合控制，并提供调整、通道、历史和属性。通过可搜索的命令和快捷键补全藏在同组里的工具。用一张包含图层、文字、调整和多个尺寸的设计稿验收工具是否可发现。 [Photoshop 工作区](https://helpx.adobe.com/photoshop/desktop/get-started/learn-the-basics/workspace-overview.html)

“轻量”先用实际操作定义。分别记录冷启动、打开和保存 4K 多图层项目、拖动变换、笔刷落下和抬起、调色预览与批量导出的耗时和内存峰值。用 sRGB 测交付，用带 ICC 的屏幕图片和 16 位渐变测色彩降级。现有两层交互原型只验证了抠图换背景这条链；这次调研未改 P一下的应用代码。 [Photoshop 位深说明](https://helpx.adobe.com/photoshop/desktop/adjust-color/color-modes/bit-depth-in-photoshop.html)
