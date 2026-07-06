FROM public.ecr.aws/docker/library/python:3.11-slim


ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig=2.15.0-2.3 \
    libx11-6=2:1.8.12-1 \
    libfreetype6=2.13.3+dfsg-1+deb13u1 \
    libxext6=2:1.3.4-1+b3 \
    libxrender1=1:0.9.12-1 \
    fonts-dejavu=2.37-8 \
    tesseract-ocr=5.5.0-1+b1 \
    tesseract-ocr-eng=1:4.1.0-2 \
    libreoffice=4:25.2.3-2+deb13u5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ./app /app/app
# COPY ./.env /app/.env
RUN addgroup --system lambda \
    && adduser --system --ingroup lambda lambdauser

USER lambdauser

EXPOSE 8000

# ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["app.main.handler"]



# ==============================
# Base image
# ==============================
# FROM public.ecr.aws/docker/library/python:3.11-slim AS base

# WORKDIR /app


# # ==============================
# # Pipenv generator
# # ==============================
# FROM base AS pipenv-generator

# COPY requirements.txt /app/

# RUN pip install --no-cache-dir pipenv
# RUN pipenv install -r /app/requirements.txt


# # ==============================
# # Runtime image
# # ==============================
# FROM base AS runtime

# COPY requirements.txt /app/

# RUN pip install --no-cache-dir -r /app/requirements.txt

# COPY ./app /app/app

# RUN addgroup --system lambda \
#     && adduser --system --ingroup lambda lambdauser

# USER lambdauser

# EXPOSE 8000

# ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]