export class SatelliteProvider {
  constructor(name = "mock") { this.name = name; }
  async analyzeField(_payload) { return { status: "not_implemented" }; }
}
