FROM python:3

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r /app/reqs.txt

CMD ["python", "/app/app.py"]



