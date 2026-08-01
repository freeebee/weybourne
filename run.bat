@echo off
REM Start the Weybourne Investment Connector (Windows).
REM
REM   run.bat                        launch the app
REM   run.bat --server.port 8600     pass extra flags through to Streamlit
REM   run.bat --setup-only           prepare the environment but don't launch
REM
REM Safe to run as often as you like: the virtual environment and dependencies
REM are only created/installed when missing or out of date.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV=.venv"
set "STAMP=%VENV%\.deps-installed"
set "SETUP_ONLY=0"
set "ARGS="

REM -- collect args, pulling out --setup-only -------------------------------- #
:parse_args
if "%~1"=="" goto args_done
if "%~1"=="--setup-only" (
    set "SETUP_ONLY=1"
) else (
    set "ARGS=!ARGS! %~1"
)
shift
goto parse_args
:args_done

REM -- 1. Find a suitable Python --------------------------------------------- #
if not exist "%VENV%\Scripts\python.exe" (
    set "PYTHON="
    for %%p in (py python3 python) do (
        if not defined PYTHON (
            %%p -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
            if !errorlevel! equ 0 set "PYTHON=%%p"
        )
    )
    if not defined PYTHON (
        echo.
        echo Could not find Python 3.10 or newer.
        echo.
        echo   Install it from https://python.org
        echo   IMPORTANT: tick "Add Python to PATH" during installation.
        echo.
        echo Then run run.bat again.
        exit /b 1
    )

    echo Creating the virtual environment ^(one-off, ~10 seconds^)...
    !PYTHON! -m venv "%VENV%"
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        exit /b 1
    )
)

set "PY=%VENV%\Scripts\python.exe"

REM -- 2. Install dependencies only when they've changed ---------------------- #
REM Hash via Python rather than certutil: no output parsing to get wrong.
set "WANT="
for /f "delims=" %%h in ('""%PY%" -c "import hashlib;print(hashlib.sha1(open('requirements.txt','rb').read()).hexdigest())""') do set "WANT=%%h"

set "HAVE="
if exist "%STAMP%" set /p HAVE=<"%STAMP%"

if not "!WANT!"=="!HAVE!" (
    echo Installing dependencies ^(one-off, a minute or two^)...
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency installation failed. Scroll up for the reason -
        echo a re-run often fixes a transient network error.
        exit /b 1
    )
    > "%STAMP%" echo !WANT!
)

REM -- 3. Check the AI backend (warning only) --------------------------------- #
where claude >nul 2>&1
if errorlevel 1 (
    echo.
    echo Note: Claude Code isn't installed, so AI features ^(triage, screening,
    echo       drafting^) will be unavailable. Everything else still works on
    echo       sample data. Install it from https://claude.com/claude-code
    echo.
)

if "%SETUP_ONLY%"=="1" (
    echo Environment ready. Run run.bat to start the app.
    exit /b 0
)

REM -- 4. Launch -------------------------------------------------------------- #
echo Starting the app - your browser will open automatically.
echo    ^(press Ctrl+C here to stop it^)
echo.
"%VENV%\Scripts\streamlit.exe" run dashboard\Home.py!ARGS!
