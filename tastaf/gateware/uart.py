# the system UART, optimized specifically for our use case.
# includes: CRC generator, receive timeout timer, receive FIFO, fixed divisor

from nmigen import *
from nmigen.asserts import Past, Rose, Fell
from nmigen.lib.cdc import FFSynchronizer
from nmigen.lib.fifo import SyncFIFOBuffered
from boneless.arch.opcode import *

from .setreset import *

# Register Map

# 0x0: (R) Status
#    Read: bit 15: 1 if transmission in progress, 0 otherwise. the transmit
#                  FIFO is empty and the bus is idle iff this bit is 0.
#          bit  0: 1 if reception in progress, 0 otherwise

# 0x1: (R/W) Error
#     R/W: bit 15: 1 if reception encountered framing error. write 1 to reset.
#          bit  2: 1 if transmit FIFO overflowed. write 1 to reset.
#          bit  1: 1 if receive timeout elapsed. write 1 to reset.
#          bit  0: 1 if receive FIFO overflowed. write 1 to reset.

# 0x2: (R/W) CRC Value / CRC Reset
#    Read:   15-0: current CRC value
#   Write:   15-0: write anything to reset CRC to 0
#   The CRC value is updated with the written or read value after every valid
#   write or read of the transmit or receive registers. It uses a bitwise
#   implementation of the CRC-16/KERMIT algorithm (as defined by crcany).
#   Because it is bitwise, there are 7 cycles of calculation after the update
#   starts, during which time the value is invalid and attempting to update it
#   will corrupt the calculation.

# 0x3: (W) Receive Timeout Timer
#   Write:   15-0: timeout value
#   The timeout timer is set to the timeout value when the UART starts receiving
#   a character, this register is written, or when the error is reset in the
#   Error register (even if it wasn't set). It decrements once every 256 cycles.
#   Once it hits zero, the timeout bit in the Error register is set.

# 0x4: (R) RX FIFO Status and Receive Data (low byte)
#    Read: bit 15: bit 0 of read character, if the RX FIFO is not empty
#          bit 14: 1 if the RX FIFO is empty, 0 otherwise
#             6-0: remaining 6 bits of read character, if RX fifo is not empty
#   This bizarre arrangement is so that ROLI(v, v, 1) sets S to 1 if the
#   character is invalid. Otherwise, S is 0 and v is the correctly aligned
#   character. The received character is now in the low 8 bits of the register.
#   The behavior of this register is identical to the "high byte" version below,
#   except for where the character is placed.

# 0x5: (R) RX FIFO Status and Receive Data (high byte)
#    Read:   15-8: the read character, if the RX FIFO is not empty
#           bit 0: 1 if the RX FIFO is empty, 0 otherwise
#   This arrangement is so that ANDI(x, v, 1) sets Z to 0 if the character is
#   invalid. Otherwise, Z is 1 and v is the character (and x is trashed either
#   way). The received character is now in the high 8 bits of the register. The
#   behavior of this register is identical to the "low byte" version above,
#   except for where the character is placed.

# 0x6: (R/W) Transmit Data / TX FIFO Status (low byte)
#    Read:  bit 0: 1 if the TX FIFO is full, 0 otherwise.
#   Write:    7-0: queue written character for transmission.
#   The behavior of this register is identical to the "high byte" version below,
#   except for where the character is placed.

# 0x7: (R/W) Transmit Data / TX FIFO Status (high byte)
#    Read:  bit 0: 1 if the TX FIFO is full, 0 otherwise.
#   Write:   15-8: queue written character for transmission.
#   The behavior of this register is identical to the "low byte" version above,
#   except for where the character is placed.

def calculate_divisor(freq, baud):
    return int(freq/baud)-1

