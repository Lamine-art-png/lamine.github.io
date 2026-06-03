from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class SampleWorkbenchFile:
    filename: str
    content_type: str
    content: bytes


SAMPLE_CONTROLLER_EVENTS = """timestamp,farm,block,zone,provider,event_type,scheduled_duration_min,applied_duration_min,flow_m3h,pressure_kpa,depth_mm,status
2026-05-12T21:00:00Z,Alpha Vineyard,Block A North,Zone 1,WiseConn,scheduled_irrigation,42,42,28.4,232,0.67,complete
2026-05-13T21:00:00Z,Alpha Vineyard,Block A North,Zone 1,WiseConn,scheduled_irrigation,40,37,27.9,228,0.58,variance_watch
2026-05-14T21:00:00Z,Alpha Vineyard,Block A North,Zone 1,WiseConn,scheduled_irrigation,42,42,27.1,229,0.60,complete
2026-05-15T21:00:00Z,Alpha Vineyard,Block A North,Zone 1,WiseConn,scheduled_irrigation,42,42,27.8,231,0.58,complete
2026-05-12T22:30:00Z,Alpha Vineyard,Block B West,Zone 2,WiseConn,scheduled_irrigation,30,30,22.8,218,,complete
2026-05-13T22:30:00Z,Alpha Vineyard,Block B West,Zone 2,WiseConn,scheduled_irrigation,30,28,22.1,,missing_pressure
2026-05-14T22:30:00Z,Alpha Vineyard,Block B West,Zone 2,WiseConn,scheduled_irrigation,34,34,23.0,221,,complete
2026-05-15T22:30:00Z,Alpha Vineyard,Block B West,Zone 2,WiseConn,planned_irrigation,28,0,0,220,,pending
2026-05-12T03:15:00Z,Delta Almonds,Almond Block 4,Zone 7,WiseConn,scheduled_irrigation,55,55,41.5,245,,complete
2026-05-13T03:15:00Z,Delta Almonds,Almond Block 4,Zone 7,WiseConn,scheduled_irrigation,55,61,42.1,247,,planned_applied_mismatch
2026-05-14T03:15:00Z,Delta Almonds,Almond Block 4,Zone 7,WiseConn,scheduled_irrigation,50,50,40.8,242,,complete
2026-05-15T03:15:00Z,Delta Almonds,Almond Block 4,Zone 7,WiseConn,planned_irrigation,48,0,0,,,missing_pressure
2026-05-12T20:45:00Z,North Ridge,Almond Block East,Zone 9,Talgil,scheduled_irrigation,46,44,36.2,239,,complete
2026-05-13T20:45:00Z,North Ridge,Almond Block East,Zone 9,Talgil,scheduled_irrigation,46,45,35.9,236,,complete
2026-05-14T20:45:00Z,North Ridge,Almond Block East,Zone 9,Talgil,scheduled_irrigation,46,38,31.2,213,,variance_watch
2026-05-15T20:45:00Z,North Ridge,Almond Block East,Zone 9,Talgil,planned_irrigation,44,0,0,238,,pending
2026-05-12T23:10:00Z,West Citrus,Vineyard Block Trial,Zone 11,Talgil,scheduled_irrigation,24,24,18.7,206,,complete
2026-05-13T23:10:00Z,West Citrus,Vineyard Block Trial,Zone 11,Talgil,scheduled_irrigation,26,24,18.3,,,missing_pressure
2026-05-14T23:10:00Z,West Citrus,Vineyard Block Trial,Zone 11,Talgil,scheduled_irrigation,26,32,19.0,207,,planned_applied_mismatch
2026-05-15T23:10:00Z,West Citrus,Vineyard Block Trial,Zone 11,Talgil,planned_irrigation,22,0,0,205,,pending
"""

