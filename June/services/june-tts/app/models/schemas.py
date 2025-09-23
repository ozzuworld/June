from pydantic import BaseModel, Field, ConfigDict


class VoiceInfo(BaseModel):
    id: str
    display_name: str
    language: str
    meta: dict = Field(default_factory=dict)


class VoiceList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    voices: list[VoiceInfo]