# handle receiving (more or less) single bytes
class Receiver(Elaboratable):
    def __init__(self, divisor):
        self.divisor = divisor

        # the signal from the outside world
        self.i_rx = Signal()

        # the received byte
        self.o_data = Signal(8)
        # write it into whatever receive buffer
        self.o_we = Signal()
        # if reception is currently ongoing
        self.o_active = Signal()
        # if there was an error during reception. not latched!
        self.o_error = Signal()

    def elaborate(self, platform):
        m = Module()
        
        # count out the bits we're receiving (including start and stop)
        bit_ctr = Signal(range(8+2-1))
        # shift in the data bits, plus start and stop
        in_buf = Signal(8+2)
        # count cycles per baud
        baud_ctr = Signal(range(self.divisor))

        # the data buf is connected directly. it's only valid for the cycle we
        # say it is though.
        m.d.comb += self.o_data.eq(in_buf[1:-1])

        # since the rx pin is attached to arbitrary external logic, we must sync
        # it with our domain first.
        i_rx = Signal(reset=1)
        rx_sync = FFSynchronizer(self.i_rx, i_rx, reset=1)
        m.submodules.rx_sync = rx_sync

        with m.FSM("IDLE"):
            with m.State("IDLE"):
                # has the receive line been asserted?
                with m.If(~i_rx):
                    m.d.sync += [
                        # start counting down the bits
                        bit_ctr.eq(8+2-1),
                        # we are now active!
                        self.o_active.eq(1),
                    ]
                    # start the baud counter at half the baud time. this way we
                    # end up halfway through the start bit when we next sample
                    # so we can make sure the start bit is still there. we're
                    # also then lined up to sample the rest of the bits in the
                    # middle.
                    m.d.sync += baud_ctr.eq(self.divisor>>1)
                    # now we just receive the start bit like any other
                    m.next = "RECV"

            with m.State("RECV"):
                m.d.sync += baud_ctr.eq(baud_ctr-1)
                with m.If(baud_ctr == 0):
                    # sample the bit once it's time. we shift bits into the MSB
                    # so the first bit ends up at the LSB once we are done.
                    m.d.sync += in_buf.eq(Cat(in_buf[1:], i_rx))
                    with m.If(bit_ctr == 0): # this is the stop bit?
                        # yes, sample it (this cycle) and finish up next
                        m.next = "FINISH"
                    with m.Else():
                        # no, wait to receive another bit
                        m.d.sync += [
                            baud_ctr.eq(self.divisor),
                            bit_ctr.eq(bit_ctr-1),
                        ]

            with m.State("FINISH"):
                # make sure that the start bit is 0 and the stop bit is 1, like
                # the standard prescribes.
                with m.If((in_buf[0] == 0) & (in_buf[-1] == 1)):
                    # tell the user we've got something
                    m.d.comb += self.o_we.eq(1)
                with m.Else():
                    # we didn't correctly receive the character. let the user
                    # know that something bad happened.
                    m.d.comb += self.o_error.eq(1)
                # but we did finish receiving, no matter the outcome
                m.d.sync += self.o_active.eq(0)
                m.next = "IDLE"
                # technically, there's still half a bit time until the stop bit
                # is over, but that's ok. the rx line is deasserted during that
                # time so we won't accidentally start receiving another bit.

        return m


# handle transmitting (more or less) single bytes
class Transmitter(Elaboratable):
    def __init__(self, divisor):
        self.divisor = divisor

        # the signal to the outside world
        self.o_tx = Signal(reset=1)

        # if there's stuff to transmit
        self.i_start_tx = Signal()
        # the byte to transmit
        self.i_data = Signal(8)
        # read it from whatever transmit buffer
        self.o_re = Signal()
        # if transmission is currently ongoing
        self.o_active = Signal()

    def elaborate(self, platform):
        m = Module()

        # count out the bits we're sending (including start and stop)
        bit_ctr = Signal(range(8+2-1))
        # shift out the data bits and stop bit
        out_buf = Signal(8+1)
        # count cycles per baud
        baud_ctr = Signal(range(self.divisor))

        with m.FSM("IDLE"):
            with m.State("IDLE"):
                # is there something to transmit?
                with m.If(self.i_start_tx):
                    # yes, read it
                    m.d.comb += self.o_re.eq(1)
                    # then transmit it
                    m.d.sync += self.o_active.eq(1)
                    m.next = "START"

            with m.State("START"):
                m.d.sync += [
                    # load data to send, plus stop bit
                    out_buf.eq(Cat(self.i_data, 1)),
                    # start counting down the bits
                    bit_ctr.eq(8+2-1),
                    # send the start bit first
                    self.o_tx.eq(0),
                    # start counting the baud time for the start bit
                    baud_ctr.eq(self.divisor),
                ]
                m.next = "SEND" # start sending data bits

            with m.State("SEND"):
                m.d.sync += baud_ctr.eq(baud_ctr-1)
                with m.If(baud_ctr == 0):
                    with m.If(bit_ctr == 0): # we just sent the stop bit?
                        # is there still something to transmit?
                        with m.If(self.i_start_tx):
                            # yes, read it
                            m.d.comb += self.o_re.eq(1)
                            # then transmit it
                            m.next = "START"
                        with m.Else():
                            # nope, we are done!
                            m.d.sync += self.o_active.eq(0)
                            m.next = "IDLE"
                    with m.Else():
                        # nope. shift out the next one and wait for the
                        # appropriate time.
                        m.d.sync += [
                            self.o_tx.eq(out_buf[0]), # bus is LSB first
                            out_buf.eq(out_buf >> 1),
                            bit_ctr.eq(bit_ctr-1), # one less bit to go
                            baud_ctr.eq(self.divisor),
                        ]
                        m.next = "SEND"

        return m