SAMPLE_WEATHER_SUMMARY = """timestamp,region,eto_mm,rain_forecast_mm,temperature_c,humidity_pct,wind_kph
2026-05-12T12:00:00Z,Central Valley North,5.8,0,29.4,42,14
2026-05-13T12:00:00Z,Central Valley North,6.1,0,30.2,39,18
2026-05-14T12:00:00Z,Central Valley North,6.4,0,31.1,36,21
2026-05-15T12:00:00Z,Central Valley North,6.2,0.4,30.8,38,17
2026-05-16T12:00:00Z,Central Valley North,5.9,1.2,28.7,44,12
2026-05-12T12:00:00Z,Delta Almond Region,6.6,0,32.1,34,20
2026-05-13T12:00:00Z,Delta Almond Region,6.8,0,33.0,32,23
2026-05-14T12:00:00Z,Delta Almond Region,6.5,0,31.7,35,16
2026-05-15T12:00:00Z,Delta Almond Region,6.1,0.2,30.9,37,14
2026-05-16T12:00:00Z,Delta Almond Region,5.7,1.0,29.8,43,11
"""

SAMPLE_SOIL_MOISTURE = """timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health
2026-05-12T06:00:00Z,Alpha Vineyard,Block A North,30,27.2,46,healthy
2026-05-12T06:00:00Z,Alpha Vineyard,Block A North,60,28.5,38,healthy
2026-05-13T06:00:00Z,Alpha Vineyard,Block A North,30,26.7,49,healthy
2026-05-13T06:00:00Z,Alpha Vineyard,Block A North,60,28.0,41,healthy
2026-05-14T06:00:00Z,Alpha Vineyard,Block A North,30,26.2,52,healthy
2026-05-14T06:00:00Z,Alpha Vineyard,Block A North,60,27.5,44,healthy
2026-05-15T06:00:00Z,Alpha Vineyard,Block A North,30,25.7,55,healthy
2026-05-15T06:00:00Z,Alpha Vineyard,Block A North,60,27.0,47,healthy
2026-05-12T06:00:00Z,Alpha Vineyard,Block B West,30,25.8,26,healthy
2026-05-12T06:00:00Z,Alpha Vineyard,Block B West,60,29.0,22,healthy
2026-05-13T06:00:00Z,Alpha Vineyard,Block B West,30,25.1,28,healthy
2026-05-13T06:00:00Z,Alpha Vineyard,Block B West,60,28.4,23,healthy
2026-05-14T06:00:00Z,Alpha Vineyard,Block B West,30,24.6,30,stale
2026-05-14T06:00:00Z,Alpha Vineyard,Block B West,60,27.9,25,healthy
2026-05-12T06:00:00Z,Delta Almonds,Almond Block 4,30,20.8,42,healthy
2026-05-12T06:00:00Z,Delta Almonds,Almond Block 4,60,24.4,35,healthy
2026-05-13T06:00:00Z,Delta Almonds,Almond Block 4,30,20.1,44,healthy
2026-05-13T06:00:00Z,Delta Almonds,Almond Block 4,60,23.8,37,healthy
2026-05-14T06:00:00Z,North Ridge,Almond Block East,30,21.5,39,healthy
2026-05-14T06:00:00Z,North Ridge,Almond Block East,60,24.8,34,healthy
"""

SAMPLE_FIELD_NOTES = """Alpha Vineyard / Block A North: mild afternoon stress on west-facing rows after 15:00.
Alpha Vineyard / Block A North: dry surface crust observed near the headland; no visible runoff near emitters.
Alpha Vineyard / Block A North: grower wants night irrigation to avoid heat and energy peak.
Alpha Vineyard / Block A North: pump pressure checked manually at the manifold; pressure looked stable.
Alpha Vineyard / Block B West: canopy looked balanced; one shallow probe may be stale.
Delta Almonds / Almond Block 4: leaves showed mild curl at the southwest corner; no ponding after prior set.
North Ridge / Almond Block East: pressure dip reported during the prior evening set.
West Citrus / Vineyard Block Trial: trial rows are being watched separately from commercial blocks.
"""

