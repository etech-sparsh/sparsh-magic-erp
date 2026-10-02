# ─── Stage 1: Build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy lock file too — ensures deterministic, fast installs
COPY package*.json ./

RUN npm ci

COPY . .

# Vite bakes VITE_* env vars into the bundle at build time
# Make sure frontend/.env has the correct VITE_API_BASE_URL before building
RUN npm run build

# ─── Stage 2: Serve with Nginx ────────────────────────────────────────────────
FROM nginx:alpine

# Remove default nginx page
RUN rm -rf /usr/share/nginx/html/*

# Copy built React app
COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx config: serve SPA, forward all unknown routes to index.html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]