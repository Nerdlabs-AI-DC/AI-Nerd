# AI Nerd 2 - Discord AI Chatbot
# Copyright (C) 2025  Nerdlabs AI
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import discord
import asyncio
import time
from collections import defaultdict, deque
from discord.ext import commands
import random
import datetime
import re
import os
import signal
import sys
from config import (
    RESPOND_TO_PINGS,
    HISTORY_SIZE,
    DEBUG,
    get_system_prompt,
    SYSTEM_SHORT,
    NATURAL_REPLIES,
    NATURAL_REPLIES_INTERVAL,
    NATURAL_REPLIES_TIMEOUT,
    DAILY_MESSAGE_LIMIT,
    CHEAP_MODEL,
    MODEL,
    KNOWLEDGE_ITEMS,
    MEMORY_TOP_K,
    KNOWLEDGE_TOP_K,
    NEWS_SUBREDDITS,
    TEMP_DIR,
    EMOJI_MAP
)
from memory import (
    init_memory_files,
    save_memory,
    get_memory_detail,
    save_user_memory,
    get_user_memory_detail,
    save_context,
    get_channel_by_user,
    get_all_summaries,
    get_user_summaries,
    load_memory_cache,
    add_memory_to_cache,
    add_user_memory_to_cache,
    flush_memory_cache,
    find_relevant_memories,
    embed_text,
    delete_memory,
    delete_user_memory
)
from openai_client import generate_response, get_subreddit_posts, analyze_image, reddit_search, load_models, unload_models
from credentials import token as TOKEN
from nerdscore import increase_nerdscore
from metrics import messages_sent, update_metrics
import storage
from knowledge import sync_knowledge, find_relevant_knowledge
from backup import BackupManager

# Some variable and function definitions

# Settings
def load_settings() -> dict:
    try:
        return storage.load_settings() or {}
    except Exception:
        return {}


def save_settings(settings: dict):
    try:
        storage.save_settings(settings or {})
    except Exception:
        pass

# Rate limiting
RATE_LIMIT = 10
RATE_PERIOD = 60
user_requests = defaultdict(lambda: deque())

# Daily message counters
from datetime import datetime, timezone, timedelta

def load_daily_counts():
    try:
        return storage.load_daily_counts() or {}
    except Exception:
        return {}


def save_daily_counts(data: dict):
    try:
        storage.save_daily_counts(data or {})
    except Exception:
        pass

def increment_user_daily_count(user_id: int) -> int:
    data = load_daily_counts()
    now = datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    last_update_str = data.get('_last_update')
    if last_update_str:
        try:
            last_update = datetime.fromisoformat(last_update_str)
        except Exception:
            last_update = None
    else:
        last_update = None

    if not last_update or last_update.date() != now.date():
        data = {'_last_update': now.isoformat(), today: {}}
    else:
        data['_last_update'] = now.isoformat()
        if today not in data:
            data[today] = {}

    day_counts = data.setdefault(today, {})
    key = str(user_id)
    day_counts[key] = day_counts.get(key, 0) + 1
    save_daily_counts(data)
    return day_counts[key]

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

import commands
commands.setup(bot)

print("Loading knowledge...")
sync_knowledge()

backup_manager = BackupManager(storage._DB_PATH)

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

def check_send_perm(channel: discord.abc.Messageable) -> bool:
    try:
        if isinstance(channel, discord.DMChannel):
            return True
        guild = getattr(channel, 'guild', None)
        if guild is None:
            return True
        me = guild.me
        perms = channel.permissions_for(me)
        can_view = getattr(perms, 'view_channel', True)
        can_send = getattr(perms, 'send_messages', False)
        if isinstance(channel, discord.Thread):
            can_send = can_send or getattr(perms, 'send_messages_in_threads', False)
        return bool(can_view and can_send)
    except Exception:
        return False

chatrevive_task_started = False

def replace_custom_emojis(text: str):
    def repl(match):
        name = match.group(1)
        if name in EMOJI_MAP:
            return f"<:{name}:{EMOJI_MAP[name]}>"
        return match.group(0)

    return re.sub(r":([a-zA-Z0-9_]+):", repl, text)

async def process_response(text, guild, count):
    if isinstance(text, list):
        try:
            parts = []
            for item in text:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            text = "".join(parts)
        except Exception:
            text = str(text)

    if isinstance(text, str) and text.strip().startswith("[{"):
        try:
            import ast
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                parts = []
                for item in parsed:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                text = "".join(parts)
        except Exception:
            pass

    if guild:
        def repl(match):
            role_id = int(match.group(1))
            role = guild.get_role(role_id)
            return f"@{role.name}" if role else "@role"
        text = re.sub(r'<@&(\d+)>', repl, text)
        text = re.sub(r'@everyone', '@redacted', text, flags=re.IGNORECASE)
        text = re.sub(r'@here', '@redacted', text, flags=re.IGNORECASE)
    if count == DAILY_MESSAGE_LIMIT:
        timestamp = int((datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc) + timedelta(days=1)).timestamp())
        text += f"\n-# It seems that you have been chatting a lot today. To reduce costs, a cheaper model will be used for the rest of the day. Responses may be slower and unstable. Your limit resets <t:{timestamp}:R>."
    
    text = replace_custom_emojis(text)

    return text


