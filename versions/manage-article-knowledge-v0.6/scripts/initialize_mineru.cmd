@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0initialize_mineru.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo MinerU initialization finished successfully.
) else (
  echo MinerU initialization did not finish. Review the message above.
)
pause
exit /b %EXIT_CODE%