# handle calculating CRC-16/KERMIT (as defined by anycrc)
class KermitCRC(Elaboratable):
    def __init__(self):
        # reset engine and set CRC to 0
        self.i_reset = Signal()
        # start CRC of the given byte. will give the wrong value if engine isn't
        # done yet!
        self.i_start = Signal()
        # the given byte
        self.i_byte = Signal(8)

        self.o_crc = Signal(16)

    def elaborate(self, platform):
        m = Module()

        bit_counter = Signal(range(8)) # count from 7 to 0

        with m.If(self.i_reset):
            m.d.sync += [
                bit_counter.eq(0),
                self.o_crc.eq(0),
            ]
        with m.Elif(self.i_start):
            crc_with_byte = Signal(16)
            m.d.comb += crc_with_byte.eq(self.o_crc ^ self.i_byte)
            m.d.sync += [
                bit_counter.eq(7),
                # do first cycle now
                self.o_crc.eq(
                    (crc_with_byte >> 1) ^ Mux(crc_with_byte[0], 0x8408, 0)),
            ]
        with m.Elif(bit_counter > 0):
            m.d.sync += [
                bit_counter.eq(bit_counter-1),
                self.o_crc.eq(
                    (self.o_crc >> 1) ^ Mux(self.o_crc[0], 0x8408, 0)),
            ]

        return m


