#!/usr/bin/env bash
set -e

export PUID=${PUID:-10000}
export PGID=${PGID:-10000}
MUMBLE_CHOWN_DATA=${MUMBLE_CHOWN_DATA:-true}

readonly DATA_DIR="/data"
readonly BARE_BONES_CONFIG_FILE="/etc/mumble/bare_config.ini"
readonly CONFIG_REGEX="^(\;|\#)?\ *([a-zA-Z_0-9.-]+)=.*"
CONFIG_FILE="${DATA_DIR}/mumble_server_config.ini"

readonly SENSITIVE_CONFIGS=(
	"dbPassword"
	"icesecretread"
	"icesecretwrite"
	"serverpassword"
	"registerpassword"
	"sslPassPhrase"
)

# ---------------------------------------------------------------------------
# FCM credentials - resolved before config is written so the decoded path can
# be injected into pushcredentialspath.  Three sources are checked in order:
#
#   1. Docker / Podman secret   /run/secrets/MUMBLE_FCM_CREDENTIALS
#        (preferred for production - credentials never touch the filesystem
#        outside the container and are never part of any image layer)
#
#   2. Base64 env var            MUMBLE_FCM_CREDENTIALS_BASE64
#        (good for CI / Kubernetes - base64-encode the JSON and pass it in)
#
#   3. Legacy file mount         leave pushcredentialspath in your ini / config
#        (still works but requires a host file path)
#
# When source 1 or 2 is used the JSON is written to a tmpfs path
# (/tmp/fcm-credentials.json) and pushcredentialspath is set automatically.
# ---------------------------------------------------------------------------
_FCM_CREDS_RUNTIME="/tmp/fcm-credentials.json"

if [[ -f /run/secrets/MUMBLE_FCM_CREDENTIALS ]]; then
	echo "Reading FCM credentials from container secret"
	cp /run/secrets/MUMBLE_FCM_CREDENTIALS "$_FCM_CREDS_RUNTIME"
	chmod 600 "$_FCM_CREDS_RUNTIME"
elif [[ -n "${MUMBLE_FCM_CREDENTIALS_BASE64:-}" ]]; then
	echo "Decoding FCM credentials from MUMBLE_FCM_CREDENTIALS_BASE64"
	if ! printf '%s' "$MUMBLE_FCM_CREDENTIALS_BASE64" | base64 -d > "$_FCM_CREDS_RUNTIME" 2>/dev/null; then
		>&2 echo "[ERROR] Failed to decode MUMBLE_FCM_CREDENTIALS_BASE64 - is it valid base64?"
		exit 1
	fi
	chmod 600 "$_FCM_CREDS_RUNTIME"
fi

# Ensure the mumble user can read the decoded file when we drop privileges.
if [[ -f "$_FCM_CREDS_RUNTIME" ]] && [[ "$(id -u)" = "0" ]]; then
	chown "${PUID}:${PGID}" "$_FCM_CREDS_RUNTIME" 2>/dev/null || true
fi

# Compile list of configuration options from the bare-bones config
readarray -t existing_config_options < <(sed -En "s/$CONFIG_REGEX/\2/p" "$BARE_BONES_CONFIG_FILE")

# Grab the original command line that is supposed to start the Mumble server
declare -a server_invocation=("${@}")
declare -a used_configs

server_version="$( "${server_invocation[@]}" --version | grep -o "[[:digit:]]\+\.[[:digit:]]\+\.[[:digit:]]\+" )"
if [[ -z "$server_version" ]]; then
	>&2 echo "Failed at obtaining/parsing server version"
	exit 1
fi

echo "Using Mumble server version ${server_version}"

