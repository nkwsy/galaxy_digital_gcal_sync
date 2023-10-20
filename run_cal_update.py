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
    while True:
        try:
            gcc = gc.GalaxyAPI()
            gcc.update_responses()
            logger.debug("Updated responses")
            time.sleep(6000)
            importlib.reload(gc)
            importlib.reload(gcal)
        except Exception as e:
            fail_count += 1
            logger.error(f"failed: {fail_count}. {e}")
            post_to_slack(f"Galaxy_gcal_sync \n failed: {fail_count} sleeptime:{fail_count*60}.\n {e}")
            time.sleep(fail_count * 6000)
            pass
update_cal()
