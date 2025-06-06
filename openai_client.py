import asyncio
import functools
from openai import OpenAI
from config import MODEL, REASONING_MODEL
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

async def generate_response(messages, functions=None, function_call=None, model=MODEL):
    loop = asyncio.get_event_loop()
    if model == REASONING_MODEL:
        completion = await loop.run_in_executor(
            None,
            functools.partial(
                _oai.chat.completions.create,
                model=model,
                messages=messages,
                functions=functions,
                function_call=function_call,
                reasoning_effort="low"
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
            )
        )
    return completion