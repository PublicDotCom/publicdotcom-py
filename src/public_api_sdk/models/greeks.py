from decimal import Decimal

from pydantic import BaseModel, Field


class GreekValues(BaseModel):
    """The actual Greek values for an option"""
    delta: Decimal = Field(
        ...,
        description=(
            "Delta is the theoretical estimate of how much an option's value "
            "may change given a $1 move UP or DOWN in the underlying security. "
            "The Delta values range from -1 to +1, with 0 representing an "
            "option where the premium barely moves relative to price changes "
            "in the underlying stock."
        ),
    )
    gamma: Decimal = Field(
        ...,
        description=(
            "Gamma represents the rate of change between an option's Delta and "
            "the underlying asset's price. Higher Gamma values indicate that "
            "the Delta could change dramatically with even very small price "
            "changes in the underlying stock or fund."
        ),
    )
    theta: Decimal = Field(
        ...,
        description=(
            "Theta represents the rate of change between the option price and "
            "time, or time sensitivity—sometimes known as an option's time "
            "decay. Theta indicates the amount an option's price would "
            "decrease as the time to expiration decreases, all else equal."
        ),
    )
    vega: Decimal = Field(
        ...,
        description=(
            "Vega measures the amount of increase or decrease in an option "
            "premium based on a 1% change in implied volatility."
        ),
    )
    rho: Decimal = Field(
        ...,
        description=(
            "Rho represents the rate of change between an option's value and "
            "a 1% change in the interest rate. This measures sensitivity to "
            "the interest rate."
        ),
    )
    implied_volatility: Decimal = Field(
        ...,
        alias="impliedVolatility",
        description=(
            "Implied volatility (IV) is a theoretical forecast of how volatile "
            "an underlying stock is expected to be in the future."
        ),
    )
