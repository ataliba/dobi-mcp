FROM python:3.12-slim

# CLI do Infisical sempre na imagem; o uso é ligado em runtime por USE_INFISICAL
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates bash \
    && curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | bash \
    && apt-get install -y --no-install-recommends infisical \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && infisical --version

RUN useradd --create-home --uid 10001 mcp
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py pipe.py config.yaml ./
COPY tools/ ./tools/
# Tools personalizadas: monte um volume aqui (ou aponte CUSTOM_TOOLS_DIR para outro lugar).
# chmod: COPY preserva o modo do host (ex.: 600), e o uid 10001 precisa ler o código.
RUN mkdir -p /app/custom_tools && chmod -R a+rX,go-w /app

USER 10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUSTOM_TOOLS_DIR=/app/custom_tools
ENTRYPOINT ["python", "pipe.py", "server.py"]
