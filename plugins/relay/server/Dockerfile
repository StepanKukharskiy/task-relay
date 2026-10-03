FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY task_relay/ ./task_relay/
COPY start.py ./
USER 65534:65534
EXPOSE 8080
CMD ["python", "start.py"]
