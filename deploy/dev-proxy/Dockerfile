FROM nginx:1.31-alpine@sha256:892bb2152464f0c5d8972593a5f5afaf8054552580b699d95f8ff4af08c2d33d
# Refresh Alpine security fixes published since the upstream image was built.
# As with the API/web images, rebuild this layer when Renovate updates the digest.
RUN apk upgrade --no-cache
