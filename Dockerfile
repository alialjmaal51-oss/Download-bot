# استخدام نسخة بايثون رسمية وخفيفة
FROM python:3.9-slim

# تحديث النظام وتثبيت أدوات أساسية
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# تحديد مجلد العمل داخل السيرفر
WORKDIR /app

# نسخ ملف المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# أمر تشغيل البوت
CMD ["python", "app.py"]