SAMPLE_FLOW_METER = """timestamp,farm,block,meter_id,planned_m3,actual_m3,variance_percent
2026-05-12T22:00:00Z,Alpha Vineyard,Block A North,FM-AV-A1,19.8,19.6,-1.0
2026-05-13T22:00:00Z,Alpha Vineyard,Block A North,FM-AV-A1,18.9,17.6,-6.9
2026-05-14T22:00:00Z,Alpha Vineyard,Block A North,FM-AV-A1,19.5,17.2,-11.8
2026-05-15T22:00:00Z,Alpha Vineyard,Block A North,FM-AV-A1,19.5,19.2,-1.5
2026-05-12T23:15:00Z,Alpha Vineyard,Block B West,FM-AV-B2,14.0,13.8,-1.4
2026-05-13T23:15:00Z,Alpha Vineyard,Block B West,FM-AV-B2,14.0,13.2,-5.7
2026-05-14T23:15:00Z,Alpha Vineyard,Block B West,FM-AV-B2,15.9,15.8,-0.6
2026-05-12T04:10:00Z,Delta Almonds,Almond Block 4,FM-DA-04,38.1,38.6,1.3
2026-05-13T04:10:00Z,Delta Almonds,Almond Block 4,FM-DA-04,38.1,42.8,12.3
2026-05-14T04:10:00Z,Delta Almonds,Almond Block 4,FM-DA-04,34.6,34.2,-1.2
2026-05-14T21:40:00Z,North Ridge,Almond Block East,FM-NR-E9,29.5,24.0,-18.6
"""

SAMPLE_CROP_PROFILE = """[
  {
    "farm": "Alpha Vineyard",
    "block": "Block A North",
    "crop": "wine grapes",
    "variety": "Cabernet Sauvignon",
    "soil_type": "clay loam",
    "irrigation_method": "drip",
    "root_zone_depth_cm": 60,
    "growth_stage": "berry set",
    "area": 3.2,
    "area_unit": "ha",
    "region": "Central Valley North",
    "operating_window": "21:00 – 23:00 local",
    "evaluation_baseline_mm": 4.9,
    "evaluation_baseline_label": "Unaided ETo-only calendar estimate — Central Valley North Cabernet Sauvignon at berry set (no soil-moisture adjustment)",
    "management_goal": "maintain moderate vine stress while avoiding runoff",
    "block_boundary_mapped": true
  },
  {
    "farm": "Alpha Vineyard",
    "block": "Block B West",
    "crop": "wine grapes",
    "variety": "Merlot",
    "soil_type": "sandy loam",
    "irrigation_method": "drip",
    "root_zone_depth_cm": 55,
    "growth_stage": "berry set",
    "management_goal": "hold steady moisture and avoid excess vigor"
  },
  {
    "farm": "Delta Almonds",
    "block": "Almond Block 4",
    "crop": "almonds",
    "variety": "Nonpareil",
    "soil_type": "silt loam",
    "irrigation_method": "micro-sprinkler",
    "root_zone_depth_cm": 90,
    "growth_stage": "kernel fill",
    "management_goal": "protect yield while avoiding applied-water variance"
  }
]"""

SAMPLE_WATER_COSTS = """region,water_source,cost_per_acre_ft,allocation_status,compliance_context
Central Valley North,Surface allocation,680,constrained,SGMA reporting and allocation tracking required
Central Valley North,Groundwater pumping,820,watch,Energy cost and groundwater accounting reviewed monthly
Delta Almond Region,Surface allocation,725,constrained,Allocation banking and district reporting required
Delta Almond Region,Groundwater pumping,910,restricted,Pumping reductions expected during peak summer period
"""

SAMPLE_SATELLITE_OBSERVATION = """timestamp,farm,block,ndvi,canopy_temperature_c,vegetation_stress_index,source_label
2026-05-12T18:00:00Z,Alpha Vineyard,Block A North,0.71,31.4,0.38,Earth observation sample layer
2026-05-13T18:00:00Z,Alpha Vineyard,Block A North,0.70,32.0,0.43,Earth observation sample layer
2026-05-14T18:00:00Z,Alpha Vineyard,Block A North,0.69,32.8,0.47,Earth observation sample layer
2026-05-12T18:00:00Z,Alpha Vineyard,Block B West,0.76,29.8,0.26,Earth observation sample layer
2026-05-13T18:00:00Z,Alpha Vineyard,Block B West,0.75,30.4,0.29,Earth observation sample layer
2026-05-14T18:00:00Z,Delta Almonds,Almond Block 4,0.67,34.2,0.52,Earth observation sample layer
"""


# ---------------------------------------------------------------------------
# Incomplete evidence scenario — missing area, high flow variance, partial soil
# ---------------------------------------------------------------------------

