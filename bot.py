import json
import discord
import asyncio
import os
import time
from collections import defaultdict, deque
from discord.ext import commands
from discord import app_commands
import config
import random
import datetime
from config import (
    RESPOND_TO_PINGS,
    HISTORY_SIZE,
    DEBUG,
    SYSTEM_PROMPT,
    SYSTEM_SHORT,
    FREEWILL,
    JOIN_MSG,
    SETTINGS_FILE
)
from memory import init_memory_files, save_memory, get_memory_detail, save_user_memory, get_user_memory_detail, save_context, get_channel_by_user
from openai_client import generate_response
from credentials import token as TOKEN
from nerdscore import increase_nerdscore

from pathlib import Path

SETTINGS_PATH = Path(SETTINGS_FILE)

def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text("{}", encoding="utf-8")
        return {}

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    if not isinstance(data, dict):
        data = {}

    return data

def save_settings(settings: dict):
    SETTINGS_PATH.write_text(json.dumps(settings, indent=4), encoding='utf-8')


# Rate limiting
RATE_LIMIT = 10
RATE_PERIOD = 60
user_requests = defaultdict(lambda: deque())

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

import commands
commands.setup(bot)

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
        'name': 'give_nerdscore',
        'description': 'Give the user some nerdscore.',
        'parameters': {
            'type': 'object',
            'properties': {}
        }
    }
]

