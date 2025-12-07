import os
import io
import threading
from collections import defaultdict, OrderedDict

from telethon import TelegramClient, events, types
from flask import Flask
from PIL import Image, ImageDraw, ImageFont
import easyocr
import numpy as np

# ====== Credentials (তোমার দেয়া) ======
API_ID = 28179017
API_HASH = "3eccbcc092d1a95e5c633913bfe0d9e9"
BOT_TOKEN = "8080322939:AAG6sVck-WSdRFkPNJfBRe9-MGQwpO71kkM"
# =======================================

# Flask (Render needs open port)
app = Flask(__name__)

@app.route("/")
def home():
    return "FF Tournament Bot is running!"

# Telethon bot client
bot = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# OCR reader (use english)
reader = easyocr.Reader(['en'], gpu=False)  # gpu=True if available

# In-memory storage for incoming images per user (chat id)
# structure: {chat_id: [bytes_images...]}
user_images = defaultdict(list)

# Default point table for placements (change easily)
PLACEMENT_POINTS = {
    1: 12, 2: 9, 3: 8, 4: 7, 5: 6, 6: 5,
    7: 4, 8: 3, 9: 2, 10: 1, 11: 0, 12: 0
}
KILL_POINT = 1  # per kill

# helper: run OCR on PIL image, return combined text lines
def ocr_image_get_lines(pil_img):
    np_img = np.array(pil_img)
    results = reader.readtext(np_img, detail=0)  # detail=0 returns text list
    # join with newline for easier regex scanning
    joined = "\n".join(results)
    return joined, results

# heuristic parser: find squad name, kills, placement if available
import re

def parse_texts_for_teams(all_texts_list):
    """
    Input: list of OCR-detected text lines from one or more screenshots.
    Returns: ordered list of dicts: {'name':str, 'kills':int, 'placement':int or None}
    """
    texts = []
    for t in all_texts_list:
        # split long lines into parts by 'Eliminations' or 'Elimination' token
        parts = re.split(r'(Eliminations|Elimination)', t, flags=re.IGNORECASE)
        # reassemble to keep 'Eliminations' markers
        if len(parts) >= 3:
            # parts in groups: [prefix, 'Eliminations', suffix, ...]
            # combine sliding windows
            idx = 0
            while idx < len(parts)-1:
                # take prefix + marker
                prefix = parts[idx].strip()
                marker = parts[idx+1]
                combined = (prefix + " " + marker).strip()
                texts.append(combined)
                idx += 2
            # leftover maybe
            if idx < len(parts):
                leftover = parts[idx].strip()
                if leftover:
                    texts.append(leftover)
        else:
            texts.append(t.strip())

    # Now extract lines that contain 'Elimin' to find kills
    team_entries = []
    for line in texts:
        if re.search(r'elim', line, flags=re.IGNORECASE):
            # try to find a number just before "Elimin"
            m = re.search(r'(\d{1,2})\s*(?:Elimin)', line, flags=re.IGNORECASE)
            if m:
                kills = int(m.group(1))
                # name is the text before that number
                name_part = line[:m.start()].strip()
                # remove stray words like 'Eliminations' etc
                name_part = re.sub(r'[^A-Za-z0-9\-\_\u00C0-\u024F\s\.\✪\★\☆\u2605\u263A\u2620]', '', name_part)
                name_part = name_part.strip()
                # sometimes ranking digit is present at start like '1' or '2'
                # try to capture a placement number if present at start of name_part
                placement = None
                pm = re.match(r'^(\d{1,2})\b', name_part)
                if pm:
                    placement = int(pm.group(1))
                    # remove that from name
                    name_part = name_part[pm.end():].strip()
                if name_part == "":
                    # fallback: try to get nearby token from full OCR results
                    name_part = "Unknown"
                team_entries.append({'name': name_part, 'kills': kills, 'placement': placement})
            else:
                # If no number captured, still try to find any number in the line
                m2 = re.search(r'(\d{1,2})', line)
                if m2:
                    kills = int(m2.group(1))
                    name_part = re.sub(r'[^A-Za-z0-9\-\_\u00C0-\u024F\s\.\✪\★\☆\u2605\u263A\u2620]', '', line[:m2.start()]).strip()
                    if name_part == "":
                        name_part = "Unknown"
                    team_entries.append({'name': name_part, 'kills': kills, 'placement': None})
    # Deduplicate preserving first-seen order by name (some names repeat across screenshots)
    ordered = OrderedDict()
    for entry in team_entries:
        key = entry['name']
        if key in ordered:
            # if another entry exists, sum kills and keep lowest placement if any
            ordered[key]['kills'] += entry['kills']
            if ordered[key]['placement'] is None and entry['placement'] is not None:
                ordered[key]['placement'] = entry['placement']
        else:
            ordered[key] = entry.copy()
    # If placements are mostly None, we will assign placements by occurrence order (1..n)
    final = list(ordered.values())
    return final

