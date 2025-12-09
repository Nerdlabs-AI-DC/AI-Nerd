# AI Nerd
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/E1E61JZM90) [![](https://dcbadge.limes.pink/api/server/rkSKtdW99R)](https://discord.gg/rkSKtdW99R)

**AI Nerd** is an AI chatbot with a unique nerdy personality. It's designed to be a part of your community, naturally responding to messages and engaging in conversations.
## Features
### Chatting
AI Nerd’s core feature is its ability to respond to and answer messages. You can talk to AI Nerd in DMs, activated channels, or by mentioning it anywhere.
### Natural Replies
AI Nerd can respond on its own without being pinged. It can react to memes, join conversations, and more, all with natural replies.
### Vision
AI Nerd can view and discuss images you send. This allows it to see memes, assist with tasks, and much more.
### Memory
AI Nerd has a memory system. It can remember important information, past conversations, and more, and recall these memories later.
### Discord Integration
AI Nerd is deeply integrated with Discord. It can see channel history, recognize which server it's in, change its status, read usernames, react to messages with emojis, and more.
### Games
AI Nerd offers a variety of game commands under the /fun category. Completing these games can increase your nerdscore, a built-in point system.
## Commands
- /config activate – Makes AI Nerd respond to all messages in the channel where the command is used, even if it's not mentioned.
- /config natural-replies – Controls how often AI Nerd should react without being mentioned.
- /config chatrevive-set - Makes AI Nerd send a chat revive message when the channel is inactive for a set amount of minutes.
- /config chatrevive-disable - Disables chat revive messages.
- /config welcome - Makes AI Nerd welcome new server members in the channel where the command is used.
- /delete-memories - Delete your personal memories.
- /status - Shows the system status of AI Nerd.
- /fun ___ - Games and fun stuff.

**Add AI Nerd to your server:**
https://discord.com/oauth2/authorize?client_id=1371176425859711066

By using AI Nerd 2 you agree to the [Terms of Service](https://docs.google.com/document/d/1CBJ7tNOX0lKOsg4MZlJlc3TMkYQd_6mWXQ8ZWMtxix8/edit?usp=sharing) and [Privacy Policy](https://docs.google.com/document/d/1-07kJ2zpO0_DVLHQE1TBvMZXqynkzdczirtTYXEnAcc/edit?usp=sharing)

---

## Running Your Own Instance

If you’d like to run or modify the bot yourself, follow these steps.

### Requirements

* Python 3.10 or higher (Python 3.13 recommended)
* A Discord bot token
* An OpenAI API key

### Environment Variables

Before running the bot, set the following environment variables:

| Variable                 | Description                                          |
| ------------------------ | ---------------------------------------------------- |
| `AI_NERD_DISCORD_TOKEN`  | Your Discord bot token                               |
| `AI_NERD_OPENAI_API_KEY` | Your OpenAI API key                                  |
| `AI_NERD_MEMORY_KEY_B64` | A base64-encoded key used for encrypting memory data |

*(On Windows, use `setx VARIABLE_NAME value`; on macOS/Linux, use `export VARIABLE_NAME=value`.)*

### Installation

```bash
git clone https://github.com/Nerdlabs-AI-DC/AI-Nerd.git
cd AI-Nerd
python -m venv venv
source venv/bin/activate  # or on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

You can adjust optional settings in `config.py` before running the bot.
Make sure your bot has the **Message Content Intent** and **Server Members Intent** enabled in the Discord Developer Portal.

### Running the Bot

To start the bot, run:

```bash
python bot.py
```

---

## Files

- [`bot.py`](bot.py): Main bot logic and event handling.
- [`commands.py`](commands.py): Slash command definitions.
- [`memory.py`](memory.py): Memory management functions.
- [`openai_client.py`](openai_client.py): Handles OpenAI API calls.
- [`config.py`](config.py): Configuration and system prompts.
- [`nerdscore.py`](nerdscore.py): Nerdscore point system management.
- [`metrics.py`](metrics.py): Handles message count tracking.
- [`storage.py`](storage.py): Handles data storage.
- [`knowledge.py`](knowledge.py): Knowledge management functions.
- [`backup.py`](backup.py): Database backup management.

---

Created by Nerdlabs AI.  
Join our Discord: https://discord.gg/rkSKtdW99R
