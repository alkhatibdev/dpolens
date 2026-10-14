# The dashboard, built to static files and served beside a forward to the API.
#
# Node is needed to build it and never to run it: the running image is nginx and
# the files.

FROM node:24-alpine AS build
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30-alpine
COPY deploy/dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /dashboard/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
