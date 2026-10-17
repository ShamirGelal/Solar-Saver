# Solar forecasting handoff

This subsystem trains a weather-aware hourly irradiance model for
Charlottesville and implements the shared `SolarForecaster` contract.

## Reproduce locally

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python scripts/prepare_ml_data.py
PYTHONPATH=. .venv/bin/python scripts/train_model.py
```

The first command downloads and caches NASA POWER irradiance history for
2020–2024 and Open-Meteo historical forecasts for 2022–2024. The training
script uses 2022 for training, 2023 for validation, and 2024 for testing.

Generated data, metrics, and model artifacts are intentionally ignored by Git.
The trained model is written to:

```text
artifacts/solar_forecaster.joblib
```

## Integration API

```python
from solar_saver.forecasting import TrainedSolarForecaster

forecaster = TrainedSolarForecaster.from_path()
profile = forecaster.predict(forecast_request)
```

Prediction retrieves live hourly cloud cover, temperature, humidity, and
precipitation from Open-Meteo, then returns a 24-hour `SolarProfile` in
aggregate simulated kW. It therefore requires internet access at prediction
time. `SeasonalDemoForecaster` remains available as an offline fallback.

## Verified performance

On the untouched 2024 test partition, the weather-aware model achieved:

- hourly MAE: 31.02 Wh/m²;
- hourly RMSE: 63.24 Wh/m²;
- daily R²: 0.882;
- median daily percentage error: 11.4%;
- annual aggregate bias: -2.45%.

The matched calendar-only model had an hourly MAE of 53.61 Wh/m². Open-Meteo
historical forecasts are a continuous series assembled from early forecast
hours, not a fixed 24-hour-lead archive, so exact day-ahead accuracy may be
lower than these results.

See `solar_saver/data/ATTRIBUTION.md` for data-source attribution.
