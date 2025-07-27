import time
from openai_client import generate_response

class ConversationState:
    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.last_active = time.time()
        self.buffer = []
        self.rolling_summary = None

class ConversationManager:
    def __init__(self, summary_func, buffer_size=10, inactivity=300):
        self.states = {}
        self.summary_func = summary_func
        self.buffer_size = buffer_size
        self.inactivity = inactivity

    def get_key(self, user_id, channel_id):
        return (user_id, channel_id)

    def process_message(self, user_id, channel_id, message):
        key = self.get_key(user_id, channel_id)
        state = self.states.get(key)
        if not state:
            state = ConversationState(channel_id)
            self.states[key] = state
        state.last_active = time.time()
        state.buffer.append(message)
        if len(state.buffer) >= self.buffer_size:
            prev_full = state.rolling_summary[0] if state.rolling_summary else None
            state.rolling_summary = self.summary_func(prev_full, state.buffer)
            state.buffer = []
        return state

    def finalize(self, user_id, channel_id):
        key = self.get_key(user_id, channel_id)
        state = self.states.get(key)
        if not state:
            return None
        prev_full = state.rolling_summary[0] if state.rolling_summary else None
        final_summary = self.summary_func(prev_full, state.buffer)
        del self.states[key]
        return final_summary

    def check_inactive(self):
        now = time.time()
        to_finalize = []
        for key, state in list(self.states.items()):
            if now - state.last_active > self.inactivity:
                to_finalize.append(key)
        return to_finalize

def simple_summary(prev_summary, messages):
    tools = [    
        {
            'name': 'summarize_conversation',
            'description': 'Create a summary of the conversation.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'short_summary': {'type': 'string'},
                    'full_summary': {'type': 'string'}
                },
                'required': ['summary', 'full_memory']
            }
        }
    ]


    messages.append({'role': 'system', 'content': f"Create a summary of the previous messages and the following summary: {prev_summary}."})
    completion = await generate_response(
        messages,
        functions=tools,
        function_call={'name': 'summarize_conversation'}
    )

    # Didn't finish this part yet

    return (full, short)
