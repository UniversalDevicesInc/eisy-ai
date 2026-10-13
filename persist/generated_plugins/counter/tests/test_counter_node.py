import os
import sys
import types
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeNode:
    def __init__(self, polyglot, primary, address, name):
        self.poly = polyglot
        self.primary = primary
        self.address = address
        self.name = name
        self.values = {}

    def setDriver(self, driver, value, *args, **kwargs):
        self.values[driver] = value

    def reportDrivers(self):
        pass


_fake = types.ModuleType('udi_interface')
_fake.Node = _FakeNode
_fake.LOGGER = logging.getLogger('test')
sys.modules['udi_interface'] = _fake

import counter_node  # noqa: E402
from counter_node import CounterNode, COUNTER_MAX  # noqa: E402


def make():
    return CounterNode(None, 'ctl', 'counter', 'Counter')


def test_tick_adds_one():
    n = make()
    n.step = 50
    n.tick()
    n.tick()
    assert n.count == 2
    assert n.values['COUNTER'] == 2


def test_tick_wraps_at_max():
    n = make()
    n.count = COUNTER_MAX
    n.tick()
    assert n.count == 0


def test_increment_uses_step():
    n = make()
    n.cmd_set_step({'value': '10'})
    n.cmd_increment()
    assert n.count == 10
    assert n.values['STEP'] == 10


def test_decrement_clamps_at_zero():
    n = make()
    n.step = 10
    n.count = 4
    n.cmd_decrement()
    assert n.count == 0


def test_set_step_rejects_out_of_range():
    n = make()
    n.cmd_set_step({'value': '0'})
    n.cmd_set_step({'value': '10001'})
    n.cmd_set_step({'value': 'abc'})
    assert n.step == 1
    n.cmd_set_step({'value': '10000'})
    assert n.step == 10000


def test_start_stop_state():
    n = make()
    n.start_counting()
    assert n.running and n.values['ST'] == 1
    n.stop_counting()
    assert (not n.running) and n.values['ST'] == 0
