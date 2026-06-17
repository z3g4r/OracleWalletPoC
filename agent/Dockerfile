FROM hashicorp/vault:1.16
USER root
RUN apk add --no-cache python3 bash curl ca-certificates
COPY . /vault/project
RUN chmod +x /vault/project/scripts/*.py && mkdir -p /vault/token && chown -R vault:vault /vault/token /vault/project
USER vault
ENTRYPOINT ["python3", "/vault/project/scripts/agent_entrypoint.py"]
