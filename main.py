import requests
import os
from dotenv import load_dotenv
import json
import gcal
from datetime import datetime
import pytz
from loguru import logger
logger.add("debug.log", format="{time} {level} {message}", level='ERROR', retention='2 days', rotation="5 MB")
load_dotenv()

#TODO: sync with internal mongoDB
api_key = os.getenv('API_KEY')
email = os.getenv('EMAIL')
password = os.getenv('PASSWORD')
calendar_id = os.getenv('CALENDAR_ID')

url = 'https://api.galaxydigital.com/api/'


shifts = {}
def login(api_key, email, password):
    login_url = 'https://api.galaxydigital.com/api/users/login'
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    data = {
        'key': f'{api_key}',
        'user_email': f'{email}',
        'user_password': f'{password}',
    }
    response = requests.post(login_url, headers=headers, json=data)
    if response.status_code == 200:
        resp = response.json()
        return resp['data']['token']  # If the response was successful, no Exception will be raised
    else:
        response.raise_for_status()  # Raises stored HTTPError, if one occurred.

token = login(api_key, email, password)
print(token)
def get_data_from_api(url_path):
    all_data = []
    records = 0
    page_return = 150
    headers = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {token}',
    }
    query = {
        'per_page': 150,
        'show_inactive': 'No',
    }
    while True:
        if records != 0:
            query['since_id'] = all_data[-1]['id']
            logger.debug(f"Since ID: {query['since_id']}")
        response = requests.get(f"{url}{url_path}", headers=headers,json=query)
        if response.status_code == 200:
            data = response.json()
            all_data.extend(data.get('data'))  # If the response was successful, no Exception will be raised
            records += len(data.get('data'))
            page_return = len(data.get('data'))
            logger.debug(f"Page: {page_return}, Records: {records}")
            logger.info(f"Data: {data.get('data')}")
            if page_return != 150:
                logger.debug(f"Fin Page: {page_return}, Records: {records}")
                # logger.debug(f"Data: {data}")
                return all_data
        else:
            response.raise_for_status()  # Raises stored HTTPError, if one occurred.

def get_needs():
    url_path = 'needs'
    data = get_data_from_api(url_path)
    return data['data']


def transform_responses(responses):
    shifts_dict = {}
    for response in responses:
        shift_id = response["shift"]["id"]
        user = response["user"]
        logger.debug(f'response: {response}')
        print(response)
        if shift_id in shifts_dict:
            shifts_dict[shift_id]["users"].append(user)
        else:
            shift = response["shift"]
            shift["start_time"] = datetime.strptime(f"{shift['start']}", "%Y-%m-%d %H:%M:%S")
            shift["end_time"] = datetime.strptime(f"{shift['end']}", "%Y-%m-%d %H:%M:%S")
            need = response["need"]
            shift["need_id"] = need["id"]
            shift["duration"] = shift["duration"]
            shift["title"] = need["need_title"]
            shift["users"] = [user]
            shifts_dict[shift_id] = shift

        shifts_dict[shift_id]["slots_filled"] = len(shifts_dict[shift_id]["users"])
    # return shifts_dict
    print(shifts_dict)
    return list(shifts_dict.values())

def update_responses():
    data = get_data_from_api('responses')
    tr = transform_responses(data)
    gcal.get_calendars(gcal.service)
    gcal.update_calendar_events(tr, gcal.service, calendar_id=calendar_id)

def get_user_list(api_key, offset=0, limit=50):
    # url = 'https://api.galaxydigital.com/agencies'
    url = 'https://volunteerapi.com/agencies'
    headers = {
        'Authorization': f'{api_key}',
    }

    response = requests.get(url, headers=headers)

    params = {
        'key': api_key,
        'offset': offset,
        'limit': limit,
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json() 
    else:
        response.raise_for_status()  

update_responses()