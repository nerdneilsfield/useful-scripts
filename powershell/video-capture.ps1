<#
.SYNOPSIS
    从视频中截取指定间隔的图像。

.DESCRIPTION
    此脚本读取一个视频文件和一个目标文件夹，首先在目标文件夹下创建一个与视频文件名（不含扩展名）同名的文件夹，然后按指定的间隔截取图像，并将图像保存到该文件夹中。

.PARAMETER VideoFile
    要处理的视频文件的路径。

.PARAMETER TargetFolder
    保存截图的目标文件夹的路径。

.PARAMETER IntervalSeconds
    截图的时间间隔（以秒为单位）。默认为 20 秒。

.EXAMPLE
    .\capture.ps1 -VideoFile "C:\path\to\your\video.mp4" -TargetFolder "C:\path\to\your\target\folder"

.EXAMPLE
    .\capture.ps1 -VideoFile "C:\path\to\your\video.mp4" -TargetFolder "C:\path\to\your\target\folder" -IntervalSeconds 30
#>

param(
    [Parameter(Mandatory = $true, HelpMessage = "要处理的视频文件的路径。")]
    [string]$VideoFile,

    [Parameter(Mandatory = $true, HelpMessage = "保存截图的目标文件夹的路径。")]
    [string]$TargetFolder,

    [Parameter(Mandatory = $false, HelpMessage = "截图的时间间隔（以秒为单位）。默认为 20 秒。")]
    [int]$IntervalSeconds = 20,

    [Parameter(Mandatory = $false)]
    [switch]$HardwareAcceleration
)

# 检查 FFmpeg 是否可用
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 FFmpeg。请确保已安装 FFmpeg，并将 ffmpeg.exe 添加到系统环境变量 PATH 中。"
    exit 1
}

# 检查 ffprobe 是否可用
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 ffprobe。请确保已安装 ffprobe，并将 ffprobe.exe 添加到系统环境变量 PATH 中。"
    exit 1
}

# 检查视频文件是否存在
if (-not (Test-Path $VideoFile)) {
    Write-Error "视频文件 '$VideoFile' 不存在。"
    exit 1
}


# 获取视频文件名（不含扩展名）
$VideoName = [System.IO.Path]::GetFileNameWithoutExtension($VideoFile)

# 创建目标文件夹
$TargetFolderPath = Join-Path $TargetFolder $VideoName
Write-Verbose "创建目标文件夹: $TargetFolderPath"
New-Item -ItemType Directory -Path $TargetFolderPath -Force | Out-Null

# 获取视频时长（秒）
Write-Verbose "获取视频时长..."
try {
        $Duration = [double](ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VideoFile")
}
catch {
        Write-Error "获取视频时长失败: $_"
        exit 1
}
Write-Verbose "视频时长: $Duration 秒"

# 计算截图数量
$NumScreenshots = [Math]::Floor([double]$Duration / $IntervalSeconds)
Write-Verbose "截图数量: $NumScreenshots"




# # 循环截图
# for ($i = 0; $i -le $NumScreenshots; $i++) {
#     $Timestamp = [string]($i * $IntervalSeconds)
#     $OutputFile = Join-Path $TargetFolderPath ($VideoName + "_" + $i + ".jpg")

#     Write-Verbose "正在创建截图: $OutputFile"
#     $FFmpegArguments = @('-i', $VideoFile, '-ss', $Timestamp, '-vframes', 1, $OutputFile, '-y')
#     Write-Verbose "FFmpeg 命令: ffmpeg $($FFmpegArguments -join ' ')"

#     # 使用 try...catch 块捕获错误
#     try {
#         $FFmpegProcess = & ffmpeg $FFmpegArguments 2>&1  # 将标准错误重定向到标准输出
#         # if ($FFmpegProcess.ExitCode -ne 0) {
#         #     # 将 $FFmpegProcess 的输出转换为字符串
#         #     $errorMessage = Out-String -InputObject $FFmpegProcess
#         #     throw "FFmpeg 执行失败，退出代码: $($FFmpegProcess.ExitCode)`n错误信息: $errorMessage"
#         # }
#     }
#     catch {
#                 Write-Error $_
#                 exit 1
#     }

#     Write-Progress -Activity "截取视频截图" -Status "正在处理: $VideoFile" -PercentComplete (($i + 1) / ($NumScreenshots + 1) * 100)
#     Write-Host "已保存截图: $OutputFile"
# }

# $FFmpegArguments = @('-i', "$VideoFile", '-vf', "select='not(mod(t\,$IntervalSeconds))'") # 使用时间间隔进行选择
$OutputFilePattern = Join-Path $TargetFolderPath ($VideoName + "_%d.jpg") # 使用 %d 作为序列模式
$FFmpegArguments = @('-i', "$VideoFile", '-vf', "select='not(mod(t\,$IntervalSeconds))'", '-vsync', 0, '-frame_pts', 1, "-q:v", 2, "$OutputFilePattern")
if ($HardwareAcceleration) {
        # 根据你的系统选择合适的硬件加速选项
        # 以下是一些常见选项，请根据你的系统进行调整
        $FFmpegArguments += @('-hwaccel', 'd3d11va') # 或 'cuda', 'vaapi', 'qsv', 'd3d11va', 'videotoolbox' 等
}    

# 循环进行截图
# for ($i = 1; $i -le $NumScreenshots; $i++) {
#     $Timestamp = $IntervalSeconds * $i
#     $OutputFile = Join-Path $TargetFolderPath ($VideoName + "_" + $i + ".jpg")
#     $FFmpegArguments += @('-vsync', 0, '-frame_pts', 1, "-q:v", 2, $OutputFile)
# }

Write-Verbose "FFmpeg 命令: ffmpeg $($FFmpegArguments -join ' ')"

# timing the running time

try {
    $StartTime = Get-Date
    $FFmpegProcess = & ffmpeg $FFmpegArguments 2>&1  # 将标准错误重定向到标准输出
    $EndTime = Get-Date
    $RunningTime = ($EndTime - $StartTime).TotalSeconds
    Write-Host "已成功创建 $($NumScreenshots) 张截图到 '$TargetFolderPath', 共花费 $RunningTime 秒"
}
catch {
    Write-Error  "FFmpeg 执行失败: $_"
    exit 1
}