import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const auth = read("../src/app/components/AuthScreen.tsx");
const client = read("../src/app/api/client.ts");

assert.match(auth, /terms_accepted: false/, "signup legal acceptance must start unchecked");
assert.match(auth, /privacy_acknowledged: false/, "privacy acknowledgment must start unchecked");
assert.match(auth, /authority_confirmed: false/, "organization authority confirmation must start unchecked");
assert.match(auth, /AGRO-AI Terms of Service/, "signup must name the Terms of Service");
assert.match(auth, /Privacy Policy/, "signup must name the Privacy Policy");
assert.match(auth, /authorized to bind my organization/, "signup must include organization authority confirmation");
assert.match(auth, /https:\/\/agroai-pilot\.com\/terms-of-service/, "signup must link the live Terms");
assert.match(auth, /https:\/\/agroai-pilot\.com\/privacy-policy/, "signup must link the live Privacy Policy");
assert.match(auth, /target="_blank"/, "legal links must preserve signup form state");
assert.match(
  auth,
  /disabled=\{isSubmitting \|\| !registerForm\.terms_accepted \|\| !registerForm\.privacy_acknowledged \|\| !registerForm\.authority_confirmed\}/,
  "Create account must remain disabled until affirmative legal acceptance",
);
assert.match(client, /terms_version: string;/, "registration payload must carry the Terms version");
assert.match(client, /privacy_version: string;/, "registration payload must carry the Privacy version");
assert.match(client, /terms_accepted: boolean;/, "registration payload must carry affirmative Terms acceptance");
assert.match(client, /authority_confirmed: boolean;/, "registration payload must carry organization authority confirmation");

console.log("Portal signup legal clickwrap contract passed.");
