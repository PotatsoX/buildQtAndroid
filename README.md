# buildQtAndroid

在 **Windows runner** 上从 Qt 源码构建 **Android（arm64-v8a / armeabi-v7a）** 版 Qt（Windows 主机交叉编译）；host 工具优先取 Qt 官方预编译 Windows 桌面包、缺失时回退源码自建（`host_mode`），产物**同时包含 target 前缀与 host 前缀**，拿到即可交叉编译并用 `androiddeployqt` 打包 APK。

> 本仓库只构建 Qt 库/Qt 前缀，不构建、不签名 APK；APK 打包属于使用方的 `androiddeployqt + Gradle` 流程。

## 结论与定位

- host 有两种来源，由输入 `host_mode` 决定：`auto`（默认）先探测该版本官方 Windows 桌面包，命中则解压官方包（提供 `qmake`/`moc`/`rcc`/`uic`/`qmlimportscanner`/`qsb`/`androiddeployqt`），未命中自动回退源码自建（MinGW）；实测官方包路径可省 **2 小时 41 分 48 秒**的 host 编译。无论哪条路径，都断言 `host/bin/qmake.exe -query QT_VERSION == qt_version`。target 一律用 `-qt-host-path` + NDK clang 交叉编译，ABI 由输入 `abi` 决定（默认 `arm64-v8a`）。
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
| MinGW-w64 | **15.1.0**（posix-seh, msvcrt, rt_v12） | 官方 host 包即由它构建；工作流不再本地安装 MinGW，运行库随包解压 |
| Ninja | **1.10.2** | 固定下载 |
| 7-Zip | **24.09** | 仅用于解压/打包 |
| Python | **3.11.9** | 官方页另一列为 3.8.1，两者均满足 Qt 构建需要 |
| OpenSSL | 3.5.4 | 本工作流不构建/不链接 Android OpenSSL，见“已知限制” |
| Perl | 5.42.2.1 | 官方 Software 表列为 strawberry 5.32.0.1；GitHub 上无该版本 portable 资产，沿用参考项目的 5.42.2.1 |

文档冲突说明：`doc.qt.io` 的 *Qt for Android — Building from Source* 写 MinGW-w64 **13.1**，6.12 版本页写 **15.1.0**。本仓库以 6.12 版本页为准 —— 实测 Qt 官方 6.12.0 Windows 桌面包的 `config_qtbase.summary` 里 Compiler 就是 **gcc 15.1.0**，与版本页一致。“Windows 主机不能用 MSVC 构建 Qt for Android”两处一致，但本仓库不受影响：target 用 NDK clang，host 用官方包。

版本页未列 **Gradle** 与 ABI 列表；但 Qt 6.12 的 Android JAR 由 Gradle 构建，Qt 自身构建期就需要 Gradle（源码树内 wrapper 指定 Gradle **9.5.1**），详见「为什么 target configure 需要 Gradle 离线缓存」。ABI 由输入 `abi` 决定（默认 `arm64-v8a`，官方 CI 对照行用的是 `armeabi-v7a`）。

## 工作流

文件：`.github/workflows/build-qt-android.yml`

触发方式：

- `workflow_dispatch`（手动，首轮推荐）
- 推送 `qt-*` tag（构建并自动发布 GitHub Release）

可调参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `qt_version` | `6.12.0` | 源码版本，下载 `qt-everywhere-src-<ver>.zip` |
| `skip_modules` | `qtwebengine` + 10 模块 + 2 feature | 空格/逗号分隔：模块名传给 configure `-skip`；以 `-` 开头的原样传给 configure（如 `-no-feature-printsupport`）。完整默认值见「模块选择机制」 |
| `host_only` | `false` | 只构建 host 工具，便于排错 |
| `host_mode` | `auto` | host Qt 来源：`auto`（官方包优先，缺失回退源码自建）/ `official`（强制官方包，探测失败直接失败）/ `build`（强制源码自建） |
| `host_modules` | `auto` | 仅 `build` 模式生效：`auto` = 只编 target 构建要用的工具模块；`all` = 全量（只减去 `skip_modules` 里的模块名）；也可给逗号分隔的模块名，未知模块直接报错 |
| `host_linkage` | `shared` | 仅 `build` 模式生效：`shared` = 共享链接（与官方包一致）；`static` = 追加 `-static -static-runtime -DFEATURE_relocatable=ON`（去 DLL 依赖，未经 CI 验证；`official` 为共享包，该值不生效） |
| `abi` | `arm64-v8a` | 目标 ABI，可选 `arm64-v8a` / `armeabi-v7a`（官方 CI 对照行用 armv7） |
| `runner` | `windows-2022` | 可换成 larger runner 标签 |

流程步骤：

1. 恢复缓存（源码归档 / Android SDK+NDK / Gradle home）。
2. 安装固定版本 JDK、Python、CMake、Ninja、Perl、7-Zip、Android SDK/NDK（MinGW 只在 `build` 模式、在 host 步骤内部下载，`official` 路径不付这笔开销）。
3. `scripts/fetch-qt-source.ps1` 下载官方 **zip** 归档（md5 校验取自 `md5sums.txt` 的 zip 行；`official_releases` 与 `archive` 两处都试），用 7-Zip 多线程**全量解压**；每 30 秒打印已解出文件数、累计字节数、7z 的 CPU 秒数与工作集。
4. **host 工具**（`Resolve host Qt mode` 决定走哪条）：
   - `official`：从 `download.qt.io` 下载该版本 Windows 桌面归档（qtbase/qtdeclarative/qttools/qtsvg + qtshadertools/qtremoteobjects/qtscxml/qtgrpc + MinGW runtime），解压到 `D:\qt\host`，`qmake.exe -v` 自检并断言版本；
   - `build`：MinGW 15.1.0 桌面 `configure -skip <host_skip_modules>` → build → install 到 `D:\qt\host`，`.cache-ok` 标记（内容为 `build:<linkage>:<host_set>`）后删 build 目录；`host_skip_modules` 由 `host_modules` 推出，默认只编 target 构建会用到的工具模块（见「host 模块集」）；`host_linkage=static` 时追加 `-static -static-runtime -DFEATURE_relocatable=ON`（见「host 链接方式」）。
