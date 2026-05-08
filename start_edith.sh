#!/bin/bash

# Ensure backend systemd daemon is active (starts chat_server and wake_listener)
systemctl --user start edith.service

# Warm up Groq connection (reduces first-request latency)
echo "Warming up Groq connection..."
/home/vaibhav/edith-env/bin/python3 -c "
import os, requests
from dotenv import load_dotenv
load_dotenv('/home/vaibhav/EDITH/.env')
key = os.getenv('GROQ_API_KEY', '')
if key:
    try:
        r = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}'},
            json={'model': 'llama-3.1-8b-instant', 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 1},
            timeout=5
        )
        print('Groq warmed up:', r.status_code)
    except Exception as e:
        print('Groq warmup failed:', e)
else:
    print('No GROQ_API_KEY found')
" 2>/dev/null || true

# Launch the widget cleanly in the background if not already running
if ! pgrep -f "edith_widget.py" > /dev/null; then
    nohup /home/vaibhav/edith-env/bin/python /home/vaibhav/EDITH/edith_widget.py > /dev/null 2>&1 &
    echo "EDITH Widget launched in background. Press Ctrl+Space to summon."
else
    echo "EDITH Widget is already running! Press Ctrl+Space to summon."
fi

