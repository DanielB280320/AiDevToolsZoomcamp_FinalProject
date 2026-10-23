# syntax=docker/dockerfile:1
# FitWise frontend image (spec §11): nginx serving the built SPA and proxying /api to the backend.
# Built once per commit and tagged with TAG (CD, #13). Runtime configuration comes only from
# environment variables (BACKEND_UPSTREAM, NGINX_RESOLVER; see the root .env.example).

ARG NODE_VERSION=24
ARG NGINX_VERSION=1.30

# ---- build: Node 24 (frontend/.nvmrc), locked dependencies, type-check + vite build ----
FROM node:${NODE_VERSION}-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ---- runtime: unprivileged nginx (uid 101, listens on 8080) ----
FROM nginxinc/nginx-unprivileged:${NGINX_VERSION}-alpine AS runtime
# The official entrypoint renders /etc/nginx/templates/*.template with envsubst at start-up,
# restricted to variables with these prefixes so nginx's own $variables are left alone.
ENV NGINX_ENVSUBST_FILTER="^(BACKEND_|NGINX_)" \
    BACKEND_UPSTREAM=backend:8000 \
    NGINX_RESOLVER=127.0.0.11
# Pull in the brotli-libs security fix (CVE-2026-111497, fixed in 1.2.1-r0) until the base image ships it.
USER root
RUN apk upgrade --no-cache 'brotli-libs>=1.2.1-r0'
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
