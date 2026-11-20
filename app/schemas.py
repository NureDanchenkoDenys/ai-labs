from pydantic import BaseModel, ConfigDict, field_validator


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
