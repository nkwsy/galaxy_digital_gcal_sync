import requests
import os
from dotenv import load_dotenv
import json
import gcal
import model
from datetime import datetime
import pytz
from loguru import logger
import model

logger.add("debug.log", format="{time} {level} {message}", retention="1 week", rotation="10 MB")
load_dotenv()

class GalaxyAPI:

    def __init__(self):
        self.api_key = os.getenv('API_KEY')
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.calendar_id = os.getenv('CALENDAR_ID')
        self.url = 'https://api.galaxydigital.com/api/'
        self.token = self.login()
        self.shifts = {}
        self.login_responce = None 
    def login(self):
        login_url = 'https://api.galaxydigital.com/api/users/login'
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        data = {
            'key': f'{self.api_key}',
            'user_email': f'{self.email}',
            'user_password': f'{self.password}',
        }
        response = requests.post(login_url, headers=headers, json=data)
        if response.status_code == 200:
            resp = response.json()
            self.login_responce = resp['data'] 
            return resp['data']['token']  # If the response was successful, no Exception will be raised
        else:
            response.raise_for_status()  # Raises stored HTTPError, if one occurred.

    def get_data_from_api(self, url_path):
        all_data = []
        records = 0
        page_return = 150
        headers = {
        'Accept': 'application/json',
        'Authorization': f"Bearer {self.token}",
        }
        query = {
            'per_page': 150,
            'show_inactive': 'No',
        }
        while True:
            if records != 0:
                query['since_id'] = all_data[-1]['id']
                logger.debug(f"Since ID: {query['since_id']}")
            response = requests.get(f"{self.url}{url_path}", headers=headers,json=query)
            if response.status_code == 200:
                data = response.json()
                all_data.extend(data.get('data'))  # If the response was successful, no Exception will be raised
                records += len(data.get('data'))
                page_return = len(data.get('data'))
                # logger.debug(f"Page: {page_return}, Records: {records}")
                # logger.info(f"Data: {data.get('data')}")
                if page_return != 150:
                    logger.debug(f"Fin Page: {page_return}, Records: {records}")
                    return all_data
            else:
                response.raise_for_status()  # Raises stored HTTPError, if one occurred.

    def get_needs(self):
        url_path = 'needs'
        data = self.get_data_from_api(url_path)

        return data['data']

    def transform_responses(self, responses):
        shifts_dict = {}
        for response in responses:
            shift_id = response["shift"]["id"]
            user = response["user"]
            logger.debug(f'response: {response}')
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
        return list(shifts_dict.values())

    def update_responses(self):
        data = self.get_data_from_api('responses')
        # response = model.ResponseObject.parse_obj(data[3])
        # print(response)
        # return data
        tr = self.transform_responses(data)
        gcal.get_calendars(gcal.service)
        gcal.update_calendar_events(tr, gcal.service, calendar_id=self.calendar_id)
        logger.debug(f"updated_responses complete")

    def get_user_list(self, api_key, offset=0, limit=50):
        url = 'https://volunteerapi.com/agencies'
        headers = {
            'Authorization': f'{api_key}',
        }
        params = {
            'key': api_key,
            'offset': offset,
            'limit': limit,
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json() 
        else:
            response.raise_for_status()  

    def transform_objects(self, responce, model_class):
        all_objects = []
        for object in responce:
            all_objects.append(model_class.parse_obj(object))
        return all_objects
# #TODO: sync with internal mongoDB
# api_key = os.getenv('API_KEY')
# email = os.getenv('EMAIL')
# password = os.getenv('PASSWORD')
# calendar_id = os.getenv('CALENDAR_ID')

# url = 'https://api.galaxydigital.com/api/'


# shifts = {}
# def login(api_key, email, password):
#     login_url = 'https://api.galaxydigital.com/api/users/login'
#     headers = {
#         'Accept': 'application/json',
#         'Content-Type': 'application/json',
#     }
#     data = {
#         'key': f'{api_key}',
#         'user_email': f'{email}',
#         'user_password': f'{password}',
#     }
#     response = requests.post(login_url, headers=headers, json=data)
#     if response.status_code == 200:
#         resp = response.json()
#         return resp['data']['token']  # If the response was successful, no Exception will be raised
#     else:
#         response.raise_for_status()  # Raises stored HTTPError, if one occurred.

# token = login(api_key, email, password)
# print(token)
# def get_data_from_api(url_path):
#     all_data = []
#     records = 0
#     page_return = 150
#     headers = {
#     'Accept': 'application/json',
#     'Authorization': f'Bearer {token}',
#     }
#     query = {
#         'per_page': 150,
#         'show_inactive': 'No',
#     }
#     while True:
#         if records != 0:
#             query['since_id'] = all_data[-1]['id']
#             logger.debug(f"Since ID: {query['since_id']}")
#         response = requests.get(f"{url}{url_path}", headers=headers,json=query)
#         if response.status_code == 200:
#             data = response.json()
#             all_data.extend(data.get('data'))  # If the response was successful, no Exception will be raised
#             records += len(data.get('data'))
#             page_return = len(data.get('data'))
#             logger.debug(f"Page: {page_return}, Records: {records}")
#             logger.info(f"Data: {data.get('data')}")
#             if page_return != 150:
#                 logger.debug(f"Fin Page: {page_return}, Records: {records}")
#                 # logger.debug(f"Data: {data}")
#                 return all_data
#         else:
#             response.raise_for_status()  # Raises stored HTTPError, if one occurred.

# def get_needs():
#     url_path = 'needs'
#     data = get_data_from_api(url_path)
#     return data['data']


# def transform_responses(responses):
#     shifts_dict = {}
#     for response in responses:
#         shift_id = response["shift"]["id"]
#         user = response["user"]
#         logger.debug(f'response: {response}')
#         print(response)
#         if shift_id in shifts_dict:
#             shifts_dict[shift_id]["users"].append(user)
#         else:
#             shift = response["shift"]
#             shift["start_time"] = datetime.strptime(f"{shift['start']}", "%Y-%m-%d %H:%M:%S")
#             shift["end_time"] = datetime.strptime(f"{shift['end']}", "%Y-%m-%d %H:%M:%S")
#             need = response["need"]
#             shift["need_id"] = need["id"]
#             shift["duration"] = shift["duration"]
#             shift["title"] = need["need_title"]
#             shift["users"] = [user]
#             shifts_dict[shift_id] = shift

#         shifts_dict[shift_id]["slots_filled"] = len(shifts_dict[shift_id]["users"])
#     # return shifts_dict
#     print(shifts_dict)
#     return list(shifts_dict.values())

# def update_responses():
#     data = get_data_from_api('responses')
#     tr = transform_responses(data)
#     gcal.get_calendars(gcal.service)
#     gcal.update_calendar_events(tr, gcal.service, calendar_id=calendar_id)

# def get_user_list(api_key, offset=0, limit=50):
#     # url = 'https://api.galaxydigital.com/agencies'
#     url = 'https://volunteerapi.com/agencies'
#     headers = {
#         'Authorization': f'{api_key}',
#     }

#     response = requests.get(url, headers=headers)

#     params = {
#         'key': api_key,
#         'offset': offset,
#         'limit': limit,
#     }
    
#     response = requests.get(url, headers=headers)
    
#     if response.status_code == 200:
#         return response.json() 
#     else:
#         response.raise_for_status()  

