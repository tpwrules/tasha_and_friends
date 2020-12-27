from nmigen import *

from .match_info import *

# reading 16 matches takes 16 cycles, and we only have about 20
assert(KEY_MATCHES_WIDTH <= 4)

# match many things at once by looking them up in RAM
class MultiMatcher(Elaboratable):
    def __init__(self):
        # SNES bus signals
        self.i_bus_valid = Signal()
        self.i_bus_addr = Signal(24)
        self.i_bus_data = Signal(8)
        self.i_bus_write = Signal()

        # config bus signals
        self.i_config = Signal(32)
        self.i_config_addr = Signal(MATCH_MEM_ADDR_WIDTH)
        self.i_config_we = Signal()

        self.o_match_type = Signal(MATCH_TYPE_BITS)

        self.match_mem = Memory(width=32, depth=2**MATCH_MEM_ADDR_WIDTH)

    def elaborate(self, platform):
        m = Module()

        m.submodules.match_mem_rd = match_mem_rd = \
            self.match_mem.read_port(transparent=False)
        m.submodules.match_mem_wr = match_mem_wr = self.match_mem.write_port()

        # allow match memory configuration to be written
        m.d.comb += [
            match_mem_wr.addr.eq(self.i_config_addr),
            match_mem_wr.en.eq(self.i_config_we),
            match_mem_wr.data.eq(self.i_config),
        ]

        # split the incoming address up into key bits and value bits. the key
        # bits are used to address the ROM, then the value bits are compared
        # with the entry to test for a match. this minimizes the number of
        # matches we have to read before the next address comes in.
        key_bits = Signal(len(KEY_BITS))
        value_bits = Signal(len(VALUE_BITS))
        get_bits = lambda source, bits: (source[b] for b in sorted(tuple(bits)))
        m.d.comb += [
            key_bits.eq(Cat(*get_bits(self.i_bus_addr, KEY_BITS))),
            value_bits.eq(Cat(*get_bits(self.i_bus_addr, VALUE_BITS))),
        ]

        # step through each of the matches at this key
        step_counter = Signal(KEY_MATCHES_WIDTH)
        stepping = Signal() # only enable matching when actively reading
        m.d.sync += stepping.eq(0)
        with m.If(self.i_bus_valid | (step_counter > 0)):
            m.d.sync += step_counter.eq(step_counter + 1)
            m.d.sync += stepping.eq(1)

        # look up the current match entry in the memory
        match_entry = Signal(32)
        m.d.comb += [
            match_mem_rd.addr.eq(Cat(step_counter, key_bits)),
            match_mem_rd.en.eq(1),
            match_entry.eq(match_mem_rd.data),
        ]

        entry_addr = Signal(len(VALUE_BITS))
        entry_type = Signal(MATCH_TYPE_BITS)
        entry_lhs = Cat(entry_addr, entry_type)
        assert(len(entry_lhs) <= 32)
        m.d.comb += entry_lhs.eq(match_entry)

        # check all the conditions for a valid match
        addr_matched = Signal()
        m.d.comb += addr_matched.eq(entry_addr == value_bits)

        # only output a nonzero match if everything checks out
        matched = Signal()
        m.d.comb += matched.eq(addr_matched & stepping)
        m.d.sync += self.o_match_type.eq(Mux(matched, entry_type, 0))

        return m
