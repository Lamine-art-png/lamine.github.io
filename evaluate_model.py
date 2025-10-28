#!/usr/bin/env python3
import json, pandas as pd, numpy as np

def main():
  ev = json.load(open('data/processed/evaluation.json'))
  fi = pd.read_csv('data/processed/feature_importance.csv')
  fi['rank'] = np.arange(1, len(fi)+1)
  bias = {"by_top_features": fi.head(10).to_dict(orient='records')}
  with open('data/processed/bias_report.json','w') as f:
    json.dump(bias, f, indent=2)
  print("Saved data/processed/bias_report.json")

if __name__ == "__main__":
  main()
