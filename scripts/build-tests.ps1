param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -property installationPath
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$output = Join-Path $projectRoot 'build'
$null = New-Item -ItemType Directory -Path $output -Force
$batch = Join-Path $output 'compile-tests.cmd'
@"
@call "$vcvars" >nul
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /utf-8 "$projectRoot\tests\skin_gpu.cpp" /Fe:"$output\skin_gpu.exe" /Fo:"$output\skin_gpu.obj" /link d3d11.lib d3dcompiler.lib
@if errorlevel 1 exit /b %errorlevel%
@cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /utf-8 "$projectRoot\tests\legacy_draw.cpp" /Fe:"$output\legacy_draw.exe" /Fo:"$output\legacy_draw.obj" /link d3dcompiler.lib user32.lib
@exit /b %errorlevel%
"@ | Set-Content -LiteralPath $batch -Encoding utf8
& cmd /d /c $batch
if ($LASTEXITCODE -ne 0) { throw 'GPU fixture compilation failed.' }
