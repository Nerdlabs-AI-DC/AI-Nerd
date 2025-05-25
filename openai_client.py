import asyncio
import functools
from openai import OpenAI
from config import openai_key, MODEL

# Initialize OpenAI client
_oai = OpenAI(api_key=openai_key)

async def generate_response(messages, functions=None, function_call=None):
    """
    Wrapper around OpenAI ChatCompletion.create with optional function calling.
    Returns the full completion object.
    """
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