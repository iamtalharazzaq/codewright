# Codewright sandbox: C++ toolchain (CMake, Ninja, g++, GoogleTest, clang-tidy, cppcheck, gcovr for coverage).
# Runs as uid 10001 (the API's uid, so both can write workspaces); the runner adds a read-only root, tmpfs $HOME and limits.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build libgtest-dev clang-tidy cppcheck gcovr ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sandbox && useradd --create-home --uid 10001 --gid 10001 sandbox
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
