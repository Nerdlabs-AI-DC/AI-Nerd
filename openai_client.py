import asyncio
import functools
import base64
from openai import OpenAI
from config import MODEL, DEBUG
from credentials import openai_key

_oai = OpenAI(api_key=openai_key)

def extract_response_content(response):
    if hasattr(response, 'output_text') and response.output_text:
        return response.output_text
    
    if hasattr(response, 'output') and response.output:
        if isinstance(response.output, list) and len(response.output) > 0:
            first_output = response.output[0]
            if hasattr(first_output, 'content') and first_output.content:
                if isinstance(first_output.content, list) and len(first_output.content) > 0:
                    first_content = first_output.content[0]
                    if hasattr(first_content, 'text') and first_content.text:
                        return first_content.text
                elif isinstance(first_output.content, str):
                    return first_output.content
    
    if hasattr(response, 'choices') and response.choices:
        first_choice = response.choices[0]
        if hasattr(first_choice, 'message') and first_choice.message:
            if hasattr(first_choice.message, 'content') and first_choice.message.content:
                return first_choice.message.content
    
    return ""

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Generating response with model: {model} and channel id: {channel_id}")
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Handle the different message formats
            instructions = None
            user_input = None
            
            if isinstance(messages, list):
                # Responses API requires proper format for all messages
                formatted_messages = []
                for msg in messages:
                    role = msg.get('role')
                    content = msg.get('content')
                    
                    # Ensure we have a valid role
                    if role not in ['system', 'user', 'assistant', 'developer']:
                        if role == 'function':
                            # For function messages, use 'developer' role as replacement
                            role = 'developer'
                        else:
                            # Default to 'user' if not a known role
                            role = 'user'
                    
                    # Format the content appropriately
                    if isinstance(content, list):
                        # For list content (e.g. user with text/image), format properly
                        new_content = []
                        for item in content:
                            if isinstance(item, dict):
                                # If it's already a dict, check if it needs to be updated
                                if item.get('type') == 'image_url':
                                    # Convert old image_url format to input_image format
                                    new_content.append({
                                        'type': 'input_image',
                                        'source': {
                                            'type': 'url',
                                            'url': item.get('image_url', {}).get('url', '')
                                        }
                                    })
                                else:
                                    # Keep other dict formats as is
                                    new_content.append(item)
                            elif isinstance(item, str):
                                # If it's a string, convert to proper message object with input_text
                                new_content.append({
                                    'type': 'input_text',
                                    'text': item
                                })
                        content = new_content
                    
                    formatted_messages.append({
                        'role': role,
                        'content': content
                    })
                
                # Use formatted messages for the API call
                kwargs = dict(model=model, input=formatted_messages, max_output_tokens=2000)
            else:
                # If input is not a list, pass it directly
                kwargs = dict(model=model, input=messages, max_output_tokens=2000)
            
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
            
            if hasattr(completion, 'output_text') and completion.output_text:
                return completion
            elif hasattr(completion, 'tool_calls') and completion.tool_calls:
                return completion
            elif hasattr(completion, 'output') and completion.output:
                return completion
            elif retry_count < max_retries - 1:
                retry_count += 1
                await asyncio.sleep(1)
                continue
            else:
                raise ValueError("Received empty response from OpenAI API")
                
        except Exception as e:
            if retry_count < max_retries - 1:
                retry_count += 1
                await asyncio.sleep(1)
                continue
            else:
                raise e
    
    raise ValueError("Failed to get a valid response after multiple attempts")

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