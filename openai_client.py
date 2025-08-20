import asyncio
import functools
import base64
from openai import OpenAI
from config import MODEL, DEBUG
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

def _extract_instructions_and_input(messages):
    """
    Convert chat messages to instructions and input for responses API.
    - The first system message becomes instructions.
    - The last user message becomes input.
    - All other messages are concatenated as context.
    """
    instructions = ""
    input_text = ""
    context = []
    def content_to_str(content):
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Flatten list of dicts (e.g., [{'type': 'text', 'text': ...}])
            return "\n".join(
                item.get('text', str(item)) if isinstance(item, dict) else str(item)
                for item in content
            )
        else:
            return str(content)

    for msg in messages:
        if msg["role"] == "system" and not instructions:
            instructions = content_to_str(msg["content"])
        elif msg["role"] == "user":
            input_text = content_to_str(msg["content"])
        else:
            # For assistant or other roles, treat as context
            context.append(f"{msg['role']}: {content_to_str(msg['content'])}")
    if context:
        input_text = "\n".join(context + [input_text])
    return instructions, input_text

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Generating response with model: {model} and channel id: {channel_id}")
    kwargs = dict(model=model, instructions=None, input=messages, max_output_tokens=2000)
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