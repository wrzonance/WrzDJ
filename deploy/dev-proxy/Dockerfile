FROM nginx:1.31-alpine@sha256:b50897d5c7b1aa08067c3d90c5e8b3e47ec4e3c91c91446f67820228f7b41e34
# Refresh Alpine security fixes published since the upstream image was built.
# As with the API/web images, rebuild this layer when Renovate updates the digest.
RUN apk upgrade --no-cache
