@echo off
REM Debug build & run: builds with debug symbols, runs under GDB in batch mode.
REM On crash GDB will automatically print a full backtrace and exit.
REM
REM Usage: dev-debug.bat [--clean]
REM   --clean   Prune the BuildKit CMake cache (full rebuild)

setlocal

set DOCKER_BUILDKIT=1
set MUMBLE_SRC=F:\Dokumente\projekte\mumble_server\mumble-server
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
  -c "rm -f /data/mumble-server.sqlite /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm && chmod 777 /data"

echo.
echo === Initializing database and setting SuperUser password ===
echo.

REM Start the server briefly so it creates the DB + virtual server, then stop it.
docker run -d --rm ^
  --name mumble-debug-init ^
  --privileged ^
  --network none ^
  --entrypoint /usr/bin/mumble-server ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-1ac7faeb7d.json":/data/fcm-credentials.json:ro ^
  mumble-server:debug ^
  --foreground --ini /data/mumble-server.ini

timeout /t 3 /nobreak >nul
docker stop mumble-debug-init 2>nul

REM Set SuperUser password on the freshly created DB.
docker run --rm ^
  --privileged ^
  --network none ^
  --entrypoint /usr/bin/mumble-server ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-1ac7faeb7d.json":/data/fcm-credentials.json:ro ^
  mumble-server:debug ^
  --foreground --ini /data/mumble-server.ini --set-su-pw "mumble123"

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
      -c "chmod 666 /data/mumble-server.sqlite && rm -f /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm"
)

REM Kill any container still holding port 64738 before launching the debug server.
for /f "tokens=*" %%C in ('docker ps -q --filter "publish=64738"') do (
    echo Stopping container %%C which is using port 64738...
    docker stop %%C >nul 2>nul
    docker rm %%C >nul 2>nul
)

echo.
echo === Launching GDB (batch mode — will print stacktrace on crash) ===
echo.

docker run --rm ^
  --name mumble-debug ^
  --privileged ^
  --entrypoint gdb ^
  -p 64738:64738/tcp ^
  -p 64738:64738/udp ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-1ac7faeb7d.json":/data/fcm-credentials.json:ro ^
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