async def enrich_mentions(text: str, guild: discord.Guild | None) -> str:
    if not text:
        return text or ''
    if guild is None:
        return text
    channel_matches = {m.group(0): int(m.group(1)) for m in re.finditer(r'<#(\d+)>', text)}
    for full, cid in channel_matches.items():
        try:
            channel = guild.get_channel(cid) or bot.get_channel(cid)
            if channel:
                replacement = f"{full}[#{channel.name}]"
                text = text.replace(full, replacement)
        except Exception:
            continue

    role_matches = {m.group(0): int(m.group(1)) for m in re.finditer(r'<@&(\d+)>', text)}
    for full, rid in role_matches.items():
        try:
            role = guild.get_role(rid)
            if role:
                replacement = f"{full}[{role.name}]"
                text = text.replace(full, replacement)
        except Exception:
            continue

    user_matches = {m.group(0): int(m.group(1)) for m in re.finditer(r'<@!?(\d+)>', text)}
    for full, uid in user_matches.items():
        name = None
        try:
            member = guild.get_member(uid)
            if member:
                name = member.display_name
            else:
                user = bot.get_user(uid)
                if user:
                    name = user.name
                else:
                    try:
                        fetched = await bot.fetch_user(uid)
                        name = fetched.name
                    except Exception:
                        name = None
        except Exception:
            name = None

        if name:
            try:
                replacement = f"{full}[{name}]"
                text = text.replace(full, replacement)
            except Exception:
                pass

    return text

async def get_news_posts():
    all_posts = []

    for sub in NEWS_SUBREDDITS:
        titles = get_subreddit_posts(sub, 3)
        for t in titles:
            all_posts.append(t)

    return all_posts

status = None

# Functions
tools = [
    {
        'name': 'save_memory',
        'description': 'Store a new memory.',
        'parameters': {
            'type': 'object',
            'properties': {
                'summary': {'type': 'string'},
                'full_memory': {'type': 'string'},
                'user_memory': {'type': 'boolean'}
            },
            'required': ['summary', 'full_memory', 'user_memory']
        }
    },
    {
        'name': 'get_memory_detail',
        'description': 'Retrieve a memory by its index.',
        'parameters': {
            'type': 'object',
            'properties': {
                'index': {'type': 'integer'},
                'user_memory': {'type': 'boolean'}
            },
            'required': ['index', 'user_memory']
        }
    },
    {
        'name': 'cancel_response',
        'description': 'Cancel the current response.',
        'parameters': {'type': 'object', 'properties': {}}
    },
    {
        'name': 'set_status',
        'description': 'Change the bot presence status.',
        'parameters': {
            'type': 'object',
            'properties': {'status': {'type': 'string'}},
            'required': ['status']
        }
    },
    {
        'name': 'send_dm',
        'description': 'Sends a DM (direct message) rather than a normal message. Use send_followup to also send a normal message.',
        'parameters': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string'},
                'send_followup': {'type': 'boolean'}
            },
            'required': ['message', 'send_followup']
        }
    },
    {
        'name': 'send_split',
        'description': 'Split the provided message by newline and send each non-empty line as a separate message with a delay (seconds) between them.',
        'parameters': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string'},
                'delay': {'type': 'number', 'description': 'Seconds to wait between lines (default 1)'}
            },
            'required': ['message']
        }
    },
    {
        'name': 'give_nerdscore',
        'description': 'Give the user some nerdscore.',
        'parameters': {
            'type': 'object',
            'properties': {}
        }
    },
    {
        'name': 'add_reaction',
        'description': 'Add emoji reactions to a message.',
        'parameters': {
            'type': 'object',
            'properties': {
                'emojis': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of emojis to react with'},
                'target': {'type': 'integer', 'description': 'The message id of the message to react to'},
                'send_followup': {'type': 'boolean', 'description': 'Whether to send a follow-up message after reacting'}
            },
            'required': ['emojis', 'target', 'send_followup'],
        }
    },
    {
        'name': 'reply',
        'description': 'Reply to a message other than the last one.',
        'parameters': {
            'type': 'object',
            'properties': {
                'message_id': {'type': 'integer'}
            },
            'required': ['message_id']
        }
    },
    {
        'name': 'delete_memory',
        'description': 'Delete a memory by its index.',
        'parameters': {
            'type': 'object',
            'properties': {
                'index': {'type': 'integer'},
                'user_memory': {'type': 'boolean'}
            },
            'required': ['index', 'user_memory']
        }
    },
    {
        'name': 'view_icon',
        'description': "View a user's profile picture or server icon.",
        'parameters': {
            'type': 'object',
            'properties': {
                'user_id': {'type': 'integer', 'description': 'The user ID to view the profile picture of. Leave empty to view the profile picture of the message author.'},
                'server_icon': {'type': 'boolean', 'description': 'If true, view the server icon instead of the user profile picture. Do not use if the current server is a DM.'}
            }
        }
    },
    {
        'name': 'search_web',
        'description': 'Search the web for a query.',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'}
            },
            'required': ['query']
        }
    }
]