5. **Gradle 离线缓存准备**：按 `qtbase/cmake/QtJavaHelpers.cmake` 报错给出的命令调用 `cmake\QtSetupAndroid.cmake`，先把 `Qt6Android` JAR 的 Gradle 依赖填进 `~/.gradle`（已命中则跳过联网）。
6. **target 构建**：`configure.bat ... -qt-host-path D:\qt\host -android-abis <abi> -android-sdk ... -android-ndk ... -no-feature-sql-* -skip <模块> <feature 参数>`，安装到 `D:\qt\android_<abi>`；实际命令行原文写入 `target-configure.txt`，最终进 `BUILD-INFO.txt`。
7. `scripts/verify-android-prefix.py` 校验 ABI/关键库/host 工具/`Qt6HostInfo`/`Qt6Android.jar`/Gradle wrapper，输出 `manifest.json`。
8. 生成 `BUILD-INFO.txt`（UTF-8 with BOM，压缩包顶层），记录版本/ABI/host 来源与链接方式、skip 项、host 生效模块、host/target configure 原文、工具链版本、runner 环境、`T_*` 阶段耗时与产物自检输出。
9. 7z 打包 **target + host 两个前缀 + `BUILD-INFO.txt`**并上传 artifact：`qt-<ver>-android-<abi>-windows-host`。

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
qtwebengine qtgrpc qtserialbus qtscxml qtopcua qtremoteobjects qtactiveqt qtwayland qttasktree qtcoap qtwebchannel -no-feature-printsupport -no-feature-spatialaudio
```

`qtwebengine` 保留在默认值里（构建开销最大且 Android 侧通常不需要）；其余为本次指定的 10 个模块 + 2 个特性。

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

没有“无法按用户方式关闭”的项；`Print Support` 与 `Spatial Audio` 用 feature 开关，代价是各自模块内的对应功能不可用。

为什么不采用「解压后删掉不需要的模块」：configure 要遍历源码树，缺目录会被当作模块不存在而跳过，删源码省不了 configure 时间，还多一轮十几万文件的删除写操作。缩小范围只用 `-skip` 与 feature 开关。

### host 模块集（`build` 模式）

反推依据：`lib/cmake/Qt6<Module>/Qt6<Module>Dependencies.cmake` 的 `__qt_<Module>_tool_deps` 声明交叉编译时要从 host 前缀取哪些工具包；工具包 `Qt6<Module>Tools` 由 `lib/cmake/Qt6<Module>Tools/Qt6<Module>ToolsConfig.cmake` 导出 `Qt6::<tool>` 导入目标，指向 `${_IMPORT_PREFIX}/bin/<tool>.exe`。

实测遍历 Qt 6.12.0 官方包的 `lib/cmake/**/Qt6*Dependencies.cmake`，声明 tool deps 的模块如下：

| target 模块 | 需要的 host 工具包 | 主要工具 |
|---|---|---|
| qtbase（Core / Gui / Widgets / DBus） | `Qt6CoreTools` / `Qt6GuiTools` / `Qt6WidgetsTools` / `Qt6DBusTools` | `moc` `rcc` `uic` `qmake` `qtpaths` `androiddeployqt` `syncqt` `tracepointgen` `windeployqt` `qdbuscpp2xml` |
| qtdeclarative（Qml / Quick） | `Qt6QmlTools` / `Qt6QuickTools` | `qmlcachegen` `qmltyperegistrar` `qmlimportscanner` `qmltc` |
| qtshadertools | `Qt6ShaderToolsTools` | `qsb` |
| qttools（Tools / Linguist） | `Qt6ToolsTools` / `Qt6LinguistTools` | `qdoc` `qhelpgenerator` `lrelease` `lupdate` |
| qtscxml | `Qt6ScxmlTools` | `qscxmlc` |
| qtremoteobjects | `Qt6RemoteObjectsTools` | `repc` |
| qtgrpc（含 qtprotobuf） | `Qt6GrpcTools` / `Qt6ProtobufTools` | `qtprotoc` `qtgrpcgen` `qtprotobufgen` |

结论：为了让 target 的**所有**模块都能编，`qtbase` + `qtdeclarative` + `qttools` + `qtshadertools` **四块不够**，还缺 **qtscxml**（`qscxmlc`）、**qtremoteobjects**（`repc`）、**qtgrpc**（`qtprotoc`/`qtgrpcgen`，连带 `Qt6ProtobufTools`）。但默认 `skip_modules` 已跳过这三项，因此默认可用的 `auto` 集合不含它们；如果把对应模块从 skip 里去掉，必须把 host 侧对应模块加回。

`qtgrpc` 另有宿主 `protoc` 依赖：`Qt6GrpcToolsDependencies.cmake:7` 写的是 `set(__qt_GrpcTools_tool_third_party_deps "WrapProtoc\\;FALSE\\;\\;\\;")`，Qt 包内不含 protoc，需 CI 或宿主安装 protobuf。默认已 `-skip qtgrpc`，默认流程不再触发该依赖（见「已知限制」）。

`auto` 候选白名单 13 个模块；按默认 `skip_modules` 过滤后实际生效 **9 个**：

| 模块 | 依据 |
|---|---|
| qtbase、qtdeclarative、qttools、qtshadertools、qtscxml、qtremoteobjects、qtgrpc | 上表的 tool deps 声明 |
| qtsvg | 无独立 host 工具，体积小；作为桌面包完整性保险保留 |
| qtquick3d、qtquick3dphysics、qtquicktimeline、qtopcua、qtlottie | 源码树带构建期工具（`shadergen`/`balsam`/`cooker`/`datatypecodegenerator`/`lottietoqml`），但官方安装包里没有对应的 `Qt6<Module>Tools` 声明，**未确认** target 构建是否消费；按“不确定就留在 host 侧”保留 |

按默认 `skip_modules` 被过滤掉的 4 个：`qtscxml`、`qtremoteobjects`、`qtgrpc`、`qtopcua`。因此默认 host 生效集合为：`qtbase`、`qtsvg`、`qtdeclarative`、`qtshadertools`、`qttools`、`qtquick3d`、`qtquick3dphysics`、`qtquicktimeline`、`qtlottie`。

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
| `-skip <skip_modules 中的模块名>` | target + host(build) | 参考项目 build-Qt6mingw64.cmd:33 引入；默认值见「模块选择机制」 |
| `-no-feature-printsupport`、`-no-feature-spatialaudio` | target | 按本次指定关闭；feature 名来自 `qtbase/configure.cmake:1146-1151` 与 `qtmultimedia/src/multimedia/configure.cmake:281-287` |
| `-qt-host-path` | target | Qt 6 交叉编译必需 |
| `-android-abis`、`-android-sdk`、`-android-ndk` | target | Qt 6 Android 必需 |
| `-android-javac-source 17`、`-android-javac-target 17` | target | Qt 6 Android 必需（配套 JDK 21） |
| `-no-openssl` | target | 本项目补充：不引入 OpenSSL 依赖 |

host 侧参数（`-platform win32-g++`、`-qt-zlib`、`-schannel` 等）只用于 `build` 模式的 host configure；`official` 模式不执行 configure。

不采用的参考项：target 侧不用 `-static`、`-static-runtime`（Android 产物必须是共享库 `.so`，Qt 不支持静态 target）；host 侧的 `-static`/`-static-runtime` 通过 `host_linkage=static` 显式开启（见「host 链接方式」）。`-qt-webp`、`-qt-tiff`、`-qt-pcre`（Qt 6 已无对应捆绑库/选项，**未核实**，传下去会报 unknown option）、`-opengl desktop`（Android 走 GLES）同样不采用。

### host 链接方式（`build` 模式，输入 `host_linkage`）

默认 `shared`。Qt 官方文档不建议静态 host 配共享 target：[Cross-compiling Qt（6.12）](https://doc-snapshots.qt.io/qt6-6.12/cross-compiling-qt.html) 原文 “Avoid building the host Qt statically if the target Qt is built shared. A static build of Qt might not contain all tools necessary to build a shared Qt.”；MinGW 静态构建也不在 Qt 官方 CI 矩阵内（Windows 静态包是 MSVC 构建，mingw 行不带 `-static`）。因此 `static` 只作 opt-in，默认路径不改变。

`configure` 接受这个组合（Qt 6.12 `qtbase/configure.cmake`，本地已核对）：

- `qt_feature_alias("static" ... ALIAS_OF_FEATURE "shared" NEGATE)`（:557-560）→ `-static` 等价于 `BUILD_SHARED_LIBS=OFF`；
- `qt_feature("static_runtime" ... CONDITION NOT QT_FEATURE_shared ... WIN32)`（:1217-1221）→ 静态 + Windows 合法；
- `qt_feature("relocatable" ... AUTODETECT QT_FEATURE_shared OR APPLE ... CONDITION QT_FEATURE_dlopen OR WIN32 OR NOT QT_FEATURE_shared)`（:1234-1239）→ Windows 静态下不会自动开启，需显式 `-DFEATURE_relocatable=ON`；源码没有“静态不可 relocatable”的拒绝分支。

| 组合 | 行为 |
|---|---|
| `build` + `shared`（默认） | 与官方包一致：`bin` 内有 `Qt6*.dll` 与 MinGW 运行库，工具可直接运行 |
| `build` + `static` | 工具静态链接，`bin` 内无 `Qt6*.dll`；`lib/*.a` 在裁剪步骤仍会删除（只留 `libQt6EntryPoint.a`），交叉编译只消费 `bin` 下的 exe |
| `official` + `static` | 官方桌面包是共享构建，`static` 不生效：显式 `host_mode=official` 直接报错；`auto` 命中 official 时忽略并写日志/摘要 |

未验证项（本机没有 Qt 源码与 MinGW 15.1.0，只验证了本机 MinGW 8.1.0 的 `gcc -static` 能正常链接）：

- 静态 host 能否编出、默认 9 个模块的工具是否齐全、`androiddeployqt` 静态版能否读写 `Qt6Android.jar` 与 Gradle wrapper、交叉编译侧 `Qt6*Tools`/`Qt6HostInfo` 是否仍能解析 —— **均需 CI 首轮确认**。
- 时间：相对 run #6 的 host 2 小时 41 分 48 秒，静态链接通常略增（推断 +10%–20%，未实测）。
- 体积：静态 exe 内嵌 Qt 库，通常大于“共享 exe + DLL”；裁剪后前缀与 7z 体积**未实测**（推断 250–400 MB / 60–120 MB）。
- 自包含（把 host 复制进 target 前缀并改写 `target_qt.conf`/`Qt6Dependencies.cmake`/`qt.toolchain.cmake`）**未落地**：静态 host 尚未经 CI 验证，且官方不建议该组合，当前保留 target/host 双前缀与显式 `QT_HOST_PATH`。若首轮 CI 证明可用，再评估嵌入，并把 `verify-android-prefix.py` 的 PE 计数改为按目录白名单。

### 磁盘与时间估算（D: 约 14 GB）

| 源码方案 | 解压后占用 | 文件数 | 解压耗时 |
|---|---|---|---|
| 全量解压（默认） | 约 1.3–1.5 GB | 约 12–15 万（推断） | 3–8 分钟（推断，zip + 7-Zip 多线程） |

- 构建目录（推断，未实测）：target 8–12 GB；峰值需同时容纳源码 + target 构建目录 + target 前缀 + host 前缀（1.4 GB），全模块很可能触到 D: 14 GB 上限。
- 时间：`official` 路径为下载约 196 MB + 解压约 1.4 GB（本机实测 20 余秒；CI 上受网络影响，推断 2–4 分钟）；`build` 路径 host 全模块在 run #6 实测 **2 小时 41 分 48 秒**，`host_modules=auto` 默认只编 9 个模块（跳过 qtgrpc/qtscxml/qtremoteobjects/qtopcua），推断省 45–75 分钟（待 CI 的 `T_HOST_*` 计时校准）。剩下的大头是 target（run #6 实测 1 小时 39 分 26 秒）；默认 skip 了 10 个模块与 2 个 feature，target 侧推断再省 5–15 分钟、磁盘占用小幅下降（均未实测）。4 vCPU 下全模块仍有超 6 小时风险；可选办法：换 larger runner，或继续加长 `skip_modules`（只改运行参数）。`official` 模式不编译 host，host 口径对它无影响。
- 解压开销构成：每文件一次的实时写入 + 扫描是主因，压缩流解码只占几十秒。工作流因此在装工具前加了 Defender 路径排除（`D:\qt`、`C:\tools`、`C:\android`、workspace），失败不致命。
- 源码用官方 **zip**（604,643,023 字节，md5 `64889aee0623311cce096be5f445c7d1`，取自官方 `md5sums.txt` 的 zip 行）：比同内容的 tar 大 36%，但 271 MB/s 下下载只差约 1 秒，换来 7-Zip 多线程解压且不必先解成中转文件。
- host 前缀体积：`build` 模式自建 1.4 GB，裁剪后 285.1 MB，按 7z `-mx=5` 单独实测 **60 MB**；明细见「host 前缀内容与用途」。`official` 模式的 host 前缀是同一批官方归档的解压结果，裁剪后体积同级。`host_linkage=static` 的体积与耗时为推断值（见「host 链接方式」）。target 前缀结构未做裁剪（本机不可测，标注为未核实）。
- ccache/sccache 未启用：Windows 下收益与稳定性未验证。

## 缓存 key

| 缓存 | key |
|---|---|
| 源码归档（约 605 MB） | `qt-src-zip-<qt_version>-v1` |
| Android SDK/NDK（约 3 GB） | `android-<ndk>-<platform>-<build-tools>-<cmdline>-v1` |
| Gradle home（推断 1–2 GB） | `gradle-qt<qt_version>-bt<build-tools>-v1` |
| host 前缀（仅 `build`，1.4 GB） | `qt-host-build-<qt_version>-<skip_key>-<linkage>-hostset<host_set>-mingw<ver>-cmake<ver>-v1` |

`host_set` 是 `host_modules` 的归一化串（非字母数字 → `-`、小写）；`.cache-ok` 标记内容为 `build:<linkage>:<host_set>`，恢复缓存后还会再校验一次，避免把旧的全量前缀当最小集用。`<linkage>` 为 `shared`/`static`，两种链接方式的前缀不可互换。

`official` 路径的 host 前缀不入缓存：官方包的确定性解压结果，重下解压（约 2 分钟）比读写 1.4 GB 缓存更划算，也不占 10 GB 配额。两条路径的缓存步骤按 `HOST_MODE_RESOLVED` 门控，不会互相命中。target 构建目录不入缓存。

## 版本与 host 来源矩阵

host 阶段由输入 `host_mode` 控制（默认 `auto`）：

| 输入 | 行为 |
|---|---|
| `auto` | 按 `qt_version` 精确探测官方 Windows 桌面包索引；命中走 official，未命中回退 build，并在日志与 job summary 写明实际路径与原因 |
| `official` | 强制 official；探测失败直接失败（不静默回退，避免用户以为用的是官方包） |
| `build` | 强制源码自建（MinGW 15.1.0 在该步骤内部下载，官方路径不付这笔开销） |

探测方式（`Resolve host Qt mode` 步骤的 `Test-OfficialIndex`）：GET `https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_<digits>/qt6_<digits>_mingw/Updates.xml`，目录名由版本数字拼成（`6.12.0`→`qt6_6120`）。命中必须同时满足：

1. HTTP 200 且 XML 可解析（404/网络失败即判定不命中）；
2. 存在 `qt.qt6.<digits>.win64_mingw`；
3. 该包 `<Version>` 取第一个 `-` 之前的值与 `qt_version` **全字符串相等**（`6.12.0-0-202609280346` → `6.12.0`），不做前缀/模糊匹配；
4. 主包 `DownloadableArchives` 含 `qtbase-`/`qtdeclarative-`/`qttools-`/`qtsvg-`；
5. 存在 `qtshadertools`/`qtremoteobjects`/`qtscxml`/`qtgrpc` 四个 addons 包（默认 skip 已关闭后三者，实际只需 qsb；探测仍保守要求，缺失只会让 `auto` 回退到 `build`）。

实测（2026-11-04，逐条 `curl` + 解析）：

| `qt_version` | 探测结果 |
|---|---|
| `6.12.0` | 命中，`6.12.0-0-202609280346` |
| `6.11.3` | 命中（补丁版同样有官方桌面包） |
| `6.12.5` | 404（该版本尚未发布），`auto` 回退 build |

矩阵：

| 该版本官方有无 Windows 桌面包 | 走哪条 host | 说明 |
|---|---|---|
| 有（如 6.12.0、6.11.3） | `auto` → official | 下载约 196 MB、解压约 1.4 GB（本机 20 余秒）；省掉实测 2 小时 41 分 48 秒的 host 编译 |
| 无，但源码公开（新补丁版索引未同步，或已过二进制支持期） | `auto` → build | 源码从 `official_releases` 或 `archive` 取（`fetch-qt-source.ps1` 两处都试） |
| 无，源码也不公开（商业 LTS 专属补丁版） | 无法构建 | 会在 `Fetch Qt sources` 阶段下载失败；开源渠道确实拿不到，需要商业许可 |

开源补丁版在二进制支持期内同时提供桌面/Android 包与源码，`auto` 一般直接命中 official。`6.12.5` 目前（2026-11-04）尚未发布，源码与桌面包都不存在，属于“尚未发布”而不是“开源拿不到”。

版本一致性硬约束（源码依据）：

- Qt **不比较** host/target 的版本字符串：`qt_create_hostinfo_package` 生成的 `Qt6HostInfoConfigVersion.cmake` 是 `COMPATIBILITY AnyNewerVersion` + `ARCH_INDEPENDENT`（`qtbase/cmake/QtPostProcessHelpers.cmake:569-575`），而 `_qt_internal_find_host_info_package` 的 `find_package(Qt6HostInfo CONFIG REQUIRED ...)`（`QtPublicDependencyHelpers.cmake:241-251`）**不传版本号**，版本文件因此基本不起作用；`qt.toolchain.cmake.in` 里 `QT_HOST_PATH` 命中数为 0。
- 真正的“同版本”要求来自工具语义（moc/rcc/qml 工具产出的中间产物要与 target 库 ABI/版本匹配）与 Qt 文档，不是 CMake 断言。因此本工作流自己断言：官方包解压后执行 `host/bin/qmake.exe -query QT_VERSION`，与 `qt_version` 全字符串比较，不等直接 `throw`。
- 若探测“误命中” 6.12.0 而用户填的是 6.12.5：目录名 `qt6_6125` 与 `qt6_6120` 不同，URL 直接 404；即使镜像返回错内容，第 3 条 `<Version>` 全串比较也会拒绝；最后还有 `qmake -query QT_VERSION` 兜底。三层都不依赖前缀匹配。

### 为什么不支持「用 6.12.0 的 host 编 6.12.5」

结论：**不提供 `official-any` 这类“同系列就近版本”档**，host 必须与 target 精确同版本；没有官方桌面包时由 `auto` 回退 `build`。

- 官方文档明确要求同版本：[Cross-compiling Qt](https://doc.qt.io/qt-6/cross-compiling-qt.html) 原文 “Ensure you use the same version of Qt for the host and target Qt to avoid incompatibility issues.”
- 但 Qt 自己**不校验**版本串：官方 6.12.0 包里 `lib/cmake/Qt6HostInfo/Qt6HostInfoConfigVersion.cmake` 只写 `set(PACKAGE_VERSION "6.12.0")` 且兼容策略为 `AnyNewerVersion`，调用方 `find_package(Qt6HostInfo CONFIG REQUIRED)` 也不传版本（实测文件 + `qtbase/cmake/QtPublicDependencyHelpers.cmake:241-251`）。混搭因此在 configure 阶段**不会**报错。
- 真正的约束在工具产物上。实测 6.12.0 的 `moc` 生成文件内含硬护栏：
  `#elif Q_MOC_OUTPUT_REVISION != 69` / `#error "This file was generated using the moc from 6.12.0. It cannot be used with the include files from this version of Qt."`；`Q_MOC_OUTPUT_REVISION` 定义在 target 的 `qtmetamacros.h`（实测 6.11.3 与 6.12.0 都是 69，但这只是当前取值，后续版本可以上调）。`qmltyperegistrar` 直接消费 moc 的 JSON（其 `--help` 写的是 `[MOC generated json file]`），`qmlcachegen`/`qsb` 产出的中间文件由 target 侧 Qt 库消费 —— 这些格式都没有跨版本的兼容承诺。
- 所以混搭失败的典型现象不是 configure 报错，而是编用户工程时 moc 抛 `#error`，或部署后运行期 QML/着色器异常，排查成本高于直接重编 host。`build` 路径的 host 有缓存 key，同版本重跑不重编，因此没有理由承担混搭风险。
- 若手工强行混搭：把 `QT_HOST_PATH` 指向旧 host，出现上述 moc `#error` 就说明中招；改回精确版本，或 `host_mode=build`。

## 使用方法

1. 打开仓库 **Actions → build-qt-android → Run workflow**，保持默认参数后运行（`skip_modules` 默认已跳过 qtwebengine + 10 个模块 + 2 个 feature，见「模块选择机制」）；若担心 6 小时上限，可继续加长跳过列表。
2. 成功后在该 run 页面下载 artifact；如推送了 `qt-*` tag，还会生成 Release 附件。7z 顶层含 `BUILD-INFO.txt`，记录本次的 configure 原文、工具链版本、阶段耗时与自检输出。
3. 使用产物：

```powershell
# 7z 解压到一个目录，会得到两个同级目录：android_<abi>\ 与 host\
# 保持两者同级且不改名；host 路径通过 -DQT_HOST_PATH 显式传入
cmake -S <your-app> -B build `
  -DCMAKE_TOOLCHAIN_FILE="D:\qt\android_<abi>\lib\cmake\Qt6\qt.toolchain.cmake" `
  -DANDROID_NDK_ROOT="C:\android\ndk\android-ndk-r27c" `
  -DANDROID_SDK_ROOT="C:\android\sdk" `
  -DQT_HOST_PATH="D:\qt\host"
```

> `qt.toolchain.cmake` 在包内写死了 `/opt/android/...` 的默认路径，必须显式传入 `ANDROID_NDK_ROOT`/`ANDROID_SDK_ROOT`，否则配置阶段会报错。

> `QT_HOST_PATH` 必须显式指向解压出来的 `host\`：target 前缀里的 `lib/cmake/Qt6/Qt6Dependencies*.cmake` 记录的是构建机上的绝对路径 `D:/qt/host`（`qtbase/cmake/QtPostProcessHelpers.cmake:429-435` 的已知限制），换机器后只能靠 `QT_HOST_PATH` 覆盖；不设置且该路径不存在时，`find_package(Qt6)` 会直接报 “host Qt not found”。

> 两种 host 来源对你的工程没有能力差异：交叉编译的库与头文件都来自 `target` 前缀，host 只提供工具。`official` 的 host 是官方完整桌面工具集；`build` 的 host 默认只含 9 个工具模块（白名单 13 个，减去默认 skip 的 4 个，见「host 模块集」），少了 `designer`/`assistant`/`linguist` 等桌面工具，但这些不参与 Android 构建。若工程用到 host 白名单之外的模块工具，configure 会报找不到工具——此时用 `official`，或在 `host_modules` 里把该模块加进去重跑 `build`。

> `host_linkage=static` 只改变 host 前缀结构（`bin` 内无 `Qt6*.dll`），产物仍是 target + host 双前缀，用户侧命令不变（仍需 `-DQT_HOST_PATH`）。

## host 前缀内容与用途

`official` 与 `build` 两条路径的 host 前缀都按同一判据裁剪；`target` 前缀结构完全不动（交叉编译与 `androiddeployqt` 都依赖它）。`host_linkage=static` 时 `bin` 内没有 `Qt6*.dll`/MinGW 运行库（工具已静态链接），`lib/*.a` 是实际静态库而非导入库，裁剪时同样删除，只留 `libQt6EntryPoint.a`。

按用途分三层：

| 层 | 内容 | 谁在用 |
|---|---|---|
| 部署 | `bin\androiddeployqt.exe`、`bin\qtpaths.exe`、`bin\Qt6*.dll`、MinGW 运行库（`libstdc++-6.dll`/`libgcc_s_seh-1.dll`/`libwinpthread-1.dll`） | `androiddeployqt` 打包 APK；DLL 是 exe 的加载依赖 |
| 交叉编译 | `bin\` 下被 `lib\cmake\**\Qt6*Targets*.cmake` 引用的 exe（`moc`/`rcc`/`uic`/`qmltyperegistrar`/`qmlcachegen`/`qmlimportscanner`/`qsb`/`qscxmlc`/`repc`/`qtprotoc` 等，实测 49 个）、`lib\cmake\`（`Qt6HostInfo`、`Qt6*Tools`）、`lib\libQt6EntryPoint.a`、`mkspecs\`、`plugins\`、`qml\`、`metatypes\`、`lib\metatypes\`、`lib\objects-RelWithDebInfo\`、`lib\*.prl` | `find_package(Qt6)` 解析 host 工具与 `Qt6HostInfo`；`qmake`/`qtpaths` 查询安装布局 |
| 已删除 | `lib\*.a`（`libQt6EntryPoint.a` 除外）、`sbom\`、14 个未被 cmake 引用的桌面 exe、`include\`、`doc\` | 桌面开发、文档用途，交叉编译不需要 |

裁剪实测（Qt 6.12.0 官方 Windows 包解压前缀）：

| 项 | 处理后 | 判据 |
|---|---|---|
| `lib\*.a` | 只留 `libQt6EntryPoint.a`（11 KB） | 工具在 Qt 构建期已链接完成；删 EntryPoint 会让 `Qt6EntryPointPrivate` 导入目标缺文件 |
| `sbom\` | 删除 | 软件物料清单，非运行必需 |
| `bin\qdoc.exe`（71 MB） | 保留 | `Qt6ToolsTools` 的导入目标指向它，删除后 `find_package(Qt6 COMPONENTS Tools)` 安装阶段失败 |
| 14 个未引用桌面 exe（约 11.8 MB） | 删除 | `designer`/`assistant`/`linguist`/`qmlls`/`qmlscene`/`qtdiag`/`pixeltool`/`qdbusviewer` 等，Android 流程不调用 |
| `include\`（24.1 MB）、`doc\`（0.5 MB） | 删除 | 交叉编译读 target 前缀头文件；host 库导入目标在删 `.a` 后本就不可链接 |
| 合计 | 1,472 MB → 309.7 MB → 285.1 MB | 本轮 7z `-mx=5` 压缩后 60 MB |

保守保留（未确认工具是否在运行期动态加载，不删）：

| 内容 | 体积 | 保留原因 |
|---|---|---|
| `lib\objects-RelWithDebInfo\` | 27 MB | 被 `Qt6::*_qtprotoreg`、`Qt6::QmlTypeRegistrarPrivate_resources_1` 等导入目标的 `IMPORTED_OBJECTS` 引用 |
| `plugins\` | 12 MB | 含 `sqldrivers`、`qmltooling`、`platforms`，工具运行期可能按需加载 |
| `metatypes\` | 7.8 MB | 被 `Qt6*` cmake 文件引用（QML 外部类型注册） |
| `qml\` | 7.4 MB | host QML 模块，`qmllint` 等可能消费 |
| `mkspecs\`、`share\` | 1.4 MB | `qmake`/`qtpaths` 的查询数据 |
| `modules\`、`phrasebooks\` | 0.4 MB | 模块元数据/短语库，未确认 `androiddeployqt` 是否读取，保留 |

> 产物不是 Windows 桌面开发 SDK：`lib\*.a` 已删，链接桌面程序会失败；host 前缀只用于交叉编译与 `androiddeployqt`。`build` 模式的 host 默认只含 9 个工具模块（白名单 13 个，见「host 模块集」）。

## 验证方式

CI 内的自动校验（`scripts/verify-android-prefix.py`）：

- `lib/*.so` 按所选 ABI 校验：`arm64-v8a` 为 ELF64 / `e_machine=183`，`armeabi-v7a` 为 ELF32 / `e_machine=40`；
- 存在 `libQt6Core*.so` 与 `lib/cmake/Qt6/Qt6Config.cmake`；
- target 前缀的 PE 文件（`.exe`/`.dll`）计数：双前缀方案下应为 0（脚本只记录到 `manifest.json`，不据此报错）；
- host 前缀存在 `qmake*.exe`、`moc.exe`、`androiddeployqt.exe` 与 `lib/cmake/Qt6HostInfo/Qt6HostInfoConfig.cmake`；
- target 前缀存在 `jar/Qt6Android.jar` 与 `src/3rdparty/gradle/gradlew.bat`（`androiddeployqt` 的运行期依赖）；
- 记录 NDK/SDK 实际版本、库清单与 SHA-256 到 `manifest.json`。

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
- 处置：target 的 `configure` 显式 `-no-feature-sql-*`，只保留 Qt 自带 bundled 的 `sql-sqlite`；`build` 模式对 host 同样关闭。`official` 模式 host 侧不执行 configure，只在 target 生效。

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
| `-no-openssl` | target | 不引入宿主 OpenSSL |

`-qt-zlib` / `-qt-libpng` / `-qt-libjpeg` / `-qt-freetype` / `-qt-harfbuzz` / `-schannel` 只适用于桌面构建，本项目不自建桌面 host，不使用。

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
| CMake / Ninja / JDK / MinGW / 7-Zip / OpenSSL | 4.3.2 / 1.10.2 / 21.0.9 / 15.1.0(posix-seh-msvcrt-rt_v12) / 24.09 / 3.5.4 | CMake/Ninja/JDK/7-Zip 同；MinGW 仅 `build` 模式在 host 步骤内下载（复用官方 CI 的 15.1.0 版本）；OpenSSL 未用 | 差异：`official` 模式不需要本地编译器 |
| Python | 3.8.1 | 3.11.9 | 保留：3.8.1 已 EOL，且 setup-python 清单里仅旧补丁版本；Qt 构建脚本两者兼容 |
| Perl (strawberry) | 5.32.0.1 | 5.42.2.1 | 保留：GitHub 上没有 5.32.0.1 的 portable 资产（实测未找到） |
| 平台镜像 | `windows-11_24h2-mingw15` | `windows-2022` | 差异：标准 runner 无该自定义镜像；`build` 模式自己下 MinGW 15.1.0，`official` 模式连编译器都不需要 |
| ABI | `armeabi-v7a` | 输入 `abi`，默认 `arm64-v8a` | 可切换 |
| 其他 configure 参数 | `-release -force-debug-info -qpa android;offscreen -nomake examples -no-feature-pkg-config` | `-release -nomake examples -nomake tests -no-feature-pkg-config` | 已纳入 pkg-config；`-force-debug-info`、`-qpa android;offscreen` 未加（未核实其对产物大小的影响） |

armv7 额外注意：

- 交叉 triple 为 `armv7a-linux-androideabi`，由 `-android-abis armeabi-v7a` 自动选择；产物 `.so` 是 ELF32、`e_machine=40`，`verify-android-prefix.py` 已按 ABI 校验 ELF class 与 machine。
- 资源编译（`windres`/`.rc`）只发生在 Windows 桌面构建；`build` 模式才会做桌面构建，`official` 模式与 target 侧都不涉及 windres，armv7 也不涉及 32 位 windres。
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
  - `Qt6Dependencies.cmake`：`__qt_platform_initial_qt_host_path` → `${Qt6_DIR}/../../../host`；`__qt_platform_initial_qt_host_path_cmake_dir` → `${Qt6_DIR}/../../../host/lib/cmake`（`:89-90`，Qt 6.4.1+）。实测 Qt 6.12.0 官方包仍用这两个变量（默认空串），改写点仍在。
  - `qt.toolchain.cmake`：`__qt_toolchain_initial_qt_host_path`、`__qt_toolchain_initial_qt_host_path_cmake_dir` → `${CMAKE_CURRENT_LIST_DIR}/../../../host[\/lib\/cmake]`（`:94-104`，Qt 6.2.4）。
- **裁剪**：没有删 `*.a`/`doc`/`examples`/`tests`/`sbom`/`qdoc`/`translations`；判据是“只复制交叉编译/部署需要的子目录”（上表白名单），而不是事后删文件。静态 host 的 `lib/*.a` 本就不复制。

| 维度 | Fs-scripts | 本仓库 | 判断 |
|---|---|---|---|
| Qt 版本上限 | 6.7.2（另有 6.2.9/6.5.3/5.15.14） | 6.12.0 | 它早于 Qt 的 Gradle 化 jar，Gradle 这块没有可借鉴内容 |
| 工具链来源 | 本机固定路径 `D:\android-sdk-windows-20240205`、`D:\android-ndk-r26d`、OpenJDK 11、CMake 3.29（`Configuration.lua:52-79`、`:392-395`） | runner 上 `sdkmanager`/7z 安装，版本钉死 | 它预置即用；不适配 hosted runner |
| host Qt | 下载其 Jenkins 产出的静态 host Qt（`hostToolsUrlwin`，`qtCompile_conf.lua:7276`），`-DFEATURE_relocatable=ON`（`:6289` 段） | `auto`：官方 Windows 桌面包，缺失回退源码自建 + Actions 缓存；`build` 可用 `host_linkage=static` opt-in | 都用预编译 host；我们来源公开可探测，缓存只用于 build |
| target 参数 | 直调 CMake：`-DQT_HOST_PATH`、`-DANDROID_ABI`、`-DANDROID_PLATFORM=27`、`-DBUILD_qtwebengine=OFF`、`-DFEATURE_icu=OFF`、`-DFEATURE_ssl=ON` + 自建 OpenSSL、`-DMYSQL_INCDIR` | `configure.bat` + `-android-abis` + `-no-feature-sql-*` | 它用自建依赖消解宿主探测，成本更高；我们直接关特性 |
| 产物形态 | 单个 `.7z`（Unix 另出 `.tar.xz`），名字含版本/ABI/NDK/host 编译器/变体 | 单个 `.7z`，名字含版本/ABI，解压得两个同级前缀 | 它命名信息更全；我们保持现有命名 |
| host 进产物 | 复制进 `<target>/host`，sed 改写相对路径，用户无需 `QT_HOST_PATH` | target 与 host 两个同级前缀，用户显式传 `QT_HOST_PATH` | 它更自包含；不采纳理由见下 |
| 裁剪 | 白名单复制（bin/libexec/lib/cmake/*.prl/metatypes） | 先全量安装，再删 `.a`/`sbom`/未引用 exe/`include`/文档 | 静态 host 与共享 host 前提不同 |
| Gradle / android jar | 无任何处理（0 处 java/jar/gradle） | 预灌 `~/.gradle` + Actions 缓存 | 它的空白正是我们卡住的点，无法照抄 |
| 缓存 | 无 Actions 缓存，靠 Jenkins workspace 持久化 | 4 类 Actions 缓存 | 本仓库更好（CI 场景） |
| 构建期外网依赖 | 内网 Jenkins artifact + 内网源码包 | 仅 GitHub 可达网络 | 环境不同，不构成优劣 |

不采纳的三点及理由：

1. **直调 CMake 取代 `configure.bat`**：Qt 6.12 的 Gradle 校验在 CMake 层，直调一样会触发；还会丢掉 configure 对特性的推导和 `-no-feature-*` 解析。
2. **自建 OpenSSL/MariaDB 再 `-DMYSQL_INCDIR`**：收益只是多一个 sql 驱动，代价是多两个第三方库的交叉编译。
3. **把 host 复制进 target 前缀（`qt6_deploy_host.sh` 做法）**：思路更自包含（解压目录整体搬迁，不需要 `QT_HOST_PATH`），但前提与适配性都不满足：
   - 它依赖 host 全静态（`-static -static-runtime`），所以只复制 `bin`/`libexec`/`lib/cmake`/`*.prl` 就够；本仓库已提供 `host_linkage=static` 作为 opt-in，但默认 `shared`（Qt 官方不建议静态 host 配共享 target，MinGW 静态也不在官方 CI）；`official` host 是共享 MinGW 构建，工具运行期需要 `Qt6*.dll` 与插件，自包含要把 285.1 MB 整份搬进 target。
   - 自包含会让 target 前缀出现 `.exe`/`.dll`，`verify-android-prefix.py:146` 的 `Windows PE files in target prefix` 计数不再为 0（当前只报告不报错，但会误导“target 是纯 Android 前缀”的校验口径）。
   - 改写依赖 Qt 内部变量；6.12 仍在，但 `qtbase/cmake/QtPostProcessHelpers.cmake:430` 注明 host path “尚未 relocatable”，Qt 升级后有再次失配的风险。
   - 收益只是省掉用户传一个 `-DQT_HOST_PATH`，而双前缀方案已通过 configure 模拟；不值得引入未在真机 Android 构建验证的结构改动。

其压缩参数 `-m0=LZMA2:d256m:fb273 -mmt=3 -myx -mqs -ms=on` 未采纳：本机 `7zr` 不接受 `d256m` 语法，无法对比；当前 `-mx=5` 已压到 60 MB，剩余体积主要由不可再压的 `qdoc` 与 DLL 构成，收益未量化前不改。

一处可借鉴但未落地的细节：它对 Android 显式传 `-DCMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH=ON`。该变量默认即为 ON，显式写只是自证，不会改变宿主机探测行为，因此不改。

## 与官方文档对齐（Qt 6.12）

依据页面（均于 2026-11-04 实际抓取核对）：

- [Qt for Android - Building from Source](https://doc-snapshots.qt.io/qt6-6.12/android-building.html)
- [Cross-compiling Qt](https://doc-snapshots.qt.io/qt6-6.12/cross-compiling-qt.html)

| 维度 | 官方表述 | 本工作流 | 判断 |
|---|---|---|---|
| host/target 版本 | “Ensure you use the same version of Qt for the host and target Qt” | `official` 解压后 `qmake -query QT_VERSION` 与 `qt_version` 全串比较，不等直接 `throw` | 一致 |
| host 静态 | “Avoid building the host Qt statically if the target Qt is built shared.” | 默认 `shared`，`static` 仅 opt-in | 一致（static 是已知偏离） |
| `QT_HOST_PATH` | configure 用 `-qt-host-path <host>`；直接用 CMake 用 `-DQT_HOST_PATH` | target configure 传 `-qt-host-path`；用户工程传 `-DQT_HOST_PATH` | 一致 |
| host 模块范围 | “build the same Qt modules on the host that you'll need on the target” | 按 tool deps 反推最小集，默认 9 个 | 比官方建议更窄，风险见「已知限制」 |
| Windows 编译器 | “Mingw-w64 13.1 toolchain” | `build` 模式用 MinGW 15.1.0 | 偏离：15.1.0 与官方 Windows 桌面包一致，`official` 模式不用 MinGW；暂不改，CI 失败再降级 |
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
- 原因：官方桌面包把 MinGW 运行库放在前缀根目录，Windows 只在 exe 同目录和 `PATH` 里找 DLL；本机 `PATH` 里其他 MinGW（如 `D:\Qt\Tools\mingw810_64\bin`）的同名 DLL 版本不匹配也会触发。
- 处置：把 `libstdc++-6.dll`/`libgcc_s_seh-1.dll`/`libwinpthread-1.dll` 放进 `host\bin`（workflow 直接把该归档解压进 `host\bin`）；运行自检时避免 `PATH` 里的其他 MinGW 抢先。

### `find_package(Qt6)` 报 `The imported target ... references the file ... but this file does not exist`

- 现象：configure 阶段 `FATAL_ERROR`，指出 `Qt6::moc`、`Qt6::syncqt`、`Qt6::qdoc` 等导入目标指向的 `bin\*.exe` 不存在。
- 原因：删掉了被 `lib\cmake\**\Qt6*Targets*.cmake` 引用的 exe；CMake include 导出文件时会校验 `IMPORTED_LOCATION`。`QT_HOST_PATH` 指错目录同样会报这条。
- 处置：恢复该 exe，或只删 `Prune host prefix` 扫描结果之外的 exe；确认真实 host 前缀路径后再传 `QT_HOST_PATH`。

### `find_package(Qt6 COMPONENTS <Module>)` 提示找不到 `Qt6<Module>Tools`

- 现象：`build` 模式的 host 缺某模块工具；configure 不报错，但编用户工程用到该模块的构建步骤失败。
- 原因：工具查找会置 `${CMAKE_FIND_PACKAGE_NAME}_FOUND FALSE`，而生成的 `Qt6<Module>Dependencies.cmake` 末尾无条件 `set(Qt6<Module>_FOUND TRUE)` 覆盖它（实测 `Qt6ScxmlDependencies.cmake:57-58`），因此缺失被延后。
- 处置：在 `host_modules` 里加该模块重跑 `build`，或改用 `official`。`qtgrpc` 还额外要求宿主 `protoc`（`Qt6GrpcToolsDependencies.cmake:7` 的 `WrapProtoc`，Qt 包内不含）。

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

1. **Qt**：`qt_version`、ABI、host 来源（official/build）、host 链接方式（shared/static）、skip 项、host 生效模块；
2. **configure 原文**：host 与 target 各一段。执行 configure 时把实际参数数组同步写入 `host-configure.txt`/`target-configure.txt`，`BUILD-INFO.txt` 只读取这两份文件，不是手写近似命令；
3. **工具链**：NDK（含 `source.properties` 的 `Pkg.Revision`）、SDK platform、build-tools、cmdline-tools、JDK、CMake、Ninja、MinGW（`official` 模式标注未安装）、Python、Perl、7-Zip；
4. **运行环境**：runner 名称/OS/架构、镜像版本、CPU 型号与逻辑核数、内存、`GITHUB_WORKSPACE`、`WORK_ROOT`；
5. **时间**：UTC 生成时间 + `T_FETCH`/`T_HOST_*`/`T_GRADLE_PREP`/`T_TARGET_*` 各阶段秒数与分钟数；
6. **产物自检**：`qmake -query QT_VERSION`、`moc --version`、`qsb --version`、`qtpaths -query QT_VERSION`、`androiddeployqt --help` 前 5 行。

编码为 **UTF-8 with BOM**（Windows PowerShell 的 `Set-Content -Encoding utf8`），避免记事本把中文当 ANSI 显示；文件首行也标注了编码。

## 已知限制与未核实项

- **未在本机编译验证**：Qt 6.12 + MinGW 15.1.0 + CMake 4.3.2 的组合以官方版本页为准，是否存在 6.12 特有的配置项差异，需以首轮 CI 结果确认。
- `-no-openssl`：用于避免引入 Android OpenSSL 预编译依赖，代价是 QtNetwork 无 TLS。若需要 HTTPS，应另行构建 OpenSSL 3.5.4 for Android 并改为 `-openssl-linked`。
- 官方版本页（Software 表）列了 Strawberry Perl 5.32.0.1，但 GitHub 上没有该版本便携资产，故用 5.42.2.1。
- `actions/setup-java` 是否可精确拉到 Temurin `21.0.9` 未在本地核实；失败时会回退到同主版本（需改 workflow）。
- 标准 runner 的实际可用磁盘可能因镜像不同而波动；工作流只打印、不强制清理系统目录。
- 全模块构建（把 `skip_modules` 置空）在 4 vCPU / 14 GB 盘上很可能超时或超盘；需 larger runner（如 `windows-latest-8-cores`），或保留较长的 `skip_modules`。
- Gradle 阶段的具体耗时与 `~/.gradle` 实际体积**未实测**：冷启动需下载 Gradle 9.5.1 分发包（140,320,662 字节）+ AGP 9.2.1 及其依赖，推断 3–6 分钟；热缓存下只跑离线校验，推断半分钟以内。`actions/cache` 对 `~/.gradle` 的压缩/解压开销也计入该时间。
- 补丁版场景：`auto` 依赖官方索引已收录该版本；若填入的是尚未发布/商业 LTS 专属的版本，会在探测（`auto`→build）与源码下载处失败，错误信息会指出是“索引 404”还是“源码两处地址都不可用”。
- artifact 为未签名的 Qt 前缀，不含 APK，不含 Android 签名材料。
- artifact 中的 host 前缀已裁剪（`lib\*.a`、`sbom\`、未引用的桌面 exe、`include\`、`doc\`），1,472 MB → 285.1 MB（7z 后 60 MB），只够交叉编译与 `androiddeployqt` 部署；需要桌面 Qt 开发能力时不要用它。
- 默认 `skip_modules` 关闭 `qtgrpc`/`qtserialbus`/`qtscxml`/`qtopcua`/`qtremoteobjects`/`qtactiveqt`/`qtwayland`/`qttasktree`/`qtcoap`/`qtwebchannel` 与 PrintSupport/SpatialAudio；需要其中任一功能时，从默认值里删掉对应 token 重跑（host 侧会随 `auto` 自动把所需模块加回）。
- `build` 模式的 host 白名单有 13 个模块，按默认 `skip_modules` 过滤后实际编 9 个（`qtbase`/`qtsvg`/`qtdeclarative`/`qtshadertools`/`qttools`/`qtquick3d`/`qtquick3dphysics`/`qtquicktimeline`/`qtlottie`）；工程用到白名单外的模块工具时 configure 会失败，需加进 `host_modules` 或用 `official`。
- `host_linkage=static` **未经 CI 验证**：本机只验证了 MinGW `gcc -static` 可用，未编译 Qt。首轮需设 `host_mode=build`、`host_linkage=static`、`host_modules=auto`，确认 host configure 无报错、10 项工具冒烟通过、target configure 能解析 `Qt6*Tools`，并实测前缀体积与 `T_HOST_*` 耗时；失败则保持默认 `shared`。
- `qtgrpc` 的 host 工具依赖宿主 `protoc`（`Qt6GrpcToolsDependencies.cmake:7` 的 `WrapProtoc`，官方 Qt 包内不含）；默认已 `-skip qtgrpc`，不会触发。若从 `skip_modules` 移除 `qtgrpc`，需在工作流安装 protobuf，否则工程 `find_package(Qt6 COMPONENTS Grpc)` 会失败（**未在 CI 实测**）。

## 文件

```
.github/workflows/build-qt-android.yml   # host（official/build/auto）+ target 构建工作流
scripts/fetch-qt-source.ps1             # 下载（md5 校验，official_releases/archive 双地址）/全量解压
scripts/verify-android-prefix.py        # 产物 ABI 与结构校验 + manifest
```
