import gcal
import model
import get_connected as gc

gcc = gc.GalaxyAPI()

# users = gcc.get_data_from_api('users')
# user_objects = [model.UserObject.parse_obj(user) for user in users]

data = gcc.get_data_from_api('responses')
response = model.ResponseObject.parse_obj(data[3])
print(response)
print(type(response))
print(type(response.shift.end))
gcc.update_responses()