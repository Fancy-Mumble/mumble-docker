FROM ubuntu:24.04 AS base

ADD ./scripts/* /mumble/scripts/
WORKDIR /mumble/scripts

ARG DEBIAN_FRONTEND=noninteractive
ARG MUMBLE_VERSION=latest

RUN sed -i 's|http://security.ubuntu.com|http://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
  && apt-get -o Acquire::Check-Date=false update && apt-get install --no-install-recommends -y \
  ca-certificates \
  libavahi-compat-libdnssd1 \
  libcap2 \
  libqt6core6t64 \
  libqt6dbus6t64 \
  libqt6gui6t64 \
  libqt6network6t64 \
  libqt6sql6t64 \
  libqt6sql6-sqlite \
  libqt6xml6t64 \
  libzeroc-ice3.7t64 \
  '^libprotobuf[0-9]+t?64?$' \
  libsqlite3-0 \
  '^libmysqlclient[0-9]+$' \
  libpq5 \
  '^libpocofoundation[0-9]+t?64?$' \
  '^libpocodata[0-9]+t?64?$' \
  '^libpocojson[0-9]+t?64?$' \
  '^libpocoxml[0-9]+t?64?$' \
  '^libpoconet[0-9]+t?64?$' \
  '^libpoconetssl[0-9]+t?64?$' \
  '^libpococrypto[0-9]+t?64?$' \
  '^libpocojwt[0-9]+t?64?$' \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /data



# Clone the mumble-server source tree (shared by plugin-host-build, sfu-build,
# and the C++ build stage so the clone happens exactly once).
FROM ubuntu:24.04 AS mumble-src
ARG DEBIAN_FRONTEND=noninteractive

ADD ./scripts/* /mumble/scripts/
RUN apt-get update && apt-get install --no-install-recommends -y \
  ca-certificates curl git \
  && rm -rf /var/lib/apt/lists/*

ARG MUMBLE_VERSION=latest
# Source repository / branch to build from.  Defaults to the Fancy Mumble
# server fork.  Override with --build-arg MUMBLE_GIT_REPO=... /
# MUMBLE_GIT_BRANCH=... to build from a different fork or upstream.
ARG MUMBLE_GIT_REPO=https://github.com/Fancy-Mumble/mumble-server
ARG MUMBLE_GIT_BRANCH=1.6.x
ENV MUMBLE_GIT_REPO=${MUMBLE_GIT_REPO}
ENV MUMBLE_GIT_BRANCH=${MUMBLE_GIT_BRANCH}

WORKDIR /mumble/scripts
ARG CACHE_BUST
RUN /mumble/scripts/clone.sh


# Build the Rust mumble-plugin-host cdylib and the bundled dynamic plugins
# (file-server, live-doc) in isolation so the Rust toolchain is not needed
# inside the C++ build stage.
# Build the file-server web frontend (React + MUI -> single-file password.html)
# ONCE, on the native build platform. The output is static, architecture-
# independent HTML, so it must NOT be built under per-target emulation: NodeSource
# publishes no armhf packages, which breaks the linux/arm/v7 leg of the matrix.
# Pinning to $BUILDPLATFORM also avoids emulating Node for every target arch.
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS fileserver-web-build
COPY --from=mumble-src /mumble/repo/3rdparty/mumble-plugin-host/file-server/web /web
WORKDIR /web
RUN npm ci && npm run build


FROM ubuntu:24.04 AS plugin-host-build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install --no-install-recommends -y \
  curl ca-certificates build-essential pkg-config libssl-dev \
  && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"
# Disable incremental compilation to significantly reduce disk usage during
# multi-platform CI builds (each platform builds in parallel, and incremental
# artifacts can exhaust the runner's available disk space).
ENV CARGO_INCREMENTAL=0
COPY --from=mumble-src /mumble/repo/3rdparty/mumble-plugin-host /plugin-host
WORKDIR /plugin-host
# Drop in the pre-built, architecture-independent web artifact (password.html,
# embedded by the crate via include_str!) from the native-platform web build.
# MUMBLE_FILESERVER_SKIP_WEB_BUILD tells the crate's build.rs to reuse it instead
# of invoking npm (which is not installed in this per-target stage).
COPY --from=fileserver-web-build /web/dist /plugin-host/file-server/web/dist
ENV MUMBLE_FILESERVER_SKIP_WEB_BUILD=1
# wasmtime's cranelift JIT backend has no 32-bit ARM ISA, so the WASM plugin host
# cannot compile for armv7 (TARGETARCH=arm). On that arch only, build the host
# WITHOUT the wasm-plugins feature: native cdylib plugins still load and the C ABI
# is unchanged (no extern "C" export is feature-gated), but WASM component plugins
# are unavailable. The plugin crates depend only on mumble-plugin-api (never on
# the host), so they build identically on every arch.
ARG TARGETARCH
RUN set -eux; \
    if [ "${TARGETARCH}" = "arm" ]; then \
      cargo build --release --no-default-features -p mumble-plugin-host; \
      cargo build --release -p mumble-file-server -p mumble-live-doc -p mumble-link-preview -p mumble-calendar -p mumble-friends -p mumble-audit; \
    else \
      cargo build --release \
        -p mumble-plugin-host \
        -p mumble-file-server \
        -p mumble-live-doc \
        -p mumble-link-preview \
        -p mumble-calendar \
        -p mumble-friends \
        -p mumble-audit; \
    fi; \
    strip target/release/libmumble_plugin_host.so \
          target/release/libmumble_file_server.so \
          target/release/libmumble_live_doc.so \
          target/release/libmumble_link_preview.so \
          target/release/libmumble_calendar.so \
          target/release/libmumble_friends.so \
          target/release/libmumble_audit.so; \
    mkdir -p /plugin-host/plugins; \
    cp target/release/libmumble_file_server.so /plugin-host/plugins/; \
    cp target/release/libmumble_live_doc.so   /plugin-host/plugins/; \
    cp target/release/libmumble_link_preview.so /plugin-host/plugins/; \
    cp target/release/libmumble_calendar.so /plugin-host/plugins/; \
    cp target/release/libmumble_friends.so /plugin-host/plugins/; \
    cp target/release/libmumble_audit.so /plugin-host/plugins/


FROM base AS build
ARG DEBIAN_FRONTEND=noninteractive

ADD ./scripts/* /mumble/scripts/
WORKDIR /mumble/repo

RUN apt-get -o Acquire::Check-Date=false update && apt-get install --no-install-recommends -y \
  build-essential \
  ca-certificates \
  cmake \
  curl \
  ninja-build \
  gdb \
  git \
  libavahi-compat-libdnssd-dev \
  libboost-dev \
  libcap-dev \
  libprotoc-dev \
  libprotobuf-dev \
  libssl-dev \
  libxi-dev \
  libzeroc-ice-dev \
  libsqlite3-dev \
  libmysqlclient-dev \
  libpq-dev \
  libpoco-dev \
  pkg-config \
  protobuf-compiler \
  python3 \
  qt6-base-dev \
  qt6-tools-dev \
  qt6-tools-dev-tools \
  qt6-svg-dev \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

ARG MUMBLE_VERSION=latest
ARG MUMBLE_BUILD_NUMBER=""
ARG MUMBLE_CMAKE_ARGS="-Dwebrtc-sfu=OFF"

# Copy the cloned source from the mumble-src stage.
COPY --from=mumble-src /mumble/repo /mumble/repo

# Drop the prebuilt plugin-host artefacts where CMake expects them so the
# C++ link step can resolve the cdylib symbols.
RUN mkdir -p 3rdparty/mumble-plugin-host/lib 3rdparty/mumble-plugin-host/include
COPY --from=plugin-host-build /plugin-host/target/release/libmumble_plugin_host.so \
    /mumble/repo/3rdparty/mumble-plugin-host/lib/libmumble_plugin_host.so
COPY --from=plugin-host-build /plugin-host/host/include/mumble_plugin_host.h \
    /mumble/repo/3rdparty/mumble-plugin-host/include/mumble_plugin_host.h

RUN /mumble/scripts/build.sh
RUN /mumble/scripts/copy_one_of.sh ./scripts/murmur.ini ./auxiliary_files/mumble-server.ini default_config.ini

RUN git clone https://github.com/ncopa/su-exec.git /mumble/repo/su-exec \
    && cd /mumble/repo/su-exec && make


# Download the fancy-plugin-example plugins from GitHub Releases.
# Supports linux/amd64 and linux/arm64; other architectures skip
# silently (the plugins directory will just be empty for them).
# Override FANCY_PLUGIN_VERSION at build time to pin a specific release.
#
# Each plugin ships its own per-arch tarball; the names follow the
# pattern  fancy-<crate>-linux-<arch>.tar.gz  (see the upstream CI in
# fancy-plugin-example/.github/workflows/ci.yml).
# ------------------------------------------------------------------
FROM ubuntu:24.04 AS plugin-fetch
ARG TARGETARCH
ARG FANCY_PLUGIN_VERSION=v0.2.0
ARG FANCY_PLUGINS="fancy-greeter fancy-gallery-showcase fancy-info-card fancy-feedback-form fancy-quick-poll fancy-chat-card"
RUN apt-get update && apt-get install --no-install-recommends -y curl ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /plugins \
  && case "${TARGETARCH}" in \
       amd64) ARCH_SUFFIX="linux-x86_64" ;; \
       arm64) ARCH_SUFFIX="linux-aarch64" ;; \
       *)     echo "No fancy-plugin-example builds for arch '${TARGETARCH}', skipping."; ARCH_SUFFIX="" ;; \
     esac \
  && if [ -n "${ARCH_SUFFIX}" ]; then \
       for crate in ${FANCY_PLUGINS}; do \
         ARCHIVE="${crate}-${ARCH_SUFFIX}.tar.gz"; \
         URL="https://github.com/Fancy-Mumble/fancy-plugin-example/releases/download/${FANCY_PLUGIN_VERSION}/${ARCHIVE}"; \
         echo "Fetching ${ARCHIVE}"; \
         if ! curl -fsSL "${URL}" | tar -xz -C /plugins; then \
           echo "WARNING: failed to fetch ${ARCHIVE} - skipping"; \
         fi; \
       done; \
     fi


# Build the Rust WebRTC SFU shared library in its own stage.
FROM ubuntu:24.04 AS sfu-build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install --no-install-recommends -y \
  curl ca-certificates build-essential pkg-config libssl-dev \
  && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"
COPY --from=mumble-src /mumble/repo/3rdparty/webrtc-sfu /sfu
WORKDIR /sfu
RUN cargo build --release && strip target/release/libwebrtc_sfu.so



FROM base

COPY --from=build /mumble/repo/build/mumble-server /usr/bin/mumble-server
# FCM push module (optional - glob avoids failure if not built)
COPY --from=build /mumble/repo/build/src/murmur/fcm/libmumble_push_fcm.so* /usr/bin/
# WebRTC SFU Rust module - built in the sfu-build stage.
COPY --from=sfu-build /sfu/target/release/libwebrtc_sfu.so /usr/bin/
# mumble-plugin-host Rust cdylib - dlopen'd at runtime by mumble-server.
COPY --from=plugin-host-build /plugin-host/target/release/libmumble_plugin_host.so /usr/lib/
# Bundled dynamic plugins (file-server, live-doc) the host loads on startup.
# Operators can drop additional .so files into /etc/mumble/plugins (mountable)
# without rebuilding the image; see MUMBLE_PLUGIN_DIRS below.
COPY --from=plugin-host-build /plugin-host/plugins/ /usr/lib/mumble-server/plugins/
# Third-party plugins downloaded from GitHub Releases.
COPY --from=plugin-fetch /plugins/ /usr/lib/mumble-server/plugins/
COPY --from=build /mumble/repo/default_config.ini /etc/mumble/bare_config.ini
COPY --from=build --chmod=755 /mumble/repo/su-exec/su-exec /usr/local/bin/su-exec


EXPOSE 64738/tcp 64738/udp 64739/tcp 64740/tcp 10000/udp
COPY entrypoint.sh /entrypoint.sh

# Plugin discovery: the host scans every directory listed in
# MUMBLE_PLUGIN_DIRS (':'-separated) in addition to the `plugins_dir`
# server config key. `/etc/mumble/plugins` is empty by default and exists
# as a mount point for operator-supplied .so plugins.
ENV MUMBLE_PLUGIN_DIRS="/usr/lib/mumble-server/plugins:/etc/mumble/plugins"
RUN mkdir -p /etc/mumble/plugins

VOLUME ["/data", "/etc/mumble/plugins"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/mumble-server"]

