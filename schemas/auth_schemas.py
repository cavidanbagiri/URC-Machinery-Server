


from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegisterSchema(BaseModel):
    """Public registration payload.

    ``status_id`` is intentionally not accepted from the client: every new
    account is created with the read-only status by the repository.
    """

    model_config = ConfigDict(extra="forbid")

    firstname: str = Field(..., min_length=1, max_length=100)
    lastname: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("firstname", "lastname")
    @classmethod
    def strip_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ad boş olamaz")
        return value


class UserLoginSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
