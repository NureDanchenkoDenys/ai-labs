import math
import re
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator

MAX_INT32 = 2147483647
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
MIN_QUANTITY = Decimal("0.001")
MAX_QUANTITY = Decimal("10000")
ALLOWED_UNITS: tuple[str, ...] = ("шт", "кг", "г", "л", "мл", "уп")
INTEGER_ONLY_UNITS: tuple[str, ...] = ("шт", "уп")

QuantityValue = Annotated[
    Decimal,
    WithJsonSchema(
        {
            "type": "number",
            "minimum": 0.001,
            "maximum": 10000,
        }
    ),
]

UnitValue = Annotated[
    str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": list(ALLOWED_UNITS),
        }
    ),
]


def quantity_to_milli(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Кількість має бути JSON-числом.")
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Кількість має бути скінченним числом.")
        dec = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Кількість має бути скінченним числом.")
        dec = Decimal(str(value))
    else:
        raise ValueError("Кількість має бути JSON-числом.")

    if dec < MIN_QUANTITY or dec > MAX_QUANTITY:
        raise ValueError(
            "Має бути від 0.001 до 10000 з урахуванням одиниці вимірювання."
        )

    sign, digits, exponent = dec.as_tuple()
    if sign != 0 or not isinstance(exponent, int):
        raise ValueError("Кількість має бути скінченним додатним числом.")

    if exponent < -3:
        extra_frac = -3 - exponent
        if extra_frac >= len(digits) or any(d != 0 for d in digits[-extra_frac:]):
            raise ValueError(
                "Кількість може мати не більше 3 знаків після десяткової крапки."
            )
        significant_digits = digits[:-extra_frac]
        scale_shift = 0
    else:
        significant_digits = digits
        scale_shift = exponent + 3

    quantity_milli = 0
    for digit in significant_digits:
        quantity_milli = quantity_milli * 10 + digit
    quantity_milli *= 10**scale_shift

    if not (1 <= quantity_milli <= 10_000_000):
        raise ValueError(
            "Має бути від 0.001 до 10000 з урахуванням одиниці вимірювання."
        )

    return quantity_milli


class CategoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    description: str


class ShoppingListCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str

    @field_validator("name", mode="after")
    @classmethod
    def validate_and_normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(
                "Після видалення крайніх пробілів потрібен щонайменше 1 символ."
            )
        if len(normalized) > 120:
            raise ValueError(
                "Максимальна довжина назви після видалення крайніх пробілів — 120 символів."
            )
        return normalized


class ShoppingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    created_at: str


def _validate_and_normalize_item_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(
            "Після видалення крайніх пробілів потрібен щонайменше 1 символ."
        )
    if len(normalized) > 160:
        raise ValueError(
            "Максимальна довжина назви після видалення крайніх пробілів — 160 символів."
        )
    return normalized


def _validate_and_normalize_unit(value: str) -> str:
    normalized = value.strip()
    if normalized not in ALLOWED_UNITS:
        raise ValueError(
            "Допустимі одиниці вимірювання: шт, кг, г, л, мл, уп."
        )
    return normalized


class ShoppingItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    quantity: QuantityValue
    unit: UnitValue
    category_id: int = Field(ge=1, le=MAX_INT32)

    @field_validator("name", mode="after")
    @classmethod
    def validate_and_normalize_name(cls, value: str) -> str:
        return _validate_and_normalize_item_name(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, value: Any) -> Decimal:
        milli = quantity_to_milli(value)
        return Decimal(milli) / Decimal(1000)

    @field_validator("unit", mode="after")
    @classmethod
    def validate_and_normalize_unit(cls, value: str) -> str:
        return _validate_and_normalize_unit(value)

    @property
    def quantity_milli(self) -> int:
        return quantity_to_milli(self.quantity)


class ShoppingItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(default_factory=str)
    quantity: QuantityValue = Field(default_factory=Decimal)
    unit: UnitValue = Field(default_factory=str)
    category_id: int = Field(default_factory=int, ge=1, le=MAX_INT32)

    @field_validator("name", mode="after")
    @classmethod
    def validate_and_normalize_name(cls, value: str) -> str:
        return _validate_and_normalize_item_name(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, value: Any) -> Decimal:
        milli = quantity_to_milli(value)
        return Decimal(milli) / Decimal(1000)

    @field_validator("unit", mode="after")
    @classmethod
    def validate_and_normalize_unit(cls, value: str) -> str:
        return _validate_and_normalize_unit(value)

    @property
    def quantity_milli(self) -> int | None:
        if "quantity" not in self.model_fields_set:
            return None
        return quantity_to_milli(self.quantity)


class ShoppingItemPurchaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    is_purchased: bool


class ShoppingItemFilterQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category_id: int | None = None
    is_purchased: bool | None = None

    @field_validator("category_id", mode="before")
    @classmethod
    def validate_category_id(cls, value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _ASCII_DIGITS_RE.fullmatch(value):
            raise ValueError(
                "Параметр category_id має бути додатним десятковим цілим від 1 до 2147483647."
            )
        stripped = value.lstrip("0")
        if not stripped or len(stripped) > 10:
            raise ValueError(
                "Параметр category_id має бути додатним десятковим цілим від 1 до 2147483647."
            )
        parsed = int(stripped)
        if not (1 <= parsed <= MAX_INT32):
            raise ValueError(
                "Параметр category_id має бути додатним десятковим цілим від 1 до 2147483647."
            )
        return parsed

    @field_validator("is_purchased", mode="before")
    @classmethod
    def validate_is_purchased(cls, value: Any) -> bool | None:
        if value is None:
            return None
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError("Параметр is_purchased приймає лише рівно true або false.")


class ShoppingItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    list_id: int
    name: str
    quantity: int | float
    unit: str
    category_id: int
    is_purchased: bool
    created_at: str


class ShoppingListDetailResponse(ShoppingListResponse):
    model_config = ConfigDict(extra="forbid")

    items: list[ShoppingItemResponse]


class CategoryStatisticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: int = Field(ge=1, le=10)
    category_name: str
    total_items: int = Field(ge=0)
    purchased_items: int = Field(ge=0)
    unpurchased_items: int = Field(ge=0)


class ShoppingListStatisticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_id: int = Field(ge=1, le=MAX_INT32)
    total_items: int = Field(ge=0)
    purchased_items: int = Field(ge=0)
    unpurchased_items: int = Field(ge=0)
    categories: list[CategoryStatisticsResponse]
