import requests
import os
from dotenv import load_dotenv
import json
import gcal
import model
from datetime import datetime
import time
import pytz
from loguru import logger
import model

logger.add("debug.log", format="{time} {level} {message}", level='ERROR', retention="1 week", rotation="10 MB")
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

    def get_data_from_api(self, url_path, additional_params=None):
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
        
        # Merge additional parameters if provided
        if additional_params:
            query.update(additional_params)
        
        while True:
            if records != 0:
                query['since_id'] = all_data[-1]['id']
                logger.debug(f"Since ID: {query['since_id']}")
            
            response = requests.get(f"{self.url}{url_path}", headers=headers, json=query)
            
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

        current_date = datetime.now().strftime('%Y-%m-%d')
        # data = self.get_data_from_api(f'responses?since_updated={current_date}')
        data = self.get_data_from_api('responses')
        # response = model.ResponseObject.parse_obj(data[3])
        # print(response)
        # return data
        tr = self.transform_responses(data)
        # Save transformed responses to JSON file
        with open('transformed_responses.json', 'w') as f:
            json.dump(tr, f, default=str)
        gcal.get_calendars(gcal.service)
        gcal.update_calendar_events(tr, gcal.service, calendar_id=self.calendar_id, add_attendees=False)
        logger.debug(f"updated_responses complete")

    def user_checkin_update(self):
        with open('transformed_responses.json', 'r') as f:
            tr = json.load(f)
        shifts_to_update = []
        
        try:
            # Get current date in YYYY-MM-DD format
            current_date = datetime.now().strftime('%Y-%m-%d')
            # Fetch all hours updated today in a single API call
            hours_data = self.get_data_from_api('hours', {'since_updated': current_date})
            
            # Create a mapping of user IDs to their hour status
            user_status_map = {}
            if hours_data is not None:
                for hour in hours_data:
                    if 'user' in hour and 'id' in hour['user']:
                        user_id = hour['user']['id']
                        hour_status = hour.get('hour_status', '')
                        user_status_map[user_id] = hour_status
            
            for shift in tr:
                current_time = datetime.now(pytz.timezone('America/Chicago'))
                shift_start = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.timezone('America/Chicago'))
                time_diff = current_time - shift_start
                if time_diff.total_seconds() <= 72000 and time_diff.total_seconds() >= -72000:
                    shift_updated = False
                    for user in shift['users']:
                        # Check if user ID is in our map of updated statuses
                        if user['id'] in user_status_map:
                            user['status'] = user_status_map[user['id']]
                            logger.debug(f"user: {user}")
                            shift_updated = True
                    
                    # Only add shifts that had users with updated statuses
                    if shift_updated:
                        shifts_to_update.append(shift)
            
            if len(shifts_to_update) > 0:
                logger.debug(f"Updating {len(shifts_to_update)} shifts")
                logger.debug(f"shifts_to_update: {shifts_to_update}")
                
                # Convert string datetime values to datetime objects before passing to gcal
                for shift in shifts_to_update:
                    if isinstance(shift['start_time'], str):
                        shift['start_time'] = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S')
                    if isinstance(shift['end_time'], str):
                        shift['end_time'] = datetime.strptime(shift['end_time'], '%Y-%m-%d %H:%M:%S')
                
                gcal.get_calendars(gcal.service)
                gcal.update_calendar_events(shifts_to_update, gcal.service, calendar_id=self.calendar_id, add_attendees=False)
        except Exception as e:
            logger.error(f"Error updating checkin shifts: {e}")
        return shifts_to_update
    
    def get_next_shift(self):
        with open('transformed_responses.json', 'r') as f:
            tr = json.load(f)
        next_shift_time_diff = 0
        for shift in tr:
            current_time = datetime.now(pytz.timezone('America/Chicago'))
            shift_start = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.timezone('America/Chicago'))
            time_diff = current_time - shift_start
            if time_diff.total_seconds() > next_shift_time_diff:
                next_shift_time_diff = time_diff.total_seconds()
                next_shift = shift
        return next_shift_time_diff
    
    def get_last_shift(self):
        with open('transformed_responses.json', 'r') as f:
            tr = json.load(f)
        #Larger than 10000 is a long time ago
        last_shift_time_diff = 10000
        for shift in tr:
            current_time = datetime.now(pytz.timezone('America/Chicago'))
            shift_start = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.timezone('America/Chicago'))
            time_diff = shift_start - current_time
            if 0 < time_diff.total_seconds() < last_shift_time_diff:
                last_shift_time_diff = time_diff.total_seconds()
                last_shift = shift
        return last_shift_time_diff
            

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

