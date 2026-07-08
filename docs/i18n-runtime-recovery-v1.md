# I18n runtime recovery v1

Incident: non-French portal locales fail with `/v1/i18n/catalog` 500/503 while English/French remain available.

Root cause:
- only `en` and `fr-FR` are bundled complete catalogs;
- all other enabled UI locales depend on runtime catalog generation;
- frontend requests large parallel chunks with repeated passes;
- edge public translation is globally serialized and wrapped in a 12s generation timeout;
- timeout falls through to an unhealthy upstream translation backend;
- partial progress is not durably persisted and full-scope failure can clear reusable cache.

Recovery direction:
- make edge public translation the independent first path for bounded chunks;
- eliminate global provider head-of-line blocking;
- chunk by character budget so one public provider request is normally sufficient;
- persist validated progressive chunks immediately and never erase them on a later chunk failure;
- keep explicit selected locale and retry missing chunks instead of rolling back to English.
