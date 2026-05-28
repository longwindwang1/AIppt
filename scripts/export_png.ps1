# 把 PPTX 导成 PNG（headless，不弹 PowerPoint 窗口）
# 用法： .\scripts\export_png.ps1 path\to\deck.pptx out_dir

param(
    [Parameter(Mandatory=$true)][string]$PptxPath,
    [Parameter(Mandatory=$true)][string]$OutDir
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ppt = New-Object -ComObject PowerPoint.Application
# msoFalse = headless / 后台跑
$ppt.Visible = [Microsoft.Office.Core.MsoTriState]::msoFalse
try {
    $pres = $ppt.Presentations.Open($PptxPath, $false, $false, $false)
    $pres.Export($OutDir, "PNG", 1280, 720)
    $pres.Close()
    Write-Output "Exported $(Get-ChildItem $OutDir -Filter *.png | Measure-Object | Select-Object -ExpandProperty Count) PNGs to $OutDir"
} finally {
    $ppt.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
