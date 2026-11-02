# 下载并解压 Qt 全量源码，只保留需要的子模块
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Modules,
    [Parameter(Mandatory = $true)][string]$ArchiveDir,
    [Parameter(Mandatory = $true)][string]$SrcRoot
)

$ErrorActionPreference = 'Stop'

$keep = $Modules.Trim() -split '[\s,]+' | Where-Object { $_ }
if ($keep -notcontains 'qtbase') {
    throw "模块列表必须包含 qtbase，当前: $Modules"
}

$majorMinor = ($Version -split '\.')[0..1] -join '.'
$archiveName = "qt-everywhere-src-$Version.tar.xz"
$archive = Join-Path $ArchiveDir $archiveName

if (-not (Test-Path $archive)) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    $url = "https://download.qt.io/official_releases/qt/$majorMinor/$Version/single/$archiveName"
    Write-Output "下载源码: $url"
    curl.exe -L --fail --retry 5 --retry-delay 10 --max-time 2400 -o $archive $url
    if ($LASTEXITCODE -ne 0) { throw "源码下载失败: $url" }
}

$root = Join-Path $SrcRoot "qt-everywhere-src-$Version"
New-Item -ItemType Directory -Force -Path $SrcRoot | Out-Null

if (-not (Test-Path (Join-Path $root 'configure.bat'))) {
    Write-Output "解压源码到 $SrcRoot"
    tar -xf $archive -C $SrcRoot
    if ($LASTEXITCODE -ne 0) { throw '源码解压失败' }
}

# 缺模块时从缓存归档中补解压
foreach ($module in $keep) {
    if (-not (Test-Path (Join-Path $root $module))) {
        tar -xf $archive -C $SrcRoot "qt-everywhere-src-$Version/$module"
        if ($LASTEXITCODE -ne 0) { throw "补解压失败: $module" }
    }
}

# 删除本次不构建的模块目录，控制磁盘占用
Get-ChildItem $root -Directory |
    Where-Object { $_.Name -like 'qt*' -and $keep -notcontains $_.Name } |
    ForEach-Object {
        Write-Output "裁剪模块: $($_.Name)"
        Remove-Item $_.FullName -Recurse -Force
    }

$srcSize = (Get-ChildItem $root -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Output ("源码就绪: {0} ({1:N2} GB)" -f $root, $srcSize)
