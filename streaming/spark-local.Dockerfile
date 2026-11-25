FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir \
    py4j==0.10.9.9 pandas==3.1.1 numpy==2.5.5 "psycopg[binary]==3.3.9" \
    python-dotenv==1.2.4 confluent-kafka==2.16.1 nbformat==5.11.1 \
    nbclient==0.11.0 ipykernel==7.4.0

ENV SPARK_HOME=/opt/pyspark-runtime/pyspark \
    PYTHONPATH=/opt/pyspark-runtime \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
