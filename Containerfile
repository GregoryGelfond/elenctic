# syntax=docker/dockerfile:1
# Minimal image whose only purpose is running elenctic (CLI entrypoint; clingo and clingcon included).
#
# Build:  docker build -f Containerfile -t elenctic .
# Run:    docker run --rm -v "$PWD":/work:ro elenctic [elenctic arguments]
# No published image; no CI build — ship the recipe only.

FROM docker.io/library/python:3.14-slim-trixie@sha256:af8a5aa14780025dbfbcfbc81bd8a91ebd87711dd5b0f48ed71090949dd7cb1d AS build
COPY --from=docker.io/astral/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY docs/reference/output-v1.schema.json ./docs/reference/output-v1.schema.json
RUN uv venv /opt/elenctic \
 && UV_PROJECT_ENVIRONMENT=/opt/elenctic uv sync --frozen --no-dev --extra theory --no-editable \
 && /opt/elenctic/bin/python -c "import clingo, clingcon; import elenctic"

FROM docker.io/library/python:3.14-slim-trixie@sha256:af8a5aa14780025dbfbcfbc81bd8a91ebd87711dd5b0f48ed71090949dd7cb1d
COPY --from=build /opt/elenctic /opt/elenctic
ENV PATH=/opt/elenctic/bin:$PATH
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["elenctic"]
