#!/usr/bin/env python3
import pandas as pd, json
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

def main():
  df = pd.read_parquet('data/processed/features.parquet')
  y = df['eto_mm']
  X = df.drop(columns=['eto_mm','timestamp_et','date'])
  X = X.select_dtypes(include='number').fillna(0)
  X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
  model = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
  model.fit(X_train, y_train)
  preds = model.predict(X_test)
  mae = float(mean_absolute_error(y_test, preds))
  r2  = float(r2_score(y_test, preds))
  imp = getattr(model, "feature_importances_", None)
  if imp is not None:
    import pandas as pd
    pd.Series(imp, index=X.columns).sort_values(ascending=False).to_csv('data/processed/feature_importance.csv')
  with open('data/processed/evaluation.json','w') as f:
    json.dump({"MAE": mae, "R2": r2}, f, indent=2)
  print("Saved data/processed/evaluation.json and feature_importance.csv")

if __name__ == "__main__":
  main()
