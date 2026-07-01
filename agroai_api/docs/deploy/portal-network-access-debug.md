# Portal network access debug

The portal can show `Backend unavailable. Retry.` even when `/v1/health` is healthy. That message is emitted by the browser frontend when `fetch()` throws before it receives an HTTP response.

The most common causes are:

1. The portal is being tested from a Cloudflare Pages preview domain that is not in API CORS.
2. The frontend bundle was built with a stale API base URL.
3. The API route throws before the browser can read the response with CORS headers.

This fix adds a narrow CORS regex for AGRO-AI Cloudflare Pages preview projects while keeping the production custom domain allowlist.

Quick browser console tests from the portal page:

```js
fetch('https://api.agroai-pilot.com/v1/health', { mode: 'cors' })
  .then(async r => console.log(r.status, await r.text()))
  .catch(console.error)

fetch('https://api.agroai-pilot.com/v1/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'not-real@example.com', password: 'not-real-password' })
})
  .then(async r => console.log(r.status, await r.text()))
  .catch(console.error)
```

Expected result for the fake login test is an HTTP response, usually `401` or `422`, not a browser-level `TypeError: Failed to fetch`.
