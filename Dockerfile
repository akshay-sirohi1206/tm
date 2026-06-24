FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

# System tools install kiya requirements build karne ke liye
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev build-essential && rm -rf /var/lib/apt/lists/*

# Ab direct requirements copy ho jayegi kyunki git isi folder ka root h
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki saara code copy kiya
COPY . .

EXPOSE 8000

CMD ["uvicorn", "mainV2:app", "--host", "0.0.0.0", "--port", "8000"]

