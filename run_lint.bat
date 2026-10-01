@echo off
setlocal

set "ROOT=%~dp0"
set "RUFF_EXE=%ROOT%.venv\Scripts\ruff.exe"

if not exist "%RUFF_EXE%" (
    echo [ERROR] Ruff is not installed in the workspace .venv.
    echo Install development tools offline with:
    echo   .\.venv\Scripts\python.exe -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-dev.txt
    exit /b 1
)

pushd "%ROOT%"
"%RUFF_EXE%" check .
set "LINT_EXIT=%ERRORLEVEL%"
popd
if not "%LINT_EXIT%"=="0" (
    echo.
    echo [FAIL] Ruff checks found issues.
    exit /b %LINT_EXIT%
)

echo [PASS] Ruff checks passed.
endlocal
