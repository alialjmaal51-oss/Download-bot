import os
import time
import asyncio
import aiohttp
import humanize
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from fastapi import FastAPI
import uvicorn
from threading import Thread
import math

# إنشاء تطبيق FastAPI لعرض حالة البوت
fastapi_app = FastAPI()

@fastapi_app.get("/")
async def root():
    return {
        "status": "running",
        "bot_name": "Telegram Download Bot",
        "message": "البوت يعمل بشكل طبيعي ✅"
    }

@fastapi_app.get("/health")
async def health():
    return {"status": "healthy"}

# تكوين البوت من المتغيرات البيئية
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not all([API_ID, API_HASH, BOT_TOKEN]):
    print("⚠️ تحذير: بعض المتغيرات البيئية غير موجودة!")

app = Client(
    "download_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# قاموس لتخزين معلومات التحميل لكل مستخدم
download_progress = {}

class DownloadTracker:
    def __init__(self):
        self.start_time = None
        self.last_update_time = None
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = 0
        self.message = None
        self.is_completed = False
        self.file_name = ""
        
def format_bytes(bytes):
    """تحويل البايتات إلى صيغة مقروءة"""
    return humanize.naturalsize(bytes)

def format_speed(bytes_per_second):
    """تنسيق سرعة التحميل"""
    if bytes_per_second < 1024:
        return f"{bytes_per_second:.2f} B/s"
    elif bytes_per_second < 1024 * 1024:
        return f"{bytes_per_second / 1024:.2f} KB/s"
    elif bytes_per_second < 1024 * 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.2f} MB/s"
    else:
        return f"{bytes_per_second / (1024 * 1024 * 1024):.2f} GB/s"

def format_time(seconds):
    """تنسيق الوقت المتبقي"""
    if seconds < 60:
        return f"{seconds:.0f} ثانية"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} دقيقة"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f} ساعة"
    else:
        days = seconds / 86400
        return f"{days:.1f} يوم"

def create_progress_bar(percentage, length=20):
    """إنشاء شريط التقدم"""
    filled_length = int(length * percentage // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"`{bar}`"

async def download_file(url, file_name, message, user_id):
    """تحميل الملف مع عرض التقدم"""
    
    tracker = DownloadTracker()
    tracker.start_time = time.time()
    tracker.last_update_time = time.time()
    tracker.message = message
    tracker.file_name = file_name
    
    download_progress[user_id] = tracker
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                total_size = int(response.headers.get('content-length', 0))
                tracker.total_bytes = total_size
                
                # إنشاء المجلد إذا لم يكن موجوداً (في /tmp للتشغيل على Hugging Face)
                download_dir = "/tmp/downloads"
                os.makedirs(download_dir, exist_ok=True)
                
                file_path = os.path.join(download_dir, file_name)
                
                with open(file_path, 'wb') as f:
                    downloaded = 0
                    
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        tracker.downloaded_bytes = downloaded
                        
                        # حساب السرعة كل ثانية
                        current_time = time.time()
                        if current_time - tracker.last_update_time >= 1:
                            time_diff = current_time - tracker.last_update_time
                            bytes_diff = downloaded - (tracker.downloaded_bytes - len(chunk))
                            tracker.speed = bytes_diff / time_diff
                            tracker.last_update_time = current_time
                            
                            # تحديث شريط التقدم
                            await update_progress_message(user_id)
                
                tracker.is_completed = True
                await update_progress_message(user_id)
                return file_path
                
    except Exception as e:
        await message.edit_text(f"❌ حدث خطأ في التحميل: {str(e)}")
        return None

async def update_progress_message(user_id):
    """تحديث رسالة التقدم"""
    tracker = download_progress.get(user_id)
    if not tracker:
        return
    
    if tracker.total_bytes == 0:
        percentage = 0
    else:
        percentage = (tracker.downloaded_bytes / tracker.total_bytes) * 100
    
    # حساب الوقت المتبقي
    elapsed_time = time.time() - tracker.start_time
    if tracker.speed > 0:
        remaining_bytes = tracker.total_bytes - tracker.downloaded_bytes
        remaining_time = remaining_bytes / tracker.speed
    else:
        remaining_time = 0
    
    # إنشاء شريط التقدم
    progress_bar = create_progress_bar(percentage)
    
    # إنشاء نص التقدم
    if tracker.is_completed:
        text = f"✅ **اكتمل التحميل!**\n\n"
        text += f"📁 **الملف:** `{tracker.file_name}`\n"
        text += f"📊 **الحجم الكلي:** {format_bytes(tracker.total_bytes)}\n"
        text += f"⚡ **متوسط السرعة:** {format_speed(tracker.total_bytes / elapsed_time)}\n"
        text += f"⏱️ **الوقت المستغرق:** {format_time(elapsed_time)}"
    else:
        text = f"**جاري التحميل...**\n\n"
        text += f"📁 **الملف:** `{tracker.file_name}`\n\n"
        text += f"{progress_bar}  **{percentage:.1f}%**\n\n"
        text += f"📥 **تم تحميل:** {format_bytes(tracker.downloaded_bytes)} / {format_bytes(tracker.total_bytes)}\n"
        text += f"⚡ **السرعة:** {format_speed(tracker.speed)}\n"
        text += f"⏳ **الوقت المتبقي:** {format_time(remaining_time)}\n"
        text += f"📊 **الحجم الكلي:** {format_bytes(tracker.total_bytes)}"
    
    # إضافة أزرار إذا اكتمل التحميل
    if tracker.is_completed:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 تحميل ملف آخر", callback_data="new_download")]
        ])
        try:
            await tracker.message.edit_text(text, reply_markup=keyboard)
        except:
            pass
    else:
        try:
            await tracker.message.edit_text(text)
        except:
            pass

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """معالجة أمر البدء"""
    welcome_text = """
👋 **مرحباً بك في بوت التحميل!**

📥 **أرسل لي رابط الملف الذي تريد تحميله**
⚡ **سأقوم بتحميله وعرض التقدم والسرعة والوقت المتبقي**

**مثال:** https://example.com/file.zip
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 قناة البوت", url="https://t.me/your_channel")],
        [InlineKeyboardButton("👨‍💻 المطور", url="https://t.me/your_username")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client, message: Message):
    """معالجة أمر المساعدة"""
    help_text = """
