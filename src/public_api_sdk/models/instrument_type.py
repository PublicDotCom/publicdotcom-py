from enum import Enum


class InstrumentType(str, Enum):
    ALT = "ALT"
    BOND = "BOND"
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    MULTI_LEG_INSTRUMENT = "MULTI_LEG_INSTRUMENT"
    OPTION = "OPTION"
    TREASURY = "TREASURY"
