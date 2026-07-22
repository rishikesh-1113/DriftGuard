# bad: using latest tag
FROM python:latest

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# bad: running as root (no USER directive)
CMD ["python", "app.py"]
