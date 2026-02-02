FROM python:3.14-alpine
WORKDIR /app
RUN pip install paho-mqtt
COPY verifier.py .
CMD ["python", "-u", "verifier.py"]
