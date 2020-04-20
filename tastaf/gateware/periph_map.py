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

_uart_periph_num = 0
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

p_map = _namedtupleton("p_map",
    uart=_uart,
)
