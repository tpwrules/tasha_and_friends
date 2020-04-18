from nmigen import *

# SetReset: the output value becomes 1 the cycle after set is asserted or 0
# after reset is asserted. if both set and reset are asserted on the same cycle,
# the value becomes the prioritized state.
class SetReset(Elaboratable):
    def __init__(self, parent, *, priority, initial_value=False):
        # if both set and reset are asserted on the same cycle, the value
        # becomes the prioritized state.
        if priority not in ("set", "reset"):
            raise ValueError("Priority must be either 'set' or 'reset', "
                "not '{}'.".format(priority))

        self.priority = priority

        self.set = Signal()
        self.reset = Signal()
        self.value = Signal(reset=initial_value)

        # avoid the user having to remember to add us
        parent.submodules += self

    def elaborate(self, platform):
        m = Module()

        if self.priority == "set":
            with m.If(self.set):
                m.d.sync += self.value.eq(1)
            with m.Elif(self.reset):
                m.d.sync += self.value.eq(0)
        elif self.priority == "reset":
            with m.If(self.reset):
                m.d.sync += self.value.eq(0)
            with m.Elif(self.set):
                m.d.sync += self.value.eq(1)

        return m
