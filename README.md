# buildQtAndroid

在 **Windows runner** 上从 Qt 源码构建 **Android（arm64-v8a / armeabi-v7a）** 版 Qt（Windows 主机交叉编译），产物为可直接用于 Qt Android 工程交叉编译的 Qt 前缀。

> 本仓库只构建 Qt 库/Qt 前缀，不构建、不签名 APK；APK 打包属于使用方的 `androiddeployqt + Gradle` 流程。

## 结论与定位

- 采用两阶段构建：先构建 **host Qt 工具**（MinGW，提供 `qmake`/`moc`/`rcc`/`qmlimportscanner`/`androiddeployqt`），再用 `-qt-host-path` 交叉编译 **target Qt**（NDK clang，ABI 由输入 `abi` 决定，默认 `arm64-v8a`）。
- 默认参数基线取自参考项目 [yuanpeirong/buildQt](https://github.com/yuanpeirong/buildQt) 的 `buildQt6/build-Qt6mingw64.cmd:33`：全量解压源码 + `-nomake examples -nomake tests` + `-skip qtwebengine`，构建范围靠 configure 参数控制，不删源码。
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
| Perl | 5.42.2.1 | 官方 Software 表列为 strawberry 5.32.0.1；GitHub 上无该版本 portable 资产，沿用参考项目的 5.42.2.1 |

文档冲突说明：`doc.qt.io` 的 *Qt for Android — Building from Source* 页面写的是 MinGW-w64 **13.1**，并明确 **Windows 主机不支持用 MSVC 构建 Qt for Android**。本仓库以 6.12 版本页的 **15.1.0** 为准；“不能用 MSVC”这一点两处一致，因此 host 构建固定 MinGW。

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
| `skip_modules` | `qtwebengine` | 透传给 configure `-skip`，空格分隔；加长即可缩小构建范围（如 `qtwebengine qtpdf qtdoc qttranslations`） |
| `host_only` | `false` | 只构建 host 工具，便于排错 |
| `abi` | `arm64-v8a` | 目标 ABI，可选 `arm64-v8a` / `armeabi-v7a`（官方 CI 对照行用 armv7） |
| `runner` | `windows-2022` | 可换成 larger runner 标签 |

流程步骤：

1. 恢复缓存（源码归档 / host 前缀 / Android SDK+NDK / Gradle home）。
2. 安装固定版本 JDK、Python、MinGW、CMake、Ninja、Perl、7-Zip、Android SDK/NDK。
3. `scripts/fetch-qt-source.ps1` 下载官方 **zip** 归档（md5 校验取自 `md5sums.txt` 的 zip 行），用 7-Zip 多线程**全量解压**；每 30 秒打印已解出文件数、累计字节数、7z 的 CPU 秒数与工作集。
4. **host 构建**：`configure.bat ... -platform win32-g++ -nomake examples -nomake tests -skip <skip_modules>`，安装到 `D:\qt\host`，标记 `.cache-ok` 后删除 build 目录。
5. **Gradle 离线缓存准备**：按 `qtbase/cmake/QtJavaHelpers.cmake` 报错给出的命令调用 `cmake\QtSetupAndroid.cmake`，先把 `Qt6Android` JAR 的 Gradle 依赖填进 `~/.gradle`（已命中则跳过联网）。
6. **target 构建**：`configure.bat ... -qt-host-path D:\qt\host -android-abis <abi> -android-sdk ... -android-ndk ... -no-feature-sql-* -skip <skip_modules>`，安装到 `D:\qt\android_<abi>`。
7. `scripts/verify-android-prefix.py` 校验 ABI/关键库/host 工具，输出 `manifest.json`。
8. 7z 打包并上传 artifact：`qt-<ver>-android-<abi>-windows-host`。

磁盘布局：源码、构建目录与安装前缀放在 **D:**（runner 临时盘）；SDK/NDK/工具装在 **C:**，避免挤占 14 GB 的 D: 盘。

## 模块选择机制

Qt 顶层 `configure` **不做自动选择**：源码树里存在哪个模块目录，就默认纳入构建；`-skip` 只做减法。本项目的控制链是：

1. 全量解压 `qt-everywhere-src`（与参考项目行为一致），源码树保持完整；
2. `configure.bat` 用 `-skip $skip_modules` 与 `-nomake examples -nomake tests` 决定构建范围；
3. 单一来源：工作流输入 `skip_modules` → 环境变量 `QT_SKIP_MODULES` → host/target 两次 configure，脚本只负责下载/解压，不参与模块决策。

为什么不采用「解压后删掉不需要的模块」：configure 要遍历源码树，缺目录会被当作“模块不存在”而直接跳过，删源码并不能省 configure 时间；而删除本身是十几万文件的第二轮写操作（本机实测删除约 667 文件/秒）。要缩小范围就用 `-skip`，不要动源码。

### 默认参数（逐项来源）

| 参数 | 阶段 | 来源 |
|---|---|---|
| `-release`、`-opensource`、`-confirm-license`、`-prefix` | host + target | 参考项目 |
| `-nomake examples`、`-nomake tests` | host + target | 参考项目 |
| `-skip <skip_modules>` | host + target | 参考项目（默认仅 `qtwebengine`） |
| `-platform win32-g++` | 仅 host | 参考项目（Android target 不能带，会覆盖交叉 toolchain） |
| `-qt-zlib`、`-qt-libpng`、`-qt-libjpeg`、`-qt-freetype`、`-qt-harfbuzz` | 仅 host | 参考项目 |
| `-schannel` | 仅 host | 参考项目（Windows TLS 后端；Android 用 OpenSSL/keystore，不适用） |
| `-qt-host-path` | 仅 target | Qt 6 交叉编译必需 |
| `-android-abis`、`-android-sdk`、`-android-ndk` | 仅 target | Qt 6 Android 必需 |
| `-android-javac-source 17`、`-android-javac-target 17` | 仅 target | Qt 6 Android 必需（配套 JDK 21） |
| `-no-openssl` | host + target | 本项目补充（不引入 OpenSSL 依赖） |

不沿用参考项目的项：`-static`、`-static-runtime`（产物是给 `androiddeployqt` 用的共享库 `.so`，静态 Qt 不适用）；`-qt-webp`、`-qt-tiff`、`-qt-pcre`（Qt 6 已无对应捆绑库/选项，**未核实**，保留会有 configure 报 unknown option 的风险）；`-opengl desktop`（Android 走 GLES）。

### 磁盘与时间估算（D: 约 14 GB）

| 源码方案 | 解压后占用 | 文件数 | 解压耗时 |
|---|---|---|---|
| 全量解压（默认，参考项目行为） | 约 1.3–1.5 GB | 约 12–15 万（推断） | 3–8 分钟（推断，zip + 7-Zip 多线程） |
| 选择性解压（仅 4 模块，本仓库旧方案） | 约 0.35 GB | 约 3–4 万（推断） | 3–5 分钟（推断） |

- 构建目录（推断，未实测）：host 6–9 GB、target 8–12 GB；峰值需同时容纳源码 + 构建目录 + 安装前缀，全模块很可能触到 D: 14 GB 上限。
- 时间：4 vCPU 下全模块（仅跳 `qtwebengine`）的 host + target 很可能超过 6 小时。可选办法：换 larger runner，或把 `skip_modules` 加长（只改运行参数，无需改代码）。
- 解压开销构成：每文件一次的实时写入 + 扫描是主因，压缩流解码只占几十秒。工作流因此在装工具前加了 Defender 路径排除（`D:\qt`、`C:\tools`、`C:\android`、workspace），失败不致命。
- 源码归档改用官方 **zip**：实测 604,643,023 字节（旧方案压缩包为 443,394,020 字节，大 36%），但 271 MB/s 下下载只差约 1 秒；换来的是 7-Zip 多线程解压、不必先把整段压缩流解成中转文件，解压路径更短也更少一类失败点。md5 取自官方 `md5sums.txt` 的 zip 行（`64889aee0623311cce096be5f445c7d1`）。
- 缓存策略：源码归档（约 605 MB）、host 前缀（约 1–2 GB）、Android SDK/NDK（约 3 GB）、Gradle home（体积未实测，推断 1–2 GB）；均带版本号 key，避免脏命中。target 构建目录不入缓存（体积大且多数场景下缓存收益低），因此仓库缓存总量控制在 10 GB 限额内。
- ccache/sccache 未启用：Windows + MinGW 下收益与稳定性未验证，host 前缀缓存已覆盖重复构建的主要成本。

## 使用方法

1. 打开仓库 **Actions → build-qt-android → Run workflow**，保持默认参数（`skip_modules=qtwebengine`）后运行；若担心 6 小时上限，在 `skip_modules` 里加长跳过列表。
2. 成功后在该 run 页面下载 artifact；如推送了 `qt-*` tag，还会生成 Release 附件。
3. 使用产物：

```powershell
# 解压后得到 android_<abi> 前缀
cmake -S <your-app> -B build `
  -DCMAKE_TOOLCHAIN_FILE="D:\qt\android_<abi>\lib\cmake\Qt6\qt.toolchain.cmake" `
  -DANDROID_NDK_ROOT="C:\android\ndk\android-ndk-r27c" `
  -DANDROID_SDK_ROOT="C:\android\sdk" `
  -DQT_HOST_PATH="D:\qt\host"
```

> `qt.toolchain.cmake` 在包内写死了 `/opt/android/...` 的默认路径，必须显式传入 `ANDROID_NDK_ROOT`/`ANDROID_SDK_ROOT`，否则配置阶段会报错。

## 验证方式

CI 内的自动校验（`scripts/verify-android-prefix.py`）：

- `lib/*.so` 按所选 ABI 校验：`arm64-v8a` 为 ELF64 / `e_machine=183`，`armeabi-v7a` 为 ELF32 / `e_machine=40`；
- 存在 `libQt6Core*.so` 与 `lib/cmake/Qt6/Qt6Config.cmake`；
- target 前缀中无 `.exe`/`.dll`（host 工具只应存在于 host 前缀）；
- host 前缀存在 `qmake*.exe`、`moc.exe`、`androiddeployqt.exe`；
- 记录 NDK/SDK 实际版本、库清单与 SHA-256 到 `manifest.json`。

本地只做静态校验（YAML 语法、PowerShell/Python 语法）；Qt 编译由 CI 执行。

## 显式关闭的特性（不依赖 runner 预装软件）

GitHub `windows-2022` 镜像预装了大量 SDK。Qt 的 `configure` 对这些 SQL 驱动是 **auto 探测**：找到宿主头文件就编插件。本轮踩坑就是 PostgreSQL：

- 现象：`qtbase/src/plugins/sqldrivers/psql` 的 `QPSQLDriverPlugin_resource.rc` 编译时，MinGW `windres` 传给 `cc1.exe` 的 `-I "C:/Program Files/PostgreSQL/14/include"` 没有引号保护，被空格拆开 → `cc1.exe: fatal error: Files/PostgreSQL/14/include: No such file or directory`，host 构建在 11763/13980 处失败。
- 根因：不是工具链问题，而是“本可关闭、却被宿主环境自动打开”的插件；runner 预装的 PostgreSQL 版本还会漂移（版本页 Software 表写 9.6.16-1，实际命中 `PostgreSQL/14`）。
- 处理：host 与 target 的 `configure` 都显式 `-no-feature-sql-*`，只保留 Qt 自带 bundled 的 `sql-sqlite`。

特征名取自源码 `qtbase/src/plugins/sqldrivers/configure.cmake`（`sql-db2`、`sql-ibase`、`sql-mysql`、`sql-oci`、`sql-odbc`、`sql-psql`、`sql-sqlite`、`sql-mimer`），写法沿用官方 CI 行的 `-no-feature-<name>` 形式（官方行里即 `-no-feature-pkg-config`）。

| 开关 | 阶段 | 理由 |
|---|---|---|
| `-no-feature-sql-psql` | host + target | 命中 runner 预装 PostgreSQL；windres 空格路径直接失败 |
| `-no-feature-sql-mysql` | host + target | runner 预装 MySQL（版本页 Software 表 `MySQL 8.0.36`），同类风险 |
| `-no-feature-sql-odbc` | host + target | 依赖 Windows ODBC 头文件/库，属宿主环境 |
| `-no-feature-sql-oci` | host + target | 源码明确提示 Qt 不支持用 MinGW 编译 Oracle 驱动 |
| `-no-feature-sql-db2` / `-no-feature-sql-ibase` / `-no-feature-sql-mimer` | host + target | 同属外部商业库探测，一并关掉，避免版本漂移 |
| `-no-feature-cups` | host + target | 依赖 `Cups_FOUND`（`src/printsupport/configure.cmake`），宿主装了 CUPS 就会开 |
| `-no-feature-pkg-config` | target | 官方 CI 行原样；避免 pkg-config 把宿主库当成交叉编译依赖 |
| `-no-openssl` | host + target | 不引入宿主 OpenSSL |
| `-qt-zlib` / `-qt-libpng` / `-qt-libjpeg` / `-qt-freetype` / `-qt-harfbuzz` | host | 强制用 Qt 自带副本 |
| `-schannel` | host | Windows TLS 后端 |

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
| CMake / Ninja / JDK / MinGW / 7-Zip / OpenSSL | 4.3.2 / 1.10.2 / 21.0.9 / 15.1.0(posix-seh-msvcrt-rt_v12) / 24.09 / 3.5.4 | 同 | 一致 |
| Python | 3.8.1 | 3.11.9 | 保留：3.8.1 已 EOL，且 setup-python 清单里仅旧补丁版本；Qt 构建脚本两者兼容 |
| Perl (strawberry) | 5.32.0.1 | 5.42.2.1 | 保留：GitHub 上没有 5.32.0.1 的 portable 资产（实测未找到） |
| 平台镜像 | `windows-11_24h2-mingw15` | `windows-2022` | 差异：标准 runner 无该自定义镜像；MinGW 版本已对齐 15.1.0 |
| ABI | `armeabi-v7a` | 输入 `abi`，默认 `arm64-v8a` | 可切换 |
| 其他 configure 参数 | `-release -force-debug-info -qpa android;offscreen -nomake examples -no-feature-pkg-config` | `-release -nomake examples -nomake tests -no-feature-pkg-config` | 已纳入 pkg-config；`-force-debug-info`、`-qpa android;offscreen` 未加（未核实其对产物大小的影响） |

armv7 额外注意：

- 交叉 triple 为 `armv7a-linux-androideabi`，由 `-android-abis armeabi-v7a` 自动选择；产物 `.so` 是 ELF32、`e_machine=40`，`verify-android-prefix.py` 已按 ABI 校验 ELF class 与 machine。
- 资源编译（`windres`/`.rc`）只发生在 **host**（x64 MinGW），与 target ABI 无关，armv7 不涉及 32 位 windres。
- 每种 ABI 是独立构建：`TARGET_PREFIX` 按 ABI 命名（`D:\qt\android_<abi>`），artifact 名也带 ABI；host 前缀与 ABI 无关，缓存 key 不含 ABI。
- minSdk 下限由 Qt 版本决定（具体数值**未核实**）；armv7 只对 32 位旧设备有意义，Google Play 自 2019 年起要求 64 位。

## 与 Fs-scripts 的对照

参考对象 `Fsu0413/Fs-scripts` @ `d22229c`（最后提交 2024-09-30）。它有 Android 配置，但**没有独立的 Android 构建脚本**：配置全在 `Compile/lib/qtCompile/conf.lua` 的 Lua 表里，由 Jenkins 环境变量驱动，仓库 35 个文件中 `java`/`jar`/`gradle` 出现 **0 次**（忽略大小写核对过）。

| 维度 | Fs-scripts | 本仓库 | 判断 |
|---|---|---|---|
| Qt 版本上限 | 6.7.2（另有 6.2.9/6.5.3/5.15.14） | 6.12.0 | 它早于 Qt 的 Gradle 化 jar，**Gradle 这块没有可抄的东西** |
| 工具链来源 | 本机固定路径 `D:\android-sdk-windows-20240205`、`D:\android-ndk-r26d`、OpenJDK **11**、CMake 3.29（`Configuration.lua` L52-79、L392-395） | runner 上 `sdkmanager`/7z 安装，版本钉死 | 它更好（预置即用）；不适配 hosted runner |
| host Qt | 下载 Jenkins 产出的静态 host Qt（`hostToolsUrlwin` L7276），该包用 `-DFEATURE_relocatable=ON` 构建（L6289 段） | 首次自建 host 前缀 + Actions 缓存 | 等价；缓存已覆盖重复构建成本 |
| target 参数 | 直调 CMake：`-DQT_HOST_PATH`、`-DANDROID_ABI=arm64-v8a`、`-DANDROID_PLATFORM=27`、`-DBUILD_qtwebengine=OFF`、`-DFEATURE_icu=OFF`、`-DFEATURE_ssl=ON` + 自建 OpenSSL、`-DMYSQL_INCDIR` 自建 MariaDB | `configure.bat` + `-android-abis` + `-no-feature-sql-*` | 它用"自建依赖"消解宿主机探测，成本更高；我们直接关特性 |
| Gradle / android jar | 无任何处理（0 处 java/jar/gradle） | 预灌 `~/.gradle` + Actions 缓存 | 它的空白正是我们卡住的点，无法照抄 |
| 缓存 | 无 Actions 缓存，靠 Jenkins workspace 持久化 | 4 类 Actions 缓存 | 本仓库更好（CI 场景） |
| 构建期外网依赖 | 内网 Jenkins artifact + 内网源码包 | 仅 GitHub 可达网络 | 环境不同，不构成优劣 |

不采纳的三点及理由：

1. **直调 CMake 取代 `configure.bat`**：Qt 6.12 的 Gradle 校验在 CMake 层，直调一样会触发；还会丢掉 configure 对特性的推导和 `-no-feature-*` 解析。
2. **自建 OpenSSL/MariaDB 再 `-DMYSQL_INCDIR`**：收益只是多一个 sql 驱动，代价是多两个第三方库的交叉编译。
3. **把 host 工具复制进 target 前缀（其 `qt6_deploy_host.sh` 做法）**：它靠正则改写 `Qt6Dependencies.cmake`/`qt.toolchain.cmake` 里的 `HostPrefix`，只对 ≤6.7 验证过；Qt 6.12 的 `Qt6Dependencies.cmake.in` 已无 `__qt_platform_initial_qt_host_path`（本仓库核对，0 命中），照抄不成立。要用需实测，暂记为可选事项。

一处可借鉴但未落地的细节：它对 Android 显式传 `-DCMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH=ON`。该变量默认即为 ON，显式写只是自证，不会改变宿主机探测行为，因此不改。

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

### `Fetch Qt sources` 长时间「解压中: 0 个文件」

进度行给出多个互不依赖的指标，先分清是“没落盘”还是“计数路径不对”：

| 观测 | 含义 | 处理 |
|---|---|---|
| 文件数/GB 为 0，但 `7z CPU` 秒数持续增长 | 7-Zip 正在解压，尚未大量落盘 | 继续等，几分钟内文件数应上涨 |
| 文件数/GB、`7z CPU`、工作集都完全不动 | 7-Zip 真卡住（阻塞在读写或进程异常） | 该步骤重跑；仍不动则先删掉 `D:\qt\src\qt-everywhere-src-<ver>` 再重跑 |
| 出现 `落盘确认: ... (前 3 个: ...)` 但与预期不符 | 落盘位置不对 | 核对 zip 内顶层目录名是否与 `$Version` 一致 |
| 出现 `未找到 7z.exe ... 回退 Expand-Archive` | runner 没有 7-Zip，走了 PowerShell 单线程解压 | 只会更慢（推断 20–40 分钟），不必改脚本 |

`$root`（`D:\qt\src\qt-everywhere-src-<ver>`）与 zip 内顶层目录同名（由同一个 `$Version` 生成），正常应在数秒内出现；脚本在它尚未出现时改数 `D:\qt\src` 本身，因此“路径不存在被静默当成 0 个文件”不再是盲区。

历史备注：早期用另一种单线程流式压缩包直解，曾出现进度长期为 0、整步阻塞的情况；改为官方 zip + 7-Zip 多线程后不再走那条路径。

### target configure 报 `The offline Gradle check failed ...`

日志形如 `QtJavaHelpers.cmake:66 (_qt_internal_verify_gradle_offline_cache)` ← `src/android/jar/CMakeLists.txt:60 (qt_internal_add_jar)`。含义是 `~/.gradle` 里没有 `Qt6Android.jar` 所需依赖，或 `$ANDROID_SDK_ROOT/build-tools/<rev>` 缺失。

| 现象 | 处理 |
|---|---|
| 缓存步骤打印「未命中」后解析成功，但 target configure 仍失败 | 两处的 `GRADLE_BUILD_VARIANT` / `QT_ANDROID_SDK_BUILD_TOOLS_REVISION` 不一致（本工作流两处都用 `Release` + `SDK_BUILD_TOOLS`） |
| 解析步骤报下载失败 | runner 出网问题；日志里已打印 wrapper 属性与 `gradlew --version`，可区分 DNS/代理，还是 JDK 版本不兼容 |
| `Android build-tools 'x' is not installed` | SDK 缓存过期或 `SDK_BUILD_TOOLS` 被改，删掉 `android-*` 缓存后重跑 |

不要用 `QT_ALLOW_DOWNLOAD=ON` 作为长期方案：它跳过校验并把下载推到构建期，构建时间与成功率都依赖 runner 当时的网络。

## 已知限制与未核实项

- **未在本机编译验证**：Qt 6.12 + MinGW 15.1.0 + CMake 4.3.2 的组合以官方版本页为准，是否存在 6.12 特有的配置项差异，需以首轮 CI 结果确认。
- `-no-openssl`：用于避免引入 Android OpenSSL 预编译依赖，代价是 QtNetwork 无 TLS。若需要 HTTPS，应另行构建 OpenSSL 3.5.4 for Android 并改为 `-openssl-linked`。
- 官方版本页（Software 表）列了 Strawberry Perl 5.32.0.1，但 GitHub 上没有该版本便携资产，故用 5.42.2.1。
- `actions/setup-java` 是否可精确拉到 Temurin `21.0.9` 未在本地核实；失败时会回退到同主版本（需改 workflow）。
- 标准 runner 的实际可用磁盘可能因镜像不同而波动；工作流只打印、不强制清理系统目录。
- 全模块构建（仅跳 `qtwebengine`）在 4 vCPU / 14 GB 盘上很可能超时或超盘；需 larger runner（如 `windows-latest-8-cores`）或加长 `skip_modules`。
- Gradle 阶段的具体耗时与 `~/.gradle` 实际体积**未实测**：冷启动需下载 Gradle 9.5.1 分发包（140,320,662 字节）+ AGP 9.2.1 及其依赖，推断 3–6 分钟；热缓存下只跑离线校验，推断半分钟以内。`actions/cache` 对 `~/.gradle` 的压缩/解压开销也计入该时间。
- artifact 为未签名的 Qt 前缀，不含 APK，不含 Android 签名材料。

## 文件

```
.github/workflows/build-qt-android.yml   # 两阶段构建工作流
scripts/fetch-qt-source.ps1             # 下载（md5 校验）/全量解压 Qt 源码
scripts/verify-android-prefix.py        # 产物 ABI 与结构校验 + manifest
```
