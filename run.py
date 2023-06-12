import get_connected as gc
import gcal
import model

gcc = gc.GalaxyAPI()

data = gcc.get_data_from_api('responses')
response = model.ResponseObject.parse_obj(data[3])
print(response)
print(type(response))
print(type(response.shift.end))
gcc.update_responses()