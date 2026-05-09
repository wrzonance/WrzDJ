# WrzDJ StageLinQ Bridge Dockerfile
#
# NOTE: This container must run with network_mode: host (or --network host)
# for StageLinQ UDP broadcast discovery to work.

FROM node:26-alpine@sha256:e71ac5e964b9201072425d59d2e876359efa25dc96bb1768cb73295728d6e4ea

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
