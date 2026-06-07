@echo off
REM Build & run the Mumble server fuzz harnesses in a container.
REM Thin wrapper around `python -m tools.dev_fuzz` (MUMBLE_SRC comes from .env).
REM
REM Usage:
REM   dev-fuzz.bat list
REM   dev-fuzz.bat rust fileserver_path_validate
REM   dev-fuzz.bat cpp fuzz_opengraph -- -timeout=2
REM   dev-fuzz.bat smoke              (quick CI gate)
REM   dev-fuzz.bat all                (every target, 300s each)
REM   dev-fuzz.bat --rebuild list     (force a fresh image build)

setlocal
pushd "%~dp0"
python -m tools.dev_fuzz %*
set RC=%ERRORLEVEL%
popd
exit /b %RC%
