import get_connected as gc
import gcal
import model
import importlib
import time
from loguru import logger


def update_cal():
    while True:
        gcc = gc.GalaxyAPI()
        gcc.update_responses()
        logger.debug("Updated responses")
        time.sleep(6000)
        importlib.reload(gc)
        importlib.reload(gcal)

update_cal()
