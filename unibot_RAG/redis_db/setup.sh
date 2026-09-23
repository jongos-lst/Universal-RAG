#!/bin/sh
set -eu
# Run from the repository root. Uses the pinned, isolated Compose service.
exec docker compose up -d redis
