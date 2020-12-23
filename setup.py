from setuptools import setup, find_packages

# WARNING!!!!!
# this must be installed with python3 -m pip install <dir with setup.py>

# if you try python3 <dir with setup.py/setup.py install then the git versions
# of the packages will not be used and everything will be broken.
# symptoms include ModuleNotFoundError: No module named 'boneless.arch'

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
        "boneless @ git+https://github.com/whitequark/Boneless-CPU@bdf1eefccc86f4c4b23ad69172b4a441a29c29cf#egg=boneless",
        "nmigen @ git+https://github.com/nmigen/nmigen@b466b724fe9f62140062afc9ecde9a920a261487#egg=nmigen",
        "nmigen_boards @ git+https://github.com/nmigen/nmigen-boards@b40c3d6cb20081ff8941fc4addef92170ffb01a9#egg=nmigen_boards",
    ]
)
