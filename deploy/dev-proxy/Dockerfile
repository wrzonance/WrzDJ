FROM nginx:1.31-alpine@sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11
# Refresh Alpine security fixes published since the upstream image was built.
# As with the API/web images, rebuild this layer when Renovate updates the digest.
RUN apk upgrade --no-cache