# https://stackoverflow.com/a/5257398
version_components=( ${server_version//./ } )
if [[ ${#version_components[@]} -ne 3 ]]; then
	>&2 echo "Server version doesn't have the expected number of components"
fi

if [[ ${version_components[0]} -gt 1 ]] || [[ ${version_components[1]} -gt 5 ]]; then
	use_legacy_cli_args=false
else
	use_legacy_cli_args=true
fi

normalize_cli_arg() {
	local arg="$1"

	# CLI argument names have changed in 1.6, so if we're using an earlier version
	# we have to back-translate the argument names for things to work out
	if [[ "$use_legacy_cli_args" = "true" ]]; then
		case "$arg" in
			"--foreground")
				arg="-fg"
				;;
			"--verbose")
				arg="-v"
				;;
			"--ini")
				arg="-ini"
				;;
			"--set-su-pw")
				arg="-supw"
				;;
		esac
	fi

	echo "$arg"
}

# To keep the server from detaching
server_invocation+=( "$( normalize_cli_arg "--foreground" )" )

normalize_name() {
	local uppercase="${1^^}"
	local stripped="${uppercase//_/}"
	stripped="${stripped//./}"
	stripped="${stripped//-/}"
	echo "$stripped"
}

# Create an associative array for faster config option lookup
declare -A option_for

for config in "${existing_config_options[@]}"; do
	option_for["$(normalize_name "$config")"]="$config"
done

array_contains() {
	local array_expansion="$1[@]" seeking="$2"
	for element in "${!array_expansion}"; do
		[[ "$element" = "$seeking" ]] && return 0
	done
	return 1
}

set_config() {
	local config_name="$1" config_value="$2" is_default="$3"
	local apply_value=true

	[[ "$is_default" = true ]] && array_contains "used_configs" "$config_name" && \
		apply_value=false # Don't use default value if the user already set one!

	[[ "$apply_value" != true ]] && return 0

	if array_contains "SENSITIVE_CONFIGS" "$config_name"; then
		echo "Setting config \"$config_name\" to: *********"
	else
		echo "Setting config \"$config_name\" to: '$config_value'"
	fi
	used_configs+=("$config_name")

	# Append config to our on-the-fly-built config file
	echo "${config_name}=${config_value}" >> "$CONFIG_FILE"
}

# Drop the user into a shell, if they so wish
if [[ "$1" = "bash" ||  "$1" = "sh" ]]; then
	echo "Dropping into interactive BASH session"
	exec "${@}"
fi

if [[ -f "$MUMBLE_CUSTOM_CONFIG_FILE" ]]; then
	echo "Using manually specified config file at $MUMBLE_CUSTOM_CONFIG_FILE"
	echo "All MUMBLE_CONFIG variables will be ignored"
	CONFIG_FILE="$MUMBLE_CUSTOM_CONFIG_FILE"
else
	# Ensures the config file is empty, starting from a clean slate
	echo -e "# Config file automatically generated from the MUMBLE_CONFIG_* environment variables" > "${CONFIG_FILE}"
	echo -e "# or secrets in /run/secrets/MUMBLE_CONFIG_* files\n" >> "${CONFIG_FILE}"

	# Process settings through variables of format MUMBLE_CONFIG_*

	while IFS='=' read -d '' -r var value; do
		config_option="${option_for[$(normalize_name "$var")]}"

		if [[ -z "$config_option" ]]; then
			if [[ "$MUMBLE_ACCEPT_UNKNOWN_SETTINGS" = true ]]; then
				echo "[WARNING]: Unable to find config corresponding to variable \"$var\". Make sure that it is correctly spelled, using it as-is"
				set_config "$var" "$value"
			else
				>&2 echo "[ERROR]: Unable to find config corresponding to variable \"$var\""
				exit 1
			fi
		else
			set_config "$config_option" "$value"
		fi

	done < <( printenv --null | sed -zn 's/^MUMBLE_CONFIG_//p' )
	# ^ Feeding it in like this, prevents the creation of a subshell for the while-loop

	# Check any docker/podman secrets matching the pattern and set config from there
	while read -r var; do
		config_option="${option_for[$(normalize_name "$var")]}"
		secret_file="/run/secrets/MUMBLE_CONFIG_$var"
		if [[ -z "$config_option" ]]; then
			if [[ "$MUMBLE_ACCEPT_UNKNOWN_SETTINGS" = true ]]; then
				echo "[WARNING]: Unable to find config corresponding to container secret \"$secret_file\". Make sure that it is correctly spelled, using it as-is"
				set_config "$var" "$value"
			else
				>&2 echo "[ERROR]: Unable to find config corresponding to container secret \"$secret_file\""
				exit 1
			fi
		else
			set_config "$config_option" "$(cat $secret_file)"
		fi
	done < <( ls /run/secrets 2> /dev/null | sed -n 's/^MUMBLE_CONFIG_//p' )

	# Apply default settings if they're missing

	# Compatibilty with old DB filename
	OLD_DB_FILE="${DATA_DIR}/murmur.sqlite"
	if [[ -f "$OLD_DB_FILE" ]]; then
		set_config "database" "$OLD_DB_FILE" true
	else
		set_config "database" "${DATA_DIR}/mumble-server.sqlite" true
	fi

	# When FCM credentials were decoded from an env var or secret, auto-set
	# pushcredentialspath so the user doesn't have to configure it manually.
	if [[ -f "$_FCM_CREDS_RUNTIME" ]]; then
		set_config "pushcredentialspath" "$_FCM_CREDS_RUNTIME" true
	fi

	set_config "ice" "\"tcp -h 127.0.0.1 -p 6502\"" true

	if ! array_contains "used_configs" "welcometextfile"; then
		set_config "welcometext" "\"<br />Welcome to this server, running the official Mumble Docker image.<br />Enjoy your stay!<br />\"" true
	fi

	set_config "port" 64738 true
	set_config "users" 100 true

	{ # Add ICE section
		echo -e "\n[Ice]"
		echo "Ice.Warn.UnknownProperties=1"
		echo "Ice.MessageSizeMax=65536"
	} >> "$CONFIG_FILE"
fi

# Additional environment variables

[[ "$MUMBLE_VERBOSE" = true ]] && server_invocation+=( "$( normalize_cli_arg "--verbose" )" )

# Make sure the correct configuration file is used
server_invocation+=( "$( normalize_cli_arg "--ini" )" "${CONFIG_FILE}")

if [[ -f /run/secrets/MUMBLE_SUPERUSER_PASSWORD ]]; then
	MUMBLE_SUPERUSER_PASSWORD="$(cat /run/secrets/MUMBLE_SUPERUSER_PASSWORD)"
	echo "Read superuser password from container secret"
fi

# Set privileges for /data BEFORE the password-setting call so we can drop
# privileges for that call too. Running --set-su-pw as root would otherwise
# emit a flurry of "running murmurd as root", "Failed to set initial/final
# capabilities", and "Failed to set priority limits" warnings, even though
# the long-running server itself runs unprivileged via su-exec below.
if [[ "$(id -u)" = "0" ]] && [[ "${PUID}" != "0" ]] && [[ "${MUMBLE_CHOWN_DATA}" = true ]]; then
	chown -R ${PUID}:${PGID} /data
fi

if [[ -n "${MUMBLE_SUPERUSER_PASSWORD}" ]]; then
	#Variable to change the superuser password
	if [[ "$(id -u)" = "0" ]] && [[ "${PUID}" != "0" ]]; then
		su-exec ${PUID}:${PGID} "${server_invocation[@]}" "$( normalize_cli_arg "--set-su-pw" )" "$MUMBLE_SUPERUSER_PASSWORD"
	else
		"${server_invocation[@]}" "$( normalize_cli_arg "--set-su-pw" )" "$MUMBLE_SUPERUSER_PASSWORD"
	fi
	echo "Successfully configured superuser password"
fi

# Show /data permissions, in case the user needs to match the mount point access
echo "Running Mumble server as uid=${PUID} gid=${PGID}"
echo "\"${DATA_DIR}\" has the following permissions set:"
echo "  $( stat ${DATA_DIR} --printf='%A, owner: \"%U\" (UID: %u), group: \"%G\" (GID: %g)' )"

echo "Command run to start the service : ${server_invocation[*]}"
echo "Starting..."

# Drop privileges (when asked to) if root, otherwise run as current user
if [[ "$(id -u)" = "0" ]] && [[ "${PUID}" != "0" ]]; then
	exec su-exec ${PUID}:${PGID} "${server_invocation[@]}"
else
	exec "${server_invocation[@]}"
fi
