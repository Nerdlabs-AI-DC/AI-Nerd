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
    METRICS_FILE,
    FREEWILL_MESSAGE_INTERVAL,
    FREEWILL_TIMEOUT
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
    },
    {
        'name': 'add_reaction',
        'description': 'Add emoji reactions to a message. Can be used to react to user\'s message or your own message after sending.',
        'parameters': {
            'type': 'object',
            'properties': {
                'emojis': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of emojis to react with'},
                'target': {'type': 'string', 'enum': ['user', 'self'], 'description': 'Whether to react to user\'s message or your own message'}
            },
            'required': ['emojis', 'target']
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
        asyncio.create_task(freewill_task())
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
            if not system_msg:
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
            if replied_content:
                content.append({'type': 'text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
            content.append({'type': 'text', 'text': f"Message ID: {msg.id}"})
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
        if replied_content:
            user_content.append({'type': 'text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
        user_content.append({'type': 'text', 'text': f"Message ID: {message.id}"})
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

    reply_msg = None

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
        elif name == 'add_reaction' and config.REACTIONS:
            if isinstance(args.get('emojis'), list) and args.get('target') == 'user':
                for emoji in args.get('emojis'):
                    try:
                        if DEBUG:
                            print(f"Adding reaction {emoji} to user message")
                        await message.add_reaction(emoji)
                        await asyncio.sleep(0.5)
                        messages.append({'role': 'system', 'content': f'You reacted to {message.author.name}\'s message with {emoji}.'})
                    except Exception as e:
                        if DEBUG:
                            print(f"Error adding reaction: {e}")
                        messages.append({'role': 'system', 'content': f'Failed to add reaction {emoji}: {str(e)}'})
            elif isinstance(args.get('emojis'), list) and args.get('target') == 'self':
                messages.append({'role': 'system', 'content': f'You will react to your own message with emoji(s): {", ".join(args.get("emojis"))}'})
        elif name == 'reply':
            reply_msg = await message.channel.fetch_message(args['message_id'])
            messages.append({'role': 'system', 'content': f'You used the reply function with message ID {args["message_id"]}.'})
            if DEBUG:
                print(f"Replying to message ID {args['message_id']}")
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
    if reply_msg:
        await reply_msg.reply(content, mention_author=False)
    elif is_dm or is_allowed or freewill or force_response:
        await message.channel.send(content)
    else:
        await message.reply(content, mention_author=False)
    messages_sent.inc()

    # super-duper epic reactions yay
    if config.REACTIONS and msg_obj.function_call and msg_obj.function_call.name == 'add_reaction':
        args = json.loads(msg_obj.function_call.arguments or '{}')
        if args.get('target') == 'self' and isinstance(args.get('emojis'), list) and len(args.get('emojis')) > 0:
            last_message = None
            async for msg in message.channel.history(limit=1):
                if msg.author.id == bot.user.id:
                    last_message = msg
                    break
            if last_message:
                for emoji in args.get('emojis'):
                    try:
                        await last_message.add_reaction(emoji)
                    except Exception as e:
                        if DEBUG:
                            print(f"Error adding reaction: {e}")

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

async def freewill_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        if DEBUG:
            print("Running freewill task")
        try:
            try:
                with open(config.CONTEXT_FILE, 'r', encoding='utf-8') as f:
                    context = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                context = {}

            settings = load_settings()
            for user_id, info in context.items():
                channel_id = info.get('channel_id')
                if not channel_id:
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
                is_dm = isinstance(channel, discord.DMChannel)
                if is_dm:
                    rate = "mid"
                else:
                    if not guild:
                        continue
                    sid = str(guild.id)
                    guild_settings = settings.get(sid, {})
                    rate = guild_settings.get('freewill_rate', "mid")
                    if rate == 0:
                        continue
                messages = []
                try:
                    async for msg in channel.history(limit=5):
                        messages.append(msg)
                except Exception:
                    continue
                if not messages:
                    continue
                last_bot_message_time = None
                for msg in messages:
                    if msg.author.id == bot.user.id:
                        last_bot_message_time = msg.created_at
                        break
                now = datetime.datetime.now(datetime.timezone.utc)
                if last_bot_message_time:
                    time_since_last = (now - last_bot_message_time).total_seconds()
                    # if time_since_last < 600:
                    #     continue
                #     if time_since_last > 7200:
                #         if rate == "low":
                #             chance = 0.05
                #         elif rate == "mid":
                #             chance = 0.15
                #         else:
                #             chance = 0.3
                #     else:
                #         if rate == "low":
                #             chance = 0.01
                #         elif rate == "mid":
                #             chance = 0.05
                #         else:
                #             chance = 0.1
                # else:
                #     if rate == "low":
                #         chance = 0.03
                #     elif rate == "mid":
                #         chance = 0.08
                #     else:
                #         chance = 0.15
                chance = 1
                if random.random() <= chance:
                    if DEBUG:
                        if is_dm:
                            print(f"Attempting free will message to DM with user {user_id}")
                        else:
                            print(f"Attempting free will message to {guild.name}/{channel.name}")
                    try:
                        await send_message(
                            messages[0],
                            system_msg=FREEWILL_TIMEOUT
                        )
                    except Exception as e:
                        if DEBUG:
                            print(f"Free will message error: {e}")
        except Exception as e:
            if DEBUG:
                print(f"Free will task error: {e}")
        await asyncio.sleep(config.FREEWILL_MESSAGE_INTERVAL)

# Runs the bot
if __name__ == '__main__':
    bot.run(TOKEN)