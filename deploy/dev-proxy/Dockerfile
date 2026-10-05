FROM nginx:1.31-alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2
# Refresh Alpine security fixes published since the upstream image was built.
# As with the API/web images, rebuild this layer when Renovate updates the digest.
RUN apk upgrade --no-cache
