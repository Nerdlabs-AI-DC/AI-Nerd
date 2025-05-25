# current version: alpha 1.0.0

import os
import json
import asyncio
import functools
import discord
from discord.ext import commands
from openai import OpenAI

# ================== CONFIGURATION ==================
CONFIG = {
    "token": os.getenv("DISCORD_TOKEN", "MTM3MTE3NjQyNTg1OTcxMTA2Ng.GH7hzm.prQ1i1GjpnakS9L8WVFFecVNWZBpWDxP2qaBN8"),
    "openai_key": os.getenv("OPENAI_API_KEY", "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"),
    "allowed_channels": [1371754649862012928, 1298198711565811771],
    "respond_to_pings": True,
    "history_size": 10,
    "model": "gpt-4.1-nano",
    "debug": False,
    "summaries_file": "summaries.json",
    "full_memory_file": "memories.json",
    "system": """You are AI Nerd 2, the nerdiest chatbot on Discord.
    AI Nerd 2 often uses nerdy phrases like “uhm actually” and “according to my calculations”. AI Nerd 2 always thinks he's right, and will correct user if he's wrong.
AI Nerd 2 always responds with short messages, one word up to two sentences long. AI Nerd 2 will never do any roleplay actions. AI Nerd 2 will not always say user's name when talking. AI Nerd 2 uses abbreviations like “idc, fr, k, idk, ngl, nm, wbu” and will curse at user only if user curses at AI Nerd 2.
AI Nerd 2 will be funny (but not excessively).
AI Nerd 2 always uses one or more of the following emoji's in their message:
<:uhm_actually:1371757874950311976>, <:sob:1371757961088733224>, <:moyai:1371758040218472458>, <:skull:1371758256665526352>, <:fire:1371758338236219402>, <:troll:1371758449540595772>, <:thumbsup:1371758587759689759>, <:thumbsdown:1371758669687164960>, <:neutral_face:1371758770769756190>, <:raised_eyebrow:1371758897433677875>, <:angry:1371758972402667610>, <:blushing:1371759043521024040>, <:cute:1371759114526396458>, <:crying:1371759185154277457>, <:cool:1371759296513314859>, <:cold:1371759367845842945>, <:giga_chad:1371759428801527848>, <:happy:1371759579414790165>, <:dumb:1371759661526814770>, <:flushed:1371759959661875310>, <:rizz:1371760019191758860>, <:hot:1371760084367052901>, <:idea:1371760146119659570>, <:money_mounth:1371760202495426561>, <:innocent:1371760303016247326>, <:exploding_head:1371760445391896646>, <:party:1371760646563041341>, <:heart:1371760745838149685>, <:evil:1371760812519194644>, <:love:1371760882060886076>, <:poop:1371760945440886784>, <:vomiting:1371761099308793916>, <a:pat:1371761608849887304>, <:man_face:1371761643519869044>, <:rofl:1371761705649967205>, <:sad:1371761782649127013>, <:scream:1371761838491959396>, <:shocked:1371761897182986262>, <:silly:1371761958533202011>, <:sleeping:1371762019459403776>, <:smirk:1371762076774826004>, <:surprised:1371762132516995133>, <:thinking:1371762289098756096>, <a:typing:1371762366500311061>, <a:yes:1371762433764495441>, <:yum:1371762482863018066>
You are created by @purpyel.
Always save new relevant information to memory, even if not explicitly asked. Constantly monitor for new data to store. Always retrieve and use memory when responding, unless no relevant memory exists. Prioritize memory to improve personalization and coherence across interactions.
If user ended the conversation, sent an incomplete sentence, or made an one word comment, cancel your response. You are able to change your Discord status, randomly change it whenever you want."""
}

# Ensure memory files exist
def init_memory_files():
    if not os.path.isfile(CONFIG['summaries_file']):
        with open(CONFIG['summaries_file'], 'w', encoding='utf-8') as f:
            json.dump([], f)
    if not os.path.isfile(CONFIG['full_memory_file']):
        with open(CONFIG['full_memory_file'], 'w', encoding='utf-8') as f:
            json.dump([], f)

# Memory operations
def save_memory(summary: str, full_memory: str) -> int:
    with open(CONFIG['summaries_file'], 'r', encoding='utf-8') as f:
        summaries = json.load(f)
    with open(CONFIG['full_memory_file'], 'r', encoding='utf-8') as f:
        memories = json.load(f)
    summaries.append(summary)
    memories.append(full_memory)
    with open(CONFIG['summaries_file'], 'w', encoding='utf-8') as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)
    with open(CONFIG['full_memory_file'], 'w', encoding='utf-8') as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)
    return len(summaries)

def get_memory_detail(index: int) -> str:
    with open(CONFIG['full_memory_file'], 'r', encoding='utf-8') as f:
        memories = json.load(f)
    if 1 <= index <= len(memories):
        return memories[index-1]
    return ""

# Initialize OpenAI client
oai = OpenAI(api_key=CONFIG['openai_key'])

