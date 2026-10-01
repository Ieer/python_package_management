@echo off
setlocal

set "ROOT=%~dp0"
set "PACKAGE_DIR=%ROOT%package311"
set "REQUIREMENTS=%ROOT%pwistron.txt"
set "UV_VERSION=0.12.11"
set "PYTHON_EXE="

if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%P in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    echo Python 3.11 was not found. Install Python 3.11 or activate its virtual environment first.
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 (
    echo The selected interpreter must be 64-bit Python 3.11: %PYTHON_EXE%
    exit /b 1
)

if not exist "%PACKAGE_DIR%\uv-%UV_VERSION%-py3-none-win_amd64.whl" (
    echo Required local uv wheel not found: %PACKAGE_DIR%\uv-%UV_VERSION%-py3-none-win_amd64.whl
    exit /b 1
)
if not exist "%PACKAGE_DIR%\ms-playwright.zip" (
    echo Required browser archive not found: %PACKAGE_DIR%\ms-playwright.zip
    exit /b 1
)

for %%I in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpI"
if defined VIRTUAL_ENV (
    set "UV_CACHE_DIR=%VIRTUAL_ENV%\.uv-cache"
) else (
    set "UV_CACHE_DIR=%PYTHON_DIR%\.uv-cache"
)
set "UV_EXE=%PYTHON_DIR%uv.exe"
echo Selected Python: "%PYTHON_EXE%"
echo Expected uv executable: "%UV_EXE%"

if not exist "%UV_EXE%" (
    echo Bootstrapping uv %UV_VERSION% from the local wheelhouse...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check --no-index --find-links "%PACKAGE_DIR%" "uv==%UV_VERSION%"
    if errorlevel 1 (
        echo Failed to bootstrap uv from the local wheelhouse.
        exit /b 1
    )
)

if not exist "%UV_EXE%" (
    echo uv.exe was not found beside the selected Python installation.
    exit /b 1
)

echo Installing requirements into %PYTHON_EXE% using the local wheelhouse...
"%UV_EXE%" pip install --offline --no-config --find-links "%PACKAGE_DIR%" --python "%PYTHON_EXE%" -r "%REQUIREMENTS%"
if errorlevel 1 (
    echo Offline uv installation failed.
    exit /b 1
)

"%UV_EXE%" pip check --python "%PYTHON_EXE%"
if errorlevel 1 (
    echo Installed packages have dependency conflicts.
    exit /b 1
)

echo Extracting the local Playwright browser archive to %LOCALAPPDATA%...
"%PYTHON_EXE%" -c "import sys, zipfile; z=zipfile.ZipFile(sys.argv[1]); z.extractall(sys.argv[2]); z.close()" "%PACKAGE_DIR%\ms-playwright.zip" "%LOCALAPPDATA%"
if errorlevel 1 (
    echo Failed to extract the Playwright browser archive.
    exit /b 1
)

echo Offline uv installation, dependency check, and browser extraction completed successfully.
exit /b 0