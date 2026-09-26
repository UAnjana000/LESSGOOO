# syntax=docker/dockerfile:1.7
# Operations image: the api image plus PostgreSQL client tools matching the server's major version.
# The api image ships Debian bookworm's postgresql-client (15); pg_dump refuses to dump a newer server
# (pgvector/pgvector:*-pg17), and pg_restore 15 cannot read a pg_dump 17 archive.
# "base" is the released api image, supplied by scripts/Invoke-ReleaseBuild.ps1:
#   docker build --build-context base=docker-image://ambedkar-archive/api:<tag> -t ambedkar-archive/ops:<tag> ops
FROM base

ARG PG_MAJOR=17
USER root
RUN install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
         https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/usr/lib/postgresql/${PG_MAJOR}/bin:${PATH}"
USER archive
HEALTHCHECK NONE
