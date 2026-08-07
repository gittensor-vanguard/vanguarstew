# Private self-hosted runtime. No secret is copied into this image.
FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 vanguarstew \
    && mkdir -p /var/lib/vanguarstew \
    && chown -R vanguarstew:vanguarstew /app /var/lib/vanguarstew

USER vanguarstew
ENV VANGUARSTEW_DATA_DIR=/var/lib/vanguarstew
EXPOSE 8080
CMD ["vanguarstew", "serve", "--config", "/app/vanguarstew.json"]
