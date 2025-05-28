import requests
import urllib.parse
import json
import os
import asyncio
import urllib3
from pyrogram.errors import FloodWait
import asyncio

async def safe_reply(message, text):
    try:
        await message.reply_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await message.reply_text(text)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient
from datetime import datetime, timezone

API_ID = 26614080
API_HASH = "7d2c9a5628814e1430b30a1f0dc0165b"
BOT_TOKEN = "8096415693:AAG4pJXX558c6LxCVaJHMqzXXCcGVhhoQFs"
CHANNEL_ID = -1002537575674  # Private channel ID
LOG_CHANNEL_ID = -1002683262330  # Log channel ID (replace with your log channel)
MONGO_URL = "mongodb+srv://padigo6784:8CQy1fuxFourJbqH@cluster0.goi41z2.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# MongoDB setup
mongo = MongoClient(MONGO_URL)
db = mongo["teraboxbot"]
users_col = db["users"]
logs_col = db["logs"]
files_col = db["files"]

# Pyrogram client
app = Client("teraboxbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def is_valid_terabox_url(url: str) -> bool:
    domains = [
        'terabox.com', 'freeterabox.com', '1024terabox.com',
        'teraboxapp.com', 'terabox.app', 'teraboxlink.com'
    ]
    return any(domain in url.lower() for domain in domains)

def get_video_info(terabox_url: str):
    try:
        if not is_valid_terabox_url(terabox_url):
            return {"error": "Invalid TeraBox URL"}
        encoded_url = urllib.parse.quote(terabox_url, safe='')
        api_url = f"https://terabox.sg61x.workers.dev?url={encoded_url}"
        response = requests.get(api_url, timeout=30, verify=False)  # <-- yahan verify=False add karein
        if response.status_code == 200:
            raw_data = response.json()
            if raw_data.get("status") != "success":
                return {"error": "API returned error status"}
            data = raw_data.get("data", {})
            structure = data.get("structure", {})
            if structure:
                return structure
            else:
                return {"error": "No video data found in API response"}
        else:
            return {"error": f"API request failed with status {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

def download_video(download_url: str, filename: str) -> tuple:
    try:
        os.makedirs('downloads', exist_ok=True)
        file_path = os.path.join('downloads', filename)
        with requests.get(download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return True, file_path
    except Exception as e:
        return False, str(e)

@app.on_message(filters.private & filters.text & ~filters.command(["start", "help"]))
async def handle_url(client: Client, message: Message):
    text = message.text.strip()
    url = text  # <-- yeh line add karein

    user_id = message.from_user.id
    username = message.from_user.username or ""
    # Save user info to MongoDB
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"username": username, "last_active": datetime.now(timezone.utc)}},
        upsert=True
    )

    if not is_valid_terabox_url(url):
        await safe_reply(message, "❌ Invalid TeraBox URL.\nSend a valid TeraBox link.")
        return

    await message.reply_text("⏳ Processing your request...")

    video_info = get_video_info(url)
    if "error" in video_info:
        if "status 500" in video_info["error"]:
            await message.reply_text("❌ TeraBox server busy hai ya down hai. Thodi der baad try karein.")
        else:
            await message.reply_text(f"❌ Error: {video_info['error']}")
        logs_col.insert_one({
            "user_id": user_id,
            "username": username,
            "url": url,
            "error": video_info['error'],
            "time": datetime.now(timezone.utc)
        })
        return

    filename = video_info.get('file_name', 'Unknown')
    size = video_info.get('size', 'Unknown')
    sizebytes = video_info.get('sizebytes', 0)
    download_url = (video_info.get('download_url') or 
                    video_info.get('direct_link') or 
                    video_info.get('dlink'))

    if not download_url:
        await message.reply_text("❌ No download URL found.")
        return

    if sizebytes > 50 * 1024 * 1024:
        await message.reply_text(
            "❌ Sorry, this bot can only send files up to 50MB due to Telegram limits.\n"
            "Please try another (smaller) TeraBox video URL."
        )
        return

    # Download file to temp
    await message.reply_text("⬇️ Downloading video...")

    success, file_path = download_video(download_url, filename)
    if not success:
        await message.reply_text(f"❌ Download Failed: {file_path}")
        logs_col.insert_one({
            "user_id": user_id,
            "username": username,
            "url": url,
            "error": file_path,
            "time": datetime.now(timezone.utc)
        })
        return

    try:
        # 1. Upload to database channel
        sent = await client.send_video(
            chat_id=CHANNEL_ID,
            video=file_path,
            caption=f"Uploaded by [{username}](tg://user?id={user_id})\nFile: `{filename}`\nSize: {size}"
        )
        # 2. Forward to user using file_id
        await message.reply_video(
            video=sent.video.file_id,
            caption=f"✅ Downloaded Successfully!\n\n📝 File: `{filename}`\n📏 Size: {size}"
        )
        # 3. Log to log channel
        await client.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=f"User: [{username}](tg://user?id={user_id})\nFile: `{filename}`\nSize: {size}\nURL: {url}"
        )
        # 4. Save file info to MongoDB
        files_col.insert_one({
            "user_id": user_id,
            "username": username,
            "file_id": sent.video.file_id,
            "filename": filename,
            "size": size,
            "url": url,
            "time": datetime.now(timezone.utc)
        })
    except Exception as e:
        await message.reply_text(f"❌ Upload Failed: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "🤖 TeraBox Download Bot\n\n"
        "Send any TeraBox video URL and I'll download it for you!\n"
        "Use /help for more info."
    )

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(
        "🆘 How to use this bot:\n\n"
        "1️⃣ Copy any TeraBox video URL\n"
        "2️⃣ Send it to this bot\n"
        "3️⃣ Wait for processing\n"
        "4️⃣ Download your video!\n\n"
        "Example URLs:\n"
        "• https://terabox.com/s/1abc123\n"
        "• https://freeterabox.com/s/1xyz789\n"
        "• https://teraboxlink.com/s/1def456\n\n"
        "⚠️ Note:\n"
        "- Only video files are supported\n"
        "- File size limit: 50MB (Telegram limit)\n"
        "- Processing may take a few seconds\n\n"
        "Need more help? Contact @your_username"
    )

if __name__ == "__main__":
    print("🤖 TeraBox Pyrogram Bot Started!")
    app.run()
