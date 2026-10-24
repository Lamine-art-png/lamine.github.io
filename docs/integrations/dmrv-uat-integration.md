# DMRV integration evaluation

The TEST-only DMRV UAT preview (`dmrv-uat/2`) runs the deterministic,
evidence-grounded DMRV engine. It covers gazetteer location resolution, NASA
POWER-derived climate normals, SoilGrids topsoil context, FAO-56 crop
parameters and registered scientific tools. It runs without a model, without
billing, without production data, without provider writes and without physical
actions. See `dmrv-advisory-api.md`.

Production recommendations require separate LIVE access under a signed
agreement. See `intelligence-contract-billing.md` for the payment-to-access
path.
