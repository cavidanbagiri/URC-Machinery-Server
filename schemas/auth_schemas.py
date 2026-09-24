


from pydantic import BaseModel, EmailStr


class UserRegisterSchema(BaseModel):

    firstname: str
    lastname: str
    email: EmailStr()
    password: str
    status_id: int




class UserLoginSchema(BaseModel):

    email: EmailStr()
    password: str
