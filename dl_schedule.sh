#!/bin/bash
# Cleanup on aisle two!
rm -rf /var/log/liain/*
rm -rf /var/log/PBOOK*.csv

# Time to get this show on the road
source /root/venv_liain/bin/activate

echo 'running python'
python3 /root/liain/liain.py