# Bot initialization
@bot.event
async def on_ready():
    init_memory_files()
    try:
        load_memory_cache()
    except Exception:
        if DEBUG:
            print("Failed to load memory cache on startup")
    try:
        backup_manager.start()
    except Exception:
        if DEBUG:
            print("Failed to start BackupManager")
    try:
        if not hasattr(bot, 'status_task'):
            bot.status_task = bot.loop.create_task(update_status())
    except Exception:
        if DEBUG:
            print("Failed to start status update task")
    try:
        if not hasattr(bot, 'prune_task'):
            bot.prune_task = bot.loop.create_task(prune_image_descriptions_task())
    except Exception:
        if DEBUG:
            print("Failed to start image description prune task")
    try:
        load_models()
    except Exception:
        if DEBUG:
            print("Failed to load models on startup")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    await bot.tree.sync()
    print(f"Ready as {bot.user}")


# Main message handler
async def send_message(message, system_msg=None, force_response=False, functions=True):
    global status
    start_time = time.time()

    # Condition checking & free will
    if message.author.id == bot.user.id and force_response == False:
        return
    try:
        banned_map = storage.load_banned_map()
        if message.author.id in banned_map:
            meta = banned_map.get(message.author.id) or {}
            notified = bool(meta.get('notified'))
            if not notified:
                try:
                    await message.reply(
                        "You have been banned from using AI Nerd 2. Further messages will be ignored.",
                        mention_author=False
                    )
                except Exception:
                    pass
                try:
                    storage.mark_banned_user_notified(message.author.id)
                except Exception:
                    pass
            if DEBUG:
                print(f"Ignoring message from banned user {message.author.id}")
            return
    except Exception:
        pass
    
    if not check_send_perm(message.channel):
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    allowed = []
    if message.guild:
        settings = load_settings()
        guild_settings = settings.get(str(message.guild.id), {})
        allowed = guild_settings.get("allowed_channels", [])
    is_allowed = message.channel.id in allowed
    is_pinged = RESPOND_TO_PINGS and bot.user in message.mentions
    if not (is_dm or is_allowed or is_pinged or force_response):
        settings = load_settings()
        sid = str(message.guild.id) if message.guild else None
        guild_settings = settings.get(sid, {})
        rate = guild_settings.get('freewill_rate', "mid")
        if rate == 0:
            return
        messages = [msg async for msg in message.channel.history(limit=2)]
        if len(messages) < 2:
            return
        msg = messages[1]
        now = datetime.now(timezone.utc)
        delta = now - msg.created_at
        if delta.total_seconds() < 60 and msg.author.id == bot.user.id:
            if rate == "low":
                chance = 0.75
            if rate == "mid":
                chance = 0.9
            if rate == "high":
                chance = 1
        # elif delta.total_seconds() > 36000:
        #     if rate == "low":
        #         chance = 0.25
        #     if rate == "mid":
        #         chance = 0.5
        #     if rate == "high":
        #         chance = 0.75
        elif delta.total_seconds() > 300:
            if rate == "low":
                chance = 0.05
            if rate == "mid":
                chance = 0.1
            if rate == "high":
                chance = 0.2
        else:
            if rate == "low":
                chance = 0.01
            if rate == "mid":
                chance = 0.05
            if rate == "high":
                chance = 0.1
        if random.random() <= chance:
            freewill = True
            if not system_msg:
                system_msg = NATURAL_REPLIES
        else:
            return
    else:
        freewill = False

    # Rate limiting
    user_id = message.author.id
    now = time.time()
    dq = user_requests[user_id]
    while dq and now - dq[0] > RATE_PERIOD:
        dq.popleft()
    if len(dq) >= RATE_LIMIT:
        try:
            await message.channel.send(
                "You are going too fast. Let me take a breath pls."
            )
        except discord.Forbidden:
            pass
        return
    dq.append(now)

    # System prompt building
    channel_id, timestamp = get_channel_by_user(user_id)
    if channel_id == message.channel.id or time.time() - timestamp > 300 or freewill:
        history_channel = message.channel
        moved = False
    else:
        try:
            history_channel = await bot.fetch_channel(int(channel_id)) if channel_id else None
        except Exception:
            history_channel = None

        if history_channel is None:
            history_channel = message.channel
            moved = False
        else:
            moved = True
    history = []
    last_author_id = None
    last_role = None
    async for msg in history_channel.history(limit=HISTORY_SIZE*2+1, oldest_first=False):
        if msg.id == message.id:
            continue

        if msg.author.id == bot.user.id:
            role = 'assistant'
            content_item = msg.content or ''
            try:
                content_item = await enrich_mentions(content_item, msg.guild)
            except Exception:
                pass
            if last_role == 'assistant' and last_author_id == msg.author.id and history:
                prev = history[-1]
                prev['content'] = (content_item + '\n' + prev['content']).strip()
            else:
                history.append({'role': role, 'content': content_item})
                last_role = role
                last_author_id = msg.author.id

        else:
            role = 'user'
            content = []
            try:
                replied_message = await msg.channel.fetch_message(msg.reference.message_id)
                replied_content = replied_message.content
            except Exception:
                replied_content = None
            if replied_content:
                try:
                    replied_content = await enrich_mentions(replied_content, msg.guild)
                except Exception:
                    pass
                content.append({'type': 'input_text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
            content.append({'type': 'input_text', 'text': f"Message ID: {msg.id}"})
            content.append({'type': 'input_text', 'text': f"Display name: {msg.author.display_name}, Username: {msg.author.name}, User ID: {msg.author.id}"})
            try:
                enriched = await enrich_mentions(msg.content or '', msg.guild)
            except Exception:
                enriched = msg.content or ''
            content.append({'type': 'input_text', 'text': f"Message content: {enriched}"})
            for attach in msg.attachments:
                filename = attach.filename.lower()
                ext = os.path.splitext(filename)[1]

                if ext in ALLOWED_IMAGE_EXTS:
                    try:
                        cached = storage.get_image_description(attach.id)
                    except Exception:
                        cached = None
                    if cached:
                        content.append({'type': 'input_text', 'text': f"Image description: {cached}"})
                    else:
                        file_path = os.path.join(TEMP_DIR, f"{attach.id}_{attach.filename}")
                        await attach.save(file_path)

                        image_desc = await analyze_image(file_path)
                        content.append({
                            'type': 'input_text',
                            'text': f"Image description: {image_desc}"
                        })

                        try:
                            try:
                                storage.save_image_description(attach.id, image_desc)
                            except Exception:
                                if DEBUG:
                                    print("Failed to save image description to storage")
                        finally:
                            try:
                                os.remove(file_path)
                            except Exception:
                                if DEBUG:
                                    print(f"Failed to delete temp file {file_path}")

                else:
                    content.append({
                        'type': 'input_text',
                        'text': f"Attachment: {attach.filename}"
                    })


            history.append({'role': role, 'content': content})
            last_role = role
            last_author_id = msg.author.id

        if len(history) >= HISTORY_SIZE:
            break
    history.reverse()
    if moved:
        history.append({'role': 'system', 'content': 'The conversation has moved to a different channel.'})

    embedded_msg = embed_text(message.content)
    try:
        relevant_globals = find_relevant_memories(embedded_msg, top_k=MEMORY_TOP_K, user_id=None)
        if relevant_globals:
            summary_list = "\n".join(f"{r['index']}. {r['summary']}" for r in relevant_globals)
        else:
            summary_list = "No relevant global memories found."
    except Exception:
        summaries = get_all_summaries()
        summary_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries))

    try:
        relevant_user = find_relevant_memories(embedded_msg, top_k=MEMORY_TOP_K, user_id=message.author.id)
        if relevant_user:
            user_summaries = "\n".join(f"{r['index']}. {r['summary']}" for r in relevant_user)
        else:
            user_summaries = "No relevant user memories found."
    except Exception:
        user_summaries_list = get_user_summaries(message.author.id)
        if user_summaries_list:
            user_summaries = "\n".join(f"{i+1}. {s}" for i, s in enumerate(user_summaries_list))
        else:
            user_summaries = "No user memories found."
            
    try:
        relevant_knowledge = find_relevant_knowledge(embedded_msg, top_k=KNOWLEDGE_TOP_K)
        if relevant_knowledge:
            knowledge_list = "\n".join(f"* {r['text']}" for i, r in enumerate(relevant_knowledge))
        else:
            knowledge_list = "No relevant knowledge found."
    except Exception:
        knowledge_list = "\n".join(f"* {s}" for i, s in enumerate(KNOWLEDGE_ITEMS))

    channel_name = message.channel.name if not is_dm else 'DM'
    guild_name = message.guild.name if not is_dm else 'DM'
    system = (
        f"Server: {guild_name}\n"
        f"Channel: {channel_name}\n\n"
        f"{get_system_prompt(status)}\n"
        f"Relevant Knowledge:\n{knowledge_list}\n"
        f"Relevant global memories:\n{summary_list}\n"
        f"Relevant user memories for {message.author.name}:\n{user_summaries}"
    )

    user_content = []
    try:
        replied_message = await message.channel.fetch_message(message.reference.message_id)
        replied_content = replied_message.content
    except:
        replied_content = None
    if message.content:
        if replied_content:
            try:
                replied_content = await enrich_mentions(replied_content, message.guild)
            except Exception:
                pass
            user_content.append({'type': 'input_text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
        user_content.append({'type': 'input_text', 'text': f"Message ID: {message.id}"})
        user_content.append({'type': 'input_text', 'text': f"Display name: {message.author.display_name}, Username: {message.author.name}, User ID: {message.author.id}"})
        try:
            enriched_msg = await enrich_mentions(message.content or '', message.guild)
        except Exception:
            enriched_msg = message.content or ''
        user_content.append({'type': 'input_text', 'text': f"Message content: {enriched_msg}"})
    for attach in message.attachments:
        filename = attach.filename.lower()
        ext = os.path.splitext(filename)[1]

        if ext in ALLOWED_IMAGE_EXTS:
            try:
                cached = storage.get_image_description(attach.id)
            except Exception:
                cached = None
            if cached:
                user_content.append({'type': 'input_text', 'text': f"Image description: {cached}"})
            else:
                file_path = os.path.join(TEMP_DIR, f"{attach.id}_{attach.filename}")
                await attach.save(file_path)

                image_desc = await analyze_image(file_path)
                user_content.append({
                    'type': 'input_text',
                    'text': f"Image description: {image_desc}"
                })

                try:
                    try:
                        storage.save_image_description(attach.id, image_desc)
                    except Exception:
                        if DEBUG:
                            print("Failed to save image description to storage")
                finally:
                    try:
                        os.remove(file_path)
                    except Exception:
                        if DEBUG:
                            print(f"Failed to delete temp file {file_path}")

        else:
            user_content.append({
                'type': 'input_text',
                'text': f"Attachment: {attach.filename}"
            })


    messages = [
    *history,
    {'role': 'user', 'content': user_content}
    ]

    if system_msg:
        messages.append({'role': 'developer', 'content': system_msg})
        
    # OpenAI request
    local_tools = tools
    functioncall = 'auto'
    if not functions:
        local_tools = None
        functioncall = None

    if DEBUG:
        print('--- MESSAGE REQUEST ---')
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        latency = time.time() - start_time
        print(f"Message processing took {latency} seconds")

    count = None

    if freewill:
            model_to_use = CHEAP_MODEL
            try:
                completion = await generate_response(
                    messages,
                    tools=local_tools,
                    tool_choice=functioncall,
                    channel_id=message.channel.id,
                    instructions=system,
                    model=model_to_use,
                    user=f"naturalreplies_{message.author.name}:{message.author.id}"
                )
            except Exception:
                return
    else:
        async with message.channel.typing():
            count = increment_user_daily_count(user_id)
            user = None
            if count > DAILY_MESSAGE_LIMIT:
                model_to_use = CHEAP_MODEL
                user = f"limited_{message.author.name}:{message.author.id}"
            else:
                model_to_use = MODEL
                user = f"standard_{message.author.name}:{message.author.id}"
            try:
                completion = await generate_response(
                    messages,
                    tools=local_tools,
                    tool_choice=functioncall,
                    channel_id=message.channel.id,
                    instructions=system,
                    model=model_to_use,
                    user=user
                )
            except Exception:
                if count > DAILY_MESSAGE_LIMIT:
                    return
                else:
                    raise
    class MsgObj:
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.function_call = None
            if tool_calls:
                self.function_call = tool_calls[0] if tool_calls else None
    msg_obj = MsgObj(completion.output_text, getattr(completion, 'tool_calls', None))
    last_message = None
    try:
        async for m in message.channel.history(limit=1):
            last_message = m
    except Exception:
        last_message = None

    force_mention_original = False
    if last_message and last_message.id != message.id and getattr(last_message, 'created_at', None) and last_message.created_at > message.created_at:
        if last_message.author.id == message.author.id:
            if DEBUG:
                print("Message from same user detected. Cancelling current reply and restarting on the new message.")
            if is_allowed or is_dm:
                return
            else:
                return await send_message(last_message, system_msg=system_msg, force_response=force_response, functions=functions)
        else:
            if DEBUG:
                print("Message from different user detected. Will mention the original message when sending the reply.")
            force_mention_original = True

    reply_msg = None
    cancelled = False
    memory_cache_modified = False

# Function call handling
    messages += completion.output
    for item in completion.output:
        if item.type == "function_call":
            name = item.name
            args = json.loads(item.arguments or "{}")
            call_id = item.call_id
            tool_result = None
            is_image = False

            if DEBUG:
                print(f"Function {name} called with args {args}")

            if name == 'save_memory':
                if args.get('user_memory'):
                    try:
                        idx = add_user_memory_to_cache(message.author.id, args['summary'], args['full_memory'])
                        memory_cache_modified = True
                        tool_result = f'User memory saved to cache. Index {idx}.'
                    except Exception:
                        idx = save_user_memory(message.author.id, args['summary'], args['full_memory'])
                        tool_result = f'User memory saved. Index {idx}.'
                else:
                    try:
                        idx = add_memory_to_cache(args['summary'], args['full_memory'])
                        memory_cache_modified = True
                        tool_result = f'Global memory saved to cache. Index {idx}.'
                    except Exception:
                        idx = save_memory(args['summary'], args['full_memory'])
                        tool_result = f'Global memory saved. Index {idx}.'

            elif name == 'get_memory_detail':
                if args.get('user_memory'):
                    detail = get_user_memory_detail(message.author.id, int(args['index']))
                    tool_result = f'User memory: {detail}'
                else:
                    detail = get_memory_detail(int(args['index']))
                    tool_result = f'Memory: {detail}'

            elif name == 'set_status':
                new_status = args['status']
                await bot.change_presence(activity=discord.CustomActivity(new_status))
                status = new_status
                tool_result = f'Status set to {new_status}'

            elif name == 'cancel_response':
                cancelled = True
                tool_result = "Response cancelled by function call."
                messages.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({"result": tool_result + "\nTool execution is complete. Do not call any more functions. Respond only with plain text to the user."})
                })
                break

            elif name == 'send_dm':
                dmmessage = args['message']
                user = message.author
                try:
                    await user.send(dmmessage)
                    tool_result = f"DM sent to {user.name}"
                except discord.Forbidden:
                    tool_result = "Failed to send DM"
                if args.get("send_followup") is False:
                    cancelled = True
                    messages.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"result": tool_result})
                    })
                    break

            elif name == 'send_split':
                split_message = args.get('message', '')
                processed_message = await process_response(split_message, message.guild, count)
                delay = args.get('delay', 1)
                lines = [l.strip() for l in processed_message.splitlines()]
                sent_lines = 0
                for line in lines:
                    if not line:
                        continue
                    try:
                        if sent_lines == 0:
                            if force_mention_original:
                                await message.reply(line, mention_author=False)
                            elif reply_msg:
                                await reply_msg.reply(line, mention_author=False)
                            elif is_dm or is_allowed or freewill or force_response:
                                await message.channel.send(line)
                            else:
                                await message.reply(line, mention_author=False)
                        else:
                            await message.channel.send(line)
                        sent_lines += 1
                    except Exception as e:
                        if DEBUG:
                            print(f"Error sending split line: {e}")
                    try:
                        await asyncio.sleep(float(delay))
                    except Exception:
                        await asyncio.sleep(1)
                tool_result = f"Sent {sent_lines} lines (split send)."
                cancelled = True
                messages.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({"result": tool_result})
                })
                break

            elif name == 'give_nerdscore':
                increase_nerdscore(message.author.id, 1)
                tool_result = f"Nerdscore +1 for {message.author.name}"

            elif name == 'add_reaction':
                react_msg = await message.channel.fetch_message(args['target'])
                for emoji in args['emojis']:
                    try:
                        emoji = replace_custom_emojis(emoji)
                        await react_msg.add_reaction(emoji)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        if DEBUG:
                            print(f"Error adding reaction: {e}")
                tool_result = f"Reactions {args['emojis']} added to user message"
                if args.get("send_followup") is False:
                    cancelled = True
                    messages.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"result": tool_result})
                    })
                    break

            elif name == 'reply':
                reply_msg = await message.channel.fetch_message(args['message_id'])
                tool_result = f"Reply used on {args['message_id']} (content not auto-sent)."

            elif name == 'delete_memory':
                try:
                    if args.get('user_memory'):
                        delete_user_memory(message.author.id, int(args['index']))
                        memory_cache_modified = True
                        tool_result = f'User memory index {args["index"]} deleted.'
                    else:
                        delete_memory(int(args['index']))
                        memory_cache_modified = True
                        tool_result = f'Global memory index {args["index"]} deleted.'
                except Exception as e:
                    tool_result = f'Error deleting memory: {e}'
            
            elif name == 'view_icon':
                target_user_id = args.get('user_id') or message.author.id
                server_icon = args.get('server_icon', False)
                if server_icon and message.guild:
                    icon = message.guild.icon if message.guild.icon else None
                    if icon:
                        file_path = os.path.join(TEMP_DIR, str(message.guild.id))
                        await icon.save(file_path)

                        image_desc = await analyze_image(file_path)

                        tool_result = f"Server icon description: {image_desc}"

                        try:
                            os.remove(file_path)
                        except Exception:
                            print(f"Failed to delete temp file {file_path}")
                            pass
                    else:
                        tool_result = "This server does not have an icon."
                else:
                    try:
                        target_user = await bot.fetch_user(int(target_user_id))
                        avatar = target_user.display_avatar if target_user.display_avatar else None
                        if avatar:
                            file_path = os.path.join(TEMP_DIR, str(target_user.id))
                            await avatar.save(file_path)

                            image_desc = await analyze_image(file_path)

                            tool_result = f"User profile picture description: {image_desc}"

                            try:
                                os.remove(file_path)
                            except Exception:
                                print(f"Failed to delete temp file {file_path}")
                                pass
                        else:
                            tool_result = "This user does not have a profile picture."
                    except Exception as e:
                        tool_result = f"Error fetching user: {e}"
                
            elif name == 'search_web':
                query = args.get('query')
                search_results = await reddit_search(query, 3)
                if search_results:
                    tool_result = f"Web search results for '{query}':\n{search_results}"
                    if DEBUG:
                        print(f"Web search results for '{query}': {search_results}")
                else:
                    tool_result = f"No results found for '{query}'."

            if not is_image:
                tool_result = json.dumps({"result": tool_result})
            messages.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": tool_result
            })
            if not cancelled:
                completion2 = await generate_response(
                    messages,
                    tools=None,
                    tool_choice=None,
                    channel_id=message.channel.id,
                    instructions=system,
                    user = f"tool_{message.author.name}:{message.author.id}"
                )
                msg_obj = MsgObj(completion2.output_text, getattr(completion2, 'tool_calls', None))

    # Sending response
    if DEBUG:
        print('--- RESPONSE ---')
        print(msg_obj.content)
    # this stupid ai forgets how to call functions sometimes so i added this
    if cancelled or (isinstance(msg_obj.content, str) and msg_obj.content.strip() in ("cancel_response", "cancel_response()")) or not msg_obj.content.strip():
        if DEBUG:
            print("Cancelling response.")
        # Post-response processing
        messages_sent.inc()
        update_metrics(user_id)
        try:
            save_context(user_id, message.channel.id)
        except Exception:
            pass
        if system_msg == NATURAL_REPLIES_TIMEOUT:
            try:
                freewill_attempts = storage.get_freewill_attempts() or {}
            except Exception:
                freewill_attempts = {}
            freewill_attempts[str(channel_id)] = message.id
            try:
                storage.save_freewill_attempts(freewill_attempts)
            except Exception:
                pass
        try:
            if memory_cache_modified:
                flush_memory_cache()
        except Exception:
            if DEBUG:
                print("Failed to flush memory cache after cancelled response")
        return

    content = await process_response(msg_obj.content, message.guild, count)
    if force_mention_original:
        await message.reply(content, mention_author=False)
    elif reply_msg:
        await reply_msg.reply(content, mention_author=False)
    elif is_dm or is_allowed or freewill or force_response:
        await message.channel.send(content)
    else:
        await message.reply(content, mention_author=False)

    # Post-response processing
    messages_sent.inc()
    update_metrics(user_id)
    try:
        save_context(user_id, message.channel.id)
    except Exception:
        pass
    if system_msg == NATURAL_REPLIES_TIMEOUT:
        try:
            freewill_attempts = storage.get_freewill_attempts() or {}
        except Exception:
            freewill_attempts = {}
        freewill_attempts[str(channel_id)] = message.id
        try:
            storage.save_freewill_attempts(freewill_attempts)
        except Exception:
            pass

    try:
        if memory_cache_modified:
            flush_memory_cache()
            try:
                load_memory_cache()
            except Exception:
                pass
    except Exception:
        if DEBUG:
            print("Failed to flush memory cache after response")

