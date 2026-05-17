export class TranslationProvider {
  constructor(name = "mock") { this.name = name; }
  async translate(_text, _language) { throw new Error("TranslationProvider.translate not implemented"); }
}
