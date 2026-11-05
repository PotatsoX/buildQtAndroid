# buildQtAndroid

在 **Windows runner** 上从 Qt 源码构建 **Android（arm64-v8a / armeabi-v7a）** 版 Qt（Windows 主机交叉编译）；host 工具在同一次 run 里由本工作流从源码自建（Windows 桌面构建，MinGW 15.1.0），产物**同时包含 target 前缀与 host 前缀**，拿到即可交叉编译并用 `androiddeployqt` 打包 APK。

> 本仓库只构建 Qt 库/Qt 前缀，不构建、不签名 APK；APK 打包属于使用方的 `androiddeployqt + Gradle` 流程。

## 结论与定位

- host 只有一种来源：本工作流在同一轮 run 里用 MinGW 15.1.0 从同一份源码自建 Windows 桌面 host（`host_linkage` 决定 shared/static）。代价是 host 每轮都要编，实测约 **2 小时 41 分 48 秒**；仅当 host 前缀缓存命中（`.cache-ok` 标识一致）时才跳过。host 与 target 同源码构建，版本天然一致，不再单独断言版本。target 一律用 `-qt-host-path` + NDK clang 交叉编译，ABI 由输入 `abi` 决定（默认 `arm64-v8a`）。
- 产物是 **target 前缀 + host 前缀** 两个同级目录，7z 内保持同级，因此 `target/bin/target_qt.conf` 的相对 `HostPrefix` 解压后仍能解析到 host 工具；压缩包顶层另附 `BUILD-INFO.txt`（UTF-8 with BOM），记录本次的 configure 原文、工具链版本与阶段耗时。
- 默认参数基线取自参考项目 [yuanpeirong/buildQt](https://github.com/yuanpeirong/buildQt) 的 `buildQt6/build-Qt6mingw64.cmd:33`：全量解压源码 + `-nomake examples -nomake tests` + `-skip qtwebengine`；本仓库默认再追加本次指定的跳过项（见「模块选择机制」），构建范围靠 configure 参数控制，不删源码。
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
| MinGW-w64 | **15.1.0**（posix-seh, msvcrt, rt_v12） | host 阶段在构建步骤内部下载使用；target 用 NDK clang |
| Ninja | **1.10.2** | 固定下载 |
| 7-Zip | **24.09** | 仅用于解压/打包 |
| Python | **3.11.9** | 官方页另一列为 3.8.1，两者均满足 Qt 构建需要 |
| OpenSSL | **3.5.4（仅头文件）** | 版本对齐 Qt 6.12 版本页；解出源码包 `include/openssl` 并用 `Configure`+`util/dofile.pl` 生成实体 `.h`，供 target 的 `-openssl-runtime` 探测/编译后端插件；不编译、不链接、不随包分发库，见「下游如何用 TLS」 |
| Perl | 5.42.2.1 | 官方 Software 表列为 strawberry 5.32.0.1；GitHub 上无该版本 portable 资产，沿用参考项目的 5.42.2.1 |

文档冲突说明：`doc.qt.io` 的 *Qt for Android — Building from Source* 写 MinGW-w64 **13.1**，6.12 版本页写 **15.1.0**。本仓库以 6.12 版本页为准 —— 实测 Qt 6.12.0 的 `config_qtbase.summary` 里 Compiler 就是 **gcc 15.1.0**，与版本页一致。“Windows 主机不能用 MSVC 构建 Qt for Android”两处一致，本仓库也不受影响：target 用 NDK clang，host 用 MinGW 15.1.0 自建。

版本页未列 **Gradle** 与 ABI 列表；但 Qt 6.12 的 Android JAR 由 Gradle 构建，Qt 自身构建期就需要 Gradle（源码树内 wrapper 指定 Gradle **9.5.1**），详见「为什么 target configure 需要 Gradle 离线缓存」。ABI 由输入 `abi` 决定（默认 `arm64-v8a`，官方 CI 对照行用的是 `armeabi-v7a`）。

## 工作流

文件：`.github/workflows/build-qt-android.yml`

触发方式：

- `workflow_dispatch`（手动，首轮推荐）
- 推送 `qt-*` tag（构建并自动发布 GitHub Release）

可调参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `qt_version` | `6.12.0` | 源码版本，下载 `qt-everywhere-src-<ver>.zip`；必须是 `x.y.z`，在 `Compute cache key suffix` 步骤校验 |
| `openssl_version` | `3.5.4` | 只用于下载 OpenSSL 源码包并生成 `include/openssl` 下的实体头文件（runtime SSL 的头文件依赖）；必须是 `x.y.z`；改动会同时换掉头文件缓存 key |
| `skip_modules` | `qtwebengine` + 10 模块 + 3 feature | 空格/逗号分隔：模块名传给 configure `-skip`；以 `-` 开头的原样传给 target configure（如 `-no-feature-printsupport`）。默认另含 `-no-feature-tiff`，保留 png/jpeg/webp/svg/ico/gif。完整默认值见「模块选择机制」 |
| `host_modules` | `auto` | host 阶段编译的模块集：`auto` = 白名单 ∩ target 实际构建的模块；`all` = 全量（只减去 `skip_modules` 里的模块名）；也可给逗号分隔的模块名，未知模块直接报错且必须包含 `qtbase` |
| `abi` | `arm64-v8a` | 目标 ABI，可选 `arm64-v8a` / `armeabi-v7a`（官方 CI 对照行用 armv7） |
| `host_only` | `false` | 只构建 host 工具（调试用） |
| `host_linkage` | `shared` | host 链接方式：`shared` = 共享链接（工具运行期依赖 `Qt6*.dll`）；`static` = 追加 `-static -static-runtime -DFEATURE_relocatable=ON`（去 DLL 依赖，未经 CI 验证） |
| `host_tools` | `android` | host 工具裁剪：`android` = 只留 Android 构建链路需要（裁掉桌面专用工具）；`full` = 跳过 `bin` 裁剪，用于排查“是不是裁太狠” |
| `runner` | `windows-2022` | 可换成 larger runner 标签 |

流程步骤：

1. 恢复缓存（源码归档 / Android SDK+NDK / OpenSSL 头文件 / host 前缀；Gradle home 在 target configure 前恢复）。
2. 安装固定版本 JDK、Python、CMake、Ninja、Perl、7-Zip、Android SDK/NDK；MinGW 15.1.0 在 host 构建步骤内部下载，target 用 NDK clang。
3. **准备 OpenSSL 头文件**：下载 `openssl-<openssl_version>.tar.gz`（release 资产，有 `.sha256` 就校验，取不到只告警并明说未校验）→ 7z 解压 → **Perl 模块预检**（`Configure`/`util/dofile.pl` 实际 `use` 的 10 个模块，缺一个就打印模块名与报错并失败）→ `perl Configure linux-x86_64 no-shared no-tests`（不探测编译器、只为产出 `configdata.pm`）→ `util/dofile.pl` 把 28 个 `.h.in` 生成成实体 `.h` → 校验总数为 144、`ssl.h`/`opensslv.h`/`x509v3.h` 存在且 `OPENSSL_VERSION_MAJOR=3` → 只留 `include/openssl` 到 `D:\qt\openssl-headers`，随即删除源码树、源码包与临时目录。该目录由 Actions 缓存，命中时跳过下载/Configure/生成（近 0 秒）；日志会分别打出 download/extract/precheck/configure/generate/verify 各自秒数。实体头文件为何必须生成见「下游如何用 TLS」。
4. `scripts/fetch-qt-source.ps1` 下载官方 **zip** 归档（md5 校验取自 `md5sums.txt` 的 zip 行；`official_releases` 与 `archive` 两处都试），用 7-Zip 多线程**全量解压**；每 30 秒打印已解出文件数、累计字节数、7z 的 CPU 秒数与工作集。
5. **host 工具（源码自建）**：MinGW 15.1.0 桌面 `configure -skip <host_skip_modules>` → build → `install --strip` 到 `D:\qt\host`，写 `.cache-ok`（内容为 `build:<linkage>:<host_set>`）后删 build 目录；若 `.cache-ok` 与本次标识一致则直接跳过编译。`host_skip_modules` 由 `host_modules` 推出，默认只编 target 构建会用到的工具模块（见「host 模块集」）；`host_linkage=static` 时追加 `-static -static-runtime -DFEATURE_relocatable=ON`（见「host 链接方式」）。
6. **Gradle 离线缓存准备**：按 `qtbase/cmake/QtJavaHelpers.cmake` 报错给出的命令调用 `cmake\QtSetupAndroid.cmake`，先把 `Qt6Android` JAR 的 Gradle 依赖填进 `~/.gradle`（已命中则跳过联网）。
7. **target 构建**：`configure.bat ... -qt-host-path D:\qt\host -android-abis <abi> -android-sdk ... -android-ndk ... -openssl-runtime -DFEATURE_ssl=ON -DOPENSSL_ROOT_DIR=D:\qt\openssl-headers -no-feature-sql-* -skip <模块> <feature 参数>`，安装到 `D:\qt\android_<abi>`；实际命令行原文写入 `target-configure.txt`，最终进 `BUILD-INFO.txt`。SSL 为 runtime 模式：只编入能力，不链接、不分发库（见「下游如何用 TLS」）。
8. `scripts/verify-android-prefix.py` 校验 ABI/关键库/host 工具/`Qt6HostInfo`/`Qt6Android.jar`/Gradle wrapper，并新增 SSL 三条断言（`QT_FEATURE_ssl=1`、`QtNetwork`/openssl 后端的 `NEEDED` 不含 `libssl`/`libcrypto`、前缀内无 `libssl*.so`/`libcrypto*.so`），输出 `manifest.json`。
9. **裁剪 host 前缀**（`host_tools=android` 时）：目录/`lib`/`bin` 三级白名单，被删清单写入 `D:\qt\prune-report.txt`（见「host 前缀内容与用途」）。
10. **重定位**：把交付前缀里残留的构建机绝对路径改写成相对表达式（`target/bin/qmake*.bat` → `%~dp0..\..\host\bin\…`，`Qt6Dependencies.cmake` → `${Qt6_DIR}/../../../../host`，`QtBuildInternalsExtra.cmake` → `${CMAKE_CURRENT_LIST_DIR}/../../..`，`mkspecs/modules/qt_ext_*.pri` 的源码树头文件目录置空），并校验 `target_qt.conf` 的 `HostPrefix=../../host` 确实解析到 host 前缀；末尾硬校验整个交付前缀内 `D:\qt` / `D:/qt` 命中必须为 0，否则打印文件清单并失败。
11. **冒烟 host 工具**：用裁剪后的 host 前缀对最小 Qt Widgets+Quick 工程跑 `cmake` 配置（`-DCMAKE_TOOLCHAIN_FILE=<NDK>/build/cmake/android.toolchain.cmake`、`-DANDROID_ABI=<abi>`、`-DCMAKE_PREFIX_PATH=<target>`、`-DQT_HOST_PATH=<host>`）+ `androiddeployqt --help`，失败会点名缺失工具；随后**不传 `-DQT_HOST_PATH`** 再配置一次，配置通过且 `CMakeCache` 里有 `Qt6HostInfo_DIR` 才算相对路径真的生效。
12. 生成 `BUILD-INFO.txt`（UTF-8 with BOM，压缩包顶层），记录版本/ABI/host 来源与链接方式、skip 项、host 生效模块、SSL 模式与 OpenSSL 头文件版本、重定位改写处数与校验命中数、host/target configure 原文、工具链版本、runner 环境、`T_*` 阶段耗时、`[裁剪记录]`、产物自检输出与 target 图像插件清单。
13. 7z 打包 **target + host 两个前缀 + `BUILD-INFO.txt`**（`-mx=9 -ms=on`）并上传 artifact：`qt-<ver>-android-<abi>-windows-host`。

磁盘布局：源码、构建目录与安装前缀放在 **D:**（runner 临时盘）；SDK/NDK/工具装在 **C:**，避免挤占 14 GB 的 D: 盘。

## 工作流使用的 Action 版本

全部已支持 Node 24（各 tag 的 `action.yml` 为 `runs.using: node24`），不再触发 Node 20 弃用告警。工作流按主版本 tag 引用（`@v6`/`@v7`），下表版本为 2026-11-04 的实际解析结果：

| Action | 版本 | 依据 | 参数核对 |
|---|---|---|---|
| `actions/checkout` | v6.1.0 | [v6.1.0 action.yml](https://github.com/actions/checkout/blob/v6.1.0/action.yml) | 无参数，`pull_request_target` 相关变更不涉及 |
| `actions/cache` | v6.1.0 | [v6.1.0 action.yml](https://github.com/actions/cache/blob/v6.1.0/action.yml) | `path`/`key`/`restore-keys` 未变；`save-always` 已弃用（未使用） |
| `actions/setup-java` | v6.1.0 | [v6.1.0 action.yml](https://github.com/actions/setup-java/blob/v6.1.0/action.yml) | `distribution: temurin`、`java-version`、`architecture` 未变；v6 移除 adopt 系 distribution（未使用），未用 `cache` |
| `actions/setup-python` | v6.3.0 | [v6.3.0 action.yml](https://github.com/actions/setup-python/blob/v6.3.0/action.yml) | `python-version`/`architecture` 未变 |
| `actions/upload-artifact` | v7.0.2 | [v7.0.2 action.yml](https://github.com/actions/upload-artifact/blob/v7.0.2/action.yml) | `name`/`path`/`compression-level`/`retention-days` 未变 |
| `softprops/action-gh-release` | v3.0.3 | [v3.0.3 action.yml](https://github.com/softprops/action-gh-release/blob/v3.0.3/action.yml) | `files` 与 v2 兼容 |

`actions/download-artifact` 未使用（若将来引入，v5 的单 ID 下载路径已从 `path/<name>/` 改为 `path/`，v8 起哈希不匹配默认报错）。

## 模块选择机制

Qt 顶层 `configure` **不做自动选择**：源码树里有哪个模块目录，就默认纳入构建；缩小的方式只有两类：`-skip <模块>` 删掉整个模块，`-no-feature-<feature>` 关闭模块内的特性。

`skip_modules` 的解析规则：

- 空格或逗号分隔；
- 不以 `-` 开头的 token → `-skip <token>`；
- 以 `-` 开头的 token → 原样传给 target configure（如 `-no-feature-printsupport`）；host 阶段只消费模块名，不下发 feature 参数，避免 host 未编该模块时 `configure` 报 unknown feature。

默认值：

```
qtwebengine qtgrpc qtserialbus qtscxml qtopcua qtremoteobjects qtactiveqt qtwayland qttasktree qtcoap qtwebchannel -no-feature-printsupport -no-feature-spatialaudio -no-feature-tiff
```

`qtwebengine` 保留在默认值里（构建开销最大且 Android 侧通常不需要）；其余为本次指定的 10 个模块 + 3 个特性（PrintSupport、SpatialAudio、TIFF）。GIF 明确保留。

用户清单 → 实际开关：

| 用户写法 | 实际模块 / feature | 关闭方法 | 核实 |
|---|---|---|---|
| gRPC | `qtgrpc`（含 `qtprotobuf`） | `-skip qtgrpc` | 是：`qt5` 6.12.0 顶层模块目录 |
| Serial Bus | `qtserialbus` | `-skip qtserialbus` | 是 |
| SCXML | `qtscxml` | `-skip qtscxml` | 是 |
| OPC UA | `qtopcua` | `-skip qtopcua` | 是 |
| Remote Objects | `qtremoteobjects` | `-skip qtremoteobjects` | 是 |
| Active Qt | `qtactiveqt` | `-skip qtactiveqt` | 是 |
| Wayland | `qtwayland` | `-skip qtwayland` | 是 |
| Print Support | **不是独立模块**：qtbase 的 `printsupport` feature（SECTION `Module`，即 QtPrintSupport） | `-no-feature-printsupport` | 是：`qtbase/configure.cmake:1146-1151`；关闭后 QtPrintSupport 整个不构建 |
| CoAP | `qtcoap` | `-skip qtcoap` | 是 |
| Spatial Audio | **qtmultimedia 内的 feature**：`spatialaudio`（`spatialaudio_quick3d` 依赖它） | `-no-feature-spatialaudio` | 是：`qtmultimedia/src/multimedia/configure.cmake:281-287`；代价是 QtMultimedia 的空间音频 API 与相关 Quick3D 集成不可用，其余多媒体功能保留 |
| WebChannel | `qtwebchannel` | `-skip qtwebchannel` | 是 |
| TaskTree | **独立模块** `qttasktree`（不在 qtbase 内） | `-skip qttasktree` | 是：`qt5` 6.12.0 顶层目录，`qttasktree/dependencies.yaml` 仅依赖 qtbase |

上述 12 项没有“无法按用户方式关闭”的项；`Print Support` 与 `Spatial Audio` 用 feature 开关，代价是各自模块内的对应功能不可用。

为什么不采用「解压后删掉不需要的模块」：configure 要遍历源码树，缺目录会被当作模块不存在而跳过，删源码省不了 configure 时间，还多一轮十几万文件的删除写操作。缩小范围只用 `-skip` 与 feature 开关。

### 图像格式（默认只保留 png / jpeg / webp / svg / ico / gif）

默认 `skip_modules` 末尾只追加 `-no-feature-tiff`，`ico`、`gif` 保持开启。Qt 6.12 的图像格式分三类：

| 格式 | 实现位置 | 默认开关 | 源码依据 |
|---|---|---|---|
| png | qtbase QtGui **内建 handler**（不是插件） | 保留；`-no-feature-png` 会把 PNG 整体去掉，不要用 | [qtbase/src/gui/configure.cmake:1202](https://github.com/qt/qtbase/blob/v6.12.0/src/gui/configure.cmake#L1202)、[qtbase/src/gui/CMakeLists.txt:668-671](https://github.com/qt/qtbase/blob/v6.12.0/src/gui/CMakeLists.txt#L668-L671) |
| bmp / ppm / xbm / xpm | qtbase QtGui **内建 handler** | 始终编译，**没有 feature 开关** | [qtbase/src/gui/CMakeLists.txt:69,89-91](https://github.com/qt/qtbase/blob/v6.12.0/src/gui/CMakeLists.txt#L69-L91) |
| jpeg | qtbase 插件 `qjpeg` | 保留 | [configure.cmake:1190-1196](https://github.com/qt/qtbase/blob/v6.12.0/src/gui/configure.cmake#L1190-L1196)、[qtbase/src/plugins/imageformats/CMakeLists.txt:7-9](https://github.com/qt/qtbase/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L7-L9) |
| gif | qtbase 插件 `qgif` | 保留（明确选择，`QMovie`/`AnimatedImage` 动图可用） | [configure.cmake:1180-1184](https://github.com/qt/qtbase/blob/v6.12.0/src/gui/configure.cmake#L1180-L1184)、[CMakeLists.txt:10-12](https://github.com/qt/qtbase/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L10-L12) |
| ico | qtbase 插件 `qico` | 保留（目标格式之一） | [configure.cmake:1185-1189](https://github.com/qt/qtbase/blob/v6.12.0/src/gui/configure.cmake#L1185-L1189)、[CMakeLists.txt:4-6](https://github.com/qt/qtbase/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L4-L6) |
| webp | qtimageformats 插件 `qwebp`（内含 libwebp 源码） | 保留 | [qtimageformats/src/imageformats/configure.cmake:76-87](https://github.com/qt/qtimageformats/blob/v6.12.0/src/imageformats/configure.cmake#L76-L87)、[.../plugins/imageformats/CMakeLists.txt:17-19](https://github.com/qt/qtimageformats/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L17-L19) |
| tiff | qtimageformats 插件 `qtiff`（内含 libtiff 源码） | **关闭**：`-no-feature-tiff` | [configure.cmake:65-76](https://github.com/qt/qtimageformats/blob/v6.12.0/src/imageformats/configure.cmake#L65-L76)、[CMakeLists.txt:14-16](https://github.com/qt/qtimageformats/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L14-L16) |
| svg | qtsvg 插件 `qsvg`（`Qt::SvgPrivate`） | 保留；**不能** `-skip qtsvg` | [qtsvg/src/plugins/imageformats/CMakeLists.txt:4](https://github.com/qt/qtsvg/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L4)、[.../svg/CMakeLists.txt:8-18](https://github.com/qt/qtsvg/blob/v6.12.0/src/plugins/imageformats/svg/CMakeLists.txt#L8-L18) |

插件是否真的不产出，取决于 `qt_internal_add_plugin` 外层有没有 `if(QT_FEATURE_<name>)`：gif/ico/jpeg 在 [qtbase/src/plugins/imageformats/CMakeLists.txt](https://github.com/qt/qtbase/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L4-L12) 里按 feature 决定 `add_subdirectory`，tiff/webp 在 [qtimageformats 同名文件](https://github.com/qt/qtimageformats/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L14-L19) 里同理；所以 `-no-feature-tiff` 是“整目录不参与构建”，不是只改编译选项。`tiff` 是 qtimageformats 的模块级 feature，configure 在解析参数前会收集所有模块的 feature，可直接用 `-no-feature-<name>`；若某版本报 unknown feature，退化为 `-DFEATURE_tiff=OFF`。

**无法用 configure 单独关闭**（明确保留，不做静默处理）：

- `bmp`/`ppm`/`xbm`/`xpm`：handler 无条件编进 QtGui，Qt 6.12 没给 feature。
- `tga`、`wbmp`：qtimageformats 顶层无条件 `add_subdirectory`（[CMakeLists.txt:12-13](https://github.com/qt/qtimageformats/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L12-L13)）。
- `icns`：只受 qtbase `regularexpression` feature 门控（[:23-25](https://github.com/qt/qtimageformats/blob/v6.12.0/src/plugins/imageformats/CMakeLists.txt#L23-L25)），单关它要 `-no-feature-regularexpression`，会连带去掉 QRegularExpression，不可接受。
- `mng`/`jasper`(jp2)：`AUTODETECT OFF` 且需 libmng/JasPer，默认不构建；Qt 6.12 的 qtimageformats **没有 heic 插件**。

副作用：TIFF 文件不再可读；png/jpeg/webp/svg/ico/gif 不受影响；`qt_add_resources` 把资源编进二进制，不经过插件，仍按 png 正常加载。SVG 插件与 `QSvgRenderer` 同在 qtsvg 模块，skip qtsvg 会一起消失。

收益（run #9 产物 `plugins/imageformats` 实测，android arm64-v8a）：共 8 个插件 **1.20 MB/ABI**，`qtiff` 已不产出（关闭生效）；保留项为 `qjpeg` 496.9、`qwebp` 460.8、`qicns` 64.5、`qico` 50.6、`qgif` 45.8、`qsvg` 39.4、`qtga` 36.4、`qwbmp` 32.9 KB。对比 Qt 5.15.2 关闭前的 1.46 MB，约省 0.26 MB/ABI。构建期还少编 bundled libtiff（约 40 个 C 文件）。`qtga`/`qwbmp`/`qicns` 无法用 configure 关闭，合计 133.8 KB。

### host 模块集（输入 `host_modules`）

反推依据：`lib/cmake/Qt6<Module>/Qt6<Module>Dependencies.cmake` 的 `__qt_<Module>_tool_deps` 声明交叉编译时要从 host 前缀取哪些工具包；工具包 `Qt6<Module>Tools` 由 `lib/cmake/Qt6<Module>Tools/Qt6<Module>ToolsConfig.cmake` 导出 `Qt6::<tool>` 导入目标，指向 `${_IMPORT_PREFIX}/bin/<tool>.exe`。

实测遍历 Qt 6.12.0 前缀的 `lib/cmake/**/Qt6*Dependencies.cmake`，声明 tool deps 的模块如下：

| target 模块 | 需要的 host 工具包 | 主要工具 |
|---|---|---|
| qtbase（Core / Gui / Widgets / DBus） | `Qt6CoreTools` / `Qt6GuiTools` / `Qt6WidgetsTools` / `Qt6DBusTools` | `moc` `rcc` `uic` `qmake` `qtpaths` `androiddeployqt` `syncqt` `tracepointgen` `windeployqt` `qdbuscpp2xml` |
| qtdeclarative（Qml / Quick） | `Qt6QmlTools` / `Qt6QuickTools` | `qmlcachegen` `qmltyperegistrar` `qmlimportscanner` `qmltc` |
| qtshadertools | `Qt6ShaderToolsTools` | `qsb` |
| qttools（Tools / Linguist） | `Qt6ToolsTools` / `Qt6LinguistTools` | `qdoc` `qhelpgenerator` `lrelease` `lupdate` |
| qtscxml | `Qt6ScxmlTools` | `qscxmlc` |
| qtremoteobjects | `Qt6RemoteObjectsTools` | `repc` |
| qtgrpc（含 qtprotobuf） | `Qt6GrpcTools` / `Qt6ProtobufTools` | `qtprotoc` `qtgrpcgen` `qtprotobufgen` |
| qtcanvaspainter（6.12 新增） | `Qt6CanvasPainterTools` | `qcshadergen` |

结论：为了让 target 的**所有**模块都能编，`qtbase` + `qtdeclarative` + `qttools` + `qtshadertools` **四块不够**，还缺 **qtscxml**（`qscxmlc`）、**qtremoteobjects**（`repc`）、**qtgrpc**（`qtprotoc`/`qtgrpcgen`，连带 `Qt6ProtobufTools`）与 **qtcanvaspainter**（`qcshadergen`，6.12 新增、默认不 skip）。默认 `skip_modules` 已跳过前三项，因此默认 `auto` 集合不含它们；`qtcanvaspainter` 默认参与构建，host 侧必须常驻白名单。

`qtgrpc` 另有宿主 `protoc` 依赖：`Qt6GrpcToolsDependencies.cmake:7` 写的是 `set(__qt_GrpcTools_tool_third_party_deps "WrapProtoc\\;FALSE\\;\\;\\;")`，Qt 包内不含 protoc，需 CI 或宿主安装 protobuf。默认已 `-skip qtgrpc`，默认流程不再触发该依赖（见「已知限制」）。

`auto` 候选白名单 14 个模块；按默认 `skip_modules` 过滤后实际生效 **10 个**：

| 模块 | 依据 |
|---|---|
| qtbase、qtdeclarative、qttools、qtshadertools、qtscxml、qtremoteobjects、qtgrpc、qtcanvaspainter | 上表的 tool deps 声明 |
| qtsvg | 无独立 host 工具，体积小；作为 host 前缀完整性保险保留 |
| qtquick3d、qtopcua、qtlottie | 源码树有 `qt_internal_add_tool`（`balsam`/`shadergen`/`instancer`/`shapegen`、`datatypecodegenerator`/`internalgenerator`、`lottietoqml`）；target 构建是否消费未核实 |
| qtquick3dphysics、qtquicktimeline | 无 host 工具（`cooker` 是 app；qtquicktimeline 6.12 无 `tools` 目录），按“不确定就留在 host 侧”保留 |

按默认 `skip_modules` 被过滤掉的 4 个：`qtscxml`、`qtremoteobjects`、`qtgrpc`、`qtopcua`。因此默认 host 生效集合为：`qtbase`、`qtsvg`、`qtdeclarative`、`qtshadertools`、`qttools`、`qtquick3d`、`qtquick3dphysics`、`qtquicktimeline`、`qtlottie`、`qtcanvaspainter`。

`host_modules` 取值：

| 取值 | 行为 |
|---|---|
| `auto`（默认） | 白名单 ∩（全量 − `skip_modules`），只编 host 必需的工具模块 |
| `all` | 全量（只减去 `skip_modules`），host 侧不再裁剪 |
| 模块列表 | 精确指定；未知模块名直接报错，且必须包含 `qtbase` |

`host_modules` 的缓存影响：host 前缀缓存 key 与 `.cache-ok` 标记都带 `host_set`（`host_modules` 归一化后的串），换模块集必然换 key，不会命中旧的全量前缀。

缺 host 工具时的表现（两段实测报错）：

- **缺整个 `Qt6<Module>Tools` 包**：`configure` 一般不失败。`Qt6<Module>Dependencies.cmake` 末尾无条件 `set(Qt6<Module>_FOUND TRUE)`，会覆盖 `_qt_internal_find_tool_dependencies` 置的 `FALSE`；`Qt6::<tool>` 导入目标不存在，失败延后到真正调用该工具（生成阶段报 target 不存在）。
- **包在但 exe 被删**：`configure` 直接 `FATAL_ERROR`，原文 *"The imported target \"Qt6::<tool>\" references the file ... but this file does not exist."*（由 CMake 导出文件生成）。

### 默认参数（逐项来源）

| 参数 | 阶段 | 来源 |
|---|---|---|
| `-release`、`-opensource`、`-confirm-license`、`-prefix` | target | [参考项目 build-Qt6mingw64.cmd:33](https://github.com/yuanpeirong/buildQt/blob/main/build-Qt6mingw64.cmd#L33) |
| `-nomake examples`、`-nomake tests` | target | 同上 |
| `-skip <skip_modules 中的模块名>` | target + host | 参考项目 build-Qt6mingw64.cmd:33 引入；默认值见「模块选择机制」 |
| `-no-feature-printsupport`、`-no-feature-spatialaudio` | target | 按本次指定关闭；feature 名来自 `qtbase/configure.cmake:1146-1151` 与 `qtmultimedia/src/multimedia/configure.cmake:281-287` |
| `-no-feature-tiff` | target | 保留 png/jpeg/webp/svg/ico/gif，只关 tiff；feature 名来自 `qtimageformats/src/imageformats/configure.cmake:65`（详见「图像格式」） |
| `-qt-host-path` | target | Qt 6 交叉编译必需 |
| `-android-abis`、`-android-sdk`、`-android-ndk` | target | Qt 6 Android 必需 |
| `-android-javac-source 17`、`-android-javac-target 17` | target | Qt 6 Android 必需（配套 JDK 21） |
| `-openssl-runtime`、`-DFEATURE_ssl=ON`、`-DOPENSSL_ROOT_DIR` | target | 本项目选择 runtime SSL：只需要 OpenSSL 3.5.4 头文件（`OPENSSL_ROOT_DIR` 指向生成后的 `include/openssl` 上层）来开启特性探测与编译 openssl 后端；不链接、不分发库（见「下游如何用 TLS」） |

host 侧参数（`-platform win32-g++`、`-qt-zlib`、`-schannel` 等）只用于 host 的桌面 configure，target 侧不使用。

不采用的参考项：target 侧不用 `-static`、`-static-runtime`（Android 产物必须是共享库 `.so`，Qt 不支持静态 target）；host 侧的 `-static`/`-static-runtime` 通过 `host_linkage=static` 显式开启（见「host 链接方式」）。`-qt-webp`、`-qt-tiff`、`-qt-pcre`（Qt 6 已无这些捆绑库开关，**未核实**，传下去会报 unknown option；webp/tiff 改用 `-no-feature-webp`/`-no-feature-tiff`）、`-opengl desktop`（Android 走 GLES）同样不采用。

### host 链接方式（输入 `host_linkage`）

默认 `shared`。Qt 官方文档不建议静态 host 配共享 target：[Cross-compiling Qt（6.12）](https://doc-snapshots.qt.io/qt6-6.12/cross-compiling-qt.html) 原文 “Avoid building the host Qt statically if the target Qt is built shared. A static build of Qt might not contain all tools necessary to build a shared Qt.”；MinGW 静态构建也不在 Qt 官方 CI 矩阵内（Windows 静态包是 MSVC 构建，mingw 行不带 `-static`）。因此 `static` 只作 opt-in，默认路径不改变。

`configure` 接受这个组合（Qt 6.12 `qtbase/configure.cmake`，本地已核对）：

- `qt_feature_alias("static" ... ALIAS_OF_FEATURE "shared" NEGATE)`（:557-560）→ `-static` 等价于 `BUILD_SHARED_LIBS=OFF`；
- `qt_feature("static_runtime" ... CONDITION NOT QT_FEATURE_shared ... WIN32)`（:1217-1221）→ 静态 + Windows 合法；
- `qt_feature("relocatable" ... AUTODETECT QT_FEATURE_shared OR APPLE ... CONDITION QT_FEATURE_dlopen OR WIN32 OR NOT QT_FEATURE_shared)`（:1234-1239）→ Windows 静态下不会自动开启，需显式 `-DFEATURE_relocatable=ON`；源码没有“静态不可 relocatable”的拒绝分支。

| 组合 | 行为 |
|---|---|
| `shared`（默认） | `bin` 内有 `Qt6*.dll` 与 MinGW 运行库，工具可直接运行 |
| `static` | 工具静态链接，`bin` 内无 `Qt6*.dll`；`lib/*.a` 在裁剪步骤仍会删除（只留 `libQt6EntryPoint.a`），交叉编译只消费 `bin` 下的 exe |

未验证项（本机没有 Qt 源码与 MinGW 15.1.0，只验证了本机 MinGW 8.1.0 的 `gcc -static` 能正常链接）：

- 静态 host 能否编出、默认 10 个模块的工具是否齐全、`androiddeployqt` 静态版能否读写 `Qt6Android.jar` 与 Gradle wrapper、交叉编译侧 `Qt6*Tools`/`Qt6HostInfo` 是否仍能解析 —— **均需 CI 首轮确认**。
- 时间：相对 run #6 的 host 2 小时 41 分 48 秒，静态链接通常略增（推断 +10%–20%，未实测）。
- 体积（run #9 实测，host 静态自建、旧裁剪口径）：host 前缀 2015.1 MB / 6890 文件，target 前缀 420.5 MB / 16804 文件，7z 包（`-mx=5`）384.7 MB；其中 host `bin` 1956.3 MB（61 个 exe）占 host 的 97%，`lib` 13.0 MB、`plugins` 25.6 MB、`qml` 9.2 MB、`metatypes` 9.0 MB、`mkspecs` 0.7 MB。新白名单裁剪（见「host 前缀内容与用途」）会整块删掉 plugins/qml/share/modules/include/doc/sbom 与 `lib/objects-Release`，并排除一批美术/部署器类 exe，体积会再降；具体数值以首轮 CI 的 `[裁剪记录]` 为准（未实测）。
- 静态 host 前缀不可重定位：`qmake -query` 能返回编译期的 `D:/qt/host`，但没有 `bin/qt.conf` 时 `qmake` 生成 Makefile 会报 `Could not find qmake spec 'win32-g++'`；补一行 `[Paths] Prefix=..` 的 `bin/qt.conf` 即可（实测）。
- 自包含（把 host 复制进 target 前缀）**未落地**：仍保留 target/host 双前缀，但已通过 `Relocate prefixes` 步骤把两者之间的引用改成相对表达式，因此**不再需要**显式 `QT_HOST_PATH`（保持同级目录即可）；把 host 嵌进 target 前缀仍是另一种做法，需同步改 `target_qt.conf` 与 `QtBuildInternalsExtra.cmake` 的路径推导，未做。

### 磁盘与时间估算（D: 约 14 GB）

| 源码方案 | 解压后占用 | 文件数 | 解压耗时 |
|---|---|---|---|
| 全量解压（默认） | 约 1.3–1.5 GB | 约 12–15 万（推断） | 3–8 分钟（推断，zip + 7-Zip 多线程） |

- 构建目录（推断，未实测）：target 8–12 GB；峰值需同时容纳源码 + target 构建目录 + target 前缀 + host 前缀（1.4 GB），全模块很可能触到 D: 14 GB 上限。
- 时间：host 一律自建，全模块在 run #6 实测 **2 小时 41 分 48 秒**——这是每轮都要付的成本，仅当 host 前缀缓存命中（`.cache-ok` 标识一致）时才跳过；`host_modules=auto` 默认只编 10 个模块（跳过 qtgrpc/qtscxml/qtremoteobjects/qtopcua），推断省 45–75 分钟（待 CI 的 `T_HOST_*` 计时校准）。剩下的大头是 target（run #6 实测 1 小时 39 分 26 秒）；默认 skip 了 10 个模块与 3 个 feature，target 侧推断再省 5–15 分钟、磁盘占用小幅下降（均未实测）。关闭 `qtiff` 后不再编 bundled libtiff（约 40 个 C 文件），推断再省 1–3 分钟；target 前缀少约 0.46 MB/ABI（按 Qt 5.15.2 官方 Android 包实测，6.12 待 CI 校准）。4 vCPU 下全模块仍有超 6 小时风险；可选办法：换 larger runner，或继续加长 `skip_modules`（只改运行参数）。
- 解压开销构成：每文件一次的实时写入 + 扫描是主因，压缩流解码只占几十秒。工作流因此在装工具前加了 Defender 路径排除（`D:\qt`、`C:\tools`、`C:\android`、workspace），失败不致命。
- 源码用官方 **zip**（604,643,023 字节，md5 `64889aee0623311cce096be5f445c7d1`，取自官方 `md5sums.txt` 的 zip 行）：比同内容的 tar 大 36%，但 271 MB/s 下下载只差约 1 秒，换来 7-Zip 多线程解压且不必先解成中转文件。
- host 前缀体积：自建（未裁剪）约 1.4 GB，旧裁剪口径下 285.1 MB、按 7z `-mx=5` 单独实测 **60 MB**；明细见「host 前缀内容与用途」。新白名单裁剪更激进，体积以首轮 CI 的 `[裁剪记录]` 实测为准。`host_linkage=static` 的体积与耗时为推断值（见「host 链接方式」）。target 前缀结构未做裁剪（本机不可测，标注为未核实）。
- 打包：`-mx=9 -ms=on`（LZMA2 256MB 字典、solid），压缩率对齐 Fs 产物的 ~9.7x（旧 `-mx=5` 为 5.5x）；代价是打包步骤从约 4 分钟升到 10–15 分钟。按 275 MB 的整包实测基准推算，新参数下整包约 **100–130 MB**（推断，不是实测）。
- ccache/sccache 未启用：Windows 下收益与稳定性未验证。

## 缓存 key

| 缓存 | key |
|---|---|
| 源码归档（约 605 MB） | `qt-src-zip-<qt_version>-v1` |
| Android SDK/NDK（约 3 GB） | `android-<ndk>-<platform>-<build-tools>-<cmdline>-v1` |
| Gradle home（推断 1–2 GB） | `gradle-qt<qt_version>-bt<build-tools>-v1` |
| host 前缀（未裁剪约 1.4 GB） | `qt-host-build-<qt_version>-<skip_key>-<linkage>-hostset<host_set>-mingw<ver>-cmake<ver>-v1`；`auto` 时 `<host_set>` 为白名单内容的 8 位散列 |

`host_set` 是 `host_modules` 的归一化串（非字母数字 → `-`、小写）；`auto` 时取白名单内容的 SHA-256 前 8 位（`auto-xxxxxxxx`），白名单一变缓存即失效。`.cache-ok` 标记内容为 `build:<linkage>:<host_set>`，恢复缓存后还会再校验一次，避免把旧的全量前缀当最小集用。`<linkage>` 为 `shared`/`static`，两种链接方式的前缀不可互换。

host 前缀是最贵的一项缓存：命中即跳过约 2 小时 41 分 48 秒的 host 编译，未命中（key 变化或 `.cache-ok` 标识不符）就整段重编。它与源码归档、Android SDK/NDK、Gradle home 共用仓库 **10 GB 配额**，其中 SDK/NDK 约 3 GB、源码归档约 605 MB、未裁剪 host 前缀约 1.4 GB。target 构建目录不入缓存（每次构建前删除），target 前缀本身也不入缓存。

## 版本一致性

host 与 target 用同一份源码、在同一次 run 里构建（host 是 MinGW 桌面构建，target 是 NDK 交叉构建），版本天然一致，工作流不再对 host 做 `qmake -query` 断言。源码拉取失败的情形只有一类：版本尚未发布，或属商业 LTS 专属补丁版，会在 `Fetch Qt sources` 阶段报错（`official_releases` 与 `archive` 两处都试过）。

但 Qt **自己不比较** host/target 的版本字符串：`qt_create_hostinfo_package` 生成的 `Qt6HostInfoConfigVersion.cmake` 是 `COMPATIBILITY AnyNewerVersion` + `ARCH_INDEPENDENT`（`qtbase/cmake/QtPostProcessHelpers.cmake:569-575`），而 `_qt_internal_find_host_info_package` 的 `find_package(Qt6HostInfo CONFIG REQUIRED ...)`（`QtPublicDependencyHelpers.cmake:241-251`）**不传版本号**；`qt.toolchain.cmake.in` 里 `QT_HOST_PATH` 命中数为 0。真正的“同版本”要求来自工具语义与文档：

- 官方文档明确要求同版本：[Cross-compiling Qt](https://doc.qt.io/qt-6/cross-compiling-qt.html) 原文 “Ensure you use the same version of Qt for the host and target Qt to avoid incompatibility issues.”
- 实测 6.12.0 的 `moc` 生成文件内含硬护栏：`#elif Q_MOC_OUTPUT_REVISION != 69` / `#error "This file was generated using the moc from 6.12.0. It cannot be used with the include files from this version of Qt."`；`Q_MOC_OUTPUT_REVISION` 定义在 target 的 `qtmetamacros.h`（实测 6.11.3 与 6.12.0 都是 69，但这只是当前取值，后续版本可以上调）。`qmltyperegistrar` 消费 moc 的 JSON，`qmlcachegen`/`qsb` 产出的中间文件由 target 侧 Qt 库消费 —— 这些格式都没有跨版本的兼容承诺。
- 因此**不要手工把 `QT_HOST_PATH` 指向别版本的 host 前缀**：混搭在 configure 阶段不会报错，典型现象是编用户工程时 moc 抛 `#error`，或部署后运行期 QML/着色器异常。出现上述 `#error` 就说明中招，改回与 target 同版本的 host 前缀即可。本工作流每次都从同一份源码编 host，不会产生混搭；同版本重跑时 host 前缀缓存可避免重编。

## 使用方法

1. 打开仓库 **Actions → build-qt-android → Run workflow**，保持默认参数后运行（`skip_modules` 默认已跳过 qtwebengine + 10 个模块 + 3 个 feature，见「模块选择机制」）；若担心 6 小时上限，可继续加长跳过列表。
2. 成功后在该 run 页面下载 artifact；如推送了 `qt-*` tag，还会生成 Release 附件。7z 顶层含 `BUILD-INFO.txt`，记录本次的 configure 原文、工具链版本、阶段耗时与自检输出。
3. 使用产物：

```powershell
# 7z 解压到一个目录，会得到两个同级目录：android_<abi>\ 与 host\
# 保持两者同级且不改名：target 前缀里的相对路径会自己找到 host\
cmake -S <your-app> -B build `
  -DCMAKE_TOOLCHAIN_FILE="D:\qt\android_<abi>\lib\cmake\Qt6\qt.toolchain.cmake" `
  -DANDROID_NDK_ROOT="C:\android\ndk\android-ndk-r27c" `
  -DANDROID_SDK_ROOT="C:\android\sdk" `
  -DCMAKE_PREFIX_PATH="D:\qt\android_<abi>"
# 可选：host 放到别处时再显式指定 -DQT_HOST_PATH="<...>\host"
```

> `qt.toolchain.cmake` 在包内写死了 `/opt/android/...` 的默认路径，必须显式传入 `ANDROID_NDK_ROOT`/`ANDROID_SDK_ROOT`，否则配置阶段会报错。

> **`QT_HOST_PATH` 现在可省略**：`Relocate prefixes` 步骤已把 target 前缀里的绝对路径改成相对表达式（`${Qt6_DIR}/../../../../host`），`target/bin/qmake*.bat` 也改成 `%~dp0..\..\host\bin\…`，所以只要 `CMAKE_PREFIX_PATH` 指向解压出来的 target 前缀，`find_package(Qt6)` 就能按同级目录自己找到 `host\`。显式传 `-DQT_HOST_PATH` 仍然有效（优先级更高），用于把 host 放到别的目录。构建期冒烟会跑一次**不传** `QT_HOST_PATH` 的配置来证明这一点。

> host 前缀只提供工具，交叉编译的库与头文件都来自 `target` 前缀，两者不存在能力差异。host 默认只含 10 个工具模块（白名单 14 个，减去默认 skip 的 4 个，见「host 模块集」），`bin` 又按 Android 构建链路的白名单裁剪（见「host 前缀内容与用途」）：`designer`/`assistant`/`linguist` 等桌面工具不在其中，这些不参与 Android 构建。若工程用到白名单之外的模块工具，configure 会报找不到工具——此时在 `host_modules` 里把该模块加进去重跑；若怀疑是裁得太狠（被排除的工具仍被 `Qt6*ToolsTargets` 引用），用 `host_tools=full` 复跑对比。

> `host_linkage=static` 只改变 host 前缀结构（`bin` 内无 `Qt6*.dll`），产物仍是 target + host 双前缀，用户侧命令不变（相对路径自动找到同级 host；也可继续用 `-DQT_HOST_PATH` 覆盖）。

### 下游如何用 TLS（runtime 模式）

本产物把 SSL **能力编入**（target configure 用 `-openssl-runtime`），但**不链接、也不随包分发** OpenSSL：`libQt6Network` 与 `plugins/tls/*qopensslbackend*` 在运行期才加载库。

- 下游 App 要自己把 OpenSSL 3.x 的 `libssl_3.so` / `libcrypto_3.so` 打进 APK（与本工作流解出的 3.5.4 头文件同一个主版本）：
  - CMake：`set_target_properties(<target> PROPERTIES QT_ANDROID_EXTRA_LIBS "<dir>/libssl_3.so" "<dir>/libcrypto_3.so")`
  - qmake：`ANDROID_EXTRA_LIBS += <dir>/libssl_3.so <dir>/libcrypto_3.so`
- `QT_ANDROID_EXTRA_LIBS` / `ANDROID_EXTRA_LIBS` **只负责把文件塞进 APK，不改名**。Qt 6.12 在 Android 上按 `libssl.so`+后缀、`libcrypto.so`+后缀加载，后缀默认是 `"_" QT_OPENSSL_VERSION`（OpenSSL 3 → `libssl_3.so`、`libcrypto_3.so`，见 `qsslsocket_openssl_symbols.cpp` 的 `Q_OS_ANDROID` 分支）；不匹配时会退化为在库搜索路径里按后缀配对 `libssl.*`/`libcrypto.*`。
- 若你的库名不是 `*_3.so`：App 启动前 `qputenv("ANDROID_OPENSSL_SUFFIX", "<后缀>")`。
- 不提供库时 `QSslSocket::supportsSsl()` 返回 `false`，HTTPS 等 TLS 功能不可用（不崩溃，只是没有可用后端）。
- 库必须是 3.x（1.1.1 的后缀命名是 `*_1_1`，与默认值不符）、ABI 与 APK 一致；用 NDK r27+ 构建的库默认满足 Android 15 的 16 KB page size 要求。

**头文件为什么必须"生成"**：OpenSSL 源码包的 `include/openssl` 里只有 116 个实体 `.h` + 28 个 `.h.in` 模板，`ssl.h`、`opensslv.h`、`x509v3.h` 都没有实体文件，必须由 `Configure` + `util/dofile.pl` 做模板替换生成（Qt 的 `FindOpenSSL` 只认 `openssl/ssl.h`，只有模板时 `WrapOpenSSLHeaders` 直接找不到）。所以该步骤需要 Perl（Strawberry 自带 `Text::Template`，OpenSSL 包内也带了一份 vendored 副本），但**不需要编译器、不构建 OpenSSL 库**。耗时是秒级（本机实测：解压 3.3 s、`Configure` 约 84 s（msys perl；CI 的 Strawberry 通常更快）、生成 0.5 s），缓存命中时近似 0。

## host 前缀内容与用途

`target` 前缀结构完全不动（交叉编译与 `androiddeployqt` 都依赖它）；host 前缀在 `Prune host prefix` 步骤按白名单裁剪（`host_tools=android` 默认，`full` 跳过 `bin` 白名单裁剪）。`host_linkage=static` 时 `bin` 内没有 `Qt6*.dll`/MinGW 运行库（工具已静态链接），`lib/*.a` 是实际静态库而非导入库，裁剪时同样删除，只留 `libQt6EntryPoint.a`。

按用途分三层：

| 层 | 内容 | 谁在用 |
|---|---|---|
| 部署 | `bin\androiddeployqt.exe`、`bin\qtpaths.exe`、`bin\Qt6*.dll`、MinGW 运行库（`libstdc++-6.dll`/`libgcc_s_seh-1.dll`/`libwinpthread-1.dll`） | `androiddeployqt` 打包 APK；DLL 是 exe 的加载依赖 |
| 交叉编译 | `bin\` 白名单 exe（`*ToolsTargets-release.cmake` 实际引用的 55 项 ∪ 21 项必需工具）、`lib\cmake\`（`Qt6HostInfo`、`Qt6*Tools`）、`lib\libQt6EntryPoint.a`、`lib\*.prl`、`mkspecs\`、`metatypes\` | `find_package(Qt6)` 解析 host 工具与 `Qt6HostInfo`；`qmake`/`qtpaths` 查询安装布局 |
| 已删除 | `plugins\`、`qml\`、`share\`、`phrasebooks\`、`modules\`、`include\`、`doc\`、`sbom\`、`lib\objects-Release\`、`lib\*.a`（`libQt6EntryPoint.a` 除外）、白名单外的 exe | 桌面开发、文档、美术工具，交叉编译不需要 |

裁剪规则：

- **顶层目录只留 `bin`、`lib`、`mkspecs`、`metatypes`**，其余整块删除。`metatypes` 是 host 前缀顶层目录（实测 9.0 MiB JSON，不是 `lib/metatypes`），host 自身的 `Qt6CoreTargets.cmake` 用 `${_IMPORT_PREFIX}/./metatypes` 引用它，保留作兜底。
- **`mkspecs` 本次不动**：target 前缀的 `target_qt.conf` 里 `HostSpec=win32-g++`，删了会让 target 的 `qmake` 报找不到 spec。
- **`lib` 只留 `cmake` 子目录 + `libQt6EntryPoint.a` + `*.prl`**；`lib/objects-Release` 删除。删 EntryPoint 会让 `Qt6EntryPointPrivate` 导入目标缺文件，Windows 侧 configure 直接失败。
- **`bin` 只留白名单 exe**：`lib/cmake` 里 `*ToolsTargets-release.cmake` 实际引用的 55 项（去掉已批准排除的）∪ 21 项必需工具（`moc`/`rcc`/`uic`/`qmake`/`qmake6`/`qtpaths`/`qtpaths6`/`androiddeployqt`/`androiddeployqt6`/`androidtestrunner`/`cmake_automoc_parser`/`qsb`/`qmlcachegen`/`qmlimportscanner`/`qmltyperegistrar`/`qmltc`/`lrelease`/`lrelease-pro`/`lupdate`/`lupdate-pro`/`lconvert`）；`bin` 下 10 个非 exe 小文件（`qt-cmake*.bat`、`qt-android-runner.py` 等）保留。
- **明确排除**：`windeployqt`/`wasmdeployqt`/`harmonydeployqt`、`qdbus` 系列、`qhelpgenerator`、`qtattributionsscanner`/`svgtoqml`、`qmltestrunner`/`qmlpreview`/`qmlprofiler`/`ltext2id`/`lcheck`/`qmlaotstats`/`qlalr`/`qmlcontextpropertydump`/`qcshadergen`/`qvkgen`/`cooker`，以及全部 3D 美术工具（`balsam`/`balsamui`/`lightmapviewer`/`meshdebug`/`materialeditor`/`shadergen`/`particleshadergen`/`instancer`/`shapegen`/`lottietoqml`）。
- **`.cache-ok` 保留在前缀里**：`actions/cache` 在 job 末尾才保存，删掉它下一轮就无法校验缓存命中（会白跑一遍 host 编译）；打包用 `7z -x!.cache-ok` 排除，产物中不含该文件。

**风险**：被排除的工具多数仍是 `Qt6*ToolsTargets` 的导入目标，对应组件的 `find_package` 可能报 *"The imported target ... references the file ... but this file does not exist"*。`host_tools=full` 是一键排除开关（跳过 `bin` 白名单裁剪），用于判断“是不是裁太狠”。被删清单（逐项文件数与 MB）写入 `D:\qt\prune-report.txt`，数量与总大小汇总进 `BUILD-INFO.txt` 的 `[裁剪记录]` 段。

裁剪历史实测（旧口径，保留整个 `bin`、`plugins`、`qml`、`metatypes`、`objects-Release`）：1,472 MB → 309.7 MB → 285.1 MB，该口径下 7z `-mx=5` 压缩后 60 MB。新白名单更激进，体积以首轮 CI 的 `[裁剪记录]` 为准（未实测）。

> 产物不是 Windows 桌面开发 SDK：`lib\*.a` 已删、桌面与美术工具已被裁掉，链接桌面程序会失败；host 前缀只用于交叉编译与 `androiddeployqt`。host 默认只含 10 个工具模块（白名单 14 个，见「host 模块集」）。

## 验证方式

CI 内的自动校验（`scripts/verify-android-prefix.py`）：

- `lib/*.so` 按所选 ABI 校验：`arm64-v8a` 为 ELF64 / `e_machine=183`，`armeabi-v7a` 为 ELF32 / `e_machine=40`；
- 存在 `libQt6Core*.so` 与 `lib/cmake/Qt6/Qt6Config.cmake`；
- target 前缀的 PE 文件（`.exe`/`.dll`）计数：双前缀方案下应为 0（脚本只记录到 `manifest.json`，不据此报错）；
- host 前缀存在 `qmake*.exe`、`moc.exe`、`androiddeployqt.exe` 与 `lib/cmake/Qt6HostInfo/Qt6HostInfoConfig.cmake`；
- target 前缀存在 `jar/Qt6Android.jar` 与 `src/3rdparty/gradle/gradlew.bat`（`androiddeployqt` 的运行期依赖）；
- 记录 NDK/SDK 实际版本、库清单与 SHA-256 到 `manifest.json`。

`Prune host prefix` 之后另有一道 `Smoke host tools (minimal Android project configure)` 步骤：

- 用裁剪后的 host 前缀对最小 Qt Widgets+Quick 工程跑 `cmake` 配置（`-DCMAKE_TOOLCHAIN_FILE=<NDK>/build/cmake/android.toolchain.cmake`、`-DANDROID_ABI=<abi>`、`-DCMAKE_PREFIX_PATH=<target>`、`-DQT_HOST_PATH=<host>`），验证 `find_package(Qt6: Core/Gui/Widgets/Qml/Quick/QuickControls2)` 与 QML 模块解析；
- 再跑一次 `androiddeployqt --help`；缺工具时直接 `throw` 并点名，日志里出现 `does not exist`/`Could not find` 会作为告警打印。

拿到 7z 后逐条确认 host 前缀可用（解压目录设为 `D:\qt`）：

```powershell
& "D:\qt\host\bin\qmake.exe" -query QT_VERSION          # 6.12.0
& "D:\qt\host\bin\moc.exe" --version                    # moc 6.12.0
& "D:\qt\host\bin\rcc.exe" --help
& "D:\qt\host\bin\uic.exe" --help
& "D:\qt\host\bin\qsb.exe" --version                    # qsb 6.12.0
& "D:\qt\host\bin\qmltyperegistrar.exe" --help
& "D:\qt\host\bin\qmlcachegen.exe" --help
& "D:\qt\host\bin\qmlimportscanner.exe"                 # 无参会打印用法
& "D:\qt\host\bin\androiddeployqt.exe" --help           # 无参会打印用法并返回 1，能打印即依赖齐全
& "D:\qt\host\bin\qtpaths.exe" -query QT_VERSION
```

> 以上 10 项也是 `Prune host prefix` 步骤的自检项；只看退出码是否等于 `-1073741515`（`STATUS_DLL_NOT_FOUND`）或 `-1073741511`（`STATUS_ENTRYPOINT_NOT_FOUND`）。出现这两个码说明 MinGW 运行库或 `Qt6*.dll` 不在 `host\bin`。

本地（2026-11-04）未跑真正的 Android configure（缺 NDK/SDK）。等价验证：把 target 前缀里的 `Qt6*Tools` 目录移走，仅留 `QT_HOST_PATH=<裁剪后 host>`，并加 `-DQT_REQUIRE_HOST_PATH_CHECK=ON` 强制走交叉编译的 host 解析路径，`find_package(Qt6 COMPONENTS Core Gui Widgets Qml Quick ShaderTools LinguistTools Scxml RemoteObjects)` 与 `qt_add_executable` 均 `Configuring done`。

若要真正跑一次部署，还需要本机 Android SDK + NDK 与 JDK：`androiddeployqt` 会用 target 前缀里的 `jar/Qt6Android.jar` 和 `src/3rdparty/gradle` 的 wrapper 起 Gradle。

本地只做静态校验（YAML 语法、PowerShell/Python 语法）；Qt 编译由 CI 执行。

## 显式关闭的特性（不依赖 runner 预装软件）

GitHub `windows-2022` 镜像预装了大量 SDK。Qt 的 `configure` 对这些 SQL 驱动是 **auto 探测**：找到宿主头文件就编插件，因此显式关闭：

- 现象：`qtbase/src/plugins/sqldrivers/psql` 编 `QPSQLDriverPlugin_resource.rc` 时，MinGW `windres` 把 `-I "C:/Program Files/PostgreSQL/14/include"` 按空格拆开 → `cc1.exe: fatal error: Files/PostgreSQL/14/include: No such file or directory`。
- 原因：本可关闭的插件被宿主环境自动打开，且 runner 预装版本会漂移（版本页写 9.6.16-1，实际命中 `PostgreSQL/14`）。
- 处置：target 的 `configure` 显式 `-no-feature-sql-*`，只保留 Qt 自带 bundled 的 `sql-sqlite`；host 的桌面 configure 同样关闭。

特征名取自源码 `qtbase/src/plugins/sqldrivers/configure.cmake`（`sql-db2`、`sql-ibase`、`sql-mysql`、`sql-oci`、`sql-odbc`、`sql-psql`、`sql-sqlite`、`sql-mimer`），写法沿用官方 CI 行的 `-no-feature-<name>` 形式（官方行里即 `-no-feature-pkg-config`）。

| 开关 | 阶段 | 理由 |
|---|---|---|
| `-no-feature-sql-psql` | target | 命中 runner 预装 PostgreSQL；同类 `windres` 空格路径问题在宿主探测中会复发 |
| `-no-feature-sql-mysql` | target | runner 预装 MySQL（版本页 Software 表 `MySQL 8.0.36`），同类风险 |
| `-no-feature-sql-odbc` | target | 依赖 Windows ODBC 头文件/库，属宿主环境 |
| `-no-feature-sql-oci` | target | 源码明确提示 Qt 不支持用 MinGW 编译 Oracle 驱动 |
| `-no-feature-sql-db2` / `-no-feature-sql-ibase` / `-no-feature-sql-mimer` | target | 同属外部商业库探测，一并关掉，避免版本漂移 |
| `-no-feature-cups` | target | 依赖 `Cups_FOUND`（`src/printsupport/configure.cmake`），宿主装了 CUPS 就会开 |
| `-no-feature-pkg-config` | target | 官方 CI 行原样；避免 pkg-config 把宿主库当成交叉编译依赖 |
| `-no-openssl` → `-openssl-runtime` | target | 原 `-no-openssl` 已移除：runtime 模式不探测宿主库（`OPENSSL_ROOT_DIR` 只指向我们自己解出的头文件），但会把 `QT_FEATURE_ssl` 编成 1 |

`-qt-zlib` / `-qt-libpng` / `-qt-libjpeg` / `-qt-freetype` / `-qt-harfbuzz` / `-schannel` 只用于 host 的 Windows 桌面 configure，target 侧不使用。

评估后**不**显式关闭的项：

- `fontconfig`：`CONDITION NOT APPLE AND NOT WIN32 AND ...`（`src/gui/configure.cmake`），Windows 上不可能命中。
- `vulkan`：`CONDITION QT_FEATURE_library AND QT_FEATURE_vkgen AND WrapVulkanHeaders_FOUND`，runner 未装 Vulkan SDK 时自动关闭；如需彻底固定可加 `-no-feature-vulkan`（本工作流未加）。
- `zstd`：`qt_feature("zstd" ... CONDITION WrapZSTD_FOUND)`，Qt 用自带 3rdparty 副本，不依赖宿主。
- `icu`：Windows 下需显式 `-icu` 才启用，默认不探测（**未逐行核实**）。
- `sql-sqlite`：Qt 自带 bundled sqlite，保留。

## 与官方 CI 行对齐（`android-armv7-on-windows`）

官方 CI 行的列是 `ID / Dependencies / Target / Host / Coin Options / Configure Arguments / Environment Variables`，工具版本要到 Software 表的 **Windows 11 24H2 x86_64** 列去核对。

| 工具 | 官方 CI（Windows 11 24H2 x86_64 列） | 本工作流 | 处理 |
|---|---|---|---|
| NDK / SDK platform / build-tools / cmdline-tools | r27c / android-37.0 / 37.0.0 / 19.0 | 同 | 一致 |
| CMake / Ninja / JDK / MinGW / 7-Zip / OpenSSL | 4.3.2 / 1.10.2 / 21.0.9 / 15.1.0(posix-seh-msvcrt-rt_v12) / 24.09 / 3.5.4 | CMake/Ninja/JDK/7-Zip 同；MinGW 15.1.0 在 host 步骤内下载（复用官方 CI 版本）；OpenSSL 3.5.4 仅头文件（官方 CI 行为完整 OpenSSL 3.5.4） | 版本一致：host 与官方 CI 用同一编译器版本，OpenSSL 同版本（我们只取头文件） |
| Python | 3.8.1 | 3.11.9 | 保留：3.8.1 已 EOL，且 setup-python 清单里仅旧补丁版本；Qt 构建脚本两者兼容 |
| Perl (strawberry) | 5.32.0.1 | 5.42.2.1 | 保留：GitHub 上没有 5.32.0.1 的 portable 资产（实测未找到） |
| 平台镜像 | `windows-11_24h2-mingw15` | `windows-2022` | 差异：标准 runner 无该自定义镜像；工作流自己下 MinGW 15.1.0 |
| ABI | `armeabi-v7a` | 输入 `abi`，默认 `arm64-v8a` | 可切换 |
| 其他 configure 参数 | `-release -force-debug-info -qpa android;offscreen -nomake examples -no-feature-pkg-config` | `-release -nomake examples -nomake tests -no-feature-pkg-config` | 已纳入 pkg-config；`-force-debug-info`、`-qpa android;offscreen` 未加（未核实其对产物大小的影响） |

armv7 额外注意：

- 交叉 triple 为 `armv7a-linux-androideabi`，由 `-android-abis armeabi-v7a` 自动选择；产物 `.so` 是 ELF32、`e_machine=40`，`verify-android-prefix.py` 已按 ABI 校验 ELF class 与 machine。
- 资源编译（`windres`/`.rc`）只发生在 Windows 桌面构建（host 阶段）；target 侧不涉及 windres，armv7 也不涉及 32 位 windres。
- 每种 ABI 是独立构建：`TARGET_PREFIX` 按 ABI 命名（`D:\qt\android_<abi>`），artifact 名也带 ABI；host 前缀与 ABI 无关，两种 ABI 各带同一份 host 前缀。
- minSdk 下限由 Qt 版本决定（具体数值**未核实**）；armv7 只对 32 位旧设备有意义，Google Play 自 2019 年起要求 64 位。

## 与 Fs-scripts 的对照

参考对象 `Fsu0413/Fs-scripts` @ `d22229c`（最后提交 2024-09-30）。它有 Android 配置，但**没有独立的 Android 构建脚本**：配置全在 `Compile/lib/qtCompile/conf.lua` 的 Lua 表里，由 Jenkins 环境变量驱动；仓库内 `java`/`jar`/`gradle` 出现 0 次（忽略大小写）。

### 它的打包/发布做法

- **产物**：Windows 只出一个 `.7z`，`7z a -t7z -m0=LZMA2:d256m:fb273 -mmt=3 -myx -mqs -ms=on`（`Compile_lib_Generate.lua:128-129`），先写带日期名再复制成稳定名；Unix 另出 `.tar.xz`（同文件 `:465-469`），不分卷。`conf.lua` 没有 `compression`/`archive`/`package` 字段，压缩只在 Generate 脚本里。
- **命名**：`INSTALLPATH` 由配置表 `name` 展开 `&HOSTTOOLVERSION&`/`&TARGETTOOLVERSION&`（`Compile_lib_Configuration.lua:723`），Android 形如 `Qt6.2.9-Android-arm64-v8a-Clang-NDKr23c-xWindows-x86_64-MinGW`（`qtCompile_conf.lua:3254`）；`INSTALLPATHWITHDATE = INSTALLPATH .. "-" .. date`（`Compile_lib_Generate.lua:1036`）。版本、ABI、NDK、host 编译器、静态变体都在文件名里。
- **host 进产物的方式**：不单独打包 host，而是 install 后调用 `qt6_deploy_host.sh`（`Compile_lib_Configuration.lua:560-567`）把它复制进 `<target>/host`：

| 复制项 | 源 → 目标 | 说明 |
|---|---|---|
| `bin` | `$HOST/bin` → `$TARGET/host/bin` | 复制后删 `host/bin/qt.conf`（`qt6_deploy_host.sh:33-34`） |
| `libexec` | `$HOST/libexec` → `$TARGET/host/libexec` | 存在才复制（`:35`） |
| `lib/cmake` | `$HOST/lib/cmake` → `$TARGET/host/lib/cmake` | `:37` |
| `lib/metatypes` | `$HOST/lib/metatypes` → `$TARGET/host/lib/metatypes` | `:38` |
| `lib/*.prl` | `$HOST/lib` 一层 → `$TARGET/host/lib` | `:39` |

  不复制 `include`/`qml`/`plugins`/`mkspecs`/`lib/*.so`：它的 host 用 `-static`、`-static-runtime`、`-DFEATURE_relocatable=ON` 构建（`qtCompile_conf.lua:6289` 段），工具静态链接、无 DLL 依赖。
- **路径重写**（`qt6_deploy_host.sh`）：
  - `target_qt.conf`：`HostPrefix=../host`、`HostData=..`（`:84-85`）；`bin/qmake`、`bin/qtpaths`（及 `qmake6`/`qtpaths6`）被替换为 sh 包装脚本，转调 `../host/bin/qmake -qtconf target_qt.conf`（`:41-65`）。
  - `Qt6Dependencies.cmake`：`__qt_platform_initial_qt_host_path` → `${Qt6_DIR}/../../../host`；`__qt_platform_initial_qt_host_path_cmake_dir` → `${Qt6_DIR}/../../../host/lib/cmake`（`:89-90`，Qt 6.4.1+）。实测 Qt 6.12.0 的 `Qt6Dependencies.cmake` 仍用这两个变量（默认空串），改写点仍在。
  - `qt.toolchain.cmake`：`__qt_toolchain_initial_qt_host_path`、`__qt_toolchain_initial_qt_host_path_cmake_dir` → `${CMAKE_CURRENT_LIST_DIR}/../../../host[\/lib\/cmake]`（`:94-104`，Qt 6.2.4）。
  - 本仓库布局不同（`android_<abi>\` 与 `host\` 是本工作流根目录下的两个同级目录，而不是把 host 放进 target 前缀），所以深度是**上溯四层**：`${Qt6_DIR}/../../../../host`；实测我们的 `qt.toolchain.cmake` 内没有绝对路径，无需改写。对应步骤是 `Relocate prefixes`，还会一并处理 `bin/qmake*.bat`、`QtBuildInternalsExtra.cmake`、`mkspecs/modules/qt_ext_*.pri`，并对整个交付前缀做 0 命中硬校验。
- **裁剪**：没有删 `*.a`/`doc`/`examples`/`tests`/`sbom`/`qdoc`/`translations`；判据是“只复制交叉编译/部署需要的子目录”（上表白名单），而不是事后删文件。静态 host 的 `lib/*.a` 本就不复制。

| 维度 | Fs-scripts | 本仓库 | 判断 |
|---|---|---|---|
| Qt 版本上限 | 6.7.2（另有 6.2.9/6.5.3/5.15.14） | 6.12.0 | 它早于 Qt 的 Gradle 化 jar，Gradle 这块没有可借鉴内容 |
| 工具链来源 | 本机固定路径 `D:\android-sdk-windows-20240205`、`D:\android-ndk-r26d`、OpenJDK 11、CMake 3.29（`Configuration.lua:52-79`、`:392-395`） | runner 上 `sdkmanager`/7z 安装，版本钉死 | 它预置即用；不适配 hosted runner |
| host Qt | 下载其 Jenkins 产出的静态 host Qt（`hostToolsUrlwin`，`qtCompile_conf.lua:7276`），`-DFEATURE_relocatable=ON`（`:6289` 段） | 本工作流从源码自建（默认 `shared`，可 `host_linkage=static` opt-in）+ Actions 缓存 | 它直接用 Jenkins 预编译 host；我们自建，靠缓存避免重编 |
| target 参数 | 直调 CMake：`-DQT_HOST_PATH`、`-DANDROID_ABI`、`-DANDROID_PLATFORM=27`、`-DBUILD_qtwebengine=OFF`、`-DFEATURE_icu=OFF`、`-DFEATURE_ssl=ON` + `-DINPUT_openssl=linked` + 自建静态 OpenSSL 3.0.14、`-DMYSQL_INCDIR` | `configure.bat` + `-android-abis` + `-no-feature-sql-*` + `-openssl-runtime`（只生成 OpenSSL 3.5.4 头文件，不建库、不链接） | SSL 取舍不同：它静态链进 `libQt6Network`，我们让下游自带库（见下） |
| 产物形态 | 单个 `.7z`（Unix 另出 `.tar.xz`），名字含版本/ABI/NDK/host 编译器/变体 | 单个 `.7z`，名字含版本/ABI，解压得两个同级前缀 | 它命名信息更全；我们保持现有命名 |
| host 进产物 | 复制进 `<target>/host`，sed 改写相对路径，用户无需 `QT_HOST_PATH` | target 与 host 两个同级前缀，用户显式传 `QT_HOST_PATH` | 它更自包含；不采纳理由见下 |
| 裁剪 | 白名单复制（bin/libexec/lib/cmake/*.prl/metatypes） | 先全量 `install`，再按白名单裁（顶层只留 `bin`/`lib`/`mkspecs`/`metatypes`，`bin` 只留工具白名单） | 静态 host 与共享 host 前提不同 |
| Gradle / android jar | 无任何处理（0 处 java/jar/gradle） | 预灌 `~/.gradle` + Actions 缓存 | 它的空白正是我们卡住的点，无法照抄 |
| 缓存 | 无 Actions 缓存，靠 Jenkins workspace 持久化 | 5 类 Actions 缓存 | 本仓库更好（CI 场景） |
| 构建期外网依赖 | 内网 Jenkins artifact + 内网源码包 | 仅 GitHub 可达网络 | 环境不同，不构成优劣 |

不采纳的三点及理由：

1. **直调 CMake 取代 `configure.bat`**：Qt 6.12 的 Gradle 校验在 CMake 层，直调一样会触发；还会丢掉 configure 对特性的推导和 `-no-feature-*` 解析。
2. **自建 OpenSSL/MariaDB 再 `-DMYSQL_INCDIR`**：收益只是多一个 sql 驱动，代价是多两个第三方库的交叉编译。
3. **把 host 复制进 target 前缀（`qt6_deploy_host.sh` 做法）**：思路更自包含（解压目录整体搬迁，不需要 `QT_HOST_PATH`），但前提与适配性都不满足：
   - 它依赖 host 全静态（`-static -static-runtime`），所以只复制 `bin`/`libexec`/`lib/cmake`/`*.prl` 就够；本仓库已提供 `host_linkage=static` 作为 opt-in，但默认 `shared`（Qt 官方不建议静态 host 配共享 target，MinGW 静态也不在官方 CI）；默认的共享 host 工具运行期需要 `Qt6*.dll`，自包含要把整份 host 前缀搬进 target。
   - 自包含会让 target 前缀出现 `.exe`/`.dll`，`verify-android-prefix.py:146` 的 `Windows PE files in target prefix` 计数不再为 0（当前只报告不报错，但会误导“target 是纯 Android 前缀”的校验口径）。
   - 改写依赖 Qt 内部变量；6.12 仍在，但 `qtbase/cmake/QtPostProcessHelpers.cmake:430` 注明 host path “尚未 relocatable”，Qt 升级后有再次失配的风险。
   - 收益只是省掉用户传一个 `-DQT_HOST_PATH`，而双前缀方案已通过 configure 模拟；不值得引入未在真机 Android 构建验证的结构改动。

**SSL 取舍（与 Fs 不同）**：Fs 交叉编译静态 OpenSSL 3.0.14 并用 `-DINPUT_openssl=linked` 把 TLS 直接链进 `libQt6Network`；本仓库有意选择 `-openssl-runtime`，头文件取 **3.5.4**（对齐 Qt 6.12 版本页；只解出 `include/openssl`，不建库、不链接、不分发）。**版本与模式都不同，是有意为之**：Fs 钉在 3.0.14 是因为它的静态库要自己交叉编译并随包分发；我们只借头文件做配置期探测，所以跟随 Qt 版本页取 3.5.4。理由：不给 prefix 绑定某个 OpenSSL 版本（升级 OpenSSL 不用重编 Qt）、不引入第二条交叉编译链（Windows runner 上编 OpenSSL 需要 msys2+perl）。代价：下游必须自带 `libssl_3.so`/`libcrypto_3.so`、文件名后缀要对上（或设 `ANDROID_OPENSSL_SUFFIX`）、TLS 缺失只在运行时暴露（`QSslSocket::supportsSsl()` 为 false）。用法见「下游如何用 TLS」。

其压缩参数 `-m0=LZMA2:d256m:fb273 -mmt=3 -myx -mqs -ms=on` 未采纳：本机 `7zr` 不接受 `d256m` 语法，无法对比。本仓库改用 7z 的 `-mx=9 -ms=on`（LZMA2 256MB 字典 + solid），压缩率对齐 Fs 产物的 ~9.7x（旧 `-mx=5` 为 5.5x）；按 275 MB 的整包实测基准推算，整包约 100–130 MB（推断，不是实测），代价是打包耗时从约 4 分钟升到 10–15 分钟。

一处可借鉴但未落地的细节：它对 Android 显式传 `-DCMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH=ON`。该变量默认即为 ON，显式写只是自证，不会改变宿主机探测行为，因此不改。

## 与官方文档对齐（Qt 6.12）

依据页面（均于 2026-11-04 实际抓取核对）：

- [Qt for Android - Building from Source](https://doc-snapshots.qt.io/qt6-6.12/android-building.html)
- [Cross-compiling Qt](https://doc-snapshots.qt.io/qt6-6.12/cross-compiling-qt.html)

| 维度 | 官方表述 | 本工作流 | 判断 |
|---|---|---|---|
| host/target 版本 | “Ensure you use the same version of Qt for the host and target Qt” | host 与 target 同源码、同一次 run 构建，版本天然一致 | 一致 |
| host 静态 | “Avoid building the host Qt statically if the target Qt is built shared.” | 默认 `shared`，`static` 仅 opt-in | 一致（static 是已知偏离） |
| `QT_HOST_PATH` | configure 用 `-qt-host-path <host>`；直接用 CMake 用 `-DQT_HOST_PATH` | target configure 传 `-qt-host-path`；用户工程传 `-DQT_HOST_PATH` | 一致 |
| host 模块范围 | “build the same Qt modules on the host that you'll need on the target” | 按 tool deps 反推最小集，默认 10 个 | 比官方建议更窄，风险见「已知限制」 |
| Windows 编译器 | “Mingw-w64 13.1 toolchain” | host 阶段用 MinGW 15.1.0 | 偏离：15.1.0 与 Qt 6.12 官方 Windows 构建一致；暂不改，CI 失败再降级 |
| 生成器 | 有 `ninja` 时总是使用 Ninja | 安装 Ninja 1.10.2 并置于 PATH，不显式传 `-G` | 一致（由 configure 自动选择） |
| javac | `-android-javac-source 17 -android-javac-target 17` | 同 | 一致 |
| ABI | 支持 `arm64-v8a` / `x86_64` / `x86` / `armeabi-v7a` | 只提供 `arm64-v8a` / `armeabi-v7a` | 少两种模拟器 ABI，非构建必需；需要时扩展输入 |
| 构建/安装 | `cmake --build . --parallel` / `cmake --install .` | 同 | 一致 |
| `androiddeployqt` / minSdk / targetSdk | 这两页未涉及（`androiddeployqt` 用法在 `android-building-projects-from-commandline`；min/targetSdk 是应用工程变量） | 不直接调用 `androiddeployqt`，由 Qt CMake API 驱动 | 无遗漏，未改工作流 |

“做了但官方不建议”的项：host 静态构建（仅 opt-in）、host 模块范围窄于 target。其余参数与官方一致；两页没有要求 `-android-abis` 之外的 SDK/ABI 参数，也没有 minSdk/targetSdk 的 configure 写法。

## 为什么 target configure 需要 Gradle 离线缓存 / 我们的处理方式

Qt 6.12 里 Android 的 `Qt6Android.jar` 由源码树内的 Gradle 工程构建（`qtbase/src/android/jar`）。Qt 的 CMake 在 **configure 阶段**就检查这些依赖是否已在本地，未缓存会直接 `FATAL_ERROR`（源码 `qtbase/cmake/QtJavaHelpers.cmake:65-66`、`:236-291`），因此失败发生在 target configure，而不是构建期。

- 检查对象：Gradle 用户目录（默认 `~/.gradle`）里是否有该 JAR 工程所需依赖；它调用 `cmake/QtSetupAndroid.cmake` 跑一次 `resolveDependencies` 并带 `--offline`（`:66-68`）。
- 判定路径：先要求 `$ANDROID_SDK_ROOT/build-tools/<rev>` 存在（`QtJavaHelpers.cmake:259-262`），再以 `ANDROID_SDK_ROOT` 为环境变量执行校验；退出码非 0 即失败。
- 缓存来源：wrapper 在 `qtbase/src/3rdparty/gradle/`，`gradle-wrapper.properties` 指定 `gradle-9.5.1-bin.zip`；依赖仓库是 `google()`、`mavenCentral()`、`gradlePluginPortal()`（`src/android/jar/settings.gradle`），AGP 版本 `9.2.1`（`src/android/jar/gradle/libs.versions.toml`）。

本工作流的处理（`Prepare Gradle offline cache` 步骤）：

1. 先用 `-DONLY_VERIFY_GRADLE_CACHE=ON` 校验；命中就直接跳过，冷启动才联网。
2. 未命中则用 Qt 报错原文给出的命令（去掉 `ONLY_VERIFY`）联网填充 `~/.gradle`：wrapper 会自行下载 Gradle 9.5.1（分发包实测 140,320,662 字节），再从 google/Maven 拉 AGP 与依赖。
3. `actions/cache` 缓存 `~/.gradle/caches` 与 `~/.gradle/wrapper`，key 为 `gradle-qt<版本>-bt<build-tools>-v1`，与 host 前缀的 key 无关。
4. 解析失败时打印 `gradle-wrapper.properties`、`gradlew --version` 与 `~/.gradle` 体积，便于区分“网络/DNS 问题”还是“SDK/build-tools 不匹配”。

不采用的替代方案：`QT_ALLOW_DOWNLOAD=ON`（configure 里写成变量赋值 `QT_ALLOW_DOWNLOAD=ON`）可让校验直接放行、把下载推迟到构建期，但每次构建都依赖网络且不可缓存；直接跳过 jar 目标没有官方开关（`src/android/CMakeLists.txt` 里 `if(ANDROID) add_subdirectory(jar)` 是无条件分支），只能改源码，且产物缺少 `Qt6Android.jar`，使用方 `androiddeployqt` 打包会受影响。

## 故障排查

每条按「现象 → 原因 → 处置」组织。

### `Fetch Qt sources` 长时间「解压中: 0 个文件」

| 现象 | 原因 | 处置 |
|---|---|---|
| 文件数/GB 为 0，但 `7z CPU` 秒数持续增长 | 7-Zip 正在解压，尚未大量落盘 | 继续等，几分钟内文件数应上涨 |
| 文件数/GB、`7z CPU`、工作集都完全不动 | 7-Zip 阻塞在读写或进程异常 | 重跑该步骤；仍不动则先删 `D:\qt\src\qt-everywhere-src-<ver>` 再重跑 |
| 出现 `落盘确认: ... (前 3 个: ...)` 但与预期不符 | 落盘位置不对 | 核对 zip 顶层目录名是否与 `$Version` 一致 |
| 出现 `未找到 7z.exe ... 回退 Expand-Archive` | runner 没有 7-Zip，走了 PowerShell 单线程解压 | 只会更慢（推断 20–40 分钟），不必改脚本 |

`$root` 与 zip 顶层目录同名，正常数秒内出现；脚本在它出现前改数 `D:\qt\src` 本身。

### host 工具报 `STATUS_ENTRYPOINT_NOT_FOUND`（0xC0000139）或缺少 `libstdc++-6.dll`

- 现象：`host\bin\*.exe` 无法启动，退出码 `-1073741511`，或提示缺 `libstdc++-6.dll`。
- 原因：host 是 MinGW 15.1.0 的共享构建，exe 依赖 `Qt6*.dll` 与 MinGW 运行库，Windows 只在 exe 同目录和 `PATH` 里找 DLL；本机 `PATH` 里其他 MinGW（如 `D:\Qt\Tools\mingw810_64\bin`）的同名 DLL 版本不匹配也会触发。
- 处置：把缺失的 `libstdc++-6.dll`/`libgcc_s_seh-1.dll`/`libwinpthread-1.dll` 补进 `host\bin`；运行自检时避免 `PATH` 里的其他 MinGW 抢先。

### `find_package(Qt6)` 报 `The imported target ... references the file ... but this file does not exist`

- 现象：configure 阶段 `FATAL_ERROR`，指出 `Qt6::moc`、`Qt6::syncqt`、`Qt6::qdoc` 等导入目标指向的 `bin\*.exe` 不存在。
- 原因：删掉了被 `lib\cmake\**\Qt6*Targets*.cmake` 引用的 exe；CMake include 导出文件时会校验 `IMPORTED_LOCATION`。`Prune host prefix` 的批准排除清单正是这条报错的常见来源；`QT_HOST_PATH` 指错目录同样会报。
- 处置：先用 `host_tools=full` 复跑，确认是不是裁得太狠；确需该工具时把它加进 `bin` 白名单（或恢复该 exe）；确认真实 host 前缀路径后再传 `QT_HOST_PATH`。

### `find_package(Qt6 COMPONENTS <Module>)` 提示找不到 `Qt6<Module>Tools`

- 现象：host 缺某模块工具；configure 不报错，但编用户工程用到该模块的构建步骤失败。
- 原因：工具查找会置 `${CMAKE_FIND_PACKAGE_NAME}_FOUND FALSE`，而生成的 `Qt6<Module>Dependencies.cmake` 末尾无条件 `set(Qt6<Module>_FOUND TRUE)` 覆盖它（实测 `Qt6ScxmlDependencies.cmake:57-58`），因此缺失被延后。
- 处置：在 `host_modules` 里加该模块重跑。`qtgrpc` 还额外要求宿主 `protoc`（`Qt6GrpcToolsDependencies.cmake:7` 的 `WrapProtoc`，Qt 包内不含）。

### target configure 报 `The offline Gradle check failed ...`

日志形如 `QtJavaHelpers.cmake:66 (_qt_internal_verify_gradle_offline_cache)` ← `src/android/jar/CMakeLists.txt:60 (qt_internal_add_jar)`。含义是 `~/.gradle` 里没有 `Qt6Android.jar` 所需依赖，或 `$ANDROID_SDK_ROOT/build-tools/<rev>` 缺失。

| 现象 | 原因 | 处置 |
|---|---|---|
| 缓存步骤打印「未命中」后解析成功，但 target configure 仍失败 | 两处的 `GRADLE_BUILD_VARIANT` / `QT_ANDROID_SDK_BUILD_TOOLS_REVISION` 不一致 | 两处都用 `Release` + `SDK_BUILD_TOOLS` |
| 解析步骤报下载失败 | runner 出网问题（DNS/代理），或 JDK 版本不兼容 | 看日志里已打印的 wrapper 属性与 `gradlew --version` |
| `Android build-tools 'x' is not installed` | SDK 缓存过期或 `SDK_BUILD_TOOLS` 被改 | 删掉 `android-*` 缓存后重跑 |

不要用 `QT_ALLOW_DOWNLOAD=ON` 作为长期方案：它跳过校验并把下载推到构建期，构建时间与成功率都依赖 runner 当时的网络。

## 产物中的 BUILD-INFO.txt

字段（7z 顶层，与 target/host 前缀同级）：

1. **Qt**：`qt_version`、ABI、host 来源（固定写「源码自建（链接方式 shared|static）」）、skip 项、host 生效模块、重定位（绝对路径改写处数 / 校验命中数）、SSL（runtime 模式、`QT_FEATURE_ssl` 实际值、OpenSSL 头文件版本、未分发 TLS 库的说明）；
2. **configure 原文**：host 与 target 各一段。执行 configure 时把实际参数数组同步写入 `host-configure.txt`/`target-configure.txt`，`BUILD-INFO.txt` 只读取这两份文件，不是手写近似命令；
3. **工具链**：NDK（含 `source.properties` 的 `Pkg.Revision`）、SDK platform、build-tools、cmdline-tools、JDK、CMake、Ninja、MinGW、Python、Perl、7-Zip；
4. **运行环境**：runner 名称/OS/架构、镜像版本、CPU 型号与逻辑核数、内存、`GITHUB_WORKSPACE`、`WORK_ROOT`；
5. **时间**：UTC 生成时间 + `T_FETCH`/`T_HOST_*`/`T_GRADLE_PREP`/`T_TARGET_*`/`T_RELOCATE` 各阶段秒数与分钟数；
6. **裁剪记录**：`[裁剪记录]` 段只搬数量与总大小（`host_tools` 模式、精简前后 MB/文件数、删除明细项数），完整明细在 `D:\qt\prune-report.txt`；
7. **产物自检**：`qmake -query QT_VERSION`、`moc --version`、`qsb --version`、`qtpaths -query QT_VERSION`、`androiddeployqt --help` 前 5 行，以及 `plugins/imageformats` 下实际插件清单与各自体积（用于核对 png/jpeg/webp/svg/ico/gif 的保留结果）。

编码为 **UTF-8 with BOM**（Windows PowerShell 的 `Set-Content -Encoding utf8`），避免记事本把中文当 ANSI 显示；文件首行也标注了编码。

## 已知限制与未核实项

- **未在本机编译验证**：Qt 6.12 + MinGW 15.1.0 + CMake 4.3.2 的组合以官方版本页为准，是否存在 6.12 特有的配置项差异，需以首轮 CI 结果确认。
- **SSL 是 runtime 模式，不含 TLS 库**：target 用 `-openssl-runtime`，只生成 OpenSSL 头文件（`Configure`+`dofile.pl`，不编译库）来开启能力与编译后端插件；`libssl`/`libcrypto` 由下游 App 打进 APK（见「下游如何用 TLS」）。`QSslSocket::supportsSsl()` 在缺库时为 false，https 不可用；host 侧仍是 `-no-openssl -schannel`（host 只跑构建工具），属有意不一致。
- 官方版本页（Software 表）列了 Strawberry Perl 5.32.0.1，但 GitHub 上没有该版本便携资产，故用 5.42.2.1。
- `actions/setup-java` 是否可精确拉到 Temurin `21.0.9` 未在本地核实；失败时会回退到同主版本（需改 workflow）。
- 标准 runner 的实际可用磁盘可能因镜像不同而波动；工作流只打印、不强制清理系统目录。
- 全模块构建（把 `skip_modules` 置空）在 4 vCPU / 14 GB 盘上很可能超时或超盘；需 larger runner（如 `windows-latest-8-cores`），或保留较长的 `skip_modules`。
- Gradle 阶段的具体耗时与 `~/.gradle` 实际体积**未实测**：冷启动需下载 Gradle 9.5.1 分发包（140,320,662 字节）+ AGP 9.2.1 及其依赖，推断 3–6 分钟；热缓存下只跑离线校验，推断半分钟以内。`actions/cache` 对 `~/.gradle` 的压缩/解压开销也计入该时间。
- 补丁版场景：若填入的是尚未发布/商业 LTS 专属的版本，会在 `Fetch Qt sources` 阶段失败（`official_releases` 与 `archive` 两处地址都不可用）。
- **host 每轮必编**：全模块实测 2 小时 41 分 48 秒，仅 host 前缀缓存命中才跳过；缓存 key 任一组成（版本/skip/linkage/host_set/MinGW/CMake）变化，或 `.cache-ok` 标识不符，都会整段重编。
- artifact 为未签名的 Qt 前缀，不含 APK，不含 Android 签名材料。
- artifact 中的 host 前缀已按白名单裁剪（顶层只留 `bin`/`lib`/`mkspecs`/`metatypes`，`bin` 只留工具白名单），旧口径实测 1,472 MB → 285.1 MB（7z 后 60 MB）；新口径体积待首轮 CI 的 `[裁剪记录]`。只够交叉编译与 `androiddeployqt` 部署，需要桌面 Qt 开发能力时不要用它。
- **裁剪风险**：被排除的工具（windeployqt/wasmdeployqt/harmonydeployqt、qdbus 系列、qhelpgenerator、3D 美术工具等）多数仍是 `Qt6*ToolsTargets` 的导入目标，对应组件的 `find_package` 可能报 *"The imported target ... references the file ... but this file does not exist"*；`host_tools=full` 是一键排除开关。
- 默认 `skip_modules` 关闭 `qtgrpc`/`qtserialbus`/`qtscxml`/`qtopcua`/`qtremoteobjects`/`qtactiveqt`/`qtwayland`/`qttasktree`/`qtcoap`/`qtwebchannel`、PrintSupport/SpatialAudio，以及 TIFF 图像格式（保留 png/jpeg/webp/svg/ico/gif）；需要其中任一功能时，从默认值里删掉对应 token 重跑（host 侧会随 `auto` 自动把所需模块加回）。
- 图像格式的残留：`bmp`/`ppm`/`xbm`/`xpm` 内建在 QtGui，`tga`/`wbmp`/`icns` 插件没有独立 feature，这 7 个无法用 configure 关闭；只有靠改 qtimageformats 源码（删 `add_subdirectory(tga|wbmp|icns)`）才能去掉，默认不做源码补丁。详见「图像格式」。
- host 白名单有 14 个模块，按默认 `skip_modules` 过滤后实际编 10 个（`qtbase`/`qtsvg`/`qtdeclarative`/`qtshadertools`/`qttools`/`qtquick3d`/`qtquick3dphysics`/`qtquicktimeline`/`qtlottie`/`qtcanvaspainter`）；工程用到白名单外的模块工具时 configure 会失败，需加进 `host_modules`。
- `host_linkage=static` **未经 CI 验证**：本机只验证了 MinGW `gcc -static` 可用，未编译 Qt。首轮需设 `host_linkage=static`、`host_modules=auto`，确认 host configure 无报错、冒烟步骤通过、target configure 能解析 `Qt6*Tools`，并实测前缀体积与 `T_HOST_*` 耗时；失败则保持默认 `shared`。
- `qtgrpc` 的 host 工具依赖宿主 `protoc`（`Qt6GrpcToolsDependencies.cmake:7` 的 `WrapProtoc`，官方 Qt 包内不含）；默认已 `-skip qtgrpc`，不会触发。若从 `skip_modules` 移除 `qtgrpc`，需在工作流安装 protobuf，否则工程 `find_package(Qt6 COMPONENTS Grpc)` 会失败（**未在 CI 实测**）。

## 文件

```
.github/workflows/build-qt-android.yml   # host（源码自建）+ target 构建工作流
scripts/fetch-qt-source.ps1             # 下载（md5 校验，official_releases/archive 双地址）/全量解压
scripts/verify-android-prefix.py        # 产物 ABI 与结构校验 + manifest
```
