import { Router } from "express";
import { MockWeatherProvider } from "../providers/mockProviders.js";
import { normalizeWeatherContext } from "../services/weatherNormalizer.js";

const weatherProvider = new MockWeatherProvider("mock");

export const weatherRouter = Router();

weatherRouter.post("/context", async (req, res, next) => {
  try {
    const body = req.body || {};
    const location = body.location || "farm";
    const weather = await weatherProvider.getContext(location);
    return res.json({ ...weather, ...normalizeWeatherContext(body) });
  } catch (error) {
    return next(error);
  }
});
