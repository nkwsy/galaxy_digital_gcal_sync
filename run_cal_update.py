import get_connected as gc
import gcal
import model
import importlib
import time
from loguru import logger
import os
from dotenv import load_dotenv
import requests
import json

load_dotenv()
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

def post_to_slack( message):
    headers = {'Content-Type': 'application/json'}
    data = json.dumps({'text': message})
    
    response = requests.post(WEBHOOK_URL, headers=headers, data=data)
    if response.status_code == 200:
        print("Message posted successfully!")
    else:
        print(f"Failed to post message. Status code: {response.status_code}, Response: {response.text}")
    return response

def update_cal():
    fail_count = 0
    last_update = 0
    next_shift_time_diff = 0
    last_shift_time_diff = 0
    while True:
        try:
            gcc = gc.GalaxyAPI()
            if time.time() - last_update > 3600:
                gcc.update_responses()
                last_update = time.time()
                logger.debug("Updated responses")
                time.sleep(100)
            next_shift_time_diff = gcc.get_next_shift()
            # if next_shift_time_diff < 3600:
            #     gcc.user_checkin_update()
            #     logger.debug("Updated checkin")
            # logger.debug(f"Next shift time diff: {next_shift_time_diff}")
            # if next_shift_time_diff > 3600:
            #     last_update = time.time()
            last_shift_time_diff = gcc.get_last_shift()
            if last_shift_time_diff > 3600:
                gcc.user_checkin_update()
                logger.debug("Updated checkin")
            time.sleep(300)
            importlib.reload(gc)
            importlib.reload(gcal)
        except Exception as e:
            fail_count += 1
            logger.error(f"failed: {fail_count}. {e}")
            post_to_slack(f"Galaxy_gcal_sync \n failed: {fail_count} sleeptime:{fail_count*60}.\n {e}")
            time.sleep(fail_count * 60)
            pass
update_cal()
