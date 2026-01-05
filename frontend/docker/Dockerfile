# Multi-stage Dockerfile: build the Angular app in a Node builder stage, then serve with nginx

# Builder stage
FROM node:24-bullseye-slim AS builder
WORKDIR /app

# Copy package manifests first so we can utilize Docker cache for deps
COPY package.json package-lock.json* ./

# Install dependencies (try npm ci, fallback to npm install if lockfile missing)
RUN npm ci --silent || npm install --silent

# Copy the rest of the sources and build the app
COPY . .
RUN npm run build -- --configuration production

# Runtime stage
FROM nginx:alpine AS runtime

# Copy build output to nginx html dir
COPY --from=builder /app/dist/audio-frontend /usr/share/nginx/html

# Copy nginx template and entrypoint that will replace placeholders from assets/config.json at container start
COPY docker/nginx.conf.template /etc/nginx/conf.d/default.conf.template
COPY docker/docker-entrypoint.sh /docker-entrypoint-custom.sh
RUN chmod +x /docker-entrypoint-custom.sh

EXPOSE 80

# Use a custom entrypoint to generate final nginx config from the built assets/config.json
ENTRYPOINT ["/docker-entrypoint-custom.sh"]
CMD ["/docker-entrypoint.sh", "nginx", "-g", "daemon off;"]
