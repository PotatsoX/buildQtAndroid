# 下载并解压 Qt 全量源码（官方 zip + 7-Zip；保留全部模块，构建范围由 configure 的 -skip 控制）
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$ArchiveDir,
    [Parameter(Mandatory = $true)][string]$SrcRoot
)

$ErrorActionPreference = 'Stop'
$ProgressIntervalSec = 30

$majorMinor = ($Version -split '\.')[0..1] -join '.'
$baseUrl = "https://download.qt.io/official_releases/qt/$majorMinor/$Version"
$archiveName = "qt-everywhere-src-$Version.zip"
$rootName = "qt-everywhere-src-$Version"
$archive = Join-Path $ArchiveDir $archiveName
$root = Join-Path $SrcRoot $rootName

if (-not (Test-Path $archive)) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    $url = "$baseUrl/single/$archiveName"
    Write-Output "下载源码: $url"
    curl.exe -L --fail --retry 5 --retry-delay 10 --retry-all-errors -C - --max-time 2400 -o $archive $url
    if ($LASTEXITCODE -ne 0) { throw "源码下载失败: $url" }
}

# 官方 md5 校验：取 single/md5sums.txt 里 zip 那一行
$md5File = Join-Path $ArchiveDir "md5sums-$Version.txt"
if (-not (Test-Path $md5File)) {
    curl.exe -L --fail --max-time 120 -o $md5File "$baseUrl/single/md5sums.txt"
}
if (Test-Path $md5File) {
    $line = Select-String -Path $md5File -SimpleMatch -Pattern $archiveName | Select-Object -First 1
    if ($line) {
        $expect = ($line.Line -split '\s+')[0].TrimStart('*')
        $actual = (Get-FileHash $archive -Algorithm MD5).Hash.ToLowerInvariant()
        if ($expect -ne $actual) {
            Remove-Item $archive -Force
            throw "源码 md5 校验失败: 期望 $expect，实际 $actual"
        }
        Write-Output "源码 md5 校验通过: $actual"
    } else {
        Write-Warning "md5sums.txt 中没有 $archiveName，跳过校验"
    }
} else {
    Write-Warning "未取到官方 md5sums.txt，跳过校验"
}

New-Item -ItemType Directory -Force -Path $SrcRoot | Out-Null

if (-not (Test-Path (Join-Path $root 'configure.bat'))) {
    # 优先 runner 自带 7-Zip，其次安装步骤写入的 SEVEN_ZIP；都没有才回退 Expand-Archive
    $7z = 'C:\Program Files\7-Zip\7z.exe'
    if (-not (Test-Path $7z) -and $env:SEVEN_ZIP -and (Test-Path $env:SEVEN_ZIP)) { $7z = $env:SEVEN_ZIP }
    Write-Output ("解压源码到 {0}" -f $SrcRoot)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    if (Test-Path $7z) {
        $mt = 4
        if ($env:NUMBER_OF_PROCESSORS) { $mt = [int]$env:NUMBER_OF_PROCESSORS }
        # -bb0 关闭逐文件日志；解压期间无输出，需外部进度
        $proc = Start-Process -FilePath $7z -ArgumentList @('x', $archive, "-o$SrcRoot", '-y', "-mmt=$mt", '-bb0') -NoNewWindow -PassThru
        $sampleShown = $false
        while (-not $proc.HasExited) {
            Start-Sleep -Seconds $ProgressIntervalSec
            if ($proc.HasExited) { break }
            # 顶层目录尚未创建时改数 $SrcRoot，避免路径不存在被静默当成 0 个文件
            $probe = $SrcRoot
            if (Test-Path $root) { $probe = $root }
            $items = @(Get-ChildItem $probe -Recurse -File -ErrorAction SilentlyContinue)
            $bytes = 0
            if ($items.Count -gt 0) {
                $bytes = ($items | Measure-Object -Property Length -Sum).Sum
                if (-not $sampleShown) {
                    $sampleShown = $true
                    $rel = ($items | Select-Object -First 3 | ForEach-Object { $_.FullName.Substring($probe.Length).TrimStart('\') }) -join ', '
                    Write-Output ("  落盘确认: {0} (前 3 个: {1})" -f $probe, $rel)
                }
            }
            $cpuSec = 0
            $wsMB = 0
            try { $cpuSec = [math]::Round($proc.CPU, 1); $wsMB = [math]::Round($proc.WorkingSet64 / 1MB, 0) } catch { }
            Write-Output ("  解压中: {0} 个文件, {1:N2} GB, 7z CPU {2:N1}s, 工作集 {3:N0} MB, 已用 {4:N1} 分钟" -f `
                $items.Count, ($bytes / 1GB), $cpuSec, $wsMB, $sw.Elapsed.TotalMinutes)
        }
        $proc.WaitForExit()
        $sw.Stop()
        if ($proc.ExitCode -gt 1) { throw "源码解压失败: 7z exit=$($proc.ExitCode)" }
        if ($proc.ExitCode -eq 1) { Write-Warning "7z 返回 1：部分文件未解出，继续" }
    } else {
        Write-Warning "未找到 7z.exe（C:\Program Files\7-Zip\7z.exe 与 SEVEN_ZIP），回退 Expand-Archive（单线程，明显更慢）"
        Expand-Archive -Path $archive -DestinationPath $SrcRoot -Force
        $sw.Stop()
    }
    Write-Output ("解压完成: 用时 {0:N1} 分钟" -f $sw.Elapsed.TotalMinutes)
} else {
    Write-Output "源码已存在，跳过解压: $root"
}

$files = @(Get-ChildItem $root -Recurse -File).Count
$srcSize = (Get-ChildItem $root -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Output ("源码就绪: {0} ({1:N0} 个文件, {2:N2} GB)" -f $root, $files, $srcSize)
