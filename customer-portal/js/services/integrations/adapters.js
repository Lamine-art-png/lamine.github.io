import { IntegrationAdapter } from "./baseAdapter.js";

const makeAdapter = (provider) => new IntegrationAdapter(provider);

export const adapters = {
  WiseConn: makeAdapter("wiseconn"),
  Talgil: makeAdapter("talgil"),
  Hortau: makeAdapter("hortau"),
  Manual: makeAdapter("manual"),
  Weather: makeAdapter("weather"),
  Satellite: makeAdapter("satellite"),
  FutureProvider: makeAdapter("future_provider"),
};

export const integrationRegistry = {
  list() {
    return Object.entries(adapters).map(([name, adapter]) => ({ name, provider: adapter.provider }));
  },
  get(name) {
    return adapters[name];
  },
};
