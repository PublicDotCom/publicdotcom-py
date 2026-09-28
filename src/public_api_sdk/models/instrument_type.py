from enum import Enum


class InstrumentType(str, Enum):
    ALT = "ALT"
    BOND = "BOND"
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"
    EVENTCONTRACT = "EVENTCONTRACT"
    INDEX = "INDEX"
    MULTI_LEG_INSTRUMENT = "MULTI_LEG_INSTRUMENT"
    OPTION = "OPTION"
    TREASURY = "TREASURY"
