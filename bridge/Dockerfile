# WrzDJ StageLinQ Bridge Dockerfile
#
# NOTE: This container must run with network_mode: host (or --network host)
# for StageLinQ UDP broadcast discovery to work.

FROM node:26-alpine@sha256:7ed4edf2b680417bf06d3f465de09bb113f877ff265b15f72a27a4c6fb76fb04 AS base
# Refresh security fixes published after the pinned base image, as in dashboard/.
# This layer remains cached until the base digest changes.
RUN apk upgrade --no-cache

FROM base AS builder
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source
COPY tsconfig.json ./
COPY src/ ./src/

# Build TypeScript
RUN npm run build && npm prune --omit=dev --ignore-scripts

FROM base AS runtime
WORKDIR /app
# The bridge starts with node; npm and the compiler belong only in the builder.
RUN npm uninstall --global npm
COPY --from=builder --chown=node:node /app/package.json /app/package-lock.json ./
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/dist ./dist

# Run as the image's unprivileged `node` user (uid 1000), as the api and web images do.
# StageLinQ discovery and the Traktor listener use unprivileged ports only.
USER node

# Run the bridge
CMD ["node", "dist/index.js"]
