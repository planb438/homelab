# Runs the real ParkingClub Worker code locally (wrangler dev / workerd) for the lab.
FROM node:22-bookworm-slim
ENV WRANGLER_SEND_METRICS=false CI=1 HOME=/home/app NODE_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* \
 && npm install -g wrangler@4 && npm cache clean --force \
 && mkdir -p /home/app /work /data && chown -R 10001:65533 /home/app /work /data
COPY start.sh labconfig.mjs /opt/lab/
USER 10001
EXPOSE 8787
CMD ["/bin/sh", "/opt/lab/start.sh"]