# Message response
@bot.event
async def on_message(message: discord.Message):
    await send_message(message)

# Server join message
@bot.event
async def on_guild_join(guild):
     if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        last_message = None
        async for msg in guild.system_channel.history(limit=1):
            last_message = msg
        await send_message(last_message, system_msg=f"You have just joined the server {guild.name}. Please send a message to say hello to everyone and introduce yourself!", force_response=True, functions=False)

# Welcome message
@bot.event
async def on_member_join(member):
    guild = member.guild
    settings = load_settings()
    guild_settings = settings.get(str(guild.id), {})
    welcome_setting = guild_settings.get("welcome_msg")
    if welcome_setting:
        if DEBUG:
            print(f"{member.name} has joined {member.guild.name}")
        channel = await bot.fetch_channel(welcome_setting)
        last_message = None
        async for msg in channel.history(limit=1):
            last_message = msg
        await send_message(
            last_message,
            system_msg=f"A new member, {member.display_name}, has joined the server. Please send a welcome message. Make sure to mention them at least once using {member.mention}",
            force_response=True,
            functions=False
        )

# Chat revive
async def chatrevive_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        settings = load_settings()
        for guild in bot.guilds:
            sid = str(guild.id)
            guild_settings = settings.get(sid, {})
            chatrevive = guild_settings.get("chatrevive", {})
            channel_id = chatrevive.get("channel_id")
            timeout = chatrevive.get("timeout")
            role_id = chatrevive.get("role_id")
            if channel_id and timeout and role_id:
                try:
                    channel = await bot.fetch_channel(channel_id)
                    last_message = None
                    async for msg in channel.history(limit=1):
                        last_message = msg
                    if last_message:
                        now = datetime.now(timezone.utc)
                        delta = now - last_message.created_at
                        if delta.total_seconds() > timeout * 60:
                            role_mention = f"<@&{role_id}>"
                            await send_message(
                                last_message,
                                system_msg=f"The chat has been quiet for a while. Please send a message to help revive the conversation. Make sure to mention the revive role using {role_mention} at least once. Also, include an interesting question to get people talking again.",
                                force_response=True,
                                functions=False
                            )
                except Exception as e:
                    if DEBUG:
                        print(f"Chat revive error: {e}")
        await asyncio.sleep(60)

