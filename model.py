# generated by datamodel-codegen:
#   filename:  api.yaml
#   timestamp: 2023-06-09T22:44:12+00:00

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import List, Optional

from pydantic import AnyUrl, BaseModel, EmailStr, Field


class UgStatus(Enum):
    active = 'active'
    pending = 'pending'
    inactive = 'inactive'


class UgSuppressResume(Enum):
    Yes = 'Yes'
    No = 'No'


class UgAllowMemberRemove(Enum):
    Yes = 'Yes'
    No = 'No'


class UgSubmittedHours(Enum):
    auto = 'auto'
    manual = 'manual'
    approved = 'approved'


class UgLimit(Enum):
    Yes = 'Yes'
    No = 'No'


class UgApproval(Enum):
    Yes = 'Yes'
    No = 'No'


class TeamStatus(Enum):
    active = 'active'
    inactive = 'inactive'


class AgencyMiniObject(BaseModel):
    id: Optional[int] = None
    domain_id: Optional[int] = None
    agency_name: Optional[str] = None


class InitiativeMiniObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    init_title: Optional[str] = None


class GroupMiniObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    group_title: Optional[str] = None


class NeedMiniObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    need_title: Optional[str] = None


class ResponseAnswerObject(BaseModel):
    type: Optional[str] = None
    key: Optional[str] = None
    area: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None


class TrackMiniObject(BaseModel):
    id: Optional[str] = Field(None, example='432155')
    name: Optional[str] = Field(None, example='default')
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')


class TeamMiniObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    name: Optional[str] = None


class Leader(Enum):
    Yes = 'Yes'
    No = 'No'


class GroupUserMiniObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user_fname: Optional[str] = None
    user_lname: Optional[str] = None
    user_email: Optional[str] = None
    leader: Optional[Leader] = None


class UserMiniObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user_fname: Optional[str] = None
    user_lname: Optional[str] = None
    user_email: Optional[str] = None


class TeamMembersObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user_fname: Optional[str] = None
    user_lname: Optional[str] = None
    user_email: Optional[str] = None
    leader: Optional[Leader] = None


class Status(Enum):
    active = 'active'
    pending = 'pending'
    inactive = 'inactive'
    expired = 'expired'
    rejected = 'rejected'
    resubmit = 'resubmit'


class UserQualificationsObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    qualification_id: Optional[str] = None
    qualification_title: Optional[str] = None
    status: Optional[Status] = None
    expires: Optional[date] = None


class QualificationUsersObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user_fname: Optional[str] = None
    user_lname: Optional[str] = None
    user_email: Optional[str] = None
    status: Optional[Status] = None
    expires: Optional[date] = None


