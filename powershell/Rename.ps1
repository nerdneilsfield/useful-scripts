param (
    # if not set, use the current folder
    [string]$folderPath = ""
)

if ($folderPath -eq "") {
    $folderPath = Get-Location
}

# 定义支持的图片格式
$imageExtensions = @("*.jpg", "*.jpeg", "*.png", "*.gif", "*.bmp", "*.tiff", "*.webp", "*.heic")

# 获取所有图片文件
$imageFiles = @()
foreach ($ext in $imageExtensions) {
    $imageFiles += Get-ChildItem -Path $folderPath -Filter $ext
}

# 如果没有找到图片文件，退出脚本
if ($imageFiles.Count -eq 0) {
    Write-Host "当前目录下没有找到图片文件。" -ForegroundColor Yellow
    exit
}

Write-Host "找到 $($imageFiles.Count) 个图片文件需要重命名。" -ForegroundColor Cyan

# 对文件按照创建时间排序
$sortedFiles = $imageFiles | Sort-Object CreationTime

# 计算需要的位数（例如：如果有100张图片，需要3位数）
$digits = [Math]::Max(4, [Math]::Ceiling([Math]::Log10($sortedFiles.Count + 1)))

# 创建计数器
$counter = 0

# 重命名文件
foreach ($file in $sortedFiles) {
    $counter++
    
    # 创建新文件名（保持原始扩展名）
    $newName = "{0:D$digits}{1}" -f $counter, $file.Extension
    
    # 检查新文件名是否已存在
    if (Test-Path $newName) {
        Write-Host "警告: $newName 已存在，跳过重命名 $($file.Name)" -ForegroundColor Yellow
        continue
    }
    
    try {
        # 重命名文件
        Rename-Item -Path $file.FullName -NewName $newName -ErrorAction Stop
        Write-Host "已重命名: $($file.Name) -> $newName" -ForegroundColor Green
    }
    catch {
        Write-Host "重命名失败: $($file.Name)" -ForegroundColor Red
        Write-Host "错误信息: $_" -ForegroundColor Red
    }
}

Write-Host "`n重命名完成！" -ForegroundColor Cyan