# compute points
def compute_points(entries):
    """
    entries: list of {'name','kills','placement'}
    returns: list of {'name','kills','placement','points'}
    """
    # if placement missing for many, assign based on sorting by kills desc — but better: keep order
    # We'll assign placement by existing 'placement' if present; otherwise assign sequential placement by current order.
    # First check if any placement exist
    any_placement = any(e.get('placement') for e in entries)
    if not any_placement:
        # assign placements by order in entries as fallback
        for idx, e in enumerate(entries, start=1):
            e['placement'] = idx
    else:
        # for missing placement, set None -> determine via ranking by kills (descending)
        missing = [e for e in entries if e.get('placement') is None]
        if missing:
            # compute ranking by kills among those with no placement
            missing_sorted = sorted(missing, key=lambda x: x['kills'], reverse=True)
            # find unused placements
            used = set(e['placement'] for e in entries if e.get('placement'))
            candidate = 1
            for m in missing_sorted:
                while candidate in used:
                    candidate += 1
                m['placement'] = candidate
                used.add(candidate)
    # now compute points
    result = []
    for e in entries:
        pl = int(e.get('placement') or 0)
        placement_pts = PLACEMENT_POINTS.get(pl, 0)
        kills = int(e.get('kills') or 0)
        total = placement_pts + kills * KILL_POINT
        result.append({'name': e['name'], 'kills': kills, 'placement': pl, 'points': total})
    # sort final by points desc
    result_sorted = sorted(result, key=lambda x: x['points'], reverse=True)
    return result_sorted

# table image generator (simple tournament-themed)
def generate_table_image(result_rows, title="FF TOURNAMENT POINT TABLE"):
    # layout params
    cols = ["Squad", "Plc", "Kills", "Points"]
    row_height = 48
    header_height = 70
    padding = 20
    width = 900
    height = header_height + (len(result_rows) + 1) * row_height + padding*2

    img = Image.new("RGB", (width, height), color=(18,18,30))  # dark bg
    draw = ImageDraw.Draw(img)

    # fonts (use default PIL font if truetype not available)
    try:
        font_title = ImageFont.truetype("arial.ttf", 28)
        font_header = ImageFont.truetype("arial.ttf", 18)
        font_row = ImageFont.truetype("arial.ttf", 16)
    except:
        font_title = ImageFont.load_default()
        font_header = ImageFont.load_default()
        font_row = ImageFont.load_default()

    # Title
    draw.text((padding, padding), title, font=font_title, fill=(255,215,0))  # gold-ish

    # header background
    header_y = padding + 36
    draw.rectangle([(padding, header_y), (width - padding, header_y + header_height - 18)], fill=(28,36,64))
    # draw column headers
    col_x = [padding + 10, 480, 620, 740]
    for i, c in enumerate(cols):
        draw.text((col_x[i], header_y + 12), c, font=font_header, fill=(255,255,255))

    # rows
    start_y = header_y + header_height - 6
    for i, row in enumerate(result_rows):
        y = start_y + i * row_height
        # alternate row fill
        if i % 2 == 0:
            draw.rectangle([(padding, y), (width - padding, y + row_height)], fill=(24,24,36))
        else:
            draw.rectangle([(padding, y), (width - padding, y + row_height)], fill=(20,20,28))
        # draw values
        draw.text((col_x[0], y + 12), str(i+1) + ". " + row['name'], font=font_row, fill=(235,235,235))
        draw.text((col_x[1], y + 12), str(row['placement']), font=font_row, fill=(255,255,255))
        draw.text((col_x[2], y + 12), str(row['kills']), font=font_row, fill=(255,255,255))
        draw.text((col_x[3], y + 12), str(row['points']), font=font_row, fill=(255,215,0))

    # footer / notes
    draw.text((padding, height - padding - 10),
              f"Placement pts + {KILL_POINT} pt per kill", font=font_header, fill=(180,180,180))

    # return bytes
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)
    return b

