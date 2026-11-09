FROM node:24.22.1-trixie-slim AS node-dependencies
WORKDIR /dependencies
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --fund=false

FROM python:3.15.1-slim-trixie
WORKDIR /app

# Both official stages use Debian trixie/glibc. Keep npm build-only;
# the battery decoder needs Node and its runtime libraries in production.
RUN apt-get update \
  && apt-get install -y --no-install-recommends libstdc++6 libatomic1 \
  && rm -rf /var/lib/apt/lists/*
COPY --from=node-dependencies /usr/local/bin/node /usr/local/bin/node
COPY --from=node-dependencies /dependencies/node_modules /app/node_modules
COPY package.json package-lock.json ./
RUN node --version \
  && node -e "require('@michaelhart/meshcore-decoder/dist/crypto/key-manager.js'); require('@michaelhart/meshcore-decoder/dist/decoder/payload-decoders/group-text.js')"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/app.py
COPY scripts /app/scripts
COPY static /app/static

EXPOSE 8081
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]
