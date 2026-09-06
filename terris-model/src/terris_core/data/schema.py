from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


Role = Literal["system", "user", "assistant", "tool"]
Split = Literal["train", "validation", "test"]
Rights = Literal["public_domain", "permissive_license", "agro_ai_owned", "explicit_training_consent"]
TruthLabel = Literal["measured", "reported", "calculated", "estimated", "ai_inferred", "unknown"]


class Message(BaseModel):
    role: Role
    content: str = Field(min_length=1)


class DataProvenance(BaseModel):
    source_name: str = Field(min_length=1)
    source_uri: str | None = None
    rights: Rights
    license_id: str | None = None
    customer_data: bool = False
    training_allowed: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def training_rights_are_explicit(self):
        if self.customer_data and self.rights != "explicit_training_consent":
            raise ValueError("Customer data requires explicit_training_consent.")
        if not self.training_allowed:
            raise ValueError("Record is not approved for model training.")
        if self.rights == "permissive_license" and not self.license_id:
            raise ValueError("Permissively licensed records require license_id.")
        return self


class TruthFact(BaseModel):
    key: str
    value: str | float | int | bool | None
    truth_label: TruthLabel
    source: str


class TrainingRecord(BaseModel):
    id: str = Field(min_length=3)
    domain: str = Field(min_length=2)
    task_type: str = Field(min_length=2)
    language: str = "en"
    split: Split = "train"
    messages: list[Message] = Field(min_length=2)
    truth_context: list[TruthFact] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    safety_tags: list[str] = Field(default_factory=list)
    provenance: DataProvenance

    @model_validator(mode="after")
    def conversation_has_user_and_assistant(self):
        roles = [message.role for message in self.messages]
        if "user" not in roles or "assistant" not in roles:
            raise ValueError("Training conversations require both user and assistant messages.")
        return self
