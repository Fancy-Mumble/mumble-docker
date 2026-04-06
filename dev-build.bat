@echo off
REM Fast dev build & deploy script for mumble-server.
REM Uses Dockerfile.dev with BuildKit caching - only recompiles changed C++ files.
REM
REM Usage: dev-build.bat [--clean]
REM   --clean   Prune the BuildKit CMake cache (full rebuild)
REM
REM See also: export-db.bat  — export the live database to a local file
REM           import-db.bat  — import a local database file into the container

setlocal

set DOCKER_BUILDKIT=1
set MUMBLE_SRC=C:\Users\Sebastian\Documents\Projects\Mumble\mumble-server
set SCRIPT_DIR=%~dp0

if "%1"=="--clean" (
    echo Pruning build cache...
    docker builder prune --filter type=exec.cachemount -f
)

echo.
echo === Building mumble-server:dev (incremental) ===
echo.

docker buildx build --load ^
  -f "%SCRIPT_DIR%Dockerfile.dev" ^
  -t mumble-server:dev ^
  --build-context mumble-src="%MUMBLE_SRC%" ^
  "%SCRIPT_DIR%."

if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    exit /b 1
)

echo.
echo === Replacing container ===
echo.

docker stop mumble-pchat 2>nul
docker rm mumble-pchat 2>nul

docker run -d --name mumble-pchat ^
  -p 64738:64738/tcp ^
  -p 64738:64738/udp ^
  -e MUMBLE_CUSTOM_CONFIG_FILE=/data/mumble-server.ini ^
  -v mumble-pchat-data:/data ^
  -v "%SCRIPT_DIR%mumble-server.ini":/data/mumble-server.ini:ro ^
  -v "%SCRIPT_DIR%mumble-5e6fe-firebase-adminsdk-fbsvc-62e68c91e6.json":/data/fcm-credentials.json:ro ^
  mumble-server:dev

echo.
echo === Setting SuperUser password ===
echo.
timeout /t 2 /nobreak >nul
docker exec mumble-pchat /usr/bin/mumble-server --ini /data/mumble-server.ini --set-su-pw "mumble123"

echo.
echo === Done! Server running on localhost:64738 ===
echo === Logs: docker logs -f mumble-pchat ===
echo.
