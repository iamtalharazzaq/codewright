# Codewright sandbox: C++ toolchain (CMake, Ninja, g++, GoogleTest, clang-tidy, cppcheck).
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build libgtest-dev clang-tidy cppcheck ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 sandbox
USER sandbox
WORKDIR /work
