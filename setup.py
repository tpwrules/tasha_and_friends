from setuptools import setup, find_packages

setup(
    name="tastaf",
    version="0.1",
    author="tpw_rules",
    description="TASHA and friends; tools for console TAS replay",
    packages=find_packages(),
    install_requires=[
        "crcmod",
        "numpy",
        "pyserial",

        # somewhat temporary for now. not super sure if these are stable.
        "boneless @ git+https://github.com/whitequark/Boneless-CPU@b472ec065f7a5b2708996fbc531e355f3800b0e8#egg=boneless",
        "nmigen @ git+https://github.com/nmigen/nmigen@0e40dc0a2d336945dfe0669207fe160cafff50dc#egg=nmigen",
        "nmigen_boards @ git+https://github.com/nmigen/nmigen-boards@18315d8efc4b2d0569ff1abf19a92f495de7745d#egg=nmigen_boards",
    ]
)
