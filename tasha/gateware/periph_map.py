# map of all the peripherals in the system, and their registers. registers are
# stored here (vs. in the peripheral moduules) so that it can be imported
# without any external dependencies.

import collections

# make a namedtuple class that can hold the given kwargs names, then create an
# instance with the kwargs values and return it
def _namedtupleton(obj_name=None, **kwargs):
    if obj_name is None:
        obj_name = "namedtupleton"
    nt = collections.namedtuple(obj_name, kwargs.keys())
    return nt(**kwargs)

# offset register numbers by given peripheral's base address
def _reg_addr(periph_num, **kwargs):
    if periph_num < 8:
        base = periph_num*16
    else:
        base = ((periph_num-8)*16) + 0xFF80

    return {name: num+base for name, num in kwargs.items()}

_reset_req_periph_num = 0
_reset_req = _namedtupleton("reset_req",
    periph_num=_reset_req_periph_num,

    **_reg_addr(_reset_req_periph_num,
        # these must match reset_req.py!!!!!!
        w_enable_key_fade=0,
        w_perform_key_dead=1,
    )
)

_uart_periph_num = 1
_uart = _namedtupleton("uart",
    periph_num=_uart_periph_num,

    **_reg_addr(_uart_periph_num,
        # these must match uart.py!!!!!!
        r_status=0,
        r_error=1,
        w_error_clear=1,
        r_crc_value=2,
        w_crc_reset=2,
        w_rt_timer=3,
        r_rx_lo=4,
        r_rx_hi=5,
        r_tx_status=6,
        w_tx_lo=6,
        w_tx_hi=7,
    )
)

_timer_periph_num = 2
# put registers into array to emphasize identicality
_timer = tuple(
    # these must match timer.py!!!!!!
    (_namedtupleton("timer_n",
        **_reg_addr(_timer_periph_num,
            r_ended=ti,
            w_value=ti,
        )
    )) for ti in range(2) # NUM_TIMERS
)
_timer = _namedtupleton("timer",
    periph_num=_timer_periph_num,

    timer=_timer,
)

_snes_periph_num = 3
_snes = _namedtupleton("snes",
    periph_num=_snes_periph_num,

    **_reg_addr(_snes_periph_num,
        # these must match snes.py!!!!!!
        r_did_latch=0,
        w_force_latch=0,
        r_missed_latch_and_ack=1,
        w_enable_latch=1,

        w_apu_freq_basic=2,
        w_apu_freq_advanced=3,

        w_p1d0=4,
        w_p1d1=5,
        w_p2d0=6,
        w_p2d1=7,
    )
)

p_map = _namedtupleton("p_map",
    reset_req=_reset_req,
    uart=_uart,
    timer=_timer,
    snes=_snes,
)
