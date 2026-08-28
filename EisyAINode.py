import udi_interface, os, sys, json, time
LOGGER = udi_interface.LOGGER
Custom = udi_interface.Custom
class EisyAINode(udi_interface.Node):
    id = '261318'
    """This is a list of properties that were defined in the nodedef"""
    drivers = []

    def __init__(self, polyglot, plugin, controller='eisy-aicontrol',
        address='261318', name='Eisy AI '):
        super().__init__(polyglot, controller, address, name)
        self.plugin = plugin

    def getUOM(self, driver: str):
        try:
            for driver_def in self.drivers:
                if driver_def['driver'] == driver:
                    return driver_def['uom']
            return None
        except Exception as ex:
            return None
    """This is a list of commands that were defined in the nodedef"""
    commands = {}
    """    """
    """    """
    """########WARNING: DO NOT MODIFY THIS LINE!!! NOTHING BELOW IS REGENERATED!#########"""
