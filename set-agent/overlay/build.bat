@echo off
rem Build the overlay DLL and injector with MSVC (run from anywhere).
setlocal
set VSWHERE="%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`%VSWHERE% -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VSPATH=%%i
if "%VSPATH%"=="" ( echo Visual Studio Build Tools not found & exit /b 1 )
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
echo === building overlay.dll ===
cl /nologo /LD /EHsc /O2 /MT overlay.cpp /Fe:overlay.dll /link user32.lib gdi32.lib || exit /b 1
echo === building inject.exe ===
cl /nologo /EHsc /O2 /MT inject.cpp /Fe:inject.exe || exit /b 1
echo === done ===
dir /b *.dll *.exe
