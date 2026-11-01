# Company domain connection — 31 October 2026

Both `enginehsd.site` and `www.enginehsd.site` are now attached to Vercel project
`enginehead-company` (`prj_CQarSznezZNwSrQv04eLuZaud94c`), verified by the Vercel
API. The www domain redirects to the apex with HTTP 308. The owner detached the
old project assignments first; the previous add-domain conflict no longer applied.
No project was deleted by the assistant.

Public HTTPS verification timed out. Vercel DNS configuration reports
`misconfigured=true` for both names. Namecheap is authoritative:
`dns1.registrar-servers.com`, `dns2.registrar-servers.com`.

Observed current records:
- Apex A: `192.64.119.187` (Namecheap forwarding).
- www CNAME: `parkingpage.namecheap.com.`.

Vercel's current preferred recommendations:
- Apex A values: `216.198.79.1` and `64.29.17.1`.
- www CNAME: `afe7c6618aafae23.vercel-dns-017.com.`.

Next: owner signs into Namecheap Advanced DNS. Inspect current records before
editing; replace only conflicting website/forwarding records, preserve mail/TXT
records and nameservers. Recheck Vercel recommendations at action time, then
verify both public HTTPS addresses and certificate issuance. Project attachment
is complete; public DNS/website delivery is not yet complete.

Working fallback: https://enginehead-company.vercel.app/.
