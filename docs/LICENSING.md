# Licensing and attribution

The repository's source license remains **MIT**. The authoritative terms are in
the root [LICENSE](../LICENSE). This documentation update preserves its existing
copyright notice and permission/warranty text; it does not relicense contributions
or assign their ownership to a company.

Niblit is maintained by **Enginehead Software Development**. Niblit is the product;
Enginehead Software Development is the company identity used for development and
services. Maintainer branding is separate from source copyright attribution.

## What the root license covers

Use the root LICENSE for this repository's own source. Preserve applicable license
and copyright notices when distributing copies. [NOTICE](../NOTICE) identifies
third-party scope and must accompany release packaging where configured.

Dependencies, vendored libraries, model weights, datasets, broker/exchange software
and APIs retain their own terms. Installing, referencing or bundling one does not
make it MIT-licensed under Niblit's license. Sibling repositories must be checked
individually before a combined executable/container is distributed.

The historical NOTICE references swift-argument-parser under
`vendor/swift-argument-parser`. That directory is absent from the currently
inspected local tree; the attribution is retained for historical distributions.
If bundled again, include its upstream Apache-2.0 license and required notices.
Do not restore absent vendor files merely to satisfy that historical reference.

## Distribution checklist

1. Include the unchanged LICENSE and relevant NOTICE files.
2. Inventory the actual included dependency versions, models and assets.
3. Include their required attribution/license materials; do not assume a full
   third-party license audit has already been completed.
4. Keep private credentials, user knowledge, account state and conversation data
   out of packages and public source.
5. Document separate service terms and prices before offering a hosted paid plan.
   Source licensing alone is not a subscription, privacy policy or service agreement.

No contributor agreement, paid subscription, hosted-service terms or new trademark
license is introduced by this update. Any such policy needs its own explicit review.

