# 用 Nuitka 打包 Uxplorer 为单文件可执行程序。
# 用法：powershell -ExecutionPolicy Bypass -File scripts/nuitka-onefile.ps1
#
# 静态资源集中在 src/uxplorer/resources/，其中 __init__.py 是被编译的
# 模块（Nuitka 拒绝把 .py 当数据文件包含），因此数据文件单独包含：
# qss/ 走 --include-data-dir，rules.db 走 --include-data-file。
# lucide 的图标存于包数据 lucide.zip，由 theme.lucide_icon 按名称字符串
# 在运行时读取，Nuitka 静态分析不可见，需 --include-package-data 显式包含。

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$qssDir = Join-Path $projectRoot 'src\uxplorer\resources\qss'
$rulesDb = Join-Path $projectRoot 'src\uxplorer\resources\rules.db'

if (-not (Test-Path $rulesDb -PathType Leaf)) {
    throw "缺少 $rulesDb，请先运行: uv run scripts/build_rules_db.py"
}
if (-not (Test-Path $qssDir -PathType Container)) {
    throw "缺少 $qssDir"
}

$nuitkaArgs = @(
    '-m', 'nuitka',
    '-m', 'uxplorer',
    '--onefile',
    '--enable-plugin=pyside6',
    # GUI 程序，不弹控制台
    '--windows-console-mode=disable',
    # 静态资源：目标路径必须是包内路径，resources/__init__.py 由此定位
    "--include-data-dir=$qssDir=uxplorer/resources/qss",
    "--include-data-file=$rulesDb=uxplorer/resources/rules.db",
    "--include-package-data=lucide",
    "--output-dir=$(Join-Path $projectRoot 'dist')",
    '--output-filename=Uxplorer.exe',
    '--assume-yes-for-downloads'
)

Write-Host "uv run python $($nuitkaArgs -join ' ')"
Push-Location $projectRoot
try {
    uv run python @nuitkaArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
