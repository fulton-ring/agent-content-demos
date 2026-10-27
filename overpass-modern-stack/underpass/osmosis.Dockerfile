# Osmosis and psql, as in Underpass-API's src/postgres_osmosis/docker/osmosis/Dockerfile.
# ca.crt is empty unless the build runs behind a TLS-intercepting proxy (DOCKER_CA_BUNDLE).
FROM debian@sha256:854dd8ab51d62866dbd8f5431d15ce77b12983a2a4a1e1fe43a2395dc7ef9f61
COPY ca.crt /etc/ssl/build-ca.crt
RUN if [ -s /etc/ssl/build-ca.crt ]; then \
      sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources && \
      echo 'Acquire::https::CAInfo "/etc/ssl/build-ca.crt";' > /etc/apt/apt.conf.d/99ca; \
    fi \
 && apt-get update -y && apt-get install -y --no-install-recommends osmosis postgresql-client
