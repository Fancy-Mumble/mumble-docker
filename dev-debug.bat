@echo off
REM Debug build & run: builds with debug symbols, runs under GDB in batch mode.
REM On crash GDB will automatically print a full backtrace and exit.
REM
REM Usage: dev-debug.bat [--clean]
REM   --clean   Prune the BuildKit CMake cache (full rebuild)

setlocal

set DOCKER_BUILDKIT=1
if not defined MUMBLE_SRC set MUMBLE_SRC=F:\Dokumente\projekte\mumble_server\mumble-server
set MUMBLE_UID=1000
set MUMBLE_GID=1000
set SCRIPT_DIR=%~dp0

if "%1"=="--clean" (
    echo Pruning build cache...
    docker builder prune --filter type=exec.cachemount -f
)

echo.
echo === Building mumble-server:debug (with debug symbols) ===
echo.

docker buildx build --load ^
  -f "%SCRIPT_DIR%Dockerfile.debug" ^
  -t mumble-server:debug ^
  --build-context mumble-src="%MUMBLE_SRC%" ^
  "%SCRIPT_DIR%."

if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    exit /b 1
)

echo.
echo === Stopping existing debug containers (if any) ===
echo.

docker stop mumble-debug mumble-debug-init mumble-debug-dbcopy 2>nul
docker rm   mumble-debug mumble-debug-init mumble-debug-dbcopy 2>nul

echo.
echo === Setting up data volume ===
echo.

set LOCAL_DB=%SCRIPT_DIR%db\murmur.sqlite

REM Clear stale DB files, fix permissions.
docker run --rm ^
  --entrypoint /bin/sh ^
  -v mumble-pchat-data:/data ^
  mumble-server:debug ^
  -c "rm -rf /data/mumble-server.sqlite /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm /data/fcm-credentials.json && chown -R %MUMBLE_UID%:%MUMBLE_GID% /data && chmod 775 /data"

echo.
echo === Initializing database and setting SuperUser password ===
echo.

REM Start the server briefly so it creates the DB + virtual server, then stop it.
docker run -d --rm ^
  --name mumble-debug-init ^
  --privileged ^
  --user %MUMBLE_UID%:%MUMBLE_GID% ^
  --network none ^
  --entrypoint /usr/bin/mumble-server ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-62e68c91e6.json":/data/fcm-credentials.json:ro ^
  mumble-server:debug ^
  --foreground --ini /data/mumble-server.ini

timeout /t 3 /nobreak >nul
docker stop mumble-debug-init 2>nul

if exist "%LOCAL_DB%" (
    echo.
    echo === Importing database from %LOCAL_DB% (overwriting fresh DB) ===
    echo.

    REM Copy the local DB into the volume via a temporary container.
    docker create --name mumble-debug-dbcopy -v mumble-pchat-data:/data mumble-server:debug /bin/true >nul
    docker cp "%LOCAL_DB%" mumble-debug-dbcopy:/data/mumble-server.sqlite
    docker rm mumble-debug-dbcopy >nul

    REM Fix permissions and clear WAL/SHM so the server can use the DB cleanly.
    docker run --rm --entrypoint /bin/sh -v mumble-pchat-data:/data mumble-server:debug ^
      -c "chown %MUMBLE_UID%:%MUMBLE_GID% /data/mumble-server.sqlite && chmod 664 /data/mumble-server.sqlite && chmod 775 /data && rm -f /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm"
)

REM Set SuperUser password (after any DB import so it is never overwritten).
echo.
echo === Setting SuperUser password ===
echo.

docker run --rm ^
  --privileged ^
  --user %MUMBLE_UID%:%MUMBLE_GID% ^
  --network none ^
  --entrypoint /usr/bin/mumble-server ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-62e68c91e6.json":/data/fcm-credentials.json:ro ^
  mumble-server:debug ^
  --foreground --ini /data/mumble-server.ini --set-su-pw "mumble123"

REM Ensure the file-server storage directory exists and is owned by the server user.
REM (The plugin reads its config from mumble-server.ini via the host's .ini fallback,
REM  so no DB seeding is required.)
docker run --rm --entrypoint /bin/sh -v mumble-pchat-data:/data mumble-server:debug ^
  -c "mkdir -p /data/file-server-storage && chown -R %MUMBLE_UID%:%MUMBLE_GID% /data/file-server-storage && chmod 775 /data/file-server-storage"

REM Ensure DB and directory are writable before launching under GDB.
docker run --rm --entrypoint /bin/sh -v mumble-pchat-data:/data mumble-server:debug ^
  -c "test -f /data/mumble-server.sqlite && chown %MUMBLE_UID%:%MUMBLE_GID% /data/mumble-server.sqlite || true; test -f /data/mumble-server.sqlite && chmod 664 /data/mumble-server.sqlite || true; chown %MUMBLE_UID%:%MUMBLE_GID% /data; chmod 775 /data; rm -f /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm"

REM Kill any container still holding port 64738 before launching the debug server.
for /f "tokens=*" %%C in ('docker ps -q --filter "publish=64738"') do (
    echo Stopping container %%C which is using port 64738...
    docker stop %%C >nul 2>nul
    docker rm %%C >nul 2>nul
)

echo.
echo === Launching GDB (batch mode - will print stacktrace on crash) ===
echo.

docker run --rm ^
  --name mumble-debug ^
  --privileged ^
  --user %MUMBLE_UID%:%MUMBLE_GID% ^
  --entrypoint gdb ^
  -p 64738:64738/tcp ^
  -p 64738:64738/udp ^
  -p 64739:64739/tcp ^
  -p 10000:10000/udp ^
  -e RUST_LOG=mumble_file_server=debug,mumble_plugin_host=debug,info ^
  -e MUMBLE_PLUGIN_LOG=mumble_file_server=debug,mumble_plugin_host=debug,info ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-62e68c91e6.json":/data/fcm-credentials.json:ro ^
  mumble-server:debug ^
  --batch ^
  -ex "set pagination off" ^
  -ex "run" ^
  -ex "thread apply all bt full" ^
  -ex "quit" ^
  --args /usr/bin/mumble-server --foreground --verbose --ini /data/mumble-server.ini

echo.
echo === GDB session ended ===
echo.
