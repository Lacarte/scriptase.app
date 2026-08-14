# providers

Ported from V2 `frontend/features/providers/` in step 2.1: the provider catalog
store and schema-driven settings forms.

Step 3.2 makes all of it **instance**-aware, so two instances of one provider
type resolve their own model and voice lists through the option-source endpoint.

Secrets are write-only: the API never echoes one back, so these forms must never
try to display a stored credential.
