from re import match as re_match, findall as re_findall
from threading import Thread, Event
from time import time
from math import ceil
from html import escape
from psutil import disk_usage, cpu_percent, swap_memory, cpu_count, virtual_memory, net_io_counters, boot_time
from requests import head as rhead
from urllib.request import urlopen
from telegram import InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram.message import Message
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot import download_dict, download_dict_lock, STATUS_LIMIT, botStartTime, DOWNLOAD_DIR, dispatcher, BOT_UNAME
from bot.helper.telegram_helper.button_build import ButtonMaker
import shutil
import psutil

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

URL_REGEX = r"(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-?=%.]+"

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "Uploading...⬘"
    STATUS_DOWNLOADING = "Downloading...⬙"
    STATUS_CLONING = "Cloning..."
    STATUS_WAITING = "Queued..."
    STATUS_FAILED = "Failed . Cleaning Download..."
    STATUS_PAUSE = "Paused..."
    STATUS_ARCHIVING = "Archiving..."
    STATUS_EXTRACTING = "Extracting..."
    STATUS_SPLITTING = "Splitting..."
    STATUS_CHECKING = "CheckingUp..."
    STATUS_SEEDING = "Seeding..."

PROGRESS_MAX_SIZE = 100 // 9
PROGRESS_INCOMPLETE = ['◔', '◔', '◑', '◑', '◑', '◕', '◕']
    