async def freewill_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        if DEBUG:
            print("Running freewill task")
        try:
            try:
                context = storage.get_context() or {}
            except Exception:
                context = {}

            try:
                freewill_attempts = storage.get_freewill_attempts() or {}
            except Exception:
                freewill_attempts = {}

            settings = load_settings()
            processed_channels = set()
            for user_id, info in context.items():
                channel_id = info.get('channel_id')
                if not channel_id or channel_id in processed_channels:
                    continue
                channel = None
                guild = None
                for g in bot.guilds:
                    try:
                        ch = g.get_channel(channel_id)
                        if ch:
                            channel = ch
                            guild = g
                            break
                    except Exception:
                        continue
                if not channel:
                    try:
                        channel = await bot.fetch_channel(channel_id)
                        guild = getattr(channel, 'guild', None)
                    except Exception:
                        continue
                if not channel:
                    continue
                processed_channels.add(channel_id)
                is_dm = isinstance(channel, discord.DMChannel)
                if is_dm:
                    rate = "mid"
                else:
                    if not guild:
                        continue
                    sid = str(guild.id)
                    guild_settings = settings.get(sid, {})
                    rate = guild_settings.get('freewill_rate', "mid")
                    if rate == "low":
                        chance = 0.25
                    if rate == "mid":
                        chance = 0.5
                    if rate == "high":
                        chance = 0.75
                    if random.random() >= chance:
                        continue
                messages = []
                try:
                    async for msg in channel.history(limit=5):
                        messages.append(msg)
                except Exception:
                    continue
                if not messages:
                    continue
                last_message = messages[0]
                last_bot_message_time = None
                for msg in messages:
                    if msg.author.id == bot.user.id:
                        last_bot_message_time = msg.created_at
                        break
                now = datetime.now(timezone.utc)
                last_attempted_id = freewill_attempts.get(str(channel_id))
                if last_attempted_id == last_message.id:
                    if DEBUG:
                        if is_dm:
                            print(f"Skipping free will message to DM with user {user_id}")
                        else:
                            print(f"Skipping free will message to {guild.name}/{channel.name}")
                    continue
                chance = 1
                if random.random() <= chance:
                    if DEBUG:
                        if is_dm:
                            print(f"Attempting free will message to DM with user {user_id}")
                        else:
                            print(f"Attempting free will message to {guild.name}/{channel.name}")
                    try:
                        await send_message(
                            last_message,
                            system_msg=NATURAL_REPLIES_TIMEOUT
                        )
                    except Exception as e:
                        if DEBUG:
                            print(f"Free will message error: {e}")
        except Exception as e:
            if DEBUG:
                print(f"Free will task error: {e}")
        await asyncio.sleep(NATURAL_REPLIES_INTERVAL)

