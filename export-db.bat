@echo off
REM Exports the live mumble-server.sqlite from the running container to the local folder.
REM The server keeps running - SQLite's WAL mode allows safe online backups via the
REM backup API. We use "sqlite3 .backup" inside the container to produce a consistent
REM copy before copying it out.
REM
REM Usage: export-db.bat [output-path]
REM   output-path   Destination file on Windows (default: .\mumble-server.sqlite)

setlocal

set CONTAINER=mumble-pchat
set DB_PATH=/data/mumble-server.sqlite

if "%~1"=="" (
    set OUT=%~dp0db\murmur.sqlite
) else (
    set OUT=%~1
)

REM Check the container is running
docker inspect --format "{{.State.Running}}" %CONTAINER% 2>nul | findstr /i "true" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Container "%CONTAINER%" is not running.
    exit /b 1
)

echo Exporting database from %CONTAINER%:%DB_PATH% ...

REM Use Python's built-in sqlite3.connect().backup() for a consistent online snapshot.
docker exec %CONTAINER% python3 -c "import sqlite3; src=sqlite3.connect('%DB_PATH%'); bk=sqlite3.connect('/tmp/mumble-server-backup.sqlite'); src.backup(bk); bk.close(); src.close()" 2>nul
if %ERRORLEVEL% EQU 0 (
    docker cp %CONTAINER%:/tmp/mumble-server-backup.sqlite "%OUT%"
    docker exec %CONTAINER% rm /tmp/mumble-server-backup.sqlite
    goto :done
)

echo python3 not available, falling back to direct file copy...
REM Copy the main db file. Also grab WAL/SHM sidecars if they exist so a local
REM SQLite tool can reconstruct the full state.
docker cp %CONTAINER%:%DB_PATH% "%OUT%"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Export failed.
    exit /b 1
)
docker cp %CONTAINER%:%DB_PATH%-wal "%OUT%-wal" 2>nul
docker cp %CONTAINER%:%DB_PATH%-shm "%OUT%-shm" 2>nul

:done
echo Done! Database exported to: %OUT%
