FROM redis/redis-stack-server:7.4.0-v8@sha256:798ab84d9f266936b034ab11c4d04a2b8e4b441884c5aa7d17ac951eefdf742a
ENV REDIS_ARGS="--appendonly yes --maxmemory 1gb --maxmemory-policy noeviction"
