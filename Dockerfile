FROM ubuntu:24.04 as base

ARG DEBIAN_FRONTEND=noninteractive
RUN sed -i 's|http://security.ubuntu.com|http://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
  && apt-get update && apt-get install --no-install-recommends -y \
  ca-certificates \
  libavahi-compat-libdnssd1 \
  libcap2 \
  libqt6core6t64 \
  libqt6dbus6t64 \
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
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*



FROM base AS build
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y \
  build-essential \
  ca-certificates \
  cmake \
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

COPY ./scripts/* /mumble/scripts/
WORKDIR /mumble/repo

ARG MUMBLE_VERSION=latest
ARG MUMBLE_BUILD_NUMBER=""
ARG MUMBLE_CMAKE_ARGS=""

# Clone the repo, build it and finally copy the default server ini file. Since this file may be at different locations and Docker
# doesn't support conditional copies, we have to ensure that regardless of where the file is located in the repo, it will end
# up at a unique path in our build container to be copied further down.
RUN /mumble/scripts/clone.sh
RUN /mumble/scripts/build.sh
RUN /mumble/scripts/copy_one_of.sh ./scripts/murmur.ini ./auxiliary_files/mumble-server.ini default_config.ini



FROM base
ARG MUMBLE_UID=1000
ARG MUMBLE_GID=1000
RUN getent group $MUMBLE_GID && groupdel $(getent group $MUMBLE_GID | cut -d: -f1) || true \
  && getent passwd $MUMBLE_UID && userdel $(getent passwd $MUMBLE_UID | cut -d: -f1) || true \
  && groupadd --gid $MUMBLE_GID mumble \
  && useradd --uid $MUMBLE_UID --gid $MUMBLE_GID mumble

COPY --from=build /mumble/repo/build/mumble-server /usr/bin/mumble-server
COPY --from=build /mumble/repo/default_config.ini /etc/mumble/bare_config.ini

RUN mkdir -p /data && chown -R mumble:mumble /data && chown -R mumble:mumble /etc/mumble
USER mumble
EXPOSE 64738/tcp 64738/udp
COPY entrypoint.sh /entrypoint.sh

VOLUME ["/data"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/mumble-server", "--foreground"]

