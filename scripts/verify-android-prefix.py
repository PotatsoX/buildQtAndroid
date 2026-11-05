#!/usr/bin/env python3
"""校验 Qt for Android 交叉编译前缀，并输出 manifest。"""
import argparse
import hashlib
import io
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

AARCH64 = 183
EM_386 = 3
EM_X86_64 = 62
EM_ARM = 40

# ABI -> (ELF class, e_machine)
EXPECTED_ELF = {
    "arm64-v8a": (2, AARCH64),
    "armeabi-v7a": (1, EM_ARM),
}


def elf_header(path: Path):
    try:
        header = path.open("rb").read(20)
    except OSError:
        return None, None
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return None, None
    return header[4], struct.unpack("<H", header[18:20])[0]


def is_pe(path: Path):
    try:
        with path.open("rb") as f:
            head = f.read(2)
    except OSError:
        return False
    return head == b"MZ"


def find_llvm_readelf(ndk: Path):
    prebuilt = ndk / "toolchains" / "llvm" / "prebuilt"
    if not prebuilt.is_dir():
        return None
    candidates = sorted(prebuilt.glob("*/bin/llvm-readelf*"))
    return candidates[0] if candidates else None


def dynamic_needed(readelf: Path, so: Path):
    """返回 (NEEDED 列表, 错误详情)；执行器不可用时返回 (None, 详情)。"""
    try:
        proc = subprocess.run(
            [str(readelf), "-d", str(so)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        return None, " | ".join(detail[:3])
    return re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", proc.stdout), ""


def read_properties(path: Path):
    props = {}
    if not path.exists():
        return props
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    return props


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_utf8_stdio():
    """把 stdout/stderr 切到 UTF-8，兼容流不可重配（无 reconfigure/无 buffer）的情况。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except (ValueError, OSError):
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(sys, name, io.TextIOWrapper(buffer, encoding="utf-8", errors="replace"))
            except (ValueError, OSError):
                pass


def _emit(text, err=False):
    """输出一行；流仍无法编码时退化为 ASCII 替换，避免 UnicodeEncodeError 中断校验。"""
    stream = sys.stderr if err else sys.stdout
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), file=stream)


def main():
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Verify a cross-compiled Qt for Android prefix and write a manifest."
    )
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--host-prefix", required=True)
    parser.add_argument("--abi", default="arm64-v8a", choices=sorted(EXPECTED_ELF))
    parser.add_argument("--sdk", required=True)
    parser.add_argument("--ndk", required=True)
    parser.add_argument("--qt-version", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    prefix = Path(args.prefix)
    host = Path(args.host_prefix)
    expected_class, expected_machine = EXPECTED_ELF[args.abi]
    errors = []
    warnings = []

    if not prefix.is_dir():
        errors.append(f"target 前缀不存在: {prefix}")

    so_files = sorted(prefix.glob("lib/*.so")) if prefix.is_dir() else []
    if not so_files:
        errors.append("未找到 lib/*.so")
    bad = []
    for so in so_files:
        elf_class, machine = elf_header(so)
        if (elf_class, machine) != (expected_class, expected_machine):
            bad.append(f"{so.name}: class={elf_class} e_machine={machine}")
    if bad:
        errors.append(f"存在非 {args.abi} ELF: " + ", ".join(bad[:5]))

    core = [p for p in so_files if p.name.startswith("libQt6Core") and p.name.endswith(".so")]
    if not core:
        errors.append("缺少 libQt6Core*.so")
    gui = [p for p in so_files if p.name.startswith("libQt6Gui") and p.name.endswith(".so")]
    if not gui:
        warnings.append("缺少 libQt6Gui*.so（若仅构建 qtbase 之外的裁剪集，可忽略）")

    cmake_config = prefix / "lib" / "cmake" / "Qt6" / "Qt6Config.cmake"
    if not cmake_config.exists():
        errors.append("缺少 lib/cmake/Qt6/Qt6Config.cmake")

    target_conf = prefix / "bin" / "target_qt.conf"
    host_prefix_value = None
    if target_conf.exists():
        for line in target_conf.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("HostPrefix"):
                host_prefix_value = line.split("=", 1)[1].strip()
    else:
        warnings.append("缺少 bin/target_qt.conf")

    # target 前缀中不应出现 Windows 可执行文件/动态库；host 若被放进 <target>/host，其 PE 不属于 target 自身
    host_subtree = prefix / "host"
    pe_files = []
    for path in prefix.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".exe", ".dll"):
            continue
        if host_subtree != prefix and host_subtree in path.parents:
            continue
        pe_files.append(path.name)

    # host 前缀必须提供交叉编译所需工具
    host_tools = {}
    for name in ("qmake.exe", "qmake6.exe", "androiddeployqt.exe", "windeployqt.exe"):
        found = list(host.rglob(name))
        if found:
            host_tools[name] = str(found[0].relative_to(host))
    for name in ("moc.exe", "rcc.exe"):
        found = list(host.rglob(name))
        if found:
            host_tools[name] = str(found[0].relative_to(host))
    for required in ("androiddeployqt.exe",):
        if required not in host_tools:
            errors.append(f"host 前缀缺少 {required}")
    if not any(k.startswith("qmake") for k in host_tools):
        errors.append("host 前缀缺少 qmake.exe")
    if "moc.exe" not in host_tools:
        errors.append("host 前缀缺少 moc.exe")

    # 交叉编译必需的 host 信息包（qtbase/cmake/QtPostProcessHelpers.cmake 的 qt_create_hostinfo_package）
    if not (host / "lib" / "cmake" / "Qt6HostInfo" / "Qt6HostInfoConfig.cmake").exists():
        errors.append("host 前缀缺少 lib/cmake/Qt6HostInfo（交叉编译必需）")

    # androiddeployqt 打包 APK 的运行期依赖：Qt6Android.jar 与 Gradle wrapper（均在 target 前缀内）
    if not (prefix / "jar" / "Qt6Android.jar").exists():
        errors.append("缺少 jar/Qt6Android.jar（androiddeployqt 必需）")
    if not (prefix / "src" / "3rdparty" / "gradle" / "gradlew.bat").exists():
        errors.append("缺少 src/3rdparty/gradle/gradlew.bat（androiddeployqt 必需）")

    # SSL 为 runtime 模式：能力必须编进来，但既不能静态链接也不能动态依赖 OpenSSL
    net_cfg = prefix / "include" / "QtNetwork" / "qtnetwork-config.h"
    ssl_feature = None
    ssl_disabled = False
    if net_cfg.is_file():
        cfg_text = net_cfg.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"^#define QT_FEATURE_ssl\s+(-?\d+)", cfg_text, re.MULTILINE)
        ssl_feature = match.group(1) if match else None
        ssl_disabled = bool(re.search(r"^#define QT_NO_SSL\s+1$", cfg_text, re.MULTILINE))
        if ssl_feature != "1":
            errors.append(
                f"QtNetwork SSL feature not enabled: QT_FEATURE_ssl={ssl_feature} ({net_cfg})"
            )
        if ssl_disabled:
            errors.append(f"QtNetwork compiled without SSL: QT_NO_SSL=1 in {net_cfg}")
    else:
        errors.append(f"missing {net_cfg}")

    network_libs = [p for p in so_files if p.name.startswith("libQt6Network")]
    tls_backend = sorted(prefix.glob("plugins/tls/*openssl*"))
    if not tls_backend:
        errors.append("missing plugins/tls/*openssl* backend (runtime SSL not built in)")
    needed_all = []
    if not network_libs:
        errors.append("missing libQt6Network*.so: cannot verify OpenSSL NEEDED entries")
    else:
        readelf = find_llvm_readelf(Path(args.ndk))
        if readelf is None:
            errors.append("llvm-readelf not found in NDK: cannot verify NEEDED entries")
        else:
            for so in network_libs + tls_backend:
                entries, detail = dynamic_needed(readelf, so)
                if entries is None:
                    errors.append(f"llvm-readelf failed on {so.name}: {detail}")
                    continue
                needed_all.extend(entries)
                bad_needed = [e for e in entries if e.startswith(("libssl", "libcrypto"))]
                if bad_needed:
                    errors.append(
                        f"{so.name} links OpenSSL (runtime-only build expected): NEEDED={', '.join(entries)}"
                    )

    # 前缀内不得分发 TLS 库（下游自备）；host 子树同样不应含 .so
    tls_libs = [
        p for p in prefix.rglob("*")
        if p.is_file() and p.suffix.lower() == ".so"
        and (p.name.startswith("libssl") or p.name.startswith("libcrypto"))
    ]
    if tls_libs:
        errors.append(
            "TLS libraries must not be shipped in prefix: "
            + ", ".join(str(p.relative_to(prefix)) for p in tls_libs[:5])
        )

    ndk_props = read_properties(Path(args.ndk) / "source.properties")
    platform_props = read_properties(Path(args.sdk) / "platforms" / "android-37.0" / "source.properties")
    if not platform_props:
        # 兼容 platform 目录名带小版本号
        candidates = sorted((Path(args.sdk) / "platforms").glob("android-3*"))
        if candidates:
            platform_props = read_properties(candidates[-1] / "source.properties")

    libs = []
    for so in so_files:
        libs.append({
            "name": so.name,
            "size": so.stat().st_size,
            "sha256": sha256(so),
            "e_machine": elf_header(so)[1],
        })

    manifest = {
        "qt_version": args.qt_version,
        "abi": args.abi,
        "prefix": str(prefix),
        "host_prefix": str(host),
        "ndk_revision": ndk_props.get("Pkg.Revision"),
        "sdk_platform_api": platform_props.get("AndroidVersion.ApiLevel"),
        "sdk_platform_version": platform_props.get("Pkg.Revision"),
        "target_qt_conf_host_prefix": host_prefix_value,
        "host_tools": host_tools,
        "target_so_count": len(so_files),
        "target_pe_file_count": len(pe_files),
        "target_ssl_feature": ssl_feature,
        "target_ssl_disabled_macro": ssl_disabled,
        "target_network_needed": sorted(set(needed_all)),
        "target_tls_lib_count": len(tls_libs),
        "libs": libs,
        "warnings": warnings,
        "errors": errors,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    _emit(f"ELF check: {len(so_files)} .so files, {args.abi} mismatched {len(bad)}")
    _emit(f"Core libs: {', '.join(p.name for p in core)}")
    _emit(f"Host tools: {json.dumps(host_tools, ensure_ascii=False)}")
    _emit(f"Windows PE files in target prefix: {len(pe_files)}")
    _emit(
        f"SSL: QT_FEATURE_ssl={ssl_feature}, QT_NO_SSL={'1' if ssl_disabled else 'absent'}, "
        f"TLS libs shipped={len(tls_libs)}"
    )
    _emit(f"QtNetwork NEEDED: {', '.join(sorted(set(needed_all))) or 'n/a'}")
    for message in warnings:
        _emit(f"WARN: {message}")
    for message in errors:
        _emit(f"ERROR: {message}", err=True)
    _emit(f"manifest: {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