class EngineStatus:
    STATUS_ARIA = "Aria2c v1.35.0"
    STATUS_GDRIVE = "Google API"
    STATUS_GD = "Google Api v2.51.0"
    STATUS_MEGA = "Mega Api v3.12.0"
    STATUS_QB = "qBittorrent v4.4.2"
    STATUS_TG = "Pyrogram v2.0.27"
    STATUS_YT = "YT-dlp v22.5.18"
    STATUS_EXT = "pExtract"
    STATUS_SPLIT = "FFmpeg v2.9.1"
    STATUS_ZIP = "p7zip v16.02"

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = Event()
        thread = Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time() + self.interval
        while not self.stopEvent.wait(nextTime - time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'

def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            status = dl.status()
            if (
                status
                not in [
                    MirrorStatus.STATUS_ARCHIVING,
                    MirrorStatus.STATUS_EXTRACTING,
                    MirrorStatus.STATUS_SPLITTING,
                ]
                and dl.gid() == gid
            ):
                return dl
    return None

def getAllDownload(req_status: str):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            status = dl.status()
            if status not in [MirrorStatus.STATUS_ARCHIVING, MirrorStatus.STATUS_EXTRACTING, MirrorStatus.STATUS_SPLITTING] and dl:
                if req_status == 'down' and (status not in [MirrorStatus.STATUS_SEEDING,
                                                            MirrorStatus.STATUS_UPLOADING,
                                                            MirrorStatus.STATUS_CLONING]):
                    return dl
                elif req_status == 'up' and status == MirrorStatus.STATUS_UPLOADING:
                    return dl
                elif req_status == 'clone' and status == MirrorStatus.STATUS_CLONING:
                    return dl
                elif req_status == 'seed' and status == MirrorStatus.STATUS_SEEDING:
                    return dl
                elif req_status == 'all':
                    return dl
    return None

def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    cPart = p % 8 - 1
    p_str = '●' * cFull
    if cPart >= 0:
        p_str += PROGRESS_INCOMPLETE[cPart]
    p_str += '○' * (PROGRESS_MAX_SIZE - cFull)
    p_str = f"「{p_str}」"
    return p_str

def editMessage(text: str, message: Message, reply_markup=None):	
    try:	
        bot.editMessageText(text=text, message_id=message.message_id,	
                              chat_id=message.chat.id,reply_markup=reply_markup,	
                              parse_mode='HTMl', disable_web_page_preview=True)	
    except RetryAfter as r:	
        LOGGER.warning(str(r))	
        sleep(r.retry_after * 1.5)	
        return editMessage(text, message, reply_markup)	
    except Exception as e:	
        LOGGER.error(str(e))	
        return str(e)	
def deleteMessage(bot, message: Message):	
    try:	
        bot.deleteMessage(chat_id=message.chat.id,	
                           message_id=message.message_id)	
    except Exception as e:	
        LOGGER.error(str(e))	
def delete_all_messages():	
    with status_reply_dict_lock:	
        for data in list(status_reply_dict.values()):	
            try:	
                deleteMessage(bot, data[0])	
                del status_reply_dict[data[0].chat.id]	
            except Exception as e:	
                LOGGER.error(str(e))	
def update_all_messages(force=False):	
    with status_reply_dict_lock:	
        if not force and (not status_reply_dict or not Interval or time() - list(status_reply_dict.values())[0][1] < 3):	
            return	
        for chat_id in status_reply_dict:	
            status_reply_dict[chat_id][1] = time()	
    msg, buttons = get_readable_message()	
    if msg is None:	
        return	
    with status_reply_dict_lock:	
        for chat_id in status_reply_dict:	
            if status_reply_dict[chat_id] and msg != status_reply_dict[chat_id][0].text:	
                if buttons == "":	
                    rmsg = editMessage(msg, status_reply_dict[chat_id][0])	
                else:	
                    rmsg = editMessage(msg, status_reply_dict[chat_id][0], buttons)	
                if rmsg == "Message to edit not found":	
                    del status_reply_dict[chat_id]	
                    return	
                status_reply_dict[chat_id][0].text = msg	
                status_reply_dict[chat_id][1] = time()

def get_readable_message():
    with download_dict_lock:
        msg = ""
        if STATUS_LIMIT is not None:
            tasks = len(download_dict)
            global pages
            pages = ceil(tasks/STATUS_LIMIT)
            if PAGE_NO > pages and pages != 0:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
        for index, download in enumerate(list(download_dict.values())[COUNT:], start=1):
            source = download.users()
            mesg = source.text.split(maxsplit=1)
            acts = mesg[0].replace('/', '#').replace(f'@{BOT_UNAME}', '')
            msg += f"<code>{escape(str(download.name()))}</code>"
            msg += f"\n<b>┌ Status:</b> <i>{download.status()}</i>\n<b>├ Engine:</b> {download.eng()}"        
            if download.status() not in [
                MirrorStatus.STATUS_ARCHIVING,
                MirrorStatus.STATUS_EXTRACTING,
                MirrorStatus.STATUS_SPLITTING,
                MirrorStatus.STATUS_SEEDING,
            ]:
                msg += f"\n<b>├ </b>{get_progress_bar_string(download)}\n<b><b>├ </b>Progress: </b>{download.progress()}"
                if download.status() == MirrorStatus.STATUS_CLONING:
                    msg += f"\n<b>├ Cloned:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_UPLOADING:
                    msg += f"\n<b>├ Downloaded:</b> {get_readable_file_size(download.processed_bytes())}\n<b>├ Total Size: </b>{download.size()}"
                else:
                    msg += f"\n<b>├ Downloaded:</b> {get_readable_file_size(download.processed_bytes())}\n<b>├ Total Size: </b>{download.size()}"
                msg += f"\n<b>├ Speed:</b> {download.speed()}\n<b>├ ETA:</b> {download.eta()}"
                msg += f"\n<b>├ Elapsed: </b>{get_readable_time(time() - download.message.date.timestamp())}"
                try:
                    msg += f"\n<b>├ Seeders:</b> {download.aria_download().num_seeders}" \
                           f"\n<b>├ Peers:</b> {download.aria_download().connections}"
                except:
                    pass
                try:
                    msg += f"\n<b>├ Seeders:</b> {download.torrent_info().num_seeds}" \
                           f"\n<b>├ Leechers:</b> {download.torrent_info().num_leechs}"
                except:
                    pass
                if download.message.chat.type != 'private':
                    try:
                        chatid = str(download.message.chat.id)[4:]
                        msg += f'\n<b>├ Source: </b><a href="https://t.me/c/{chatid}/{download.message.message_id}">{download.message.from_user.first_name}</a>'
                    except:
                        pass
                msg += f"\n<b>├ Action:</b> {acts}"
                msg += f"\n<b>└ To Stop: </b><code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            elif download.status() == MirrorStatus.STATUS_SEEDING:
                msg += f"\n<b>├ Size: </b>{download.size()}"
                msg += f"\n<b>├ Speed: </b>{get_readable_file_size(download.torrent_info().upspeed)}/s"
                msg += f"\n<b>├ Engine: </b> {download.eng()}"
                msg += f"\n<b>├ Action:</b> {acts}"
                msg += f"\n<b>├ Uploaded: </b>{get_readable_file_size(download.torrent_info().uploaded)}"
                msg += f"\n<b>├ Ratio: </b>{round(download.torrent_info().ratio, 3)}"
                msg += f"\n<b>├ Time: </b>{get_readable_time(download.torrent_info().seeding_time)}"
                msg += f"\n<code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            else:
                msg += f"\n<b>├ Action:</b> {acts}"
                msg += f"\n<b>└ Size: </b>{download.size()}"
            msg += "\n\n"
            if STATUS_LIMIT is not None and index == STATUS_LIMIT:
                break
        bmsg = f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n<b>CPU:</b> {cpu_percent()}% | <b>FREE:</b> {get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)}"
        bmsg += f"\n<b>RAM:</b> {virtual_memory().percent}% | <b>UPTIME:</b> {get_readable_time(time() - botStartTime)}"
        dlspeed_bytes = 0
        upspeed_bytes = 0
        for download in list(download_dict.values()):
            spd = download.speed()
            if download.status() == MirrorStatus.STATUS_DOWNLOADING:
                if 'K' in spd:
                    dlspeed_bytes += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    dlspeed_bytes += float(spd.split('M')[0]) * 1048576
            elif download.status() == MirrorStatus.STATUS_UPLOADING:
                if 'KB/s' in spd:
                    upspeed_bytes += float(spd.split('K')[0]) * 1024
                elif 'MB/s' in spd:
                    upspeed_bytes += float(spd.split('M')[0]) * 1048576
        bmsg += f"\n<b>DL:</b> {get_readable_file_size(dlspeed_bytes)}/s | <b>UL:</b> {get_readable_file_size(upspeed_bytes)}/s"
        
        buttons = ButtonMaker()
        buttons.sbutton("Statistics", str(THREE))
        buttons.sbutton("Refresh", str(ONE))	
        buttons.sbutton("Close", str(TWO))	
        sbutton = InlineKeyboardMarkup(buttons.build_menu(3))

        if STATUS_LIMIT is not None and tasks > STATUS_LIMIT:
            msg += f"\n<b>Total Tasks:</b> {tasks}\n"
            buttons = ButtonMaker()
            buttons.sbutton("Prev", "status pre")
            buttons.sbutton(f"{PAGE_NO}/{pages}", str(THREE))
            buttons.sbutton("Next", "status nex")
            button = InlineKeyboardMarkup(buttons.build_menu(3))
            return msg + bmsg, button
        return msg + bmsg, sbutton

