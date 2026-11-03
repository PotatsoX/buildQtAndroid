# buildQtAndroid

在 **Windows runner** 上从 Qt 源码构建 **Android arm64-v8a** 版 Qt（Windows 主机交叉编译），产物为可直接用于 Qt Android 工程交叉编译的 Qt 前缀。

> 本仓库只构建 Qt 库/Qt 前缀，不构建、不签名 APK；APK 打包属于使用方的 `androiddeployqt + Gradle` 流程。

## 结论与定位

- 采用两阶段构建：先构建 **host Qt 工具**（MinGW，提供 `qmake`/`moc`/`rcc`/`qmlimportscanner`/`androiddeployqt`），再用 `-qt-host-path` 交叉编译 **target Qt**（NDK clang，ABI 固定 `arm64-v8a`）。
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
| `qt_version` | `6.12.0` | 源码版本，下载 `qt-everywhere-src-<ver>.zip` |
| `skip_modules` | `qtwebengine` | 透传给 configure `-skip`，空格分隔；加长即可缩小构建范围（如 `qtwebengine qtpdf qtdoc qttranslations`） |
| `host_only` | `false` | 只构建 host 工具，便于排错 |
| `runner` | `windows-2022` | 可换成 larger runner 标签 |

流程步骤：

1. 恢复缓存（源码归档 / host 前缀 / Android SDK+NDK）。
2. 安装固定版本 JDK、Python、MinGW、CMake、Ninja、Perl、7-Zip、Android SDK/NDK。
3. `scripts/fetch-qt-source.ps1` 下载官方 **zip** 归档（md5 校验取自 `md5sums.txt` 的 zip 行），用 7-Zip 多线程**全量解压**；每 30 秒打印已解出文件数、累计字节数、7z 的 CPU 秒数与工作集。
4. **host 构建**：`configure.bat ... -platform win32-g++ -nomake examples -nomake tests -skip <skip_modules>`，安装到 `D:\qt\host`，标记 `.cache-ok` 后删除 build 目录。
5. **target 构建**：`configure.bat ... -qt-host-path D:\qt\host -android-abis arm64-v8a -android-sdk ... -android-ndk ... -skip <skip_modules>`，安装到 `D:\qt\android_arm64_v8a`。
6. `scripts/verify-android-prefix.py` 校验 ABI/关键库/host 工具，输出 `manifest.json`。
7. 7z 打包并上传 artifact：`qt-<ver>-android-arm64-v8a-windows-host`。

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
- 缓存策略：源码归档（约 605 MB）、host 前缀（约 1–2 GB）、Android SDK/NDK（约 3 GB）；均带版本号 key，避免脏命中。target 构建目录不入缓存（体积大且多数场景下缓存收益低），因此仓库缓存总量控制在 10 GB 限额内。
- ccache/sccache 未启用：Windows + MinGW 下收益与稳定性未验证，host 前缀缓存已覆盖重复构建的主要成本。

## 使用方法

1. 打开仓库 **Actions → build-qt-android → Run workflow**，保持默认参数（`skip_modules=qtwebengine`）后运行；若担心 6 小时上限，在 `skip_modules` 里加长跳过列表。
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

## 已知限制与未核实项

- **未在本机编译验证**：Qt 6.12 + MinGW 15.1.0 + CMake 4.3.2 的组合以官方版本页为准，是否存在 6.12 特有的配置项差异，需以首轮 CI 结果确认。
- `-no-openssl`：用于避免引入 Android OpenSSL 预编译依赖，代价是 QtNetwork 无 TLS。若需要 HTTPS，应另行构建 OpenSSL 3.5.4 for Android 并改为 `-openssl-linked`。
- 官方版本页未列 Perl 版本；使用参考项目的 Strawberry Perl 5.42.2.1 便携版。
- `actions/setup-java` 是否可精确拉到 Temurin `21.0.9` 未在本地核实；失败时会回退到同主版本（需改 workflow）。
- 标准 runner 的实际可用磁盘可能因镜像不同而波动；工作流只打印、不强制清理系统目录。
- 全模块构建（仅跳 `qtwebengine`）在 4 vCPU / 14 GB 盘上很可能超时或超盘；需 larger runner（如 `windows-latest-8-cores`）或加长 `skip_modules`。
- artifact 为未签名的 Qt 前缀，不含 APK，不含 Android 签名材料。

## 文件

```
.github/workflows/build-qt-android.yml   # 两阶段构建工作流
scripts/fetch-qt-source.ps1             # 下载（md5 校验）/全量解压 Qt 源码
scripts/verify-android-prefix.py        # 产物 ABI 与结构校验 + manifest
```
