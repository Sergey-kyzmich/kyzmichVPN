FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
# config.ini must be provided via bind-mount or Docker secret
ENV PYTHONUNBUFFERED=1
EXPOSE 8443
CMD ["python", "start_services.py"]
