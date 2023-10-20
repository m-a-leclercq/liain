#!/bin/bash
# Cleanup previously donwloaded file, processed csv and original csv
rm -v /var/log/liain/*.zip /var/log/liain/*.csv /var/log/liain/extract/LIAIN_01_SIEA*.csv

# Time to get this show on the road
source /root/venv_liain/bin/activate

echo 'running python'
python3 /root/liain/liain.py
