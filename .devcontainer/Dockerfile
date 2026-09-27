FROM mcr.microsoft.com/devcontainers/python:1-3.12
# The base image includes an unrelated Yarn apt source with a stale key.
# It breaks the sshd feature's apt update; Yarn is not used in this lab.
RUN rm -f /etc/apt/sources.list.d/yarn.list
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/
