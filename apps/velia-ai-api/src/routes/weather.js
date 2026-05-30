import { Router } from "express";
import { normalizeWeatherContext } from "../services/weatherNormalizer.js";
import { createWeatherProvider } from "../services/weatherProviderFactory.js";

export const weatherRouter = Router();

weatherRouter.post("/context", async (req, res, next) => {
  try {
    const body = req.body || {};
    const location = normalizeWeatherContext(body);
    const weatherProvider = createWeatherProvider();
    const weather = await weatherProvider.getContext({
      location: body.location || location.location || "farm",
      lat: body.lat ?? body.latitude ?? body.coordinates?.lat,
      lon: body.lon ?? body.longitude ?? body.coordinates?.lon,
      coordinates: body.coordinates,
    });
    return res.json({ ...location, ...weather });
  } catch (error) {
    return next(error);
  }
});
