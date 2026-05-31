# Qanat interoperability mapping

This adapter is a clean-room mapping layer. It does not reuse AGPL source code.

| Qanat-style field | AGRO-AI compliance field |
| --- | --- |
| `parcel_identifier` / `apn` | `parcel.apn` |
| `parcel_geometry_ref` | `parcel.geometry_ref` |
| `well_identifier`, `latitude`, `longitude` | `well.*` |
| `extraction_volume`, `unit`, `truth_label` | `extraction_volume.*` |
| `water_budget` | `water_budget` |
| `reporting_period` | `reporting_period` |
| `source_provenance` | `source_provenance` |

All imported values must carry provenance and truth labels. Estimated or reported Qanat-origin values are never relabeled as certified measurements.
