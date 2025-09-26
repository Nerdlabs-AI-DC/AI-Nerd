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
    get_system_prompt,
    SYSTEM_SHORT,
    FREEWILL,
    SETTINGS_FILE,
    METRICS_FILE,
    FREEWILL_MESSAGE_INTERVAL,
    FREEWILL_TIMEOUT,
    FREEWILL_FILE,
    DAILY_MESSAGE_FILE,
    DAILY_MESSAGE_LIMIT,
    FALLBACK_MODEL,
    MODEL
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
)
from openai_client import generate_response
from credentials import token as TOKEN
from nerdscore import increase_nerdscore
from metrics import messages_sent, update_metrics

from pathlib import Path
from conversation_manager import ConversationManager, simple_summary

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

# Daily message counters
from datetime import datetime, timezone, timedelta

DAILY_PATH = Path(DAILY_MESSAGE_FILE)

def load_daily_counts():
    if not DAILY_PATH.exists():
        try:
            DAILY_PATH.write_text("{}", encoding='utf-8')
        except Exception:
            pass
        return {}
    try:
        with open(DAILY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data

def save_daily_counts(data: dict):
    try:
        with open(DAILY_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
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

chatrevive_task_started = False

async def process_response(text, guild, count):
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
        text += f"\n-# It seems that you have been chatting a lot today. To reduce costs, a less advanced model will be used for the rest of the day. Responses may be less accurate. Your limit resets <t:{timestamp}:R>."
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
        'description': 'Add emoji reactions to a message. Can be used to react to user\'s message or your own message after sending.',
        'parameters': {
            'type': 'object',
            'properties': {
                'emojis': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of emojis to react with'},
                'target': {'type': 'string', 'enum': ['user', 'self'], 'description': 'Whether to react to user\'s message or your own message'},
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
    }
]

# Conversation summary system (unused for now)
# conv_manager = ConversationManager(summary_func=simple_summary, buffer_size=10, inactivity=300)
# conversation_finalizer_task_started = False

# def get_conversation_key(message):
#     user_id = message.author.id
#     channel_id = message.channel.id
#     return user_id, channel_id

# def get_user_channel_switch(message):
#     user_id = message.author.id
#     channel_id = message.channel.id
#     last_channel_id, _ = get_channel_by_user(user_id)
#     if last_channel_id and last_channel_id != channel_id:
#         return last_channel_id
#     return None

# Bot initialization
@bot.event
async def on_ready():
    # global chatrevive_task_started, conversation_finalizer_task_started
    init_memory_files()
    try:
        load_memory_cache()
    except Exception:
        if DEBUG:
            print("Failed to load memory cache on startup")
    await bot.tree.sync()
    print(f"Ready as {bot.user}")
    # if not chatrevive_task_started:
    #     asyncio.create_task(chatrevive_task())
    #     asyncio.create_task(freewill_task())
    #     chatrevive_task_started = True
    # if not conversation_finalizer_task_started:
    #     asyncio.create_task(conversation_finalizer_task())
    #     conversation_finalizer_task_started = True

# Main message handler
async def send_message(message, system_msg=None, force_response=False, functions=True):
    start_time = time.time()
    # if not message.author.bot:
    #     user_id, channel_id = get_conversation_key(message)
    #     await conv_manager.process_message(user_id, channel_id, message.content)

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
        now = datetime.now(timezone.utc)
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
                content.append({'type': 'input_text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
            content.append({'type': 'input_text', 'text': f"Message ID: {msg.id}"})
            content.append({'type': 'input_text', 'text': f"Display name: {msg.author.display_name}, Username: {msg.author.name}"})
            content.append({'type': 'input_text', 'text': f"Message content: {msg.content}"})
            for attach in msg.attachments:
                if attach.content_type and attach.content_type.startswith('image/'):
                    content.append({'type': 'input_image', 'image_url': attach.url})
        history.append({'role': role, 'content': content})
        if len(history) >= HISTORY_SIZE:
            break
    history.reverse()
    if moved:
        history.append({'role': 'system', 'content': 'The conversation has moved to a different channel.'})

    summaries = get_all_summaries()
    summary_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries))

    user_summaries_list = get_user_summaries(message.author.id)
    if user_summaries_list:
        user_summaries = "\n".join(f"{i+1}. {s}" for i, s in enumerate(user_summaries_list))
    else:
        user_summaries = "No user memories found."

    channel_name = message.channel.name if not is_dm else 'DM'
    guild_name = message.guild.name if not is_dm else 'DM'
    system_content = (
        f"Server: {guild_name}\n"
        f"Channel: {channel_name}\n\n"
        f"{get_system_prompt()}\n"
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
            user_content.append({'type': 'input_text', 'text': f"Replying to {replied_message.author.display_name}: {replied_content}"})
        user_content.append({'type': 'input_text', 'text': f"Message ID: {message.id}"})
        user_content.append({'type': 'input_text', 'text': f"Display name: {message.author.display_name}, Username: {message.author.name}"})
        user_content.append({'type': 'input_text', 'text': f"Message content: {message.content}"})
    for attach in message.attachments:
        if attach.content_type and attach.content_type.startswith('image/'):
            user_content.append({'type': 'input_image', 'image_url': attach.url})
        
    system = system_content
    if freewill:
        system = SYSTEM_SHORT

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
            model_to_use = FALLBACK_MODEL
            completion = await generate_response(
                messages,
                tools=local_tools,
                tool_choice=functioncall,
                channel_id=message.channel.id,
                instructions=system,
                model=model_to_use,
                service_tier="flex"
            )
    else:
        async with message.channel.typing():
            count = increment_user_daily_count(user_id)
            model_to_use = FALLBACK_MODEL if count > DAILY_MESSAGE_LIMIT else MODEL
            completion = await generate_response(
                messages,
                tools=local_tools,
                tool_choice=functioncall,
                channel_id=message.channel.id,
                instructions=system,
                model=model_to_use
            )
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
            if is_allowed:
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
                tool_result = f'Status set to {new_status}'

            elif name == 'cancel_response':
                cancelled = True
                tool_result = "Response cancelled by function call."
                messages.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({"result": tool_result})
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
                # Send each non-empty line as its own message with a delay between lines.
                split_message = args.get('message', '')
                delay = args.get('delay', 1)
                lines = [l.strip() for l in split_message.splitlines()]
                sent_lines = 0
                for line in lines:
                    if not line:
                        continue
                    try:
                        # Choose channel vs DM behavior similar to normal send
                        if is_dm or is_allowed or freewill or force_response:
                            await message.channel.send(line)
                        else:
                            await message.reply(line, mention_author=False)
                        messages_sent.inc()
                        update_metrics(user_id)
                        sent_lines += 1
                    except Exception as e:
                        if DEBUG:
                            print(f"Error sending split line: {e}")
                    try:
                        await asyncio.sleep(float(delay))
                    except Exception:
                        await asyncio.sleep(1)
                tool_result = f"Sent {sent_lines} lines (split send)."
                # Prevent the default single-message send
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

            elif name == 'add_reaction' and config.REACTIONS:
                if isinstance(args.get('emojis'), list) and args.get('target') == 'user':
                    for emoji in args['emojis']:
                        try:
                            await message.add_reaction(emoji)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            if DEBUG:
                                print(f"Error adding reaction: {e}")
                    tool_result = f"Reactions {args['emojis']} added to user message"
                elif isinstance(args.get('emojis'), list) and args.get('target') == 'self':
                    tool_result = f"Would react to own message with {args['emojis']}"
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

            messages.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps({"result": tool_result})
            })
            if not cancelled:
                completion2 = await generate_response(
                    messages,
                    tools=None,
                    tool_choice=None,
                    channel_id=message.channel.id,
                    instructions=system
                )
                msg_obj = MsgObj(completion2.output_text, getattr(completion2, 'tool_calls', None))

    # Sending response
    if DEBUG:
        print('--- RESPONSE ---')
        print(msg_obj.content)
    # this stupid ai forgets how to call functions sometimes so i added this
    if cancelled or (isinstance(msg_obj.content, str) and msg_obj.content.strip() in ("cancel_response", "cancel_response()")):
        if DEBUG:
            print("Cancelling response.")
        # Post-response processing
        try:
            save_context(user_id, message.channel.id)
        except Exception:
            pass
        if system_msg == FREEWILL_TIMEOUT:
            try:
                with open(config.FREEWILL_FILE, 'r', encoding='utf-8') as f:
                    freewill_attempts = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                freewill_attempts = {}
            freewill_attempts[str(channel_id)] = message.id
            try:
                with open(config.FREEWILL_FILE, 'w', encoding='utf-8') as f:
                    json.dump(freewill_attempts, f, indent=2)
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
        await message.reply(content, mention_author=True)
    elif reply_msg:
        await reply_msg.reply(content, mention_author=False)
    elif is_dm or is_allowed or freewill or force_response:
        await message.channel.send(content)
    else:
        await message.reply(content, mention_author=False)
    messages_sent.inc()
    update_metrics(user_id)

    # Post-response processing
    try:
        save_context(user_id, message.channel.id)
    except Exception:
        pass
    if system_msg == FREEWILL_TIMEOUT:
        try:
            with open(config.FREEWILL_FILE, 'r', encoding='utf-8') as f:
                freewill_attempts = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            freewill_attempts = {}
        freewill_attempts[str(channel_id)] = message.id
        try:
            with open(config.FREEWILL_FILE, 'w', encoding='utf-8') as f:
                json.dump(freewill_attempts, f, indent=2)
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
    # old_channel_id = get_user_channel_switch(message)
    # if old_channel_id:
    #     final_summary = await conv_manager.finalize(message.author.id, old_channel_id)
    #     if final_summary:
    #         full, short = final_summary
    #         save_memory(short, full)
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
                with open(config.CONTEXT_FILE, 'r', encoding='utf-8') as f:
                    context = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                context = {}

            try:
                with open(config.FREEWILL_FILE, 'r', encoding='utf-8') as f:
                    freewill_attempts = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
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
                            system_msg=FREEWILL_TIMEOUT
                        )
                    except Exception as e:
                        if DEBUG:
                            print(f"Free will message error: {e}")
        except Exception as e:
            if DEBUG:
                print(f"Free will task error: {e}")
        await asyncio.sleep(config.FREEWILL_MESSAGE_INTERVAL)

# Background task to finalize conversations after inactivity
# async def conversation_finalizer_task():
#     await bot.wait_until_ready()
#     while not bot.is_closed():
#         to_finalize = conv_manager.check_inactive()
#         for user_id, channel_id in to_finalize:
#             final_summary = await conv_manager.finalize(user_id, channel_id)
#             if final_summary:
#                 full, short = final_summary
#                 save_memory(short, full)
#         await asyncio.sleep(60)

# Runs the bot
if __name__ == '__main__':
    bot.run(TOKEN)