"""Admin control-surface shapes. Admin is not gx, so these may nest freely."""

from datetime import datetime

from pydantic import BaseModel, Field


class ApplyIn(BaseModel):
    scenario: str = Field(description="Scenario name, i.e. the YAML file's stem.")


class ScenarioResultOut(BaseModel):
    ok: bool
    action: str
    scenario: str
    rows_changed: int
    summary: str


class ScenarioOut(BaseModel):
    name: str
    title: str
    description: str
    reset_first: bool
    subscribers: list[str]
    steps: int


class EventOut(BaseModel):
    action: str
    scenario: str
    summary: str
    rows_changed: int
    created_at: datetime


class SubscriberStateOut(BaseModel):
    party_id: str
    display_name: str
    identifier: str
    tier: str
    has_network: bool
    healthy: bool
    fault_type: str
    recommended_action: str
    wan_status: str
    extender_status: str
    worst_device_label: str
    worst_device_band: str
    worst_device_rssi: int