class SysUART(Elaboratable):
    def __init__(self, divisor, rx_fifo_depth=512): # 512x8 = 1 BRAM
        self.divisor = divisor

        # boneless bus inputs
        self.i_re = Signal()
        self.i_we = Signal()
        self.i_addr = Signal(4)
        self.o_rdata = Signal(16)
        self.i_wdata = Signal(16)

        # UART signals
        self.i_rx = Signal()
        self.o_tx = Signal(reset=1) # inverted, like usual

        self.rx_fifo = SyncFIFOBuffered(width=8, depth=rx_fifo_depth)

    def elaborate(self, platform):
        m = Module()

        # hook up the modules which do the work
        m.submodules.txm = txm = Transmitter(self.divisor)
        m.submodules.rxm = rxm = Receiver(self.divisor)
        m.d.comb += [
            rxm.i_rx.eq(self.i_rx),
            self.o_tx.eq(txm.o_tx),
        ]

        # define the signals that make up the registers
        r1_rx_error = SetReset(m, priority="set")
        r1_tx_overflow = SetReset(m, priority="set")
        r1_rx_timeout = SetReset(m, priority="set")
        r1_rx_overflow = SetReset(m, priority="set")

        r6_tx_full = SetReset(m, priority="set")

        # hook up transmit "buffer". it's just one byte.
        tx_data = Signal(8)
        m.d.comb += [
            txm.i_start_tx.eq(r6_tx_full.value),
            txm.i_data.eq(tx_data),
            r6_tx_full.reset.eq(txm.o_re),
        ]

        # hook up receive FIFO. it's big so the CPU can be busy and not miss
        # stuff
        m.submodules.rx_fifo = rx_fifo = self.rx_fifo
        m.d.comb += [
            r1_rx_overflow.set.eq(~rx_fifo.w_rdy & rxm.o_we),
            rx_fifo.w_data.eq(rxm.o_data),
            rx_fifo.w_en.eq(rxm.o_we),
        ]

        # hook up the CRC engine
        m.submodules.crc = crc = KermitCRC()

        # run the receive timeout timer
        rt_timeout_val = Signal(16)
        rt_timer_reset = SetReset(m, priority="set")
        rt_timer_curr = Signal(16)
        rt_subtimer = Signal(9)

        # keep reset if reception is ongoing
        with m.If(rxm.o_active):
            m.d.comb += rt_timer_reset.set.eq(1)

        # cancel reset request once it's been done
        m.d.sync += rt_timer_reset.reset.eq(rt_timer_reset.value)

        m.d.sync += rt_subtimer.eq(rt_subtimer-1)
        with m.If(rt_timer_reset.value):
            m.d.sync += rt_timer_curr.eq(rt_timeout_val)
        with m.Elif(rt_timer_curr > 0):
            with m.If(rt_subtimer[-1] != Past(rt_subtimer)[-1]): # rolled over?
                m.d.sync += rt_timer_curr.eq(rt_timer_curr-1)
                # timeout about to hit zero?
                m.d.comb += r1_rx_timeout.set.eq(rt_timer_curr == 1)

        # handle the boneless bus.
        read_data = Signal(16) # it expects one cycle of read latency
        m.d.sync += self.o_rdata.eq(read_data)

        with m.If(self.i_re):
            with m.Switch(self.i_addr[:3]): # we only have 8 registers
                with m.Case(0): # status register
                    m.d.comb += [
                        # transmitter remains active as long as there is data to
                        # transmit
                        read_data[15].eq(txm.o_active),
                        read_data[0].eq(rxm.o_active),
                    ]
                with m.Case(1): # error register
                    m.d.comb += [
                        read_data[15].eq(r1_rx_error.value),
                        read_data[2].eq(r1_tx_overflow.value),
                        read_data[1].eq(r1_rx_timeout.value),
                        read_data[0].eq(r1_rx_overflow.value),
                    ]
                with m.Case(2): # CRC value register
                    m.d.comb += read_data.eq(crc.o_crc)
                with m.Case(4, 5): # rx status and receive data
                    # the FIFO will be okay if we read from it while empty, so
                    # we just read from it regardless
                    m.d.comb += rx_fifo.r_en.eq(1)
                    # can be read from low or high byte
                    with m.If(self.i_addr[0]): # high byte
                        m.d.comb += [
                            read_data[8:].eq(rx_fifo.r_data),
                            read_data[0].eq(~rx_fifo.r_rdy),
                        ]
                    with m.Else(): # low byte (rotated for status bit access)
                        m.d.comb += [
                            read_data[15].eq(rx_fifo.r_data[0]),
                            read_data[:7].eq(rx_fifo.r_data[1:]),
                            read_data[14].eq(~rx_fifo.r_rdy),
                        ]
                    # if there actually was a byte, fold it into the CRC
                    with m.If(rx_fifo.r_rdy):
                        m.d.comb += [
                            crc.i_byte.eq(rx_fifo.r_data),
                            crc.i_start.eq(1),
                        ]
                with m.Case(6, 7): # tx fifo status
                    m.d.comb += read_data[0].eq(r6_tx_full.value)
        with m.Elif(self.i_we):
            with m.Switch(self.i_addr[:3]):
                with m.Case(1): # error register
                    m.d.comb += [
                        r1_rx_error.reset.eq(self.i_wdata[15]),
                        r1_tx_overflow.reset.eq(self.i_wdata[2]),
                        r1_rx_timeout.reset.eq(self.i_wdata[1]),
                        r1_rx_overflow.reset.eq(self.i_wdata[0]),
                    ]
                    with m.If(self.i_wdata[1]):
                        m.d.comb += rt_timer_reset.set.eq(1)
                with m.Case(2): # CRC reset register
                    m.d.comb += crc.i_reset.eq(1)
                with m.Case(3): # receive timeout register
                    m.d.sync += rt_timeout_val.eq(self.i_wdata)
                    m.d.comb += rt_timer_reset.set.eq(1)
                with m.Case(6, 7): # transmit data register
                    # can be written to low or high byte
                    value = Signal(8)
                    m.d.comb += value.eq(Mux(self.i_addr[0],
                        self.i_wdata[8:], self.i_wdata[:8]))
                    # do we have space available for it?
                    with m.If(~r6_tx_full.value):
                        # yes, store it and set that we've used the space
                        m.d.sync += tx_data.eq(value)
                        m.d.comb += r6_tx_full.set.eq(1)
                        # and fold it into the CRC
                        m.d.comb += [
                            crc.i_byte.eq(value),
                            crc.i_start.eq(1)
                        ]
                    with m.Else():
                        # overflowed! drop the write and raise error.
                        m.d.comb += r1_tx_overflow.set.eq(1)

        return m
