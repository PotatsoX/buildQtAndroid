# buildQtAndroid

在 **Windows runner** 上从 Qt 源码构建 **Android arm64-v8a** 版 Qt（Windows 主机交叉编译），产物为可直接用于 Qt Android 工程交叉编译的 Qt 前缀。

> 本仓库只构建 Qt 库/Qt 前缀，不构建、不签名 APK；APK 打包属于使用方的 `androiddeployqt + Gradle` 流程。

## 结论与定位

- 采用两阶段构建：先构建 **host Qt 工具**（MinGW，提供 `qmake`/`moc`/`rcc`/`qmlimportscanner`/`androiddeployqt`），再用 `-qt-host-path` 交叉编译 **target Qt**（NDK clang，ABI 固定 `arm64-v8a`）。
- 默认只构建**最小可用模块集**：`qtbase`、`qtdeclarative`、`qttools`、`qtshadertools`。全量 Qt 在标准 Windows runner 上很可能同时超出 6 小时任务上限与磁盘预算。
- 标准 GitHub Windows runner 规格为 4 vCPU / 16 GB RAM / 14 GB SSD、单 job 最长 6 小时；缓存总额 10 GB/仓库。以上为 GitHub 文档口径，本工作流会打印实际剩余空间。
- 参考项目 [PotatsoX/buildQt](https://github.com/PotatsoX/buildQt) 是 **Qt 5.15.19 + MinGW 8.1.0 的桌面构建**，与本项目目标不同；仅借鉴其工作流组织方式（`workflow_dispatch`、7z artifact、tag release）。Android/Qt 6.12 的参数全部来自 Qt 官方资料，不沿用其 Qt 5 配置。

## 工具链版本（Qt 6.12 官方要求）

来源：<https://wiki.qt.io/Qt_6.12_Tools_and_Versions>（页面标题 *Software configurations for Qt 6.12.0*），取 **Windows 11 24H2 x86_64** 列。

| 组件 | 版本 | 说明 |
|---|---|---|
| Android NDK | **r27c** | 直接使用 Google 官方 zip，`android-ndk-r27c` |
| SDK Platform | **android-37.0** | `sdkmanager "platforms;android-37.0"` |
| Build Tools | **37.0.0** | 仅安装该版本，避免 Qt 自动选到更高版本 |
| SDK Command-line Tools | **19.0** | `commandlinetools-win-13114758_latest.zip` |
| CMake | **4.3.2** | 固定下载，不使用 runner 自带版本 |
| JDK | **21.0.9 (x64)** | `actions/setup-java` Temurin |
| MinGW-w64 | **15.1.0**（posix-seh, msvcrt, rt_v12） | Qt 官方页 Windows 列版本 |
| Ninja | **1.10.2** | 固定下载 |
| 7-Zip | **24.09** | 仅用于解压/打包 |
| Python | **3.11.9** | 官方页另一列为 3.8.1，两者均满足 Qt 构建需要 |
| OpenSSL | 3.5.4 | 本工作流不构建/不链接 Android OpenSSL，见“已知限制” |
| Perl | 5.42.2.1 | 官方版本页未列出 Perl，沿用参考项目的 Strawberry Perl 便携版 |

文档冲突说明：`doc.qt.io` 的 *Qt for Android — Building from Source* 页面写的是 MinGW-w64 **13.1**，并明确 **Windows 主机不支持用 MSVC 构建 Qt for Android**。本仓库以 6.12 版本页的 **15.1.0** 为准；“不能用 MSVC”这一点两处一致，因此 host 构建固定 MinGW。

版本页未列 **Gradle** 与 **ABI 列表**，本流程不涉及 Gradle（不出 APK），ABI 固定为 `arm64-v8a`。

## 工作流

文件：`.github/workflows/build-qt-android.yml`

触发方式：

- `workflow_dispatch`（手动，首轮推荐）
- 推送 `qt-*` tag（构建并自动发布 GitHub Release）

可调参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `qt_version` | `6.12.0` | 源码版本，下载 `qt-everywhere-src-<ver>.tar.xz` |
| `modules` | `qtbase qtdeclarative qttools qtshadertools` | 必须包含 `qtbase`；其余目录在解压后裁剪 |
| `host_only` | `false` | 只构建 host 工具，便于排错 |
| `runner` | `windows-2022` | 可换成 larger runner 标签 |

流程步骤：

1. 恢复缓存（源码归档 / host 前缀 / Android SDK+NDK）。
2. 安装固定版本 JDK、Python、MinGW、CMake、Ninja、Perl、7-Zip、Android SDK/NDK。
3. `scripts/fetch-qt-source.ps1` 下载源码归档，只保留 `modules` 列出的模块目录。
4. **host 构建**：`configure.bat ... -platform win32-g++`，安装到 `D:\qt\host`，标记 `.cache-ok` 后删除 build 目录。
5. **target 构建**：`configure.bat ... -qt-host-path D:\qt\host -android-abis arm64-v8a -android-sdk ... -android-ndk ...`，安装到 `D:\qt\android_arm64_v8a`。
6. `scripts/verify-android-prefix.py` 校验 ABI/关键库/host 工具，输出 `manifest.json`。
7. 7z 打包并上传 artifact：`qt-<ver>-android-arm64-v8a-windows-host`。

磁盘布局：源码、构建目录与安装前缀放在 **D:**（runner 临时盘）；SDK/NDK/工具装在 **C:**，避免挤占 14 GB 的 D: 盘。

## 模块裁剪与可行性

- 源码归档 `qt-everywhere-src-6.12.0.tar.xz` 实测约 **443 MB**（HTTP `Content-Length`）。
- 解压后先保留全部模块再裁剪，峰值估计 **4–5 GB**（未实测）；裁剪后仅剩 4 个模块。
- 时间估计（4 vCPU，未实测）：host 约 60–120 分钟，target 约 60–150 分钟。**首轮以 CI 实际耗时为准**；若接近 6 小时，需改 larger runner 或进一步裁剪。
- 建议裁剪/不默认构建：`qtwebengine`、`qtpdf`、`qtmultimedia`、`qt3d`、`qtquick3d`、`qtcharts`、`qtdatavis3d`、`qtlocation`、`qtwebview`、`qtdoc`、`qttranslations`。需要 WebEngine 时请使用 larger runner 或自托管 runner，并单独评估磁盘与时长。
- 缓存策略：源码归档（约 443 MB）、host 前缀（约 1–2 GB）、Android SDK/NDK（约 3 GB）；均带版本号 key，避免脏命中。target 构建目录不入缓存（体积大且多数场景下缓存收益低），因此仓库缓存总量控制在 10 GB 限额内。
- ccache/sccache 未启用：Windows + MinGW 下收益与稳定性未验证，host 前缀缓存已覆盖重复构建的主要成本。

## 使用方法

1. 打开仓库 **Actions → build-qt-android → Run workflow**，保持默认参数（最小模块集）后运行。
2. 成功后在该 run 页面下载 artifact；如推送了 `qt-*` tag，还会生成 Release 附件。
3. 使用产物：

```powershell
# 解压后得到 android_arm64_v8a 前缀
cmake -S <your-app> -B build `
  -DCMAKE_TOOLCHAIN_FILE="D:\qt\android_arm64_v8a\lib\cmake\Qt6\qt.toolchain.cmake" `
  -DANDROID_NDK_ROOT="C:\android\ndk\android-ndk-r27c" `
  -DANDROID_SDK_ROOT="C:\android\sdk" `
  -DQT_HOST_PATH="D:\qt\host"
```

> `qt.toolchain.cmake` 在包内写死了 `/opt/android/...` 的默认路径，必须显式传入 `ANDROID_NDK_ROOT`/`ANDROID_SDK_ROOT`，否则配置阶段会报错。

## 验证方式

CI 内的自动校验（`scripts/verify-android-prefix.py`）：

- `lib/*.so` 全部为 ELF64、`e_machine=183`（AArch64）；
- 存在 `libQt6Core*.so` 与 `lib/cmake/Qt6/Qt6Config.cmake`；
- target 前缀中无 `.exe`/`.dll`（host 工具只应存在于 host 前缀）；
- host 前缀存在 `qmake*.exe`、`moc.exe`、`androiddeployqt.exe`；
- 记录 NDK/SDK 实际版本、库清单与 SHA-256 到 `manifest.json`。

本地只做静态校验（YAML 语法、PowerShell/Python 语法）；Qt 编译由 CI 执行。

## 已知限制与未核实项

- **未在本机编译验证**：Qt 6.12 + MinGW 15.1.0 + CMake 4.3.2 的组合以官方版本页为准，是否存在 6.12 特有的配置项差异，需以首轮 CI 结果确认。
- `-no-openssl`：用于避免引入 Android OpenSSL 预编译依赖，代价是 QtNetwork 无 TLS。若需要 HTTPS，应另行构建 OpenSSL 3.5.4 for Android 并改为 `-openssl-linked`。
- 官方版本页未列 Perl 版本；使用参考项目的 Strawberry Perl 5.42.2.1 便携版。
- `actions/setup-java` 是否可精确拉到 Temurin `21.0.9` 未在本地核实；失败时会回退到同主版本（需改 workflow）。
- 标准 runner 的实际可用磁盘可能因镜像不同而波动；工作流只打印、不强制清理系统目录。
- 全量模块构建在本仓库默认配置下不可行（时间/磁盘），如需全量请改用 larger runner（如 `windows-latest-8-cores`，需账户支持）或自托管 runner。
- artifact 为未签名的 Qt 前缀，不含 APK，不含 Android 签名材料。

## 文件

```
.github/workflows/build-qt-android.yml   # 两阶段构建工作流
scripts/fetch-qt-source.ps1             # 下载/解压/裁剪 Qt 源码
scripts/verify-android-prefix.py        # 产物 ABI 与结构校验 + manifest
```
