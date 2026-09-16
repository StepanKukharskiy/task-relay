FROM node:22-alpine
WORKDIR /app
COPY --chown=node:node server.mjs releases.mjs release-fallback.json package.json ./
COPY --chown=node:node public ./public
COPY --chown=node:node fetch-downloads.mjs downloads.json ./
RUN mkdir downloads && chown node:node downloads
USER node
RUN node fetch-downloads.mjs
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "server.mjs"]
