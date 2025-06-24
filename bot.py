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
import re
from config import (
    RESPOND_TO_PINGS,
    HISTORY_SIZE,
    DEBUG,
    SYSTEM_PROMPT,
    SYSTEM_SHORT,
    FREEWILL,
    SETTINGS_FILE,
    METRICS_FILE
)
from memory import init_memory_files, save_memory, get_memory_detail, save_user_memory, get_user_memory_detail, save_context, get_channel_by_user
from openai_client import generate_response
from credentials import token as TOKEN
from nerdscore import increase_nerdscore
from metrics import messages_sent, users, servers

from pathlib import Path

# Some variable and function definitions

# Settings
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

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

import commands
commands.setup(bot)

# Metrics (unused for now)
def update_metrics(user_id: int) -> None:
    try:
        with open(config.METRICS_FILE, 'r', encoding='utf-8') as f:
            metrics = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        metrics = {}
    if str(user_id) not in metrics:
        users.inc()
        metrics[str(user_id)] = None
        with open(config.METRICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)

chatrevive_task_started = False

async def replace_role_mentions(text, guild):
    def repl(match):
        role_id = int(match.group(1))
        role = guild.get_role(role_id)
        return f"@{role.name}" if role else "@role"
    text = re.sub(r'<@&(\d+)>', repl, text)
    text = re.sub(r'@everyone', '@redacted', text, flags=re.IGNORECASE)
    text = re.sub(r'@here', '@redacted', text, flags=re.IGNORECASE)
    return text

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

# Bot initialization
@bot.event
async def on_ready():
    global chatrevive_task_started
    init_memory_files()
    await bot.tree.sync()
    print(f"Ready as {bot.user}")
    if not chatrevive_task_started:
        asyncio.create_task(chatrevive_task())
        chatrevive_task_started = True

# Main message handler
async def send_message(message, system_msg=None, force_response=False, functions=True):
    # Condition checking & free will
    if message.author.id == bot.user.id and force_response == False:
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
            freewill = True
            system_msg = FREEWILL
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

    update_metrics(user_id)
    servers.set(len(bot.guilds))

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
        if msg.author.id == bot.user.id:
            role = 'assistant'
            content = msg.content
        else:
            role = 'user'
        if role != 'assistant':
            content = []
            try:
                replied_message = await msg.channel.fetch_message(msg.reference.message_id)
                replied_content = replied_message.content
            except:
                replied_content = None
            if replied_content and (replied_message.author != bot.user or is_dm or is_allowed):
                content.append({'type': 'text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
            content.append({'type': 'text', 'text': f"{msg.author.display_name}: {msg.content}"})
            for attach in msg.attachments:
                if attach.content_type and attach.content_type.startswith('image/'):
                    content.append({'type': 'image_url', 'image_url': {'url': attach.url}})
        history.append({'role': role, 'content': content, 'name': re.sub(r'[\s<|\\/>]', '_', msg.author.name)})
        if len(history) >= HISTORY_SIZE:
            break
    history.reverse()
    if moved:
        history.append({'role': 'system', 'content': 'The conversation has moved to a different channel.'})

    with open(config.FULL_MEMORY_FILE, 'r', encoding='utf-8') as f:
        try:
            full_data = json.load(f)
        except json.JSONDecodeError:
            full_data = {"summaries": []}
        summaries = full_data.get("summaries", [])
    summary_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries))
    
    user_key = str(message.author.id)
    with open(config.USER_MEMORIES_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
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
            user_content.append({'type': 'text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
        user_content.append({'type': 'text', 'text': f"{message.author.display_name}: {message.content}"})
    for attach in message.attachments:
        if attach.content_type and attach.content_type.startswith('image/'):
            user_content.append({'type': 'image_url', 'image_url': {'url': attach.url}})
        
    system = system_content
    if freewill:
        system = SYSTEM_SHORT

    messages = [
    {'role': 'system', 'content': system},
    *history,
    {'role': 'user', 'content': user_content, 'name': re.sub(r'[\s<|\\/>]', '_', message.author.name)} # Added regex shit so openai doesn't yell at me
    ]

    if system_msg:
        messages.append({'role': 'system', 'content': system_msg})
        
    # OpenAI request
    local_tools = tools
    functioncall = 'auto'
    if not functions:
        local_tools = None
        functioncall = None

    if DEBUG:
        print('--- MESSAGE REQUEST ---')
        print(json.dumps(messages, ensure_ascii=False, indent=2))

    if freewill:
        completion = await generate_response(
            messages,
            functions=local_tools,
            function_call=functioncall,
            user_id=message.author.id
        )
    else:
        async with message.channel.typing():
            completion = await generate_response(
                messages,
                functions=local_tools,
                function_call=functioncall,
                user_id=message.author.id
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
            function_call=None,
            user_id=message.author.id
        )
        msg_obj = completion.choices[0].message

    # Sending response
    if DEBUG:
        print('--- RESPONSE ---')
        print(msg_obj.content)
    content = await replace_role_mentions(msg_obj.content, message.guild) if message.guild and not force_response else msg_obj.content
    if is_dm or is_allowed or freewill or force_response:
        await message.channel.send(content)
    else:
        await message.reply(content, mention_author=False)
    messages_sent.inc()

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
                        now = datetime.datetime.now(datetime.timezone.utc)
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

# Runs the bot
if __name__ == '__main__':
    bot.run(TOKEN)