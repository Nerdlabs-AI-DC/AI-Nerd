import asyncio
import functools
import base64
import requests
from openai import OpenAI
from openrouter import OpenRouter
from config import MODEL, DEBUG, EMBED_MODEL
from credentials import ai_key

_oai = OpenAI(api_key=ai_key, base_url="https://openrouter.ai/api/v1")

reddit_headers = {
    "User-Agent": "AI-Nerd/1.0 (Nerdlabs AI)"
}

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None, instructions=None, effort=None):
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

async def generate_image(prompt, model="gpt-image-1", filename="image.png"):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(
            _oai.images.generate,
            model=model,
            prompt=prompt,
            quality="low"
        )
    )
    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    with open(filename, "wb") as f:
        f.write(image_bytes)
    return filename