FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects PORT at runtime; bot.py reads it via os.getenv("PORT", 8080)
CMD ["python", "bot.py"]
