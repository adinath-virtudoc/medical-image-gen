@echo off
rem Run the self-test. Double-click this file. It does not install anything or use the network.
cd /d "%~dp0"
set PYTHONUTF8=1
where uv >nul 2>nul
if errorlevel 1 goto nosetup
if not exist .venv goto nosetup
uv run --no-sync python -m medimg selftest %*
set STATUS=%ERRORLEVEL%
if "%STATUS%"=="0" (
    echo Self-test passed.
) else (
    echo The self-test found a problem ^(code %STATUS%^).
)
echo Send both report files named above to the project owner.
pause
exit /b %STATUS%
:nosetup
echo Setup has not been run on this computer yet. Run setup first (double-click setup.bat), then run this again.
pause
exit /b 1
