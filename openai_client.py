import asyncio
import functools
import base64
import requests
import html
from openai import OpenAI
from openrouter import OpenRouter
from ollama import chat, generate
from config import MODEL, DEBUG, EMBED_MODEL, IMAGE_MODEL
from credentials import ai_key

_oai = OpenAI(api_key=ai_key, base_url="https://openrouter.ai/api/v1")

reddit_headers = {
    "User-Agent": "AI-Nerd/2.0 (Nerdlabs AI)"
}

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None, instructions=None, effort=None, user=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Instructions: {instructions}. Generating response with model: {model} and channel id: {channel_id}.")
    if instructions:
        messages.insert(0, {"role": "developer", "content": instructions})
    kwargs = dict(
    model=model,
    input=messages,
    max_output_tokens=2000
    )
    if tools:
        fixed_tools = []
        for tool in tools:
            if 'type' not in tool:
                tool = dict(tool)
                tool['type'] = 'function'
            fixed_tools.append(tool)
        kwargs["tools"] = fixed_tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    if channel_id:
        kwargs["prompt_cache_key"] = str(channel_id)
    if effort:
        kwargs["extra_body"] = {
            "reasoning": {
                "enabled": True,
                "effort": effort
            }
        }
    else:
        if model.startswith("openai/"):
            kwargs["extra_body"] = {
                "reasoning": {
                    "enabled": True,
                    "effort": "minimal"
                }
            }
        else:
            kwargs["extra_body"] = {
                "reasoning": {
                    "enabled": False
                }
            }
        if user:
            kwargs["user"] = user
    completion = await loop.run_in_executor(
        None,
        functools.partial(
            _oai.responses.create,
            **kwargs
        )
    )
    return completion

def embed_text(text: str) -> list:
    if DEBUG:
        print(f"""Embedding text "{text}" with model: {EMBED_MODEL}""")
    
    with OpenRouter(
        api_key=ai_key,
    ) as open_router:
        res = open_router.embeddings.generate(input=text, model=EMBED_MODEL)
        emb = res.data[0].embedding
    return emb

def get_subreddit_posts(subreddit: str, limit: int):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={limit}"
    try:
        res = requests.get(url, headers=reddit_headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        posts = data["data"]["children"]
        return [p["data"]["title"] for p in posts]
    except Exception:
        return []

async def analyze_image(path):
    if DEBUG:
        print(f"Analyzing image: {path}")
    response = await asyncio.to_thread(chat,
        model=IMAGE_MODEL,
        messages=[
            {
            'role': 'user',
            'content': 'Describe this image in detail.',
            'images': [path],
            }
        ],
    )
    return response.message.content

async def reddit_search(query: str, limit: int = 5):
    url = "https://www.reddit.com/search.json"
    params = {
        "q": query,
        "limit": limit,
        "sort": "relevance",
        "t": "year"
    }

    try:
        r = requests.get(url, params=params, headers=reddit_headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        results = []

        for item in data["data"]["children"]:
            post = item["data"]

            title = html.unescape(post.get("title", ""))
            text = html.unescape(post.get("selftext", ""))

            combined = f"{title}\n{text}".strip()

            results.append({combined})

        return results

    except Exception:
        return []
    
def load_models():
    generate(model=IMAGE_MODEL, keep_alive='12h')

def unload_models():
    generate(model=IMAGE_MODEL, keep_alive='0')