**📚 كيفية استخدام البوت:**

1️⃣ **أرسل رابط الملف** - مباشرة في المحادثة
2️⃣ **انتظر قليلاً** - سيبدأ البوت بتحميل الملف
3️⃣ **شاهد التقدم** - سيظهر لك شريط تقدم أزرق مع:
   - نسبة التقدم
   - الوقت المتبقي
   - سرعة التحميل
   - الحجم الكلي والمنزل
4️⃣ **استلم الملف** - بعد اكتمال التحميل

**⚠️ ملاحظات مهمة:**
- البوت يدعم جميع أنواع الملفات
- الحد الأقصى للحجم: 2 جيجابايت
- يرجى التأكد من صحة الرابط

**💡 مثال:**
`https://example.com/video.mp4`
    """
    
    await message.reply_text(help_text)

@app.on_message(filters.regex(r'^https?://'))
async def handle_url(client, message: Message):
    """معالجة الروابط المرسلة"""
    
    url = message.text.strip()
    
    # إرسال رسالة بدء التحميل
    status_msg = await message.reply_text(
        "🔍 **جاري تحضير التحميل...**\n\n"
        "⏱️ الرجاء الانتظار قليلاً"
    )
    
    # استخراج اسم الملف من الرابط
    file_name = url.split('/')[-1].split('?')[0]
    if not file_name or '.' not in file_name:
        file_name = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
    
    # بدء التحميل
    file_path = await download_file(url, file_name, status_msg, message.from_user.id)
    
    if file_path and os.path.exists(file_path):
        # إرسال الملف بعد اكتمال التحميل
        await status_msg.edit_text("📤 **جاري رفع الملف...**")
        
        try:
            await message.reply_document(
                document=file_path,
                caption=f"✅ **تم التحميل بنجاح!**\n\n📁 `{file_name}`\n📊 {format_bytes(os.path.getsize(file_path))}"
            )
            
            # حذف الملف بعد الرفع
            os.remove(file_path)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ حدث خطأ في رفع الملف: {str(e)}")
    
    elif not file_path:
        await status_msg.edit_text("❌ فشل تحميل الملف. تأكد من صحة الرابط وحاول مرة أخرى.")
    
    # تنظيف بيانات التتبع
    if message.from_user.id in download_progress:
        del download_progress[message.from_user.id]

@app.on_callback_query()
async def handle_callback(client, callback_query):
    """معالجة الأزرار"""
    if callback_query.data == "new_download":
        await callback_query.message.edit_text(
            "📥 **أرسل رابط الملف الجديد**\n\n"
            "يمكنك إرسال الرابط مباشرة..."
        )
    
    await callback_query.answer()

@app.on_message(filters.command("cancel"))
async def cancel_download(client, message: Message):
    """إلغاء التحميل الحالي"""
    user_id = message.from_user.id
    
    if user_id in download_progress and not download_progress[user_id].is_completed:
        download_progress[user_id].is_completed = True  # للتوقف عن التحديث
        await message.reply_text("✅ **تم إلغاء التحميل بنجاح**")
        del download_progress[user_id]
    else:
        await message.reply_text("❌ **لا يوجد تحميل نشط لإلغائه**")

def run_bot():
    """تشغيل البوت في thread منفصل"""
    print("🤖 البوت يعمل...")
    app.run()

# تشغيل البوت في thread منفصل عند بدء التشغيل
Thread(target=run_bot, daemon=True).start()

# نقطة الدخول لـ Hugging Face
if __name__ == "__main__":
    uvicorn.run(fastapi_app, host="0.0.0.0", port=7860)