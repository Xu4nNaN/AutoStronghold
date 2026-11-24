# 第三方组件

AutoStronghold 自身的代码以 GPL-3.0-or-later 发布。发布包中还包含以下第三方组件，它们适用各自的许可证；许可证原文由构建脚本收集在发布包的 `_internal\licenses` 文件夹中（本文件与 LICENSE 也在其中）；安卓版收集在 APK 内，可在程序底部「许可证」中查看。

| 组件 | 用途 | 许可证 |
| --- | --- | --- |
| [MaaFramework](https://github.com/MaaXYZ/MaaFramework)（Python 包 `maafw`） | 模拟器与 PC 端的截图、触控、窗口输入 | LGPL-3.0 |
| MaaAgentBinary：MaaTouch、minitouch、minicap（随 MaaFramework 分发） | 推送到模拟器上运行的触控 / 截图辅助程序，与本程序通过 adb 通信，属于独立程序 | MaaTouch：AGPL-3.0（源码：[MaaAssistantArknights/MaaTouch](https://github.com/MaaAssistantArknights/MaaTouch)）；minitouch、minicap：Apache-2.0（源码：[openatx/stf-binaries](https://github.com/openatx/stf-binaries)） |
| [RapidOCR](https://github.com/RapidAI/RapidOCR)（`rapidocr-onnxruntime`） | 文字识别流程 | Apache-2.0 |
| PaddleOCR PP-OCRv4 模型（随 RapidOCR 分发） | 文字检测与识别模型 | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime)（CPU 版 `onnxruntime` / GPU 版 `onnxruntime-directml`，含 DirectML） | 模型推理 | MIT（DirectML 等见包内 ThirdPartyNotices） |
| [OpenCV](https://opencv.org/)（`opencv-python`；安卓版为 Chaquopy 构建的 `opencv-python-headless` 4.5.1） | 图像处理 | Apache-2.0 |
| NumPy、Shapely、pyclipper、PyYAML、six、Pillow、tqdm 等 | RapidOCR 与图像处理的依赖（安卓版不含 pyclipper、six、tqdm，见下） | BSD / MIT / HPND 等 |
| [PyInstaller](https://pyinstaller.org/) 引导程序 | 打包为 exe | GPL-2.0（含引导程序例外条款） |
| Python 运行时 | — | PSF License |
| [Chaquopy](https://chaquo.com/chaquopy/)（仅安卓版） | 在安卓上运行 Python 与本项目的包；NumPy、OpenCV、Shapely、PyYAML、Pillow 使用其安卓构建 | MIT |
| [ONNX Runtime for Android](https://onnxruntime.ai/)（`com.microsoft.onnxruntime:onnxruntime-android`，仅安卓版） | 安卓版的模型推理（与电脑版同一推理引擎的 Java 接口） | MIT（见其 ThirdPartyNotices） |

MaaFramework 以独立的 DLL 形式随程序分发（位于 `_internal\maa\bin`），未经修改，可按 LGPL-3.0 的要求自行替换为其他兼容版本。

安卓版没有 `onnxruntime` 与 `pyclipper` 的 Python 包。`android/app/src/main/python` 中按 RapidOCR 用到的接口重新编写了两个替代模块（推理转给 ONNX Runtime 的 Java 接口；文字框外扩改用 Shapely），未包含这两个项目的代码。

## 移植的代码

* [Stronghold-Protocol（卫戍协议：盟约 同人复刻）](https://github.com/sganggs/Stronghold-Protocol)，GPL-3.0-or-later，Copyright (C) 2026 Stronghold-Protocol contributors：`autostronghold/game/rules.py` 中休整期的规则（整备区容量、3 名合成精锐与奖励卡、出售 1 资金、刷新 1 资金、各级商店栏位、升级后价格重置）移植自其 `server/match/gamedata.js`、`server/match/player/economy.js` 与 `data/versions/act3autochess-v3_1/config.json` 的经济参数。移植部分与本项目整体同样适用 GPL-3.0-or-later。游戏数据本身（名称、数值）的权利归游戏版权方，不在上述许可证范围内。

## 参考资料（未包含其代码）

* [MAA（MaaAssistantArknights）](https://github.com/MaaAssistantArknights/MaaAssistantArknights)，AGPL-3.0：本项目未复制 MAA 的代码，只作为参考。
* GarrisonFarm 及其优化版本：未附项目级许可证，仅作为功能与界面行为参考。本项目未复制其源代码文件、bat 或二进制内容；部分界面坐标与颜色阈值参考了其中的数值并经实机截图重新核对。
* [PRTS 维基](https://prts.wiki/w/卫戍协议·规程/PRTS盟约记录)「卫戍协议·规程」页面：`resources/data/prts_lists.json` 中的策略、干员、盟约（阵营 / 特性）与装备名称列表从这些页面整理而来，只用于把识别出的文字对应到名称，不含页面正文与图片。页面内容的著作权归 PRTS 及其贡献者。
* [StrongholdAssistant（卫戍协议助手）](https://github.com/LBEILC/StrongholdAssistant)，Apache-2.0：本次未使用，仅预留了接入接口。