async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        if DEBUG:
            print("Updating status message...")
        news_posts = await get_news_posts()
        messages = [{"role": "user", "content": f"""Create a short Discord status message for the bot based on one of the following news headlines:
{news_posts}
Choose one headline and turn it into a concise, engaging Discord status.
Do not mention the headline source, and do not add explanations or extra commentary.
Respond with only the final status message."""}]
        response = await generate_response(
            messages,
            tools=None,
            tool_choice=None,
            instructions=SYSTEM_SHORT,
            user="status_update"
        )
        status_text = response.output_text
        if DEBUG:
            print(f"Setting status to: {status_text}")
        await bot.change_presence(activity=discord.CustomActivity(status_text))
        global status
        status = status_text
        now = datetime.now(timezone.utc)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        sleep_seconds = (next_midnight - now).total_seconds()
        if sleep_seconds < 0:
            sleep_seconds = 0
        await asyncio.sleep(sleep_seconds)


async def prune_image_descriptions_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            removed = storage.prune_image_descriptions(24)
            if DEBUG and removed:
                print(f"Pruned {len(removed)} stale image descriptions: {removed}")
        except Exception:
            if DEBUG:
                print("Failed to prune image descriptions")
        await asyncio.sleep(3600)

def shutdown_handler(signum, frame):
    print("Shutting down...")
    unload_models()

    loop = asyncio.get_event_loop()
    loop.create_task(bot.close())

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)


# Runs the bot
if __name__ == '__main__':
    bot.run(TOKEN)