class CategoryObject(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None


class ExtraObject(BaseModel):
    key: Optional[str] = None
    value: Optional[str] = None


class QualificationType(Enum):
    select = 'select'
    radio = 'radio'
    text = 'text'
    textarea = 'textarea'


class QualificationDuration(Enum):
    date = 'date'
    field_1month = '1month'
    field_6months = '6months'
    field_1year = '1year'
    field_2years = '2years'
    field_3years = '3years'
    forever = 'forever'
    field_1week = '1week'
    field_2weeks = '2weeks'
    firstofyear = 'firstofyear'


class QualificationApproval(Enum):
    manual = 'manual'
    auto = 'auto'
    ifCorrect = 'ifCorrect'


class QualificationObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    qualification_title: Optional[str] = None
    qualification_cat_id: Optional[str] = None
    qualification_question: Optional[str] = None
    qualification_type: Optional[QualificationType] = Field(None, example='select')
    qualification_options: Optional[List[str]] = Field(
        None, example=['Option A', 'Option B']
    )
    qualification_link_url: Optional[str] = None
    qualification_link_text: Optional[str] = None
    qualification_level: Optional[str] = None
    qualification_duration: Optional[QualificationDuration] = None
    qualification_approval: Optional[QualificationApproval] = None
    qualification_status: Optional[str] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    updated_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')


class FamilyFriendly(Enum):
    Yes = 'Yes'
    No = 'No'


class Outdoors(Enum):
    Yes = 'Yes'
    No = 'No'


class Accessible(Enum):
    Yes = 'Yes'
    No = 'No'


class BackgroundCheckRequired(Enum):
    Yes = 'Yes'
    No = 'No'


class AgencyStatus(Enum):
    active = 'active'
    inactive = 'inactive'
    pending = 'pending'
    imported = 'imported'


class AgencyPartner(Enum):
    Yes = 'Yes'
    No = 'No'


class AgencyObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    agency_name: Optional[str] = None
    agency_link: Optional[str] = None
    agency_address: Optional[str] = None
    agency_address2: Optional[str] = None
    agency_city: Optional[str] = None
    agency_state: Optional[str] = None
    agency_postal: Optional[str] = None
    agency_extra_location: Optional[str] = None
    agency_phone: Optional[str] = None
    agency_phone_extension: Optional[str] = None
    agency_fax: Optional[str] = None
    agency_twitter_link: Optional[str] = None
    agency_facebook_link: Optional[str] = None
    agency_instagram_link: Optional[str] = None
    agency_youtube_link: Optional[str] = None
    agency_linkedin_link: Optional[str] = None
    agency_email: Optional[str] = None
    agency_video: Optional[str] = None
    agency_url: Optional[str] = None
    agency_ein: Optional[str] = None
    agency_comments: Optional[str] = None
    agency_status: Optional[AgencyStatus] = None
    agency_latitude: Optional[str] = None
    agency_longitude: Optional[str] = None
    agency_contact: Optional[str] = None
    agency_contact_title: Optional[str] = None
    agency_news: Optional[str] = None
    agency_mission: Optional[str] = None
    agency_contacts: Optional[List[str]] = Field(
        None, example=['mary.smith@example.com', 'kevin@example.com']
    )
    agency_hours: Optional[str] = None
    agency_partner: Optional[AgencyPartner] = None
    logo: Optional[AnyUrl] = Field(
        None,
        description="Direct link to Agency logo. If agency hasn't provided a logo, the image will be a colored letter box.",
        example='https://www.example.com/content/www.example.com/agency/12345.jpg',
    )
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    updated_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')


class ShiftRequestSchema(BaseModel):
    slots: Optional[str] = None
    start_date: Optional[date] = None
    start_time: Optional[time] = Field(None, example='14:00:00')
    duration: Optional[int] = Field(
        None, description='Duration in minutes', example='120'
    )


class ShiftObject(BaseModel):
    id: Optional[str] = Field(None, example='1234567')
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    duration: Optional[str] = None
    slots: Optional[str] = None


class UserOneclickObject(BaseModel):
    link: Optional[str] = Field(
        None,
        example='https://volunteer.example.com/users/oneclick/c43f51d6a58ebd40caaa433585dd46a7/',
    )
    expires: Optional[str] = Field(None, example='2022-01-14 14:25:00')
    now: Optional[str] = Field(None, example='2022-01-14 14:10:00')


class UserAgeRange(Enum):
    field_13_18 = '13-18'
    field_19_24 = '19-24'
    field_25_34 = '25-34'
    field_35_44 = '35-44'
    field_45_54 = '45-54'
    field_55_64 = '55-64'
    field_65_ = '65+'


class UserDisaster(Enum):
    Yes = 'Yes'
    No = 'No'


class UserEthnicity(Enum):
    American_Indian_and_Alaska_Native = 'American Indian and Alaska Native'
    Asian = 'Asian'
    Black_or_African_American = 'Black or African American'
    Hispanic = 'Hispanic'
    Native_Hawaiian_and_Other_Pacific_Islander = (
        'Native Hawaiian and Other Pacific Islander'
    )
    Non_Hispanic_White = 'Non-Hispanic White'
    White = 'White'


class UserGender(Enum):
    Male = 'Male'
    Female = 'Female'
    PreferNotToSay = 'PreferNotToSay'
    Other = 'Other'


class UserGradSemester(Enum):
    spring = 'spring'
    summer = 'summer'
    fall = 'fall'
    winter = 'winter'


class UserStatus(Enum):
    active = 'active'
    pending = 'pending'
    imported = 'imported'
    inactive = 'inactive'


class UserObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user_reference_id: Optional[str] = None
    user_fname: Optional[str] = None
    user_mname: Optional[str] = None
    user_lname: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    user_phone_cell: Optional[str] = None
    user_username: Optional[str] = None
    user_address: Optional[str] = None
    user_address2: Optional[str] = None
    user_city: Optional[str] = None
    user_state: Optional[str] = None
    user_postal: Optional[str] = None
    user_county: Optional[str] = None
    user_country: Optional[str] = None
    user_age_range: Optional[UserAgeRange] = None
    user_disaster: Optional[UserDisaster] = Field(
        None, description='Contact in event of disaster'
    )
    user_birthday: Optional[date] = None
    user_company: Optional[str] = None
    user_company_title: Optional[str] = None
    user_department: Optional[str] = None
    user_ethnicity: Optional[UserEthnicity] = None
    user_gender: Optional[UserGender] = None
    user_grad_semester: Optional[UserGradSemester] = None
    user_grad_year: Optional[str] = None
    user_notes: Optional[str] = None
    user_comments: Optional[str] = None
    user_status: Optional[UserStatus] = Field(None, example='active')
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    updated_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')


class QType(Enum):
    textarea = 'textarea'
    input = 'input'
    radio = 'radio'
    checkbox = 'checkbox'
    select = 'select'


class QArea(Enum):
    needResponse = 'needResponse'
    initiativeResponse = 'initiativeResponse'
    reflections = 'reflections'
    initiativeNeed = 'initiativeNeed'
    userGroup = 'userGroup'
    hoursQuestion = 'hoursQuestion'


class QStatus(Enum):
    active = 'active'
    pending = 'pending'
    inactive = 'inactive'


class QuestionObject(BaseModel):
    id: Optional[str] = None
    q_type: Optional[QType] = Field(None, example='input')
    q_options: Optional[List[str]] = Field(None, example=['Option 1', 'Option 2'])
    q_area: Optional[QArea] = None
    q_area_id: Optional[str] = None
    q_status: Optional[QStatus] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    updated_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')


class HourStatus(Enum):
    pending = 'pending'
    approved = 'approved'
    entered = 'entered'
    denied = 'denied'
    inactive = 'inactive'


class HourType(Enum):
    need = 'need'
    individual = 'individual'


class HourObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user: Optional[UserMiniObject] = None
    groups: Optional[GroupMiniObject] = None
    need: Optional[NeedMiniObject] = None
    hour_description: Optional[str] = None
    hour_date_start: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    hour_date_end: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    hour_hours: Optional[str] = None
    hour_miles: Optional[str] = None
    hour_location: Optional[str] = None
    hour_contact_name: Optional[str] = None
    hour_contact_details: Optional[str] = None
    hour_relationship: Optional[str] = None
    hour_source: Optional[str] = None
    hour_status: Optional[HourStatus] = Field(None, example='approved')
    hour_type: Optional[HourType] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    updated_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')


class Status2(Enum):
    active = 'active'
    inactive = 'inactive'


class UserResponseObject(BaseModel):
    id: Optional[str] = None
    need_id: Optional[str] = None
    date_start: Optional[datetime] = None
    duration: Optional[str] = None
    status: Optional[Status2] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ResponseObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    agency: Optional[AgencyMiniObject] = None
    shift: Optional[ShiftObject] = None
    need: Optional[NeedMiniObject] = None
    user: Optional[UserMiniObject] = None
    initiative: Optional[InitiativeMiniObject] = None
    team: Optional[TeamMiniObject] = None
    response_phone: Optional[str] = None
    response_address: Optional[str] = None
    response_note: Optional[str] = None
    response_date_added: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    response_date_updated: Optional[datetime] = Field(
        None, example='2021-01-01 12:00:00'
    )
    response_source: Optional[str] = None
    response_status: Optional[str] = None
    response_comments: Optional[str] = None
    answers: Optional[List[ResponseAnswerObject]] = None


class TagObject(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None


class InterestObject(BaseModel):
    id: Optional[str] = Field(
        None, description='Unique id for the user / interest relationship'
    )
    name: Optional[str] = None


class ImpactObject(BaseModel):
    id: Optional[str] = Field(None, description='Unique id for the impact area')
    impact_name: Optional[str] = None


class CauseObject(BaseModel):
    id: Optional[str] = Field(
        None, description='Unique id for the user / cause relationship'
    )
    name: Optional[str] = None


class EventArea(Enum):
    agency = 'agency'


class EventRsvp(Enum):
    True_ = True
    False_ = False


class EventAllDay(Enum):
    True_ = True
    False_ = False


class EventObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    event_area: Optional[EventArea] = None
    event_area_id: Optional[str] = Field(
        None, description='agency the event belongs to'
    )
    event_title: Optional[str] = None
    event_description: Optional[str] = None
    event_location: Optional[str] = None
    event_address: Optional[str] = None
    event_address2: Optional[str] = None
    event_city: Optional[str] = None
    event_state: Optional[str] = None
    event_postal: Optional[str] = None
    event_email: Optional[EmailStr] = None
    event_rsvp: Optional[EventRsvp] = Field(
        None, description='Does this event accept RSVPs on the web?'
    )
    event_date_start: Optional[str] = None
    event_date_end: Optional[str] = None
    event_all_day: Optional[EventAllDay] = Field(
        None,
        description='If yes, the event_date_end will automatically be set to the end of the date it starts.',
    )
    event_comments: Optional[str] = None
    tags: Optional[List[TagObject]] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    update_at: Optional[str] = Field(None, example='2021-01-01 12:00:00')


class User(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    user_fname: Optional[str] = None
    user_lname: Optional[str] = None
    user_email: Optional[EmailStr] = None


class LoginObject(BaseModel):
    user: Optional[User] = Field(None, description='User object')
    token: Optional[str] = None
    expires: Optional[datetime] = None


class ClusterObject(BaseModel):
    id: Optional[str] = Field(
        None, description='Unique id for the agency / cluster relationship'
    )
    name: Optional[str] = None


class BenchmarkStatus(Enum):
    active = 'active'
    inactive = 'inactive'
    pending = 'pending'


class BenchmarkIcon(Enum):
    Bronze_10Hours = 'Bronze_10Hours'
    Bronze_25Hours = 'Bronze_25Hours'
    Bronze_CommunityChampion = 'Bronze_CommunityChampion'
    Bronze_I_Made_A_Difference = 'Bronze_I_Made_A_Difference'
    Bronze_OutStandingService = 'Bronze_OutStandingService'
    Silver_20Hours = 'Silver_20Hours'
    Silver_50Hours = 'Silver_50Hours'
    Silver_CommunityChampion = 'Silver_CommunityChampion'
    Silver_I_Made_A_Difference = 'Silver_I_Made_A_Difference'
    Silver_OutstandingService = 'Silver_OutstandingService'
    Gold_50Hours = 'Gold_50Hours'
    Gold_100Hours = 'Gold_100Hours'
    Gold_CommunityChampion = 'Gold_CommunityChampion'
    Gold_I_Made_A_Difference = 'Gold_I_Made_A_Difference'
    Gold_OutstandingService = 'Gold_OutstandingService'


class BenchmarkApprovalRequired(Enum):
    Yes = 'Yes'
    No = 'No'


class BenchmarkAllowIndvHours(Enum):
    Yes = 'Yes'
    No = 'No'


class BenchmarkObject(BaseModel):
    id: Optional[str] = None
    benchmark_status: Optional[BenchmarkStatus] = None
    benchmark_title: Optional[str] = None
    benchmark_icon: Optional[BenchmarkIcon] = None
    benchmark_hours: Optional[str] = None
    benchmark_date_start: Optional[date] = None
    benchmark_date_end: Optional[date] = None
    benchmark_approval_required: Optional[BenchmarkApprovalRequired] = None
    benchmark_allow_indv_hours: Optional[BenchmarkAllowIndvHours] = None
    benchmark_group_id: Optional[str] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    update_at: Optional[str] = Field(None, example='2021-01-01 12:00:00')


class BenchmarkMiniObject(BaseModel):
    id: Optional[str] = None
    benchmark_status: Optional[BenchmarkStatus] = None
    benchmark_title: Optional[str] = None
    benchmark_icon: Optional[BenchmarkIcon] = None
    benchmark_hours: Optional[str] = None
    benchmark_date_start: Optional[date] = None
    benchmark_date_end: Optional[date] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    update_at: Optional[str] = Field(None, example='2021-01-01 12:00:00')


class EventRequestSchema(BaseModel):
    event_area: EventArea
    event_area_id: str
    event_title: str
    event_description: Optional[str] = None
    event_contact: Optional[str] = None
    event_phone: Optional[str] = None
    event_email: Optional[EmailStr] = None
    event_capacity: Optional[str] = None
    event_location: Optional[str] = None
    event_address: Optional[str] = None
    event_address2: Optional[str] = None
    event_city: Optional[str] = None
    event_state: Optional[str] = None
    event_postal: Optional[str] = None
    event_country: Optional[str] = None
    event_comments: Optional[str] = None
    event_all_day: Optional[EventAllDay] = None
    event_rsvp: Optional[EventRsvp] = None
    event_date_start: datetime = Field(..., example='2021-01-01 08:00:00')
    event_date_end: Optional[datetime] = Field(None, example='2021-01-01 23:59:59')
    event_tags: Optional[List] = Field(
        None,
        description='Submitted tags will replace any existing tags for this item',
        example=['Outdoors', 'Entertainment'],
    )


class LoginRequestSchema(BaseModel):
    user_email: str
    user_password: str
    key: str


class AuthenticateRequestSchema(BaseModel):
    user_email: str
    user_password: str


class BenchmarkRequestSchema(BaseModel):
    benchmark_title: str
    benchmark_icon: BenchmarkIcon
    benchmark_hours: Optional[str] = None
    benchmark_approval_required: BenchmarkApprovalRequired
    benchmark_date_start: date
    benchmark_date_end: date
    benchmark_allow_indv_hours: Optional[BenchmarkAllowIndvHours] = None
    benchmark_group_id: Optional[str] = None
    benchmark_status: BenchmarkStatus


class ClusterRequestSchema(BaseModel):
    name: str


class UgSubmittedHours1(Enum):
    manual = 'manual'
    auto = 'auto'
    approved = 'approved'


class UgType(Enum):
    gc = 'gc'
    slm = 'slm'


class GroupRequestSchema(BaseModel):
    ug_status: UgStatus
    ug_title: str
    ug_description: Optional[str] = None
    ug_description_private: Optional[str] = None
    ug_domains: Optional[str] = None
    ug_color: Optional[str] = None
    ug_text_color: Optional[str] = None
    ug_icon: Optional[str] = None
    ug_suppress_resume: Optional[UgSuppressResume] = None
    ug_allow_member_remove: Optional[UgAllowMemberRemove] = None
    ug_submitted_hours: Optional[UgSubmittedHours1] = None
    ug_type: UgType = Field(
        ...,
        description='You can only submit slm type if you have the Service Learning module',
    )
    ug_limit: Optional[UgLimit] = None
    ug_block_id: Optional[str] = Field(None, example='432155')
    ug_goal: Optional[str] = Field(None, example='25')
    ug_approval: Optional[UgApproval] = None


class HourStatus1(Enum):
    approved = 'approved'
    inactive = 'inactive'
    pending = 'pending'
    denied = 'denied'
    entered = 'entered'


class HourRequestSchema(BaseModel):
    hour_hours: str
    hour_miles: Optional[str] = None
    hour_start: datetime
    hour_status: HourStatus1
    hour_location: Optional[str] = None
    hour_contact_name: Optional[str] = Field(None, example='Mary Smith')
    hour_contact_details: Optional[EmailStr] = None
    hour_relationship: Optional[str] = Field(None, example='Coach')
    response_id: Optional[str] = None
    user_id: Optional[str] = None
    group_ids: Optional[List[str]] = Field(None, description='Array of user group ids')


class UserRequestSchema(BaseModel):
    user_fname: str
    user_mname: Optional[str] = None
    user_lname: str
    user_email: EmailStr
    user_username: Optional[str] = None
    user_address: Optional[str] = None
    user_address2: Optional[str] = None
    user_city: Optional[str] = None
    user_state: Optional[str] = None
    user_postal: Optional[str] = None
    user_county: Optional[str] = None
    user_country: Optional[str] = None
    user_phone: Optional[str] = None
    user_phone_cell: Optional[str] = None
    user_age_range: Optional[str] = None
    user_birthday: Optional[str] = None
    user_company: Optional[str] = None
    user_company_title: Optional[str] = None
    user_department: Optional[str] = None
    user_ethnicity: Optional[str] = None
    user_grad_semester: Optional[UserGradSemester] = None
    user_grad_year: Optional[str] = None
    user_notes: Optional[str] = None
    user_comments: Optional[str] = None
    user_reference_id: Optional[str] = None
    user_disaster: Optional[str] = None
    user_status: UserStatus = Field(..., example='active')


class AgencyStatus1(Enum):
    active = 'active'
    inactive = 'inactive'
    pending = 'pending'


class AgencyRequestSchema(BaseModel):
    agency_name: str
    agency_link: Optional[str] = None
    agency_address: Optional[str] = None
    agency_address2: Optional[str] = None
    agency_city: Optional[str] = None
    agency_state: Optional[str] = None
    agency_postal: str
    agency_phone: Optional[str] = None
    agency_phone_extension: Optional[str] = None
    agency_fax: Optional[str] = None
    agency_twitter_link: Optional[str] = None
    agency_facebook_link: Optional[str] = None
    agency_instagram_link: Optional[str] = None
    agency_youtube_link: Optional[str] = None
    agency_linkedin_link: Optional[str] = None
    agency_email: Optional[str] = None
    agency_video: Optional[str] = None
    agency_url: Optional[str] = None
    agency_ein: Optional[str] = None
    agency_comments: Optional[str] = None
    agency_status: AgencyStatus1
    agency_contact: Optional[str] = None
    agency_contact_title: Optional[str] = None
    agency_news: Optional[str] = None
    agency_mission: Optional[str] = None
    agency_contacts: Optional[str] = None
    agency_partner: Optional[AgencyPartner] = None


class NeedResponse(BaseModel):
    field_5109: Optional[str] = Field(
        None, alias='5109', example='Another response example'
    )


class InitiativeResponse(BaseModel):
    field_5009: Optional[str] = Field(
        None, alias='5009', example='Answer input string one'
    )
    field_8345: Optional[List[str]] = Field(
        None, alias='8345', example=['Option 1', 'Option 2', 'Option 4']
    )
    inputFieldTest: Optional[str] = Field(None, example='Dark Chox')


class Questions(BaseModel):
    needResponse: Optional[NeedResponse] = None
    initiativeResponse: Optional[InitiativeResponse] = None


class ResponseRequestSchema(BaseModel):
    need_id: str = Field(..., example='591717')
    user_id: str = Field(..., example='3456377')
    team_id: Optional[str] = Field(None, example='874521')
    schedule_ids: List[str]
    response_note: Optional[str] = None
    questions: Optional[Questions] = Field(
        None, description='Example of customQuestions answers'
    )


class NeedDateType(Enum):
    on = 'on'
    until = 'until'
    ongoing = 'ongoing'
    shifts = 'shifts'
    recurring = 'recurring'
    multi = 'multi'


class NeedAllowGroups(Enum):
    Yes = 'Yes'
    No = 'No'
    Only = 'Only'


class VirtualNeed(Enum):
    Yes = 'Yes'
    No = 'No'


class NeedRequestSchema(BaseModel):
    agency_id: str
    initiative_id: Optional[str] = None
    groups: Optional[List[str]] = None
    event_id: Optional[str] = None
    need_title: str
    need_body: str
    need_address: Optional[str] = None
    need_address2: Optional[str] = None
    need_city: Optional[str] = None
    need_state: Optional[str] = None
    need_postal: str
    need_type: Optional[str] = None
    need_contact: Optional[str] = None
    need_response_notify: Optional[str] = None
    need_date: Optional[str] = Field(None, example='2021-10-28')
    need_date_type: NeedDateType
    need_impact_area: Optional[str] = None
    need_volunteers_needed: Optional[str] = None
    need_public: str
    need_allow_groups: Optional[NeedAllowGroups] = None
    need_hours: str
    need_hours_description: Optional[str] = Field(None, example='9am to 5pm')
    need_comments: Optional[str] = None
    need_latitude: Optional[str] = None
    need_longitude: Optional[str] = None
    need_date_close: Optional[date] = Field(None, example='2021-01-01')
    need_status: str
    virtual_need: Optional[VirtualNeed] = None
    family_friendly: Optional[FamilyFriendly] = None
    outdoors: Optional[Outdoors] = None
    accessible: Optional[Accessible] = None
    tags: Optional[List[str]] = Field(
        None,
        description='Submitted tags will replace any existing tags for this item',
        example=['Fun', 'Sun'],
    )
    attributes: Optional[List[List]] = None
    interests: Optional[List[str]] = Field(None, example=['12345', '54299'])
    shifts: Optional[List[ShiftRequestSchema]] = None


class QualificationStatus(Enum):
    active = 'active'
    inactive = 'inactive'


class QualificationType1(Enum):
    select = 'select'
    radio = 'radio'
    input = 'input'
    textarea = 'textarea'


class QualificationLevel(Enum):
    notNeeded = 'notNeeded'
    viewAny = 'viewAny'
    respondAny = 'respondAny'
    useSite = 'useSite'
    viewSelected = 'viewSelected'
    respondSelected = 'respondSelected'


class QualificationLinkShow(Enum):
    Yes = 'Yes'
    No = 'No'


class QualificationRequired(Enum):
    Yes = 'Yes'
    No = 'No'


class QualificationHideFromRegistration(Enum):
    Yes = 'Yes'
    No = 'No'


class QualificationRequestSchema(BaseModel):
    qualification_title: str
    qualification_status: QualificationStatus
    qualification_type: QualificationType1
    qualification_question: str
    qualification_options: Optional[List[str]] = Field(
        None,
        description='Comma separated list of options for question types that are select or checkbox',
        example=['222', '333'],
    )
    qualification_correct_answer: Optional[str] = Field(
        None,
        description='If used, must be one of the options unsed in qualification_options',
        example='Option 1',
    )
    qualification_approval: Optional[QualificationApproval] = None
    qualification_level: QualificationLevel
    qualification_duration: QualificationDuration
    qualification_link_url: Optional[str] = None
    qualification_link_text: Optional[str] = None
    qualification_link_show: Optional[QualificationLinkShow] = None
    qualification_required: Optional[QualificationRequired] = None
    qualification_hide_from_registration: Optional[
        QualificationHideFromRegistration
    ] = None


class TeamStatus1(Enum):
    active = 'active'
    pending = 'pending'
    inactive = 'inactive'


class TeamRequestSchema(BaseModel):
    team_title: str
    team_description: Optional[str] = None
    team_status: TeamStatus1
    need_id: str = Field(..., example='43119')
    sch_id: str = Field(..., description='Schedule ID', example='87654332')
    user_id: str = Field(
        ..., description='User ID of first team member.', example='87654332'
    )


class GroupObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    ug_status: Optional[UgStatus] = None
    ug_title: Optional[str] = None
    ug_description: Optional[str] = None
    ug_description_private: Optional[str] = None
    ug_domains: Optional[str] = None
    ug_color: Optional[str] = None
    ug_text_color: Optional[str] = None
    ug_icon: Optional[str] = None
    ug_suppress_resume: Optional[UgSuppressResume] = None
    ug_allow_member_remove: Optional[UgAllowMemberRemove] = None
    ug_submitted_hours: Optional[UgSubmittedHours] = None
    ug_block_id: Optional[str] = None
    ug_limit: Optional[UgLimit] = None
    ug_goal: Optional[str] = None
    ug_approval: Optional[UgApproval] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    needs: Optional[List[NeedMiniObject]] = Field(
        None, description='Needs attached to user group'
    )
    users: Optional[List[GroupUserMiniObject]] = Field(
        None, description='Users attached to user group'
    )
    agencies: Optional[List[AgencyMiniObject]] = Field(
        None, description='Agencies attached to user group'
    )
    questions_reflection: Optional[List[QuestionObject]] = Field(
        None, description='Reflection questions attached to user group'
    )
    questions_join: Optional[List[QuestionObject]] = Field(
        None, description='Join questions attached to user group'
    )


class TeamObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    team_status: Optional[TeamStatus] = None
    team_title: Optional[str] = None
    team_description: Optional[str] = None
    creator: Optional[UserMiniObject] = None
    agency: Optional[AgencyMiniObject] = None
    need: Optional[NeedMiniObject] = None
    members: Optional[List[TeamMembersObject]] = None


class NeedObject(BaseModel):
    id: Optional[str] = None
    domain_id: Optional[str] = None
    agency: Optional[AgencyMiniObject] = None
    initiative: Optional[InitiativeMiniObject] = None
    groups: Optional[List[GroupMiniObject]] = None
    need_title: Optional[str] = None
    need_body: Optional[str] = None
    need_address: Optional[str] = None
    need_address2: Optional[str] = None
    need_city: Optional[str] = None
    need_state: Optional[str] = None
    need_postal: Optional[str] = None
    need_type: Optional[str] = None
    need_contact: Optional[str] = None
    need_response_notify: Optional[str] = None
    need_date: Optional[str] = Field(None, example='2021-10-28')
    need_date_type: Optional[str] = None
    need_impact_area: Optional[str] = None
    need_volunteers_needed: Optional[str] = None
    need_public: Optional[str] = None
    need_allow_groups: Optional[str] = None
    need_hours: Optional[str] = None
    need_comments: Optional[str] = None
    need_latitude: Optional[str] = None
    need_longitude: Optional[str] = None
    need_date_close: Optional[date] = Field(None, example='2021-01-01')
    family_friendly: Optional[FamilyFriendly] = None
    outdoors: Optional[Outdoors] = None
    outdoors_plan: Optional[str] = None
    accessible: Optional[Accessible] = None
    tags: Optional[List[TagObject]] = None
    shifts: Optional[List[ShiftObject]] = None
    need_status: Optional[str] = None
    created_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
    background_check_required: Optional[BackgroundCheckRequired] = None
    updated_at: Optional[datetime] = Field(None, example='2021-01-01 12:00:00')
