export class IntegrationAdapter {
  constructor(provider) {
    this.provider = provider;
  }

  async connect() {
    return { provider: this.provider, status: "integration_ready" };
  }

  async fetchFields() {
    return [];
  }

  async fetchIrrigationLogs() {
    return [];
  }

  async sync() {
    return { provider: this.provider, synced: 0, status: "integration_ready" };
  }
}
