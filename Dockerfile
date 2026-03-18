# Dockerfile
FROM python:3.11-alpine

# Install essential system tools that users might want for custom actions
RUN apk add --no-cache bash curl jq speedtest-cli tzdata

WORKDIR /app

# Copy the monolithic backend
COPY share/noba-web/server.py /app/server.py

# Copy the frontend structural file
COPY share/noba-web/index.html /app/index.html

# Copy the static assets
COPY share/noba-web/static/ /app/static/

# Make the server executable
RUN chmod +x /app/server.py

# Set environment variables so the server knows where to look inside the container
ENV PORT=8080
ENV HOST=0.0.0.0
ENV NOBA_CONFIG=/app/config/config.yaml

EXPOSE 8080

CMD ["python3", "-u", "/app/server.py"]
