@echo off
REM Start the Weybourne Investment Connector (Windows).
REM React front-end + FastAPI backend at http://localhost:8000
REM
REM   run.bat                launch the app (or just double-click it)
REM   run.bat --setup-only   prepare the environment but don't launch
REM   run.bat --dev          also start the Vite dev server (hot reload, :5173)
REM
REM Safe to run as often as you like: the virtual environment, dependencies and
REM front-end build are only created/refreshed when missing or out of date.
REM
REM This window stays open on failure so the error is readable.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV=.venv"
set "REQ_COPY=%VENV%\.deps-requirements.txt"
set "SETUP_ONLY=0"
set "DEV=0"

:parse_args
if "%~1"=="" goto args_done
if "%~1"=="--setup-only" set "SETUP_ONLY=1"
if "%~1"=="--dev" set "DEV=1"
shift
goto parse_args
:args_done

REM -- 1. Find a suitable Python and build the environment -------------------- #
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
        echo   Could not find Python 3.10 or newer.
        echo.
        echo   Install it from https://python.org
        echo   IMPORTANT: tick "Add Python to PATH" on the first installer screen.
        echo   Then close this window, reopen the folder, and run this again.
        goto fail
    )

    echo Creating the virtual environment ^(one-off, about 10 seconds^)...
    !PYTHON! -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo   Could not create the virtual environment.
        goto fail
    )
)

set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo.
    echo   The virtual environment looks incomplete.
    echo   Delete the ".venv" folder inside this directory, then run this again.
    goto fail
)

REM -- 2. Install Python dependencies when missing or out of date ------------- #
set "NEED_INSTALL=0"

"%PY%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 set "NEED_INSTALL=1"

if not exist "%REQ_COPY%" set "NEED_INSTALL=1"
if exist "%REQ_COPY%" (
    fc /b requirements.txt "%REQ_COPY%" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "!NEED_INSTALL!"=="1" (
    echo.
    echo Installing dependencies. This takes a minute or two the first time -
    echo the scrolling text below is normal.
    echo.
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   Installing the dependencies failed - the reason is in the text above.
        echo   A re-run often fixes a temporary network problem.
        goto fail
    )
    copy /y requirements.txt "%REQ_COPY%" >nul
)

"%PY%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   The backend did not install correctly.
    echo   Delete the ".venv" folder inside this directory and run this again.
    goto fail
)

REM -- 3. Front-end: install + build when missing ----------------------------- #
where npm >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Could not find npm ^(Node.js^). Install the LTS version from
    echo   https://nodejs.org then run this again.
    goto fail
)

if not exist "web\node_modules" (
    echo Installing front-end dependencies...
    pushd web
    call npm install --no-audit --no-fund
    if errorlevel 1 (popd & goto fail)
    popd
)
if not exist "web\dist\index.html" (
    echo Building the front-end...
    pushd web
    call npm run build
    if errorlevel 1 (popd & goto fail)
    popd
)

REM -- 4. Check the AI backend (a note, never a blocker) ---------------------- #
where claude >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Note: Claude Code is not installed, so the AI features ^(triage,
    echo   screening, drafting^) will be unavailable. Everything else still
    echo   works on sample data. See https://claude.com/claude-code
)

if "%SETUP_ONLY%"=="1" (
    echo.
    echo Environment ready. Run this again to start the app.
    echo.
    pause
    exit /b 0
)

if "%DEV%"=="1" (
    start "Vite dev server" cmd /k "cd /d %~dp0web && npm run dev"
)

REM -- 5. Launch -------------------------------------------------------------- #
REM A previous instance (or a crashed one) may still hold port 8000 - free it
REM so a double-click always works. Only python processes are touched.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    tasklist /fi "PID eq %%p" 2>nul | findstr /i "python uvicorn" >nul && taskkill /PID %%p /F >nul 2>&1
)

echo.
echo Starting the app - your browser will open automatically at
echo http://localhost:8000
echo.
echo Keep this window open while you use the app. Press Ctrl+C to stop.
echo.
start "" http://localhost:8000
"%PY%" -m uvicorn api.main:app --port 8000

echo.
echo The app has stopped.
pause
exit /b 0

:fail
echo.
echo ---------------------------------------------------------------
echo Press any key to close this window.
pause >nul
exit /b 1
