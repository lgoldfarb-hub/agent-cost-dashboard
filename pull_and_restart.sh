#!/bin/bash
cd "$(dirname "$0")"
git pull
pkill -f "python3 server.py" 2>/dev/null
sleep 1
python3 server.py
