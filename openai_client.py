import asyncio
import functools
import base64
import requests
from openai import OpenAI
from config import MODEL, DEBUG, EMBED_MODEL
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

reddit_headers = {
    "User-Agent": "AI-Nerd/1.0 (Nerdlabs AI)"
}

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None, instructions=None, effort="minimal", service_tier="auto"):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Instructions: {instructions}. Generating response with model: {model} and channel id: {channel_id}.")
    kwargs = dict(model=model, instructions=instructions, input=messages, max_output_tokens=2000, reasoning={ "effort": effort }, service_tier=service_tier)
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
    resp = _oai.embeddings.create(model=EMBED_MODEL, input=text)
    emb = resp.data[0].embedding
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

async def edit_image(input_path, prompt, model="gpt-image-1-mini", filename="christmas.png"):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(
            _oai.images.edit,
            model=model,
            image=[open(input_path, "rb")],
            prompt=prompt,
            quality="low"
        )
    )

    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    with open(filename, "wb") as f:
        f.write(image_bytes)
    return filename