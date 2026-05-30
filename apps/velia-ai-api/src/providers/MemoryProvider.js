export class MemoryProvider {
  constructor(name = "memory") {
    this.name = name;
  }

  getFieldMemory(_fieldId) {
    throw new Error("MemoryProvider.getFieldMemory not implemented");
  }

  updateFieldMemory(_fieldId, _event) {
    throw new Error("MemoryProvider.updateFieldMemory not implemented");
  }

  summarizeFieldMemory(_fieldId) {
    throw new Error("MemoryProvider.summarizeFieldMemory not implemented");
  }
}

export class ProductionMemoryProvider extends MemoryProvider {
  constructor() {
    super("postgres-placeholder");
  }

  getFieldMemory() {
    throw new Error("Production memory is not provisioned. Use Postgres with tenant-scoped tables for production.");
  }

  updateFieldMemory() {
    throw new Error("Production memory is not provisioned. Use Postgres with tenant-scoped tables for production.");
  }
}
