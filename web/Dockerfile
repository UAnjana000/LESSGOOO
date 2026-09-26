# Proxy image: builds the kiosk / display / staff PWA and serves it from Caddy, which also terminates
# HTTPS and forwards /api and /iiif to the FastAPI service. Build context is the repository root.

FROM node:24-bookworm-slim AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM caddy:2.10-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 80 443
