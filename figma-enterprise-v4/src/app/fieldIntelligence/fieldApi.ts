// Concrete Field Intelligence transport bound to the shared apiClient.
// Kept in a .ts module so generic/arrow syntax stays out of the JSX literal scan.
import { apiClient } from "../api/client";
import type { FieldApi } from "./offlineQueue";

export const fieldApi: FieldApi = {
  initiate: (payload) => apiClient.fieldIntelligence.initiate(payload as any),
  uploadAsset: (captureId, fields, file) => apiClient.fieldIntelligence.uploadAsset(captureId, fields, file),
  complete: (captureId, payload) => apiClient.fieldIntelligence.complete(captureId, payload),
};
