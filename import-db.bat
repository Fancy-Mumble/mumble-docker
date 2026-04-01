@echo off
REM Imports a local sqlite DB into the mumble-pchat-data Docker volume.
REM If a mumble server container is running, it is stopped first and restarted after.
REM
REM Usage: import-db.bat [source-path]
REM   source-path   Local .sqlite file to import (default: db\murmur.sqlite)

setlocal

set VOLUME=mumble-pchat-data
set DB_PATH=/data/mumble-server.sqlite

if "%~1"=="" (
    set SRC=%~dp0db\murmur.sqlite
) else (
    set SRC=%~1
)

if not exist "%SRC%" (
    echo [ERROR] Source file not found: %SRC%
    exit /b 1
)

REM Stop any running containers that use this volume.
for /f "tokens=*" %%C in ('docker ps -q --filter "volume=%VOLUME%"') do (
    echo Stopping container %%C ...
    docker stop %%C >nul
)

echo Importing "%SRC%" into volume %VOLUME% at %DB_PATH% ...

REM Use a temporary container to mount the volume and copy the file in.
docker create --name mumble-import-tmp -v %VOLUME%:/data mumble-server:debug /bin/true >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    REM Fallback: try with a minimal image if debug image isn't available.
    docker create --name mumble-import-tmp -v %VOLUME%:/data alpine /bin/true >nul
)

docker cp "%SRC%" mumble-import-tmp:%DB_PATH%
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Import failed.
    docker rm mumble-import-tmp >nul 2>nul
    exit /b 1
)
docker rm mumble-import-tmp >nul

REM Fix permissions and clear stale WAL/SHM files.
docker run --rm --entrypoint /bin/sh -v %VOLUME%:/data alpine ^
  -c "chmod 666 '%DB_PATH%' && rm -f '%DB_PATH%-wal' '%DB_PATH%-shm'"

echo Done! Database imported from: %SRC%
