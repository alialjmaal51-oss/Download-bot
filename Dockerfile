FROM python:3.10-slim

# تثبيت الاعتماديات النظامية
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# إنشاء مستخدم غير جذري
RUN useradd -m -u 1000 user

# التبديل إلى المستخدم
USER user

# تعيين متغيرات البيئة
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# إنشاء مجلد العمل
WORKDIR $HOME/app

# نسخ ملف المتطلبات
COPY --chown=user requirements.txt $HOME/app/requirements.txt

# تثبيت الاعتماديات
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# نسخ باقي الملفات
COPY --chown=user . $HOME/app

# تشغيل التطبيق
CMD ["python", "app.py"]