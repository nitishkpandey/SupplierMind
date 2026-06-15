FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production: serve built files via nginx (in docker-compose.prod.yml)
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
