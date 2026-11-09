# syntax=docker/dockerfile:1
# ============================================================
# STAGE 1 — Build del frontend React (React Router 7 · SSR)
# ============================================================
FROM node:22-alpine AS builder

RUN npm install --global pnpm@11 --silent

WORKDIR /build

# Lockfile + workspace primero: capa cacheable.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --frozen-lockfile

# Configuración y fuentes del framework.
COPY vite.config.ts react-router.config.ts tsconfig.json ./
COPY app ./app
COPY public ./public

# URL INTERNA de la API horneada en el bundle SSR. En compose apunta al
# servicio `backend`; el navegador usa `ALUCARD_PUBLIC_BACKEND_PORT` en runtime.
ARG PUBLIC_BACKEND_HOST=http://backend
ARG PUBLIC_BACKEND_PORT=7331
ENV PUBLIC_BACKEND_HOST=${PUBLIC_BACKEND_HOST} \
    PUBLIC_BACKEND_PORT=${PUBLIC_BACKEND_PORT}

RUN pnpm build

# ============================================================
# STAGE 2 — Runtime (solo prod deps + build, usuario no-root)
# ============================================================
FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=7330

RUN npm install --global pnpm@11 --silent

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --frozen-lockfile --prod

COPY --from=builder --chown=node:node /build/build ./build

USER node
EXPOSE 7330

CMD ["node_modules/.bin/react-router-serve", "./build/server/index.js"]
