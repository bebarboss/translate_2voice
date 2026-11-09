# หน้าเว็บ Next.js (standalone) สำหรับ VPS
# build จาก context = โฟลเดอร์ frontend/
FROM node:20-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-bookworm-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# ค่าตอน build ของ Next (server components / route handlers ที่อ่านตอน build)
ARG BACKEND_URL=http://api:8000
ARG API_KEY=
ARG DIRECT_UPLOAD=1
ENV BACKEND_URL=$BACKEND_URL \
    API_KEY=$API_KEY \
    DIRECT_UPLOAD=$DIRECT_UPLOAD \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