def turn(data):
    try:
        with download_dict_lock:
            global COUNT, PAGE_NO
            if data[1] == "nex":
                if PAGE_NO == pages:
                    COUNT = 0
                    PAGE_NO = 1
                else:
                    COUNT += STATUS_LIMIT
                    PAGE_NO += 1
            elif data[1] == "pre":
                if PAGE_NO == 1:
                    COUNT = STATUS_LIMIT * (pages - 1)
                    PAGE_NO = pages
                else:
                    COUNT -= STATUS_LIMIT
                    PAGE_NO -= 1
        return True
    except:
        return False

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

def is_url(url: str):
    url = re_findall(URL_REGEX, url)
    return bool(url)

def is_gdrive_link(url: str):
    return "drive.google.com" in url

def is_gdtot_link(url: str):
    url = re_match(r'https?://.+\.gdtot\.\S+', url)
    return bool(url)

def is_appdrive_link(url: str):
    url = re_match(r'https?://(?:\S*\.)?(?:appdrive|driveapp)\.in/\S+', url)
    return bool(url)

def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = re_findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper

def get_content_type(link: str) -> str:
    try:
        res = rhead(link, allow_redirects=True, timeout=5, headers = {'user-agent': 'Wget/1.12'})
        content_type = res.headers.get('content-type')
    except:
        try:
            res = urlopen(link, timeout=5)
            info = res.info()
            content_type = info.get_content_type()
        except:
            content_type = None
    return content_type

ONE, TWO, THREE = range(3)

def refresh(update, context):
    query = update.callback_query
    query.edit_message_text(text="Refreshing Status...")
    sleep(5)
    update_all_messages()

def close(update, context):
    chat_id = update.effective_chat.id
    user_id = update.callback_query.from_user.id
    bot = context.bot
    query = update.callback_query
    admins = bot.get_chat_member(chat_id, user_id).status in [
        "creator",
        "administrator",
    ] or user_id in [OWNER_ID]
    if admins:
        delete_all_messages()
    else:
        query.answer(text="Only Admins can Close !", show_alert=True)
        
def pop_up_stats(update, context):
    query = update.callback_query
    stats = bot_sys_stats()
    query.answer(text=stats, show_alert=True)
    
def bot_sys_stats():
    currentTime = get_readable_time(time() - botStartTime)
    cpu = cpu_percent(interval=0.5)
    memory = virtual_memory()
    mem_p = memory.percent
    disk = psutil.disk_usage("/").percent
    total, used, free = shutil.disk_usage(".")
    total = get_readable_file_size(total)
    used = get_readable_file_size(used)
    free = get_readable_file_size(free)
    sent = get_readable_file_size(net_io_counters().bytes_sent)
    recv = get_readable_file_size(net_io_counters().bytes_recv)
    stats = "Bot Statistics"
    stats = f"""
┌ BOT UPTIME: {currentTime}
├ CPU : {cpu}%
├ RAM : {mem_p}%
├ USED : {used}
├ FREE :{free}
├ SENT : {sent}
└ RECV : {recv}
ONGOING TASKS:
┌ DL: {num_active}
├ UP : {num_upload}
├ SPLIT : {num_split}
├ ZIP : {num_archi}
├ UNZIP : {num_extract}
└ TOTAL : {tasks} 
"""
    return stats

dispatcher.add_handler(CallbackQueryHandler(refresh, pattern="^" + str(ONE) + "$"))
dispatcher.add_handler(CallbackQueryHandler(close, pattern="^" + str(TWO) + "$"))
dispatcher.add_handler(CallbackQueryHandler(pop_up_stats, pattern="^" + str(THREE) + "$"))
