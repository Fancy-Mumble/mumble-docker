@echo off
REM Build and run a vanilla Mumble 1.6.x server from the official repo.
REM SuperUser password: mumble123

setlocal

set DOCKER_BUILDKIT=1
set SCRIPT_DIR=%~dp0
set IMAGE=mumble-server:vanilla
set CONTAINER=mumble-vanilla

echo.
echo === Building vanilla Mumble 1.6.x server ===
echo.

docker buildx build --load ^
  -f "%SCRIPT_DIR%Dockerfile.vanilla" ^
  -t %IMAGE% ^
  "%SCRIPT_DIR%."

if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    exit /b 1
)

echo.
echo === Replacing container ===
echo.

docker stop %CONTAINER% 2>nul
docker rm %CONTAINER% 2>nul

docker run -d --name %CONTAINER% ^
  -p 64738:64738/tcp ^
  -p 64738:64738/udp ^
  -p 64739:64739/tcp ^
  -v mumble-vanilla-data:/data ^
  %IMAGE%

echo.
echo === Setting SuperUser password ===
echo.
timeout /t 3 /nobreak >nul
docker exec %CONTAINER% /usr/bin/mumble-server --ini /data/mumble_server_config.ini --set-su-pw "mumble123"

echo.
echo === Done! Server running on localhost:64738 ===
echo === SuperUser password: mumble123 ===
echo === Logs: docker logs -f %CONTAINER% ===
