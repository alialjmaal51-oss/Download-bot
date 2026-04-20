import os
import re
import asyncio
import threading
import subprocess
import sys
import time
import tempfile
import humanize
import requests
import aiohttp
from urllib.parse import urlparse, unquote
from datetime import datetime, timedelta
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

# -------------------- تثبيت وتحديث yt-dlp --------------------
def upgrade_yt_dlp():
    try:
        # إلغاء تثبيت الإصدارات القديمة
        subprocess.check_call([sys.executable, "-m", "pip", "uninstall", "-y", "yt-dlp", "yt-dlp-nightly"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        # تثبيت أحدث إصدار
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp-nightly"])
        print("✅ yt-dlp upgraded successfully")
    except Exception as e:
        print(f"⚠️ Failed to upgrade yt-dlp: {e}")

upgrade_yt_dlp()

# -------------------- خادم Flask لـ Hugging Face --------------------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "HY Downloader Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=7860)

threading.Thread(target=run_flask, daemon=True).start()

# -------------------- إعدادات البوت --------------------
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
COOKIES_FILE = os.getenv("COOKIES_FILE", "")
COOKIES_STRING = os.getenv("COOKIES_STRING", "")

# البحث التلقائي عن ملف cookies.txt في نفس المجلد
if not COOKIES_FILE and os.path.exists("cookies.txt"):
    COOKIES_FILE = "cookies.txt"
    print("✅ تم العثور على cookies.txt تلقائياً")

# إنشاء ملف كوكيز مؤقت إذا وُجد COOKIES_STRING
temp_cookies_file = None
if COOKIES_STRING and not COOKIES_FILE:
    try:
        temp_cookies_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        temp_cookies_file.write(COOKIES_STRING)
        temp_cookies_file.close()
        COOKIES_FILE = temp_cookies_file.name
        print("✅ تم استخدام COOKIES_STRING")
    except Exception as e:
        print(f"⚠️ فشل إنشاء ملف مؤقت: {e}")

if not BOT_TOKEN:
    raise ValueError("Missing BOT_TOKEN")

bot = Client("HY_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# -------------------- بيانات المستخدمين المؤقتة --------------------
user_data = {}

# -------------------- دوال مساعدة --------------------
def format_size(size_bytes):
    if not size_bytes or size_bytes <= 0:
        return "غير معروف"
    return humanize.naturalsize(size_bytes)

def format_time(seconds):
    if not seconds or seconds <= 0:
        return "غير معروف"
    return str(timedelta(seconds=int(seconds)))

def create_red_progress_bar(percentage, width=20):
    filled = int(width * percentage / 100)
    return "🔴" * filled + "⚪" * (width - filled)

def is_video_url(url):
    video_patterns = [
        r'youtube\.com', r'youtu\.be', r'facebook\.com', r'fb\.watch',
        r'vimeo\.com', r'dailymotion\.com', r'tiktok\.com', r'vt\.tiktok\.com',
        r'instagram\.com', r'twitter\.com', r'x\.com', r'twitch\.tv',
        r'tumblr\.com', r'reddit\.com', r'vk\.com', r'ok\.ru', r'coub\.com',
        r'bilibili\.com', r'soundcloud\.com'
    ]
    return any(re.search(pattern, url.lower()) for pattern in video_patterns)

def is_github_repo(url):
    parsed = urlparse(url)
    if parsed.netloc != 'github.com':
        return False
    path_parts = parsed.path.strip('/').split('/')
    return len(path_parts) >= 2 and not any(part in path_parts for part in ['raw', 'blob', 'tree', 'releases'])

def is_direct_file(url):
    parsed = urlparse(url)
    path = unquote(parsed.path)
    file_extensions = [
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
        '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a',
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp',
        '.txt', '.md', '.json', '.xml', '.csv',
        '.exe', '.msi', '.deb', '.rpm', '.apk',
        '.py', '.js', '.html', '.css', '.php', '.java', '.c', '.cpp'
    ]
    if any(path.lower().endswith(ext) for ext in file_extensions):
        return True
    try:
        head = requests.head(url, allow_redirects=True, timeout=5)
        content_type = head.headers.get('Content-Type', '')
        if 'application/octet-stream' in content_type or 'application/zip' in content_type:
            return True
        if 'text/html' not in content_type and content_type:
            return True
    except:
        pass
    return False

def get_github_repo_download_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    for branch in ['main', 'master']:
        zip_url = f"https://github.com/{path}/archive/refs/heads/{branch}.zip"
        try:
            resp = requests.head(zip_url, allow_redirects=True, timeout=5)
            if resp.status_code == 200:
                return zip_url
        except:
            continue
    return None

# -------------------- استخراج صيغ الفيديو (محسّن لجميع المواقع) --------------------
def get_video_formats(url):
    try:
        import yt_dlp
    except ImportError:
        return None, "❌ yt-dlp غير مثبت"

    # إعدادات متقدمة لاستخراج المعلومات
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'geo_bypass': True,
        'sleep_interval': 1,
        'max_sleep_interval': 3,
        'socket_timeout': 30,
        'retries': 10,
        'file_access_retries': 10,
        'extractor_retries': 5,
    }
    
    # إضافة إعدادات خاصة بكل موقع
    ydl_opts['extractor_args'] = {
        'youtube': {
            'player_client': ['web', 'android'],
            'skip': ['hls', 'dash'],
            'player_skip': ['configs', 'webpage'],
        },
        'facebook': {
            'prefer_https': True,
            'allow_unplayable_formats': False,
        },
        'tiktok': {
            'api_hostname': 'www.tiktok.com',
        }
    }
    
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            # إذا لم توجد صيغ، نحاول استخراج أفضل تنسيق مباشر
            if not formats and info.get('url'):
                return [{
                    'format_id': 'best',
                    'resolution': 'أفضل جودة',
                    'size': info.get('filesize', 0),
                    'is_audio': False,
                }], None
            
            video_formats = []
            audio_formats = []
            seen_resolutions = set()
            
            for f in formats:
                if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
                    continue
                
                # تنسيق صوت فقط
                if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    size = f.get('filesize') or f.get('filesize_approx') or 0
                    audio_formats.append({
                        'format_id': f['format_id'],
                        'resolution': 'mp3',
                        'size': size,
                        'is_audio': True,
                    })
                    continue
                
                # استخراج الدقة
                width = f.get('width', 0)
                height = f.get('height', 0)
                format_note = f.get('format_note', '')
                
                if width and height:
                    resolution = f"{width}x{height}"
                elif format_note:
                    if 'p' in format_note:
                        match = re.search(r'(\d+)p', format_note)
                        if match:
                            resolution = f"{match.group(1)}p"
                        else:
                            resolution = format_note
                    else:
                        resolution = format_note
                else:
                    resolution = 'فيديو'
                
                # تجنب التكرار
                if resolution in seen_resolutions:
                    continue
                seen_resolutions.add(resolution)
                
                size = f.get('filesize') or f.get('filesize_approx') or 0
                video_formats.append({
                    'format_id': f['format_id'],
                    'resolution': resolution,
                    'size': size,
                    'is_audio': False,
                })
            
            # ترتيب حسب الدقة
            def get_resolution_number(f):
                res = f['resolution']
                if 'x' in res:
                    try:
                        return int(res.split('x')[0])
                    except:
                        return 0
                elif 'p' in res:
                    try:
                        return int(res.replace('p', ''))
                    except:
                        return 0
                return 0
            
            video_formats.sort(key=get_resolution_number, reverse=True)
            video_formats = video_formats[:10]
            
            # إضافة أفضل تنسيق صوت
            if audio_formats:
                audio_formats.sort(key=lambda x: x.get('size', 0), reverse=True)
                best_audio = audio_formats[0]
                best_audio['resolution'] = 'mp3'
                all_formats = video_formats + [best_audio]
            else:
                all_formats = video_formats
            
            # إذا لم نجد أي صيغ، نضيف خيار التحميل المباشر
            if not all_formats:
                all_formats = [{
                    'format_id': 'best',
                    'resolution': 'تحميل مباشر',
                    'size': 0,
                    'is_audio': False,
                }]
            
            return all_formats, None
    except Exception as e:
        error_msg = str(e)
        # محاولة بديلة: استخدام format best
        try:
            ydl_opts_alt = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best',
            }
            with yt_dlp.YoutubeDL(ydl_opts_alt) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get('url'):
                    return [{
                        'format_id': 'best',
                        'resolution': 'تحميل مباشر',
                        'size': info.get('filesize', 0),
                        'is_audio': False,
                    }], None
        except:
            pass
        return None, error_msg

# -------------------- تحميل الفيديو (مع إعادة المحاولة) --------------------
async def download_video_with_format(url, user_id, status_msg, format_id, is_audio=False):
    try:
        import yt_dlp
    except ImportError:
        await status_msg.edit_text("❌ yt-dlp not installed.")
        return

    ydl_opts = {
        'outtmpl': '%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'restrictfilenames': True,
        'progress_hooks': [],
        'geo_bypass': True,
        'sleep_interval': 1,
        'max_sleep_interval': 3,
        'socket_timeout': 30,
        'retries': 10,
        'file_access_retries': 10,
        'extractor_retries': 5,
    }

    if is_audio:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif format_id == 'best':
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    else:
        ydl_opts['format'] = format_id

    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    progress = {'downloaded': 0, 'total': 0, 'speed': 0, 'eta': 0, 'percent': 0}

    def progress_hook(d):
        if d['status'] == 'downloading':
            if 'total_bytes' in d:
                progress['total'] = d['total_bytes']
            elif 'total_bytes_estimate' in d:
                progress['total'] = d['total_bytes_estimate']
            progress['downloaded'] = d.get('downloaded_bytes', 0)
            progress['speed'] = d.get('speed', 0)
            progress['eta'] = d.get('eta', 0)
            if progress['total'] > 0:
                progress['percent'] = (progress['downloaded'] / progress['total']) * 100

    ydl_opts['progress_hooks'].append(progress_hook)

    async def update_progress():
        last_percent = 0
        while progress['total'] == 0 and progress['percent'] == 0:
            await asyncio.sleep(1)
        while progress['percent'] < 99.9:
            await asyncio.sleep(2)
            percent = progress['percent']
            if percent == last_percent:
                continue
            last_percent = percent
            bar = create_red_progress_bar(percent)
            speed = progress['speed']
            eta = progress['eta']
            text = (
                f"**📥 جاري التحميل {percent:.1f}%**\n\n"
                f"{bar}  **{percent:.1f}%**\n\n"
                f"📦 {format_size(progress['downloaded'])} / {format_size(progress['total'])}\n"
                f"⚡ {format_size(speed)}/s\n"
                f"⏱️ الوقت المتبقي: {format_time(eta)}"
            )
            try:
                await status_msg.edit_text(text)
            except:
                pass

    loop = asyncio.get_event_loop()
    updater = asyncio.create_task(update_progress())

    # دالة التحميل مع إعادة المحاولة
    async def download_with_retry(retries=3):
        last_error = None
        for attempt in range(retries):
            try:
                info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True))
                return info, None
            except Exception as e:
                last_error = e
                error_str = str(e)
                if "sign in to confirm" in error_str.lower():
                    break
                if attempt < retries - 1:
                    await status_msg.edit_text(f"⚠️ فشل التحميل، إعادة المحاولة {attempt+2}/{retries}...")
                    await asyncio.sleep(3)
        return None, last_error

    info, download_error = await download_with_retry(retries=3)

    if download_error or not info:
        updater.cancel()
        error_msg = str(download_error) if download_error else "Unknown error"
        if "sign in to confirm" in error_msg.lower():
            await status_msg.edit_text(
                "❌ **الموقع يطلب تأكيد أنك لست بوتاً.**\n\n"
                "لحل المشكلة:\n"
                "1. ثبت إضافة 'Get cookies.txt LOCALLY' على متصفح Firefox.\n"
                "2. سجل الدخول إلى الموقع.\n"
                "3. قم بتصدير الكوكيز ورفع الملف إلى مجلد المشروع باسم `cookies.txt`.\n"
                "4. أعد تشغيل البوت."
            )
        elif "private video" in error_msg.lower() or "private" in error_msg.lower():
            await status_msg.edit_text("❌ هذا الفيديو خاص، لا يمكن تحميله.")
        elif "copyright" in error_msg.lower():
            await status_msg.edit_text("❌ الفيديو محمي بحقوق الطبع والنشر.")
        else:
            await status_msg.edit_text(f"❌ فشل التحميل: {error_msg[:150]}")
        
        for f in os.listdir('.'):
            if f.endswith('.part') or f.endswith('.ytdl'):
                try:
                    os.remove(f)
                except:
                    pass
        return

    # تحديد اسم الملف
    try:
        if is_audio:
            filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
            filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3').replace('.opus', '.mp3')
            if not os.path.exists(filename):
                for f in os.listdir('.'):
                    if info['title'] in f and f.endswith('.mp3') and not f.endswith('.part'):
                        filename = f
                        break
        else:
            filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
            if not os.path.exists(filename):
                for f in os.listdir('.'):
                    if info['title'] in f and not f.endswith('.part') and not f.endswith('.ytdl'):
                        filename = f
                        break
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ في تحديد الملف: {str(e)[:100]}")
        updater.cancel()
        return

    if os.path.exists(filename):
        await status_msg.edit_text(f"📤 **جاري رفع الملف 0%**")
        start_upload = time.time()
        total_size = os.path.getsize(filename)

        async def upload_progress(current, total):
            percent = (current / total) * 100
            bar = create_red_progress_bar(percent)
            elapsed = time.time() - start_upload
            speed = current / elapsed if elapsed > 0 else 0
            eta = (total - current) / speed if speed > 0 else 0
            text = (
                f"**📤 جاري رفع الملف {percent:.1f}%**\n\n"
                f"{bar}  **{percent:.1f}%**\n\n"
                f"📦 {format_size(current)} / {format_size(total)}\n"
                f"⚡ {format_size(speed)}/s\n"
                f"⏱️ الوقت المتبقي: {format_time(eta)}"
            )
            try:
                await status_msg.edit_text(text)
            except:
                pass

        if is_audio:
            caption = (
                f"✅ **تم التحميل بنجاح!**\n\n"
                f"🎵 **العنوان:** {info['title']}\n"
                f"📊 **الحجم:** {format_size(total_size)}\n"
                f"⏱️ **المدة:** {format_time(info.get('duration', 0))}\n"
                f"👤 **الناشر:** {info.get('uploader', 'غير معروف')}\n\n"
                f"🛡 **HY Downloader**"
            )
        else:
            caption = (
                f"✅ **تم التحميل بنجاح!**\n\n"
                f"🎬 **العنوان:** {info['title']}\n"
                f"📊 **الحجم:** {format_size(total_size)}\n"
                f"⏱️ **المدة:** {format_time(info.get('duration', 0))}\n"
                f"👤 **الناشر:** {info.get('uploader', 'غير معروف')}\n\n"
                f"🛡 **HY Downloader**"
            )

        try:
            await bot.send_document(
                user_id,
                document=filename,
                caption=caption,
                progress=upload_progress
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ فشل رفع الملف: {str(e)[:100]}")
        finally:
            try:
                os.remove(filename)
            except:
                pass
            await status_msg.delete()
    else:
        await status_msg.edit_text("❌ لم يتم العثور على الملف المحمل")

    updater.cancel()
    for f in os.listdir('.'):
        if f.endswith('.part') or f.endswith('.ytdl') or (is_audio and f.endswith(('.webm', '.m4a', '.opus'))):
            try:
                os.remove(f)
            except:
                pass

# -------------------- تحميل الملفات المباشرة --------------------
async def download_file_and_send(url, user_id, status_msg, filename=None):
    if not filename:
        filename = url.split('/')[-1].split('?')[0]
        if not filename or '.' not in filename:
            filename = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
    filepath = filename
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await status_msg.edit_text(f"❌ فشل التحميل (HTTP {resp.status})")
                    return
                total = int(resp.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()
                with open(filepath, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(1024*1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            percent = downloaded / total * 100
                            elapsed = time.time() - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            eta = (total - downloaded) / speed if speed > 0 else 0
                            bar = create_red_progress_bar(percent)
                            text = (
                                f"**📥 جاري التحميل {percent:.1f}%**\n\n"
                                f"{bar}  **{percent:.1f}%**\n\n"
                                f"📦 {format_size(downloaded)} / {format_size(total)}\n"
                                f"⚡ {format_size(speed)}/s\n"
                                f"⏱️ الوقت المتبقي: {format_time(eta)}\n"
                                f"⏱️ الوقت المنقضي: {format_time(elapsed)}"
                            )
                            await status_msg.edit_text(text)
                await status_msg.edit_text(f"📤 **جاري رفع الملف 0%**")
                start_upload = time.time()
                caption = f"✅ **تم التحميل بنجاح!**\n\n📄 **الملف:** `{filename}`\n📦 **الحجم:** {format_size(total)}"

                async def upload_progress(current, total):
                    percent = (current / total) * 100
                    bar = create_red_progress_bar(percent)
                    elapsed = time.time() - start_upload
                    speed = current / elapsed if elapsed > 0 else 0
                    eta = (total - current) / speed if speed > 0 else 0
                    text = (
                        f"**📤 جاري رفع الملف {percent:.1f}%**\n\n"
                        f"{bar}  **{percent:.1f}%**\n\n"
                        f"📦 {format_size(current)} / {format_size(total)}\n"
                        f"⚡ {format_size(speed)}/s\n"
                        f"⏱️ الوقت المتبقي: {format_time(eta)}"
                    )
                    try:
                        await status_msg.edit_text(text)
                    except:
                        pass

                await bot.send_document(
                    user_id,
                    document=filepath,
                    caption=caption,
                    progress=upload_progress
                )
                os.remove(filepath)
                await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل التحميل: {str(e)[:150]}")
        if os.path.exists(filepath):
            os.remove(filepath)

async def download_github_repo(url, user_id, status_msg):
    zip_url = get_github_repo_download_url(url)
    if not zip_url:
        await status_msg.edit_text("❌ لم نتمكن من العثور على رابط تحميل المستودع.")
        return
    await download_file_and_send(zip_url, user_id, status_msg, filename="repository.zip")

# -------------------- أوامر البوت --------------------
@bot.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply_text(
        "**✨ HY Downloader Bot ✨**\n\n"
        "أرسل رابط:\n"
        "• فيديو (يوتيوب، فيسبوك، تيك توك، إنستغرام، إلخ) → سأعرض لك خيارات الصيغ المتاحة.\n"
        "• ملف مباشر (mp4, zip, pdf, ...) → سأحمله وأرسله لك.\n"
        "• مستودع GitHub → سأحمل المستودع كـ ZIP.\n\n"
        "**💡 ملاحظة:** يتم عرض نسبة مئوية وشريط تقدم أحمر مع الوقت المتبقي.\n\n"
        "**👨‍💻 المطور:** هيثم محمود الجمال\n"
        "**📱 تواصل:** @albashekaljmaal2"
    )

@bot.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    await start_cmd(client, message)

# -------------------- معالجة الروابط --------------------
@bot.on_message(filters.text & filters.private)
async def handle_url(client, message: Message):
    url = message.text.strip()
    if not url.startswith(('http://', 'https://')):
        await message.reply_text("❌ يرجى إرسال رابط صحيح (http:// أو https://)")
        return

    status_msg = await message.reply_text("🔍 **جاري تحليل الرابط...**")

    if is_github_repo(url):
        await status_msg.edit_text("📦 **جاري تحميل مستودع GitHub...**")
        await download_github_repo(url, message.from_user.id, status_msg)
        return

    if is_direct_file(url):
        await status_msg.edit_text("📥 **جاري تحميل الملف...**")
        await download_file_and_send(url, message.from_user.id, status_msg)
        return

    if is_video_url(url):
        await status_msg.edit_text("🎬 **جاري استخراج صيغ الفيديو المتاحة...**")
        
        # استخدام timeout لاستخراج الصيغ
        try:
            loop = asyncio.get_event_loop()
            formats, error = await asyncio.wait_for(
                loop.run_in_executor(None, get_video_formats, url),
                timeout=45.0
            )
        except asyncio.TimeoutError:
            await status_msg.edit_text("❌ استغرقت عملية استخراج الصيغ وقتاً طويلاً. قد يكون الرابط معطلاً أو الفيديو غير متاح.")
            return
        
        if error or not formats:
            await status_msg.edit_text(f"❌ فشل استخراج الصيغ: {error or 'لا توجد صيغ متاحة'}")
            return

        user_id = message.from_user.id
        user_data[user_id] = {
            'url': url,
            'formats': formats,
            'status_msg_id': status_msg.id,
            'chat_id': message.chat.id
        }

        keyboard = []
        for idx, fmt in enumerate(formats):
            size_str = format_size(fmt['size']) if fmt['size'] else 'غير معروف'
            button_text = f"{fmt['resolution']} - {size_str}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"fmt_{idx}")])

        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(
            "**🎬 اختر الصيغة التي تريد تحميلها:**\n\n"
            "اضغط على أحد الأزرار أدناه لبدء التحميل.",
            reply_markup=reply_markup
        )
        return

    await status_msg.edit_text("❌ لم أتعرف على نوع الرابط. حاول رابط فيديو، ملف مباشر، أو مستودع GitHub.")

# -------------------- معالجة اختيار الصيغة --------------------
@bot.on_callback_query()
async def handle_format_selection(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if user_id not in user_data:
        await callback_query.answer("⚠️ انتهت صلاحية الجلسة، يرجى إرسال الرابط مرة أخرى.", show_alert=True)
        await callback_query.message.delete()
        return

    if data == "cancel":
        await callback_query.answer("تم الإلغاء.")
        await callback_query.message.delete()
        if user_id in user_data:
            del user_data[user_id]
        return

    if data.startswith("fmt_"):
        idx = int(data.split("_")[1])
        formats = user_data[user_id]['formats']
        if idx >= len(formats):
            await callback_query.answer("صيغة غير صالحة.", show_alert=True)
            return

        selected_format = formats[idx]
        format_id = selected_format['format_id']
        is_audio = selected_format.get('is_audio', False)
        url = user_data[user_id]['url']

        await callback_query.answer(f"جاري تحميل {selected_format['resolution']}...")
        await callback_query.message.edit_text(f"🎬 **بدء تحميل {selected_format['resolution']} ...**")

        status_msg = callback_query.message
        del user_data[user_id]

        await download_video_with_format(url, user_id, status_msg, format_id, is_audio)

# -------------------- تشغيل البوت --------------------
if __name__ == "__main__":
    print("🚀 HY Downloader Bot is running...")
    try:
        if temp_cookies_file and os.path.exists(temp_cookies_file.name):
            os.unlink(temp_cookies_file.name)
    except:
        pass
    bot.run()