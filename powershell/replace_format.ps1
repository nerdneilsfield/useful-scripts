param (
    #处理文件夹路径
    [string]$folderPath = ""
)

if ($folderPath -eq "") {
    $folderPath = Get-Location
}

# 定义替换的 Map
$replacementMap = @{
    "school" = "JK"
    "vulva" = "bi"
    "pussy" = "bi"
	"vaginal" = "bi"
	"vagina" = "bi"
	"labia" = "yinchun"
	"fuck" = "cao"
	"clitoral" = "yinhe"
	"dildo" = "jiajiba"
	"semen" = "jinye"
	"yinchun minora" = "xiao yinchun"
	"yinchun majora" = "da yinchun"
}

# 获取所有 txt 文件
$files = Get-ChildItem -Path $folderPath -Filter "*.txt" -File

# 循环处理每个文件
foreach ($file in $files) {
    # 读取文件内容
    $content = Get-Content -Path $file.FullName

    # 循环替换 Map 中的每个词
    foreach ($oldWord in $replacementMap.Keys) {
        $newWord = $replacementMap[$oldWord]
        $content = $content -replace $oldWord, $newWord
    }
	
	Write-Host "正在修改 $file.FullName "

    # 将修改后的内容写回文件
    $content | Set-Content -Path $file.FullName -Encoding UTF8
}

Write-Host "替换完成！"