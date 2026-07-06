import { apiClient } from "./client";

export type StartRecoveryPayload = { email: string };
export type CompleteRecoveryPayload = { token: string; replacement_credential: string };
export type RecoveryResponse = { message?: string; status?: string };

export const recoveryClient = {
  start(payload: StartRecoveryPayload) {
    return apiClient.post<RecoveryResponse>("/v1/auth/account-recovery/start", payload);
  },
  complete(payload: CompleteRecoveryPayload) {
    return apiClient.post<RecoveryResponse>("/v1/auth/account-recovery/complete", payload);
  },
};
