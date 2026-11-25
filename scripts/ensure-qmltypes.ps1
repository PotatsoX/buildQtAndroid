# 为 install 规则引用但未生成的 .qmltypes 补最小占位文件。
#
# 背景：Qt 6.12.1 + Ninja Multi-Config 下，部分自包含 QML 工具模块（如 qmltime）的
# .qmltypes 生成目标未纳入构建图，install 阶段报
#   file(INSTALL) cannot find ... : File exists
# 其中 "File exists" 只是残留 errno，真实原因是文件不存在。install 脚本里的路径是
# 构建树内的绝对路径，所以这里按同样的路径补文件，install 就能正常复制。
#
# 用法：& "$env:GITHUB_WORKSPACE\scripts\ensure-qmltypes.ps1" -BuildDir $env:BUILD_DIR

param(
    [Parameter(Mandatory = $true)][string]$BuildDir
)

$ErrorActionPreference = 'Stop'

$fixed = 0
$scripts = Get-ChildItem -LiteralPath $BuildDir -Filter 'cmake_install.cmake' -Recurse -File -ErrorAction SilentlyContinue
foreach ($s in $scripts) {
    $content = Get-Content -LiteralPath $s.FullName -Raw -Encoding UTF8
    if ($content -notmatch '\.qmltypes') { continue }
    foreach ($m in [regex]::Matches($content, '"([^"]+\.qmltypes)"')) {
        $p = $m.Groups[1].Value
        if (Test-Path -LiteralPath $p) { continue }
        $dir = Split-Path -Parent $p
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        @('import QtQml', 'Module {', '    name: "QmlTime"', '    isComposite: true', '}') |
            Out-File -FilePath $p -Encoding ascii
        Write-Output "补齐缺失 qmltypes: $p"
        $fixed++
    }
}
Write-Output "qmltypes 占位补齐: $fixed 个"
