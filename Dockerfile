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

# Source repository / branch to build from.  Defaults to the Fancy Mumble
# server fork.  Override with --build-arg MUMBLE_GIT_REPO=... /
# MUMBLE_GIT_BRANCH=... to build from a different fork or upstream.
ARG MUMBLE_GIT_REPO=https://github.com/SetZero/mumble-server
ARG MUMBLE_GIT_BRANCH=1.6.x
ENV MUMBLE_GIT_REPO=${MUMBLE_GIT_REPO}
ENV MUMBLE_GIT_BRANCH=${MUMBLE_GIT_BRANCH}

# Install Rust toolchain (used to build the mumble-plugin-host cdylib and
# the WebRTC SFU module from the cloned source tree).
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
  | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

# Clone the repo, build it and finally copy the default server ini file. Since this file may be at different locations and Docker
# doesn't support conditional copies, we have to ensure that regardless of where the file is located in the repo, it will end
# up at a unique path in our build container to be copied further down.
RUN /mumble/scripts/clone.sh

# Build the Rust mumble-plugin-host cdylib and publish the artefacts at the
# paths the C++ build expects (CMake otherwise warns and the linker fails
# with undefined references to plugin_host_create / plugin_host_destroy / ...).
RUN cd /mumble/repo/3rdparty/mumble-plugin-host \
    && cargo build --release -p mumble-plugin-host \
    && strip target/release/libmumble_plugin_host.so \
    && mkdir -p lib include \
    && cp target/release/libmumble_plugin_host.so lib/libmumble_plugin_host.so \
    && cp host/include/mumble_plugin_host.h include/mumble_plugin_host.h

RUN /mumble/scripts/build.sh
RUN /mumble/scripts/copy_one_of.sh ./scripts/murmur.ini ./auxiliary_files/mumble-server.ini default_config.ini

RUN git clone https://github.com/ncopa/su-exec.git /mumble/repo/su-exec \
    && cd /mumble/repo/su-exec && make


# Build the Rust WebRTC SFU shared library in its own stage.
FROM ubuntu:24.04 AS sfu-build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install --no-install-recommends -y \
  curl ca-certificates build-essential pkg-config libssl-dev \
  && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"
COPY --from=build /mumble/repo/3rdparty/webrtc-sfu /sfu
WORKDIR /sfu
RUN cargo build --release && strip target/release/libwebrtc_sfu.so



FROM base

COPY --from=build /mumble/repo/build/mumble-server /usr/bin/mumble-server
# FCM push module (optional - glob avoids failure if not built)
COPY --from=build /mumble/repo/build/src/murmur/fcm/libmumble_push_fcm.so* /usr/bin/
# WebRTC SFU Rust module - built in the sfu-build stage.
COPY --from=sfu-build /sfu/target/release/libwebrtc_sfu.so /usr/bin/
# mumble-plugin-host Rust cdylib - dlopen'd at runtime by mumble-server.
COPY --from=build /mumble/repo/3rdparty/mumble-plugin-host/lib/libmumble_plugin_host.so /usr/lib/
COPY --from=build /mumble/repo/default_config.ini /etc/mumble/bare_config.ini
COPY --from=build --chmod=755 /mumble/repo/su-exec/su-exec /usr/local/bin/su-exec


EXPOSE 64738/tcp 64738/udp 64739/tcp 10000/udp
COPY entrypoint.sh /entrypoint.sh

VOLUME ["/data"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/mumble-server"]

