@echo off
setlocal
pushd "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "BikeRideHUD.py" %*
) else (
    python "BikeRideHUD.py" %*
)

set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
    echo BikeRideHUD exited with code %APP_EXIT_CODE%.
    echo Startup output is shown above. Press any key to close this window.
    pause >nul
)

popd
exit /b %APP_EXIT_CODE%
