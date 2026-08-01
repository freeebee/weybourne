@echo off
REM Start the Weybourne Investment Connector (Windows).
REM
REM   run.bat                        launch the app (or just double-click it)
REM   run.bat --server.port 8600     pass extra flags through to Streamlit
REM   run.bat --setup-only           prepare the environment but don't launch
REM
REM Safe to run as often as you like: the virtual environment and dependencies
REM are only created/installed when missing or out of date.
REM
REM This window stays open on failure so the error is readable - double-clicking
REM a .bat otherwise closes it instantly and takes the message with it.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV=.venv"
set "REQ_COPY=%VENV%\.deps-requirements.txt"
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

REM -- 2. Install dependencies when missing or out of date -------------------- #
REM Decided by two plain checks - is Streamlit importable, and does the
REM requirements file differ from the copy saved at last install. No hashing,
REM so there is no command output to parse and get wrong.
set "NEED_INSTALL=0"

"%PY%" -c "import streamlit" >nul 2>&1
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

REM Confirm it really is installed before trying to launch, so a failure here
REM reports itself rather than surfacing as a confusing error later.
"%PY%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Streamlit did not install correctly.
    echo   Delete the ".venv" folder inside this directory and run this again.
    goto fail
)

REM -- 3. Check the AI backend (a note, never a blocker) ---------------------- #
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

REM -- 4. Launch -------------------------------------------------------------- #
REM "python -m streamlit" rather than streamlit.exe: it works even when the
REM script shim is missing or the PATH is unusual.
echo.
echo Starting the app - your browser will open automatically at
echo http://localhost:8501
echo.
echo Keep this window open while you use the app. Press Ctrl+C to stop.
echo.
"%PY%" -m streamlit run dashboard\Home.py!ARGS!

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
