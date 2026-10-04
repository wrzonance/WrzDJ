# WrzDJ StageLinQ Bridge Dockerfile
#
# NOTE: This container must run with network_mode: host (or --network host)
# for StageLinQ UDP broadcast discovery to work.

FROM node:26-alpine@sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install --production=false

# Copy source
COPY tsconfig.json ./
COPY src/ ./src/

# Build TypeScript
RUN npm run build

# Run the bridge
CMD ["node", "dist/index.js"]
