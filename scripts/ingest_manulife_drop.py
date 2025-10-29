#!/usr/bin/env python3
import pandas as pd, yaml, json, sys, os
from pathlib import Path

SCHEMA = yaml.safe_load(open('data/ingestion_schema.yaml'))

def load_csv(path, required):
  df = pd.read_csv(path)
  missing = [c for c in required if c not in df.columns]
  if missing:
    raise ValueError(f"{path}: missing {missing}")
  return df

def main(drops_dir='data/drops'):
  drops = Path(drops_dir)
  if not drops.exists():
    raise SystemExit(f"{drops_dir} not found")
  et = load_csv(drops/'et.csv', SCHEMA['et']['required_columns'])
  sm = load_csv(drops/'soil_moisture.csv', SCHEMA['soil_moisture']['required_columns'])
  wx = load_csv(drops/'weather.csv', SCHEMA['weather']['required_columns'])

  assert len(et) > 1000, "ET sample too small for pilot"
  assert len(sm) > 1000, "Soil moisture sample too small for pilot"

  et['date'] = pd.to_datetime(et['timestamp']).dt.date
  sm['date'] = pd.to_datetime(sm['timestamp']).dt.date
  wx['date'] = pd.to_datetime(wx['timestamp']).dt.date

  features = et.merge(wx, on='date', suffixes=('_et','_wx'), how='inner')
  features.to_parquet('data/processed/features.parquet', index=False)
  print("Wrote data/processed/features.parquet")

if __name__ == '__main__':
  main(*sys.argv[1:])
