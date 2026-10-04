# WrzDJ StageLinQ Bridge Dockerfile
#
# NOTE: This container must run with network_mode: host (or --network host)
# for StageLinQ UDP broadcast discovery to work.

FROM node:26-alpine@sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80 AS base
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
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# Run the bridge
CMD ["node", "dist/index.js"]
