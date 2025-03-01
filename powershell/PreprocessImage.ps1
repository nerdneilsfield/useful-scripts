param (
    [string]$inputFolder = "input",
    [string]$outputFolder = "output",
    [int]$size = 1024,
    [string]$background = "white",  # 背景色
    [int]$quality = 95,            # 输出图片质量
    [switch]$recursive             # 是否递归处理子文件夹
)

Write-Host "输入文件夹: $inputFolder"
Write-Host "输出文件夹: $outputFolder"

# 检查 ImageMagick 是否安装
if (-not (Get-Command magick -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 ImageMagick。请先安装 ImageMagick。"
    exit 1
}

# 创建输出文件夹
if (-not (Test-Path $outputFolder)) {
    New-Item -ItemType Directory -Path $outputFolder | Out-Null
    Write-Host "创建输出文件夹: $outputFolder"
}

# 扩展支持的图片格式
$imageExtensions = @("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.bmp")
$files = @()
if ($recursive) {
    foreach ($ext in $imageExtensions) {
        $files += Get-ChildItem -Recurse -Path $inputFolder -Filter $ext
    }
} else {
    foreach ($ext in $imageExtensions) {
        $files += Get-ChildItem -Path $inputFolder -Filter $ext
    }
}

# 提前计算所有文件的输入输出路径映射
$fileMapping = $files | ForEach-Object {
    $relativePath = if ($inputFolder.EndsWith('\') -or $inputFolder.EndsWith('/')) {
        $_.FullName.Substring($inputFolder.Length)
    } else {
        $_.FullName.Substring($inputFolder.Length + 1)
    }
    
    @{
        File = $_
        OutputPath = Join-Path $outputFolder $relativePath
    }
}

# 创建所有必需的输出目录（去重后一次性创建）
$fileMapping | ForEach-Object { Split-Path $_.OutputPath -Parent } | Select-Object -Unique | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }
}

$total = $fileMapping.Count
$current = 0

Write-Host "共找到 $total 个图片文件需要处理"

foreach ($map in $fileMapping) {
    $current++
    $percent = [math]::Round(($current / $total) * 100, 2)
    
    $file = $map.File
    $outputPath = $map.OutputPath
    
    Write-Progress -Activity "正在处理图片" -Status "$current/$total ($percent%)" -PercentComplete $percent
    Write-Host "正在处理 ($current/$total): $($file.Name)"

    try {
        magick "$($file.FullName)" `
            -filter Lanczos `
            -define filter:lobes=3 `
            -resize "${size}x${size}" `
            -background $background `
            -gravity center `
            -extent "${size}x${size}" `
            -quality $quality `
            "$outputPath"

        Write-Host "成功处理: $($file.Name)" -ForegroundColor Green
    }
    catch {
        Write-Host "处理失败: $($file.Name) - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`n处理完成！共处理了 $total 个图片文件" -ForegroundColor Green
