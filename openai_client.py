import asyncio
import functools
from openai import OpenAI
from config import openai_key, MODEL

_oai = OpenAI(api_key=openai_key)

async def generate_response(messages, functions=None, function_call=None):
    loop = asyncio.get_event_loop()
    completion = await loop.run_in_executor(
        None,
        functools.partial(
            _oai.chat.completions.create,
            model=MODEL,
            messages=messages,
            functions=functions,
            function_call=function_call
        )
    )
    return completion