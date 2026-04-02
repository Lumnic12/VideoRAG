# Multi-stage build for Vite + React frontend
# Stage 1: Build the static assets
# Stage 2: Serve with nginx (tiny Alpine image)

# ─── Stage 1: Build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Cache npm install layer separately from source
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# Copy source and build
COPY . .

# VITE_API_BASE is baked in at build time.
# In Docker, the frontend is served at :3000 and nginx proxies /api → backend:8000
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=${VITE_API_BASE}

RUN npm run build


# ─── Stage 2: Serve with nginx ────────────────────────────────────────────────
FROM nginx:1.27-alpine AS final

LABEL org.opencontainers.image.title="Semantic Video Synthesizer — Frontend"

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Our custom nginx config (reverse-proxies /api and /ws to backend)
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx config is COPY'd from context — see docker-compose volumes mount
# or embed inline via the heredoc below
RUN cat > /etc/nginx/conf.d/svs.conf << 'EOF'
server {
    listen 3000;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Allow large video uploads (up to 500MB)
    client_max_body_size 500M;

    # SPA fallback — all non-asset routes → index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy REST API to backend
    location /api/ {
        proxy_pass         http://backend:8000/api/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    # Proxy static keyframes (served by FastAPI StaticFiles)
    location /static/ {
        proxy_pass http://backend:8000/static/;
    }

    # WebSocket proxy
    location /ws/ {
        proxy_pass             http://backend:8000/ws/;
        proxy_http_version     1.1;
        proxy_set_header       Upgrade    $http_upgrade;
        proxy_set_header       Connection "upgrade";
        proxy_set_header       Host       $host;
        proxy_read_timeout     300s;
    }

    # Cache static assets aggressively
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:3000/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
