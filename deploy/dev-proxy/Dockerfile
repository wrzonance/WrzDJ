FROM nginx:1.31-alpine@sha256:72aeb3308ef6cb3118242fb16389518923916dfa206e32d1a8377acc328b9870
# Refresh Alpine security fixes published since the upstream image was built.
# As with the API/web images, rebuild this layer when Renovate updates the digest.
RUN apk upgrade --no-cache
