-- Migration 0008: Extend sensor catalog with full API v1.47 metadata fields
-- and add message column to event log.
--
-- Sensor metadata fields from rest.api.external v1.47:
--   minLimit, maxLimit, lowThreshold, highThreshold, readingRate, unitsDescriptor
--
-- Event log per v1.47 returns: time, context, subcontext, message
--   Adding message column to store the event message text.
--
-- Water consumption per v1.47 returns: from, until, value, valuePerArea
--   Adding value_per_area column.

-- Extend sensor catalog
ALTER TABLE talgil_sensor_catalog ADD COLUMN min_limit REAL;
ALTER TABLE talgil_sensor_catalog ADD COLUMN max_limit REAL;
ALTER TABLE talgil_sensor_catalog ADD COLUMN low_threshold REAL;
ALTER TABLE talgil_sensor_catalog ADD COLUMN high_threshold REAL;
ALTER TABLE talgil_sensor_catalog ADD COLUMN reading_rate REAL;
ALTER TABLE talgil_sensor_catalog ADD COLUMN units_descriptor TEXT;

-- Extend event log with message field
ALTER TABLE talgil_event_log ADD COLUMN message TEXT;

-- Extend water consumption with value_per_area
ALTER TABLE talgil_valve_wc ADD COLUMN value_per_area REAL;
