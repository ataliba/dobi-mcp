FROM python:3.12-slim

# CLI do Infisical só entra na imagem com --build-arg INSTALL_INFISICAL=1 (ou true/sim)
ARG INSTALL_INFISICAL=0
RUN case "$INSTALL_INFISICAL" in 1|true|yes|on|sim) \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates bash \
      && curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | bash \
      && apt-get install -y --no-install-recommends infisical \
      && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* ;; \
    esac

RUN useradd --create-home --uid 10001 mcp
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py pipe.py config.yaml ./
COPY tools/ ./tools/
# Tools personalizadas: monte um volume aqui (ou aponte CUSTOM_TOOLS_DIR para outro lugar)
RUN mkdir -p /app/custom_tools

USER 10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUSTOM_TOOLS_DIR=/app/custom_tools
ENTRYPOINT ["python", "pipe.py", "server.py"]
