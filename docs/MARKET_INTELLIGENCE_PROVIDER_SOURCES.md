# Governed Market Intelligence sources

## ECB foreign exchange reference rates

AGRO-AI uses the European Central Bank daily euro foreign exchange reference-rate publication as a governed reference FX source. The adapter converts currencies from the ECB's units-per-EUR publication into AGRO-AI's explicit quote convention: reporting-currency units per one unit of source currency.

The source is intentionally labelled `DELAYED`, not `LIVE`, because it is a daily reference publication and not a transaction or execution feed.

## USDA AMS MyMarketNews / MARS

For supported U.S. positions, AGRO-AI can retrieve USDA AMS MyMarketNews reports using the official MARS API. A configured `USDA_MMN_API_KEY` is required. The key is used as the Basic-auth username with an empty password.

The adapter stores the government observation, report slug, source URL, retrieval timestamp, observation timestamp, unit, currency, freshness policy, attribution requirement and upstream-verification marker. It only promotes a cash price into a customer's commercial position when the reported quantity unit matches the position's unit. Otherwise it keeps the observation as evidence without changing the commercial price.

AGRO-AI deliberately does not infer national or regional cash prices when a report or physical market is ambiguous.

## Customer-owned physical market data

For markets not covered by a configured upstream, authorized organization members can enter a verified realizable price and its observation time. The observation is always stored as `MANUAL`. Customer input cannot self-assign `LIVE` authority.

This is a first-class operating path rather than a fake-data fallback: many specialty crops and negotiated physical markets do not have a universal exchange price.
