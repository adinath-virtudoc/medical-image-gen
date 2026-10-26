@echo off
rem Check this computer. Double-click this file or run it from a terminal.
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
    echo Installing uv, the tool that manages Python for this app...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 goto :fail
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uv run python -m medimg assess %*
if errorlevel 1 goto :fail
exit /b 0
:fail
echo.
echo Stopped with an error. Read the message above.
pause
exit /b 1
