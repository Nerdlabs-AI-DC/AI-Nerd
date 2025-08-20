import asyncio
import functools
import base64
from openai import OpenAI
from config import MODEL, DEBUG
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Generating response with model: {model} and channel id: {channel_id}")
    kwargs = dict(model=model, instructions=None, input=messages, max_output_tokens=2000, reasoning={ "effort": "minimal" })
    if tools:
        # Ensure each tool dict has a 'type' key set to 'function'
        fixed_tools = []
        for tool in tools:
            if 'type' not in tool:
                tool = dict(tool)  # copy
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