INCOMPLETE_EVIDENCE_CONTROLLER_EVENTS = """timestamp,farm,block,zone,provider,event_type,scheduled_duration_min,applied_duration_min,flow_m3h,pressure_kpa,status
2026-05-12T22:00:00Z,Unnamed Block,Block C South,Zone 3,WiseConn,scheduled_irrigation,38,28,21.4,198,variance_watch
2026-05-13T22:00:00Z,Unnamed Block,Block C South,Zone 3,WiseConn,scheduled_irrigation,38,49,27.8,,missing_pressure
2026-05-14T22:00:00Z,Unnamed Block,Block C South,Zone 3,WiseConn,planned_irrigation,38,0,0,,missing_pressure
"""

INCOMPLETE_EVIDENCE_FLOW_METER = """timestamp,farm,block,meter_id,planned_m3,actual_m3,variance_percent
2026-05-12T23:00:00Z,Unnamed Block,Block C South,FM-UC-C3,15.2,19.5,28.3
2026-05-13T23:00:00Z,Unnamed Block,Block C South,FM-UC-C3,15.2,11.1,-27.0
"""

INCOMPLETE_EVIDENCE_SOIL_MOISTURE = """timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health
2026-05-12T06:00:00Z,Unnamed Block,Block C South,30,21.4,36,healthy
2026-05-13T06:00:00Z,Unnamed Block,Block C South,30,20.8,38,healthy
"""

INCOMPLETE_EVIDENCE_WEATHER_SUMMARY = """timestamp,region,eto_mm,rain_forecast_mm,temperature_c,humidity_pct,wind_kph
2026-05-12T12:00:00Z,Central Valley North,5.8,0,29.4,42,14
2026-05-13T12:00:00Z,Central Valley North,6.1,0,30.2,39,18
2026-05-14T12:00:00Z,Central Valley North,6.4,0,31.1,36,21
"""

INCOMPLETE_EVIDENCE_CROP_PROFILE = """[
  {
    "farm": "Unnamed Block",
    "block": "Block C South",
    "crop": "unknown",
    "variety": null,
    "soil_type": null,
    "irrigation_method": null,
    "root_zone_depth_cm": null,
    "growth_stage": null,
    "management_goal": null
  }
]"""


def get_incomplete_evidence_files() -> List[SampleWorkbenchFile]:
    return [
        SampleWorkbenchFile("controller_events.csv", "text/csv", INCOMPLETE_EVIDENCE_CONTROLLER_EVENTS.encode("utf-8")),
        SampleWorkbenchFile("weather_summary.csv", "text/csv", INCOMPLETE_EVIDENCE_WEATHER_SUMMARY.encode("utf-8")),
        SampleWorkbenchFile("soil_moisture.csv", "text/csv", INCOMPLETE_EVIDENCE_SOIL_MOISTURE.encode("utf-8")),
        SampleWorkbenchFile("flow_meter.csv", "text/csv", INCOMPLETE_EVIDENCE_FLOW_METER.encode("utf-8")),
        SampleWorkbenchFile("crop_profile.json", "application/json", INCOMPLETE_EVIDENCE_CROP_PROFILE.encode("utf-8")),
    ]


def get_sample_files() -> List[SampleWorkbenchFile]:
    return [
        SampleWorkbenchFile("controller_events.csv", "text/csv", SAMPLE_CONTROLLER_EVENTS.encode("utf-8")),
        SampleWorkbenchFile("weather_summary.csv", "text/csv", SAMPLE_WEATHER_SUMMARY.encode("utf-8")),
        SampleWorkbenchFile("soil_moisture.csv", "text/csv", SAMPLE_SOIL_MOISTURE.encode("utf-8")),
        SampleWorkbenchFile("field_notes.txt", "text/plain", SAMPLE_FIELD_NOTES.encode("utf-8")),
        SampleWorkbenchFile("flow_meter.csv", "text/csv", SAMPLE_FLOW_METER.encode("utf-8")),
        SampleWorkbenchFile("crop_profile.json", "application/json", SAMPLE_CROP_PROFILE.encode("utf-8")),
        SampleWorkbenchFile("water_costs.csv", "text/csv", SAMPLE_WATER_COSTS.encode("utf-8")),
        SampleWorkbenchFile("satellite_observation.csv", "text/csv", SAMPLE_SATELLITE_OBSERVATION.encode("utf-8")),
    ]