# Define tool specs (for our internal use)
tools = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Store a new memory with summary and full content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "full_memory": {"type": "string"}
                },
                "required": ["summary", "full_memory"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_memory_detail",
            "description": "Retrieve full memory by its index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"}
                },
                "required": ["index"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_response",
            "description": "Cancel the current response without sending anything to the user.",
            "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_status",
            "description": "Change the Discord bot’s presence status.",
            "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "The new status text, e.g. 'Playing Chess' or 'Idle'."}
            },
            "required": ["status"],
            "additionalProperties": False
            }
        }
    }
]

# Discord setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

async def generate_response(messages):
    # Helper to call OpenAI and return the assistant reply
    completion = await asyncio.get_event_loop().run_in_executor(
        None,
        functools.partial(
            oai.chat.completions.create,
            model=CONFIG['model'],
            messages=messages
        )
    )
    return completion.choices[0].message.content

@bot.event
async def on_ready():
    init_memory_files()
    print(f"Ready as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.id == bot.user.id:
        return

    # allow DMs, allowed channels, or pings
    is_dm     = isinstance(message.channel, discord.DMChannel)
    is_allowed = message.channel.id in CONFIG['allowed_channels']
    is_pinged  = CONFIG['respond_to_pings'] and bot.user in message.mentions

    if not (is_dm or is_allowed or is_pinged):
        return

    # collect history
    history = []
    async for msg in message.channel.history(limit=CONFIG['history_size']+1, oldest_first=False):
        if msg.id == message.id:
            continue
        role = 'assistant' if msg.author.id == bot.user.id else 'user'
        if role == 'assistant':
            history.append({'role': role, 'content': f"{msg.content}"})
        else:
            history.append({'role': role, 'content': f"{msg.author.display_name} (@{msg.author.name}): {msg.content}"})
        if len(history) >= CONFIG['history_size']:
            break
    history.reverse()

    # load summaries
    with open(CONFIG['summaries_file'], 'r', encoding='utf-8') as f:
        sums = json.load(f)
    summary_list = '\n'.join(f"{i+1}. {s}" for i, s in enumerate(sums))
    # detect DM vs guild channel
    if isinstance(message.channel, discord.DMChannel):
        channel_name = "DM"
        guild_name   = "DM"
    else:
        channel_name = message.channel.name
        guild_name   = message.guild.name

    system_prompt = (
        f"Server: {guild_name}\n"
        f"Channel: {channel_name}\n\n"
        f"{CONFIG['system']}\n\n"
        f"Current memories:\n{summary_list}"
    )

    messages = [{'role': 'system', 'content': system_prompt}] + history + [{'role': 'user', 'content': f"{message.author.display_name} (@{message.author.name}): {message.content}"}]

    # Prepare functions for OpenAI call
    functions_spec = []
    for t in tools:
        fn = t['function']
        functions_spec.append({
            'name': fn['name'],
            'description': fn['description'],
            'parameters': fn['parameters']
        })

    if CONFIG['debug']:
        print('---REQ---')
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        print('Functions:', [f['name'] for f in functions_spec])

    async with message.channel.typing():
        completion = await asyncio.get_event_loop().run_in_executor(
            None,
            functools.partial(
                oai.chat.completions.create,
                model=CONFIG['model'],
                messages=messages,
                functions=functions_spec,
                function_call="auto"
            )
        )
    msg = completion.choices[0].message

    # function_call handling
    if hasattr(msg, 'function_call') and msg.function_call:
        func = msg.function_call
        fname = func.name
        args = json.loads(func.arguments)
        # call the function
        if fname == 'save_memory':
            idx = save_memory(args['summary'], args['full_memory'])
            # prepare a follow-up generation prompting the assistant
            messages = messages + [
                {'role': 'system', 'content': f'You just saved a new memory. Memory index: {idx}.'}
            ]
        elif fname == 'get_memory_detail':
            content = get_memory_detail(int(args['index']))
            messages = messages + [
                {'role': 'system', 'content': f'You are recalling a stored memory. Memory content: {content}.'}
            ]
        elif fname == 'cancel_response':
                # do nothing (no reply)
                return

        elif fname == 'set_status':
                new_status = args['status']
                # change Discord presence
                await bot.change_presence(activity=discord.CustomActivity(new_status))
                # send a confirmation message
                messages = messages + [
                {'role': 'system', 'content': f'You changed your status to "{new_status}".'}
            ]
        else:
            messages = messages + [
                {'role': 'system', 'content': f'Unknown function {fname} called.'}
            ]

        # generate the assistant's natural response
        reply_text = await generate_response(messages)
        if reply_text.startswith("AI Nerd 2:"):
            reply_text = reply_text[len("AI Nerd 2:"):].lstrip()
            print("stripped response")
        if CONFIG['debug']:
            print('---REQ---')
            print(messages)
        await message.channel.send(reply_text)
        return

    # normal reply
    if msg.content and msg.content.strip():
        await message.channel.send(msg.content)
    else:
        if CONFIG['debug']:
            print('No content to send for this reply, skipping.')

if __name__ == '__main__':
    bot.run(CONFIG['token'])