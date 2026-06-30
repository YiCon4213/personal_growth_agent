FROM node:22-alpine AS dependencies
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci \
    --registry="${NPM_REGISTRY}" \
    --fetch-retries=5 \
    --fetch-retry-mintimeout=20000 \
    --fetch-retry-maxtimeout=120000 \
    --fetch-timeout=300000


FROM node:22-alpine AS builder
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL} \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build


FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    BACKEND_URL=http://backend:8000 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