@bot.event
async def on_ready():
    init_memory_files()
    await bot.tree.sync()
    print(f"Ready as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    # Condition checking & free will
    if message.author.id == bot.user.id:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    allowed = []
    if message.guild:
        settings = load_settings()
        guild_settings = settings.get(str(message.guild.id), {})
        allowed = guild_settings.get("allowed_channels", [])
    is_allowed = message.channel.id in allowed
    is_pinged = RESPOND_TO_PINGS and bot.user in message.mentions
    if not (is_dm or is_allowed or is_pinged):
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
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - msg.created_at
        if delta.total_seconds() < 60 and msg.author.id == bot.user.id:
            if rate == "low":
                chance = 0.75
            if rate == "mid":
                chance = 0.9
            if rate == "high":
                chance = 1
        elif delta.total_seconds() > 36000:
            if rate == "low":
                chance = 0.25
            if rate == "mid":
                chance = 0.5
            if rate == "high":
                chance = 0.75
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
            freewill = FREEWILL
        else:
            return
    else:
        freewill = None

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
    save_context(user_id, message.channel.id)
    history = []
    async for msg in history_channel.history(limit=HISTORY_SIZE+1, oldest_first=False):
        if msg.id == message.id:
            continue
        role = 'assistant' if msg.author.id == bot.user.id else 'user'
        if role == 'assistant':
            content = msg.content
        else:
            content = []
            try:
                replied_message = await msg.channel.fetch_message(msg.reference.message_id)
                replied_content = replied_message.content
            except:
                replied_content = None
            if replied_content and (replied_message.author != bot.user or is_dm or is_allowed):
                content.append({'type': 'text', 'text': f"Replying to {replied_message.author.display_name} ({replied_message.author.name}): {replied_content}"})
            content.append({'type': 'text', 'text': f"{msg.author.display_name} ({msg.author.name}): {msg.content}"})
            for attach in msg.attachments:
                if attach.content_type and attach.content_type.startswith('image/'):
                    content.append({'type': 'image_url', 'image_url': {'url': attach.url}})
        history.append({'role': role, 'content': content})
        if len(history) >= HISTORY_SIZE:
            break
    history.reverse()
    if moved:
        history.append({'role': 'system', 'content': 'The conversation has moved to a different channel.'})

    with open(config.SUMMARIES_FILE, 'r', encoding='utf-8') as f:
        summaries = json.load(f)
    summary_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries))
    
    user_key = str(message.author.id)
    with open(config.USER_MEMORIES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if user_key in data:
            user_summaries = "\n".join(f"{i+1}. {s}" for i, s in enumerate(data[user_key]["summaries"]))
        else:
            user_summaries = "No user memories found."

    channel_name = message.channel.name if not is_dm else 'DM'
    guild_name = message.guild.name if not is_dm else 'DM'
    system_content = (
        f"Server: {guild_name}\n"
        f"Channel: {channel_name}\n\n"
        f"{SYSTEM_PROMPT}\n"
        f"Global memories:\n{summary_list}\n"
        f"User memories for {message.author.name}:\n{user_summaries}"
    )

    user_content = []
    try:
        replied_message = await message.channel.fetch_message(message.reference.message_id)
        replied_content = replied_message.content
    except:
        replied_content = None
    if message.content:
        if replied_content and (replied_message.author != bot.user or is_dm or is_allowed):
            user_content.append({'type': 'text', 'text': f"Replying to {replied_message.author.display_name} ({replied_message.author.name}): {replied_content}"})
        user_content.append({'type': 'text', 'text': f"{message.author.display_name} ({message.author.name}): {message.content}"})
    for attach in message.attachments:
        if attach.content_type and attach.content_type.startswith('image/'):
            user_content.append({'type': 'image_url', 'image_url': {'url': attach.url}})

    if freewill:
        messages = [
        {'role': 'system', 'content': SYSTEM_SHORT},
        *history,
        {'role': 'user', 'content': user_content},
        {'role': 'system', 'content': freewill}
        ]
    else:
        messages = [
        {'role': 'system', 'content': system_content},
        *history,
        {'role': 'user', 'content': user_content}
        ]

    # Api request
    if DEBUG:
        print('--- REQUEST ---')
        print(json.dumps(messages, ensure_ascii=False, indent=2))

    if freewill:
        completion = await generate_response(
            messages,
            functions=tools,
            function_call='auto'
        )
    else:
        async with message.channel.typing():
            completion = await generate_response(
                messages,
                functions=tools,
                function_call='auto'
            )
    msg_obj = completion.choices[0].message

    # Functions
    if msg_obj.function_call is not None:
        name = msg_obj.function_call.name
        args = json.loads(msg_obj.function_call.arguments or '{}')
        if DEBUG:
            print(f"Function {name} called.")
        if name == 'save_memory':
            if 'user_memory' in args and args['user_memory']:
                idx = save_user_memory(message.author.id, args['summary'], args['full_memory'])
                messages.append({'role': 'system', 'content': f'User memory saved. Memory index for user {message.author.name}: {idx}.'})
            else:
                idx = save_memory(args['summary'], args['full_memory'])
                messages.append({'role': 'system', 'content': f'You just saved a new memory. Memory index: {idx}.'})
        elif name == 'get_memory_detail':
            if 'user_memory' in args and args['user_memory']:
                detail = get_user_memory_detail(message.author.id, int(args['index']))
                messages.append({'role': 'system', 'content': f'Recalling user memory for {message.author.name}: {detail}.'})
            else:
                detail = get_memory_detail(int(args['index']))
                messages.append({'role': 'system', 'content': f'You are recalling a stored memory. Memory content: {detail}.'})
        elif name == 'set_status':
            new_status = args['status']
            await bot.change_presence(activity=discord.CustomActivity(new_status))
            messages.append({'role': 'system', 'content': f'You changed your status to "{new_status}".'})
        elif name == 'cancel_response':
            return
        elif name == 'send_dm':
            dmmessage = args['message']
            user = message.author
            try:
                await user.send(dmmessage)
                messages.append({'role': 'system', 'content': f'DM sent to {user.name}.'})
            except discord.Forbidden:
                messages.append({'role': 'system', 'content': 'Something went wrong while trying to send a DM.'})
            if args['send_followup'] == False:
                return
        elif name == 'give_nerdscore':
            increase_nerdscore(message.author.id, 1)
            messages.append({'role': 'system', 'content': f'You gave {message.author.name} 1 nerdscore.'})
        completion = await generate_response(
            messages,
            functions=None,
            function_call=None
        )
        msg_obj = completion.choices[0].message

    # Sending response
    if DEBUG:
        print('--- RESPONSE ---')
        print(msg_obj.content)
    if is_dm or is_allowed or freewill:
        await message.channel.send(msg_obj.content)
    else:
        await message.reply(msg_obj.content, mention_author=False)
    
# Server join message
@bot.event
async def on_guild_join(guild):
     if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        await guild.system_channel.send(JOIN_MSG)

# Runs the bot
if __name__ == '__main__':
    bot.run(TOKEN)