# Bot command: /points -> start flow
@bot.on(events.NewMessage(pattern=r"^/points$"))
async def points_command(event):
    chat = await event.get_chat()
    cid = event.chat_id
    user_images[cid] = []  # reset any previous
    await event.reply("Send 6 screenshots one by one. After sending 6 images, I'll process and send the point table.")

# Handler: when user sends a photo
@bot.on(events.NewMessage(func=lambda e: e.message.photo is not None))
async def photo_handler(event):
    cid = event.chat_id
    # only accept if user started /points
    if cid not in user_images:
        # ignore or ask to start
        await event.reply("Please send /points first to start the point-table creation process.")
        return

    # download photo bytes
    img_bytes = await event.message.download_media(bytes)
    user_images[cid].append(img_bytes)
    count = len(user_images[cid])
    await event.reply(f"Received screenshot {count}/6.")

    # once 6 images received -> process
    if count >= 6:
        await event.reply("Processing images now. This may take a few seconds...")
        # run processing in background thread to avoid blocking Telethon event loop
        threading.Thread(target=process_and_send_table, args=(cid, event)).start()

def process_and_send_table(cid, event):
    try:
        imgs_bytes = user_images.get(cid, [])[:6]
        all_lines = []
        all_lists = []
        for b in imgs_bytes:
            pil = Image.open(io.BytesIO(b)).convert("RGB")
            joined, lines = ocr_image_get_lines(pil)
            # append both joined and individual lines
            all_lines.append(joined)
            all_lists.extend(lines)
        # parse
        parsed = parse_texts_for_teams(all_lists)
        if not parsed:
            # fallback: try splitting joined text by newline tokens and searching numeric kills
            fallback_entries = []
            for txt in all_lines:
                for m in re.finditer(r'([A-Za-z0-9\-\_\s]{2,30})\s+(\d{1,2})\s+Elimin', txt, flags=re.IGNORECASE):
                    name = m.group(1).strip()
                    kills = int(m.group(2))
                    fallback_entries.append({'name': name, 'kills': kills, 'placement': None})
            parsed = fallback_entries

        # compute final points
        final = compute_points(parsed)
        # generate image
        png_bytes = generate_table_image(final)
        # send back to user
        # Telethon sending must be done in async loop — use event.client.loop to schedule
        async def send_image():
            await event.reply("Here is the points table:")
            await event.client.send_file(cid, png_bytes, caption="Tournament Points Table")
            # cleanup
            if cid in user_images:
                del user_images[cid]
        # schedule coroutine
        import asyncio
        asyncio.get_event_loop().create_task(send_image())
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        async def send_error():
            await event.reply("Processing failed. Error: " + str(e))
            await event.reply("Traceback:\n" + tb[:1000])
            if cid in user_images:
                del user_images[cid]
        import asyncio
        asyncio.get_event_loop().create_task(send_error())

# start bot in background thread
def run_bot():
    print("Telegram bot started...")
    bot.run_until_disconnected()

def run_flask():
    # Render sets PORT env var; default 10000 for safety
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    run_flask()
