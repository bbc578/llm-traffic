#!/bin/bash
cd /root/llm-traffic
pip3.10 install fastapi uvicorn[standard] traci sumolib websockets aiohttp pydantic python-dotenv openai 2>&1 | tail -5
echo "Dependencies installed."
