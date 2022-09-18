#!/bin/bash
# Cleanup on aisle two!
rm -rf /var/log/liain/*


# Time to get this show on the road
source /root/venv_liain/bin/activate

echo 'running python'

if python3 /root/liain/liain.py; then
    echo 'running filebeat'
    filebeat -e -c liain.yml --path.data /var/lib/filebeat_liain/
else
    echo 'FAIL'
fi

