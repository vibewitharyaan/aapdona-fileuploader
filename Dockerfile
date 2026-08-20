FROM python:3.12-slim
WORKDIR /app
COPY app ./app
USER 1001:1001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/status',timeout=4)" || exit 1
CMD ["python3", "-m", "app"]