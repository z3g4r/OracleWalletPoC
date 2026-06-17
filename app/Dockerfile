FROM gvenzl/oracle-free:23-slim
USER root

# mkstore requires a Java runtime plus Oracle PKI / OSDT classes.
# The slim Oracle image has Oracle client/server tools, but not a complete Java
# runtime/classpath for mkstore, so provide a deterministic wrapper.
ARG ORACLE_PKI_VERSION=19.3.0.0
RUN set -eux; \
    microdnf install -y python3 findutils procps-ng curl ca-certificates unzip java-17-openjdk-headless || \
    microdnf install -y python3 findutils procps-ng curl ca-certificates unzip java-11-openjdk-headless || \
    microdnf install -y python3 findutils procps-ng curl ca-certificates unzip java-latest-openjdk-headless; \
    microdnf clean all; \
    java_bin="$(readlink -f /usr/bin/java)"; \
    java_home="$(dirname "$(dirname "$java_bin")")"; \
    ln -sfn "$java_home" /usr/local/java; \
    mkdir -p /opt/oracle/pki-lib; \
    base="https://repo1.maven.org/maven2/com/oracle/database/security"; \
    curl -fsSLo /opt/oracle/pki-lib/oraclepki.jar "$base/oraclepki/${ORACLE_PKI_VERSION}/oraclepki-${ORACLE_PKI_VERSION}.jar"; \
    curl -fsSLo /opt/oracle/pki-lib/osdt_core.jar "$base/osdt_core/${ORACLE_PKI_VERSION}/osdt_core-${ORACLE_PKI_VERSION}.jar"; \
    curl -fsSLo /opt/oracle/pki-lib/osdt_cert.jar "$base/osdt_cert/${ORACLE_PKI_VERSION}/osdt_cert-${ORACLE_PKI_VERSION}.jar"; \
    test -s /opt/oracle/pki-lib/oraclepki.jar; \
    test -s /opt/oracle/pki-lib/osdt_core.jar; \
    test -s /opt/oracle/pki-lib/osdt_cert.jar; \
    unzip -l /opt/oracle/pki-lib/oraclepki.jar | grep -q 'oracle/security/pki/OracleSecretStoreTextUI.class'; \
    printf '%s\n' \
      '#!/bin/sh' \
      'exec /usr/local/java/bin/java -cp "/opt/oracle/pki-lib/oraclepki.jar:/opt/oracle/pki-lib/osdt_core.jar:/opt/oracle/pki-lib/osdt_cert.jar" oracle.security.pki.OracleSecretStoreTextUI "$@"' \
      > /usr/local/bin/mkstore; \
    chmod +x /usr/local/bin/mkstore; \
    /usr/local/java/bin/java -version; \
    /usr/local/bin/mkstore -help >/tmp/mkstore-help.txt 2>&1 || true; \
    cat /tmp/mkstore-help.txt | head -n 5 || true

ENV JAVA_HOME=/usr/local/java
ENV PATH="/usr/local/java/bin:/usr/local/bin:${PATH}"

COPY scripts /app/scripts
COPY example /app/example
RUN chmod +x /app/scripts/*.py /app/example/*.py && \
    mkdir -p /opt/oracle/wallet && \
    chmod 0770 /opt/oracle/wallet && \
    command -v mkstore && \
    java -version && \
    python3 -m py_compile /app/scripts/*.py /app/example/*.py
USER root
ENTRYPOINT ["python3", "/app/scripts/walletd.py"]
