import asyncio
import functools
import base64
from openai import OpenAI
from config import MODEL, DEBUG
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

async def generate_response(messages, functions=None, function_call=None, model=MODEL, channel_id=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Generating response with model: {model} and channel id: {channel_id}")
    if channel_id:
        completion = await loop.run_in_executor(
            None,
            functools.partial(
                _oai.responses.create,
                model=model,
                input=messages,
                tools=functions,
                tool_choice=function_call,
                max_output_tokens=2000,
                prompt_cache_key=str(channel_id)
            )
        )
    else:
        completion = await loop.run_in_executor(
            None,
            functools.partial(
                _oai.responses.create,
                model=model,
                input=messages,
                tools=functions,
                tool_choice=function_call,
                max_output_tokens=2000
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