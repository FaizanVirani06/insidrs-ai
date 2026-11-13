# Separate image for the research pipeline, so the production images are untouched.
FROM python:3.12-slim
WORKDIR /app
COPY research/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# Code is mounted at run time (see docker-compose.research.yml), not baked in.
