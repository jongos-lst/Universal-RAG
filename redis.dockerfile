FROM redis/redis-stack-server:latest
ENV REDIS_ARGS "--save 1200 32"
ARG REDIS_PASSWORD
ENV REDIS_PASSWORD ${REDIS_PASSWORD}
ENV REDISEARCH_ARGS VSS_MAX_RESIZE 52428800000
WORKDIR /usr
RUN mkdir -p /usr/local/etc/redis
EXPOSE 6379
RUN echo "requirepass ${REDIS_PASSWORD}" > /usr/local/etc/redis/redis.conf && \
    echo "maxmemory 4gb" >> /usr/local/etc/redis/redis.conf && \
    echo "maxmemory-policy noeviction" >> /usr/local/etc/redis/redis.conf
CMD ["redis-stack-server", "/usr/local/etc/redis/redis.conf"]