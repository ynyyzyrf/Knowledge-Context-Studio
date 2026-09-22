# syntax=docker/dockerfile:1.9

FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS source
WORKDIR /source
ADD source.tar ./
COPY source-manifest.json /source-manifest.json
RUN python -c "import hashlib,json,pathlib; m=json.load(open('/source-manifest.json')); bad=[n for n,h in m.items() if not pathlib.Path(n).is_file() or hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest()!=h]; assert not bad, bad; print('SOURCE_MANIFEST_OK',len(m))"

# Stage 1: provide Rust toolchain (required by setup.py -> build_ov_cli_artifact -> cargo build)
# ragfs-python's default S3-enabled dependency set currently requires rustc >= 1.91.1.
FROM rust:1.91.1-trixie@sha256:867f1d1162913c401378a8504fb17fe2032c760dc316448766f150a130204aad AS rust-toolchain

# Stage 2: build Studio separately so npm failures stop the Docker build.
FROM node:24-trixie-slim@sha256:8ec5d7557396cfe32d21c3f9c13072355ceab22b584578ca4bb28af31120cffe AS web-studio-builder
ARG TARGETPLATFORM
WORKDIR /app/web-studio

# Keep npm install cached when only Studio sources change.
COPY --from=source /source/web-studio/package.json /source/web-studio/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,id=npm-${TARGETPLATFORM} npm ci
COPY --from=source /source/web-studio/ ./
RUN npm run build -- --base=/studio/ \
 && test -f dist/index.html

# Stage 3: build Python environment with uv (builds Rust CLI + C++ extension)
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim@sha256:5b7499c3e4048c8f9afcca908c2f2c486923cd441b857976fb6a871e6a090737 AS py-builder

# Reuse Rust toolchain from stage 1 so setup.py can compile ov CLI in-place.
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup
ENV PATH="/app/.venv/bin:/usr/local/cargo/bin:${PATH}"
ARG OPENVIKING_VERSION=0.4.19.dev20260921
ARG TARGETPLATFORM
ARG UV_LOCK_STRATEGY=locked

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ccache \
    cmake \
    git \
 && rm -rf /var/lib/apt/lists/*

# Route gcc/g++/cc through ccache so cmake (which asks shutil.which("gcc")) picks
# up /usr/lib/ccache/gcc and benefits from the BuildKit cache mount on /root/.ccache.
ENV PATH="/usr/lib/ccache:${PATH}"
ENV CCACHE_DIR=/root/.ccache
# Pin Cargo's target dir to a stable path so a BuildKit cache mount can persist
# build artifacts across layer reruns even when uv builds the wheel in an
# ephemeral isolated tempdir.
ENV CARGO_TARGET_DIR=/cargo-target

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1
ENV CARGO_BUILD_JOBS=2
ENV PYTHON_CPU_COUNT=2
ENV CMAKE_BUILD_PARALLEL_LEVEL=2
ENV UV_CONCURRENT_INSTALLS=2
ENV UV_CONCURRENT_BUILDS=1
ENV UV_CONCURRENT_DOWNLOADS=4
ENV OV_SKIP_OV_BUILD=1
WORKDIR /app

# Copy source required for setup.py artifact builds and native extension build.
COPY --from=source /source/Cargo.toml /source/Cargo.lock ./
COPY --from=source /source/pyproject.toml /source/uv.lock /source/setup.py /source/README.md ./
COPY --from=source /source/build_support/ build_support/
COPY --from=source /source/bot/ bot/
COPY --from=source /source/crates/ crates/
COPY --from=source /source/openviking/ openviking/
COPY --from=web-studio-builder /app/web-studio/dist/ openviking/web_studio/dist/
COPY --from=source /source/openviking_cli/ openviking_cli/
COPY --from=source /source/src/ src/
COPY --from=source /source/third_party/ third_party/

# Install project and dependencies. setup.py packages the copied Studio bundle
# without running npm again, while build_ext still builds native extensions.
# Default to auto-refreshing uv.lock inside the ephemeral build context when it is
# stale, so Docker builds stay unblocked after dependency changes. Set
# UV_LOCK_STRATEGY=locked to keep fail-fast reproducibility checks.
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-${TARGETPLATFORM} \
    --mount=type=cache,target=/cargo-target,id=cargo-target-${TARGETPLATFORM} \
    --mount=type=cache,target=/usr/local/cargo/registry,id=cargo-registry-${TARGETPLATFORM} \
    --mount=type=cache,target=/usr/local/cargo/git,id=cargo-git-${TARGETPLATFORM} \
    --mount=type=cache,target=/root/.ccache,id=ccache-${TARGETPLATFORM} \
    if [ -n "${OPENVIKING_VERSION:-}" ]; then \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENVIKING="${OPENVIKING_VERSION}"; \
    elif [ -f openviking/_version.py ]; then \
        export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENVIKING="$(python -c "import runpy; print(runpy.run_path('openviking/_version.py')['version'])")"; \
    else \
        echo "OPENVIKING_VERSION build arg is required when building without openviking/_version.py" >&2; \
        exit 2; \
    fi; \
    case "${UV_LOCK_STRATEGY}" in \
        locked) \
            uv sync --locked --no-editable --reinstall-package openviking --extra bot --extra gemini \
            ;; \
        auto) \
            if ! uv lock --check; then \
                uv lock; \
            fi; \
            uv sync --locked --no-editable --reinstall-package openviking --extra bot --extra gemini \
            ;; \
        *) \
            echo "Unsupported UV_LOCK_STRATEGY: ${UV_LOCK_STRATEGY}" >&2; \
            exit 2 \
            ;; \
    esac


WORKDIR /data
COPY kcs-engine-start.py /usr/local/bin/kcs-engine-start.py
EXPOSE 1933
CMD ["/app/.venv/bin/python", "-I", "/usr/local/bin/kcs-engine-start.py"]
