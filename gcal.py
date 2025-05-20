import csv
from loguru import logger
from datetime import datetime
import pytz
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time


# If modifying these SCOPES, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

creds = None
if os.path.exists('token.json'):
    creds = Credentials.from_authorized_user_file('token.json')
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open('token.json', 'w') as token:
        token.write(creds.to_json())

service = build('calendar', 'v3', credentials=creds)
def convert_to_iso(datetime_str):
    return datetime_str.replace(" ", "T")

def create_attendees_list(users):
    attendees = 'Signups: \n'
    for user in users:
        if 'status' in user:
            if user['status'] == 'pending':
                attendees += f"🟡 {user['user_fname']} {user['user_lname']} email: {user['user_email']} \n"
            elif user['status'] == 'approved':
                attendees += f"🟢 {user['user_fname']} {user['user_lname']} email: {user['user_email']} \n"
        else:
            attendees += f"🔘 {user['user_fname']} {user['user_lname']} email: {user['user_email']} \n"
    return attendees

#Hacky way to change the color of the event, https://lukeboyle.com/blog/posts/google-calendar-api-color-id
def change_color(attendees):
    if int(attendees) < 2:
        return '2'
    else:
        return '10'
    
#TODO: Add attendees to calendar event,
#TODO: Add HTML description to calendar event
#TODO: Add location to calendar event, pull from galaxy digital API
#TODO: Add description to calendar event, pull from galaxy digital API
def update_calendar_events(shifts, service, calendar_id='primary', add_attendees=False):
    events = service.events().list(calendarId=calendar_id, maxResults=2500).execute()
    logger.info(f"Updating calendar {calendar_id}")
    logger.debug(f"Events: {events}")
    RATE_LIMIT_SLEEP = 0.12  # ~8 requests/sec (600/min)
    MAX_RETRIES = 5
    for shift in shifts:
        # Check to see if duration of shift is greater than 24 hours
        if isinstance(shift['end_time'], str):
            end_time = datetime.strptime(shift['end_time'], '%Y-%m-%d %H:%M:%S')
            start_time = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S')
            time_delta = end_time - start_time
        else:
            time_delta = shift['end_time'] - shift['start_time']
        if time_delta.days > 1:
            logger.error(f"Shift {shift['id']} is longer than 24 hours, skipping")
            continue
        event_id = shift['id']
        event = {
            'id': event_id,
            'summary': f"{shift['title']} - ({shift['slots_filled']}/{shift['slots']}) ",
            'start': {
                'dateTime': shift['start_time'].isoformat(),
                'timeZone': 'America/Chicago',
            },
            'end': {
                'dateTime': shift['end_time'].isoformat(),
                'timeZone': 'America/Chicago',
            },
            'colorId': change_color(shift['slots_filled']),
        }
        # Get the list of event attendees
        if add_attendees:
            event['attendees'] = [{'email': 'test@urbanriv.org'}]
        else:
            event['description'] = create_attendees_list(shift['users'])
        # Check if event exists
        existing_event = next((e for e in events['items'] if e['id'] == event_id), None)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if existing_event:
                    logger.info(f"Updating event {event_id}, {event}")
                    service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
                else:
                    logger.info(f"Creating event {event_id}, {event}")
                    service.events().insert(calendarId=calendar_id, body=event).execute()
                break  # Success, exit retry loop
            except HttpError as error:
                if error.resp.status == 409:
                    logger.error(f"Event with this ID already exists. Consider updating it instead.")
                    break
                elif error.resp.status == 403 and 'rateLimitExceeded' in str(error):
                    wait_time = (2 ** attempt)  # Exponential backoff: 2, 4, 8, 16, 32 seconds
                    logger.error(f"Rate limit exceeded. Attempt {attempt}/{MAX_RETRIES}. Waiting {wait_time} seconds before retrying...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to create/update event {event_id}: {error}")
                    break
        time.sleep(RATE_LIMIT_SLEEP)  # Rate limit: sleep between requests
    

#TODO: Get updates from calendar and reflect in galaxy digital i.e. if a user declines a shift, update galaxy digital
def get_calendars(service):
    calendars = service.calendarList().list().execute()
    print(calendars)
    return calendars['items']

