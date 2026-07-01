import test from "node:test";
import assert from "node:assert/strict";
import { getConfig } from "../config.js";

test("Terris env names take precedence over legacy Velia env names", () => {
  process.env.TERRIS_MEMORY_FILE = "/tmp/terris-memory.json";
  process.env.VELIA_MEMORY_FILE = "/tmp/velia-memory.json";
  process.env.TERRIS_PROTECT_ENABLED = "true";
  process.env.VELIA_PROTECT_ENABLED = "false";
  const config = getConfig();
  assert.equal(config.memoryFile, "/tmp/terris-memory.json");
  assert.equal(config.terrisProtectEnabled, true);
  delete process.env.TERRIS_MEMORY_FILE;
  delete process.env.VELIA_MEMORY_FILE;
  delete process.env.TERRIS_PROTECT_ENABLED;
  delete process.env.VELIA_PROTECT_ENABLED;
});

test("legacy Velia env names remain fallback aliases", () => {
  process.env.VELIA_WEATHER_CACHE_FILE = "/tmp/legacy-weather.json";
  const config = getConfig();
  assert.equal(config.weatherCacheFile, "/tmp/legacy-weather.json");
  delete process.env.VELIA_WEATHER_CACHE_FILE;
});

test("backend beta Terris modules are disabled by default", () => {
  const config = getConfig();
  assert.equal(config.terrisWaterEnabled, true);
  assert.equal(config.terrisNutrientsEnabled, false);
  assert.equal(config.terrisEnergyEnabled, false);
  assert.equal(config.terrisOpsEnabled, false);
  assert.equal(config.terrisProofEnabled, false);
  assert.equal(config.terrisProtectEnabled, false);
  assert.equal(config.terrisRiskApiEnabled, false);
});
