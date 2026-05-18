export const integrationSetupService = {
  nextStep(setup) {
    return { ...setup, step: Math.min(setup.step + 1, 5) };
  },
  previousStep(setup) {
    return { ...setup, step: Math.max(setup.step - 1, 1) };
  },
  setProvider(setup, provider) {
    return { ...setup, provider };
  },
  setState(setup, state) {
    return { ...setup, state };
  },
};
