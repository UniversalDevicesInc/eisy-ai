import threading
import time

import udi_interface

LOGGER = udi_interface.LOGGER

COUNTER_MAX = 4294967295   # 4-byte unsigned
STEP_MIN = 1
STEP_MAX = 10000
STOPPED = 0
STARTED = 1


class CounterNode(udi_interface.Node):
    """A counter that ticks +1 every second while started.

    Increment/Decrement buttons add/subtract `step` (1..10000).
    The counter is a 4-byte unsigned integer: it never goes below 0
    and wraps to 0 after 4294967295.
    """

    id = 'counter'
    drivers = [
        {'driver': 'ST', 'value': STOPPED, 'uom': 25},
        {'driver': 'COUNTER', 'value': 0, 'uom': 110},
        {'driver': 'STEP', 'value': 1, 'uom': 56},
    ]

    def __init__(self, polyglot, primary, address, name):
        super().__init__(polyglot, primary, address, name)
        self._lock = threading.RLock()
        self._stop_evt = None
        self._thread = None
        self.count = 0
        self.step = 1
        self.running = False

    # ------------------------------------------------------------------
    # Ticker
    # ------------------------------------------------------------------
    def start_counting(self):
        with self._lock:
            if self.running:
                return
            evt = threading.Event()
            self._stop_evt = evt
            self.running = True
            self._thread = threading.Thread(
                target=self._run, args=(evt,), name='counter-tick', daemon=True)
            self._thread.start()
            self.setDriver('ST', STARTED)
        LOGGER.info('Counter started')

    def stop_counting(self, report=True):
        with self._lock:
            if not self.running:
                return
            self.running = False
            if self._stop_evt is not None:
                self._stop_evt.set()
            if report:
                self.setDriver('ST', STOPPED)
        LOGGER.info('Counter stopped')

    def _run(self, evt):
        # Fixed-rate schedule so the count does not drift.
        next_tick = time.monotonic() + 1.0
        while not evt.wait(max(0.0, next_tick - time.monotonic())):
            next_tick += 1.0
            self.tick(evt)

    def tick(self, evt=None):
        with self._lock:
            if evt is not None and evt.is_set():
                return
            self.count = 0 if self.count >= COUNTER_MAX else self.count + 1
            self.setDriver('COUNTER', self.count)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def cmd_increment(self, command=None):
        with self._lock:
            self.count = (self.count + self.step) % (COUNTER_MAX + 1)
            self.setDriver('COUNTER', self.count)

    def cmd_decrement(self, command=None):
        with self._lock:
            self.count = max(0, self.count - self.step)
            self.setDriver('COUNTER', self.count)

    def cmd_start(self, command=None):
        self.start_counting()

    def cmd_stop(self, command=None):
        self.stop_counting()

    @staticmethod
    def _command_value(command):
        if not command:
            return None
        value = command.get('value')
        if value is None:
            query = command.get('query') or {}
            for v in query.values():
                value = v
                break
        return value

    def cmd_set_step(self, command=None):
        value = self._command_value(command)
        try:
            step = int(float(value))
        except (TypeError, ValueError):
            LOGGER.error('Set Step: invalid value %r', value)
            return
        if step < STEP_MIN or step > STEP_MAX:
            LOGGER.error('Set Step: %s is outside %d..%d', step, STEP_MIN, STEP_MAX)
            return
        with self._lock:
            self.step = step
            self.setDriver('STEP', self.step)

    def query(self, command=None):
        self.reportDrivers()

    commands = {
        'INCR': cmd_increment,
        'DECR': cmd_decrement,
        'START': cmd_start,
        'STOP': cmd_stop,
        'SETSTEP': cmd_set_step,
    }
