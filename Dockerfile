# A self-contained elenctic: its own Python and its own clingo and clingcon, so running it touches
# nothing installed on the host. The image holds the tool and what the tool needs, and nothing more.
#
# Both solvers come from PyPI here, not conda-forge as in pixi.toml, because conda-forge has no
# linux-aarch64 build of clingcon and this image must also run natively on arm64 hosts (Apple
# Silicon under Docker or Podman). PyPI has cp314 wheels for both on both. They are pinned to the
# releases the image is tested with, so an image built from a tag solves as it did when tagged; the
# package itself only states floors, which is right for a library and wrong for a finished tool.
#
# Usage:  docker run --rm -v "$PWD":/work:ro elenctic [elenctic arguments]

# The build stage installs elenctic into a virtual environment; only that environment is carried
# forward, so the source tree, the build backend and pip's cache never reach the final image.
FROM docker.io/library/python:3.14-slim-trixie AS build
COPY . /src
RUN python -m venv /opt/elenctic \
 && /opt/elenctic/bin/pip install --no-cache-dir "/src[theory]" clingo==5.8.2 clingcon==5.2.1.post2 \
 && /opt/elenctic/bin/pip uninstall --yes pip

# The same base as the build stage, which the environment's interpreter links back to. Its own pip
# goes too: nothing is installed into this image after it is built.
FROM docker.io/library/python:3.14-slim-trixie
RUN python -m pip uninstall --yes --root-user-action=ignore pip
COPY --from=build /opt/elenctic /opt/elenctic
ENV PATH=/opt/elenctic/bin:$PATH

# elenctic only reads its corpus, so it runs unprivileged (as nobody) and the corpus can be mounted
# read-only.
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["elenctic"]
