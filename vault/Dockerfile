# ARM-native first: build the Oracle Vault DB plugin from source for the target architecture,
# then run Vault on Oracle Linux with Oracle Instant Client installed.
# This keeps the PoC on Vault Database Secrets Engine without downloading amd64-only plugin assets.
ARG VAULT_VERSION=1.16.3
ARG ORACLE_PLUGIN_VERSION=0.6.0
ARG IC_VERSION=23.26.2.0.0
ARG IC_DIR=instantclient_23_26

FROM oraclelinux:9-slim AS plugin-build
ARG ORACLE_PLUGIN_VERSION
ARG IC_VERSION
ARG IC_DIR

# The Oracle plugin uses OCI through cgo. Avoid oracle-instantclient-release-* packages here:
# on ARM/OL9 they may not be present in the enabled repos. Download Oracle's published ARM64
# Instant Client Basic Light + SDK ZIPs directly instead.
RUN microdnf install -y \
      git ca-certificates gcc gcc-c++ make pkgconf golang \
      curl unzip findutils libaio && \
    microdnf clean all

RUN set -eux; \
    mkdir -p /opt/oracle; \
    curl -fsSLo /tmp/ic-basiclite.zip \
      "https://download.oracle.com/otn_software/linux/instantclient/2326200/instantclient-basiclite-linux.arm64-${IC_VERSION}.zip"; \
    curl -fsSLo /tmp/ic-sdk.zip \
      "https://download.oracle.com/otn_software/linux/instantclient/2326200/instantclient-sdk-linux.arm64-${IC_VERSION}.zip"; \
    unzip -oq /tmp/ic-basiclite.zip -d /opt/oracle; \
    unzip -oq /tmp/ic-sdk.zip -d /opt/oracle; \
    rm -f /tmp/ic-basiclite.zip /tmp/ic-sdk.zip; \
    test -f "/opt/oracle/${IC_DIR}/libclntsh.so"; \
    test -f "/opt/oracle/${IC_DIR}/sdk/include/oci.h"

WORKDIR /src
RUN git clone --depth 1 --branch "v${ORACLE_PLUGIN_VERSION}" https://github.com/hashicorp/vault-plugin-database-oracle.git . || \
    git clone --depth 1 https://github.com/hashicorp/vault-plugin-database-oracle.git .

# Create an oci8 pkg-config file from the Instant Client ZIP layout.
RUN set -eux; \
    mkdir -p /usr/local/lib/pkgconfig; \
    printf 'prefix=/opt/oracle/%s\nlibdir=${prefix}\nincludedir=${prefix}/sdk/include\nName: oci8\nDescription: Oracle Instant Client\nVersion: 23\nLibs: -L${libdir} -lclntsh\nCflags: -I${includedir}\n' "${IC_DIR}" > /usr/local/lib/pkgconfig/oci8.pc; \
    cat /usr/local/lib/pkgconfig/oci8.pc

ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_23_26
RUN CGO_ENABLED=1 GOOS=linux GOARCH=arm64 go build -o /out/vault-plugin-database-oracle ./plugin

FROM oraclelinux:9-slim
ARG TARGETARCH
ARG VAULT_VERSION
ARG IC_VERSION
ARG IC_DIR

RUN microdnf install -y python3 curl unzip ca-certificates tar gzip findutils procps-ng jq shadow-utils libaio && \
    microdnf clean all

# For this PoC we are intentionally targeting ARM-native Docker on Apple Silicon.
RUN set -eux; \
    if [ "${TARGETARCH:-arm64}" != "arm64" ]; then \
      echo "This PoC Dockerfile is ARM64-native. Build with linux/arm64 for Apple Silicon." >&2; \
      exit 1; \
    fi; \
    curl -fsSLo /tmp/vault.zip "https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_linux_arm64.zip"; \
    unzip -oq /tmp/vault.zip -d /usr/local/bin; \
    rm /tmp/vault.zip; \
    chmod +x /usr/local/bin/vault; \
    vault version

RUN set -eux; \
    mkdir -p /opt/oracle; \
    curl -fsSLo /tmp/ic-basiclite.zip \
      "https://download.oracle.com/otn_software/linux/instantclient/2326200/instantclient-basiclite-linux.arm64-${IC_VERSION}.zip"; \
    unzip -oq /tmp/ic-basiclite.zip -d /opt/oracle; \
    rm -f /tmp/ic-basiclite.zip; \
    test -f "/opt/oracle/${IC_DIR}/libclntsh.so"

RUN useradd --system --home-dir /vault --shell /sbin/nologin vault && \
    mkdir -p /vault/config /vault/plugins && \
    chown -R vault:vault /vault

COPY --from=plugin-build /out/vault-plugin-database-oracle /vault/plugins/vault-plugin-database-oracle
COPY config /vault/config
RUN chmod +x /vault/plugins/vault-plugin-database-oracle /vault/config/*.py && \
    chown -R vault:vault /vault

ENV VAULT_PLUGIN_DIR=/vault/plugins
ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_23_26
EXPOSE 8200
USER vault
ENTRYPOINT ["python3", "/vault/config/vault_entrypoint.py"]
