# providers

Ported from V2 `frontend/features/providers/` in step 2.1: the provider catalog
store and schema-driven settings forms.

Step 3.2 makes all of it **instance**-aware: the catalog store, selector, and
settings forms key on instance id; option-source context carries `instance` so
two bindings of one type resolve their own model and voice lists.

Secrets are write-only: the API never echoes one back, so these forms must never
try to display a stored credential.

Plan step 5.2 replaces the settings-card index with the prototype's provider
rail/detail surface. `ProviderSimulationConsole` calls the platform-owned
`/simulate` fixture for the selected instance; that endpoint never invokes the
provider or a configured transport and returns only dummy request/response data.
