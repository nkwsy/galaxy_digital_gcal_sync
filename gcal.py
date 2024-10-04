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
        attendees += f"{user['user_fname']} {user['user_lname']} email: {user['user_email']} \n"
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
    for shift in shifts:
            # Check to see if duration of shift is greater than 24 hours
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
                # attendees = [{'email': user['user_email']} for user in shift['users']]
                # event['attendees'] = attendees
                event['attendees'] = [{'email': 'test@urbanriv.org'}]
            else:
                event['description'] = create_attendees_list(shift['users'])
            # Check if event exists
            existing_event = next((e for e in events['items'] if e['id'] == event_id), None)
            if existing_event:
                # Update the event
                logger.info(f"Updating event {event_id}, {event}")
                service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
            else:
                try:
                    # Create new event
                    logger.info(f"Creating event {event_id}, {event}")
                    service.events().insert(calendarId=calendar_id, body=event).execute()
                except HttpError as error:
                    if error.resp.status == 409:
                        logger.error(f"Event with this ID already exists. Consider updating it instead.")
                    else:
                        logger.error(f"Failed to create event {event_id}: {error}")
    

#TODO: Get updates from calendar and reflect in galaxy digital i.e. if a user declines a shift, update galaxy digital
def get_calendars(service):
    calendars = service.calendarList().list().execute()
    print(calendars)
    return calendars['items']

