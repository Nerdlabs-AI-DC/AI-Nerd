import asyncio
import functools
import base64
from openai import OpenAI
from config import MODEL, REASONING_MODEL, DEBUG
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

async def generate_response(messages, functions=None, function_call=None, model=MODEL, user_id=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Generating response with model: {model} and user id: {user_id}")
    if model == REASONING_MODEL:
        completion = await loop.run_in_executor(
            None,
            functools.partial(
                _oai.chat.completions.create,
                model=model,
                messages=messages,
                functions=functions,
                function_call=function_call,
                reasoning_effort="low",
                max_completion_tokens=2000,
                user=str(user_id)
            )
        )
    elif not user_id:
        completion = await loop.run_in_executor(
            None,
            functools.partial(
                _oai.chat.completions.create,
                model=model,
                messages=messages,
                functions=functions,
                function_call=function_call,
                max_completion_tokens=2000
            )
        )
    else:
        completion = await loop.run_in_executor(
            None,
            functools.partial(
                _oai.chat.completions.create,
                model=model,
                messages=messages,
                functions=functions,
                function_call=function_call,
                max_completion_tokens=2000,
                user=str(user_id)
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