# syntax=docker/dockerfile:1
# ============================================================
# STAGE 1 — Build del frontend Astro (SSR)
# ============================================================
FROM node:22-alpine AS builder

RUN npm install --global pnpm@11 --silent

WORKDIR /build

# Lockfile + workspace (allowBuilds para esbuild/sharp) primero: capa cacheable.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --frozen-lockfile

# Fuentes y build (cada carpeta a su destino: Docker aplana `COPY dir ./`).
COPY astro.config.mjs tsconfig.json ./
COPY src ./src
COPY public ./public

# URL de la API horneada en el bundle (SSR y cliente). En compose apunta al
# servicio interno `backend`; en local a localhost:7331.
ARG PUBLIC_BACKEND_HOST=http://backend
ARG PUBLIC_BACKEND_PORT=7331
ENV PUBLIC_BACKEND_HOST=${PUBLIC_BACKEND_HOST} \
    PUBLIC_BACKEND_PORT=${PUBLIC_BACKEND_PORT}

RUN pnpm build

# ============================================================
# STAGE 2 — Runtime (solo prod deps + dist, usuario no-root)
# ============================================================
FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=7330

RUN npm install --global pnpm@11 --silent

WORKDIR /app

# Dependencias de producción.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --frozen-lockfile --prod

# Artefactos compilados (SSR standalone de @astrojs/node).
COPY --from=builder --chown=node:node /build/dist ./dist

USER node
EXPOSE 7330

CMD ["node", "./dist/server/entry.mjs"]
