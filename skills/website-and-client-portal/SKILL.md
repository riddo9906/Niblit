---
name: website-and-client-portal
description: Build and verify Niblit's public website, client portal, onboarding, contact and account workflows.
---
# Website and client portal

Use this skill for Niblit's public website, client portal, account creation, contact channels and hosting.

- Inspect the existing frontend, backend routes, data model and deployment configuration before changing architecture.
- Keep public marketing pages separate from authenticated client and administrator workflows.
- Use the configured email address and provider only; never invent a contact address or claim email delivery without provider confirmation.
- Account creation, admin approval, password resets, database writes and email sends require explicit authorization and verified provider configuration.
- Use Supabase only if the project's actual project URL, schema and supported connection are configured.
- Verify responsive layout, navigation, form validation, server-side authorization, persistence and error states.
- Do not expose admin routes, service-role keys, database credentials or internal API endpoints to public clients.
