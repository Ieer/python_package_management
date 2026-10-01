@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON_EXE="

if exist "%ROOT%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
) else if defined VIRTUAL_ENV (
    if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%P in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    echo [ERROR] Python 3.11 not found. Please setup .venv or install 64-bit Python 3.11.
    pause
    exit /b 1
)

echo ===================================================
echo Running Offline Package System Test Suite
echo Python Interpreter : %PYTHON_EXE%
echo ===================================================
echo.

"%PYTHON_EXE%" -m unittest discover -s "%ROOT%tests" -p "test_offline_*.py" -v
if errorlevel 1 (
    echo.
    echo [FAIL] One or more tests failed.
    pause
    exit /b 1
) else (
    echo.
    echo [PASS] All offline tests passed successfully.
)
endlocal
