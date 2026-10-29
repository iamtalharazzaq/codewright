# Codewright sandbox: C++ toolchain (CMake, Ninja, g++, GoogleTest, clang-tidy, cppcheck, gcovr for coverage).
# Conan (pip-installed: light, no extra system packages) handles conanfile.txt/.py dependencies (Phase 19).
# vcpkg is NOT installed here yet: it needs a git clone + bootstrap build of its own (a few hundred MB), deferred
# until there's disk headroom to spare; `agent/language_packs/cpp.py` already plans vcpkg.json builds assuming it
# will live at /opt/vcpkg, so adding it later is just this Dockerfile, no pack code change.
# Runs as uid 10001 (the API's uid, so both can write workspaces); the runner adds a read-only root, tmpfs $HOME and limits.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build libgtest-dev clang-tidy cppcheck gcovr ca-certificates python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --break-system-packages "conan>=2,<3" \
    && groupadd --gid 10001 sandbox && useradd --create-home --uid 10001 --gid 10001 sandbox
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
