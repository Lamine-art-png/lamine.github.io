export class IntegrationProvider {
  constructor(name = "mock") { this.name = name; }
  async fetchControllerData(_payload) { return { status: "not_implemented" }; }
}
