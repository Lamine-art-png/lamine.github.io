import assert from "node:assert/strict";
import fs from "node:fs";

const overview = fs.readFileSync(new URL("../src/app/components/Overview.tsx", import.meta.url), "utf8");

assert.match(overview, />Now</);
assert.match(overview, /Next best action/);
assert.match(overview, /Needs attention/);
assert.match(overview, /Active work/);
assert.match(overview, /Quick field update/);
assert.match(overview, /Recent signals/);
assert.match(overview, /fieldOps\.fieldMessage/);
assert.match(overview, /channel:\s*"portal"/);
assert.match(overview, /sender_role:\s*"operator"/);
assert.match(overview, /center\.recent_signals/);
assert.match(overview, /activeTasks/);
assert.match(overview, /hasActiveTask/);
assert.doesNotMatch(overview, /Field Update Intake/);
assert.doesNotMatch(overview, /Audit Trail/);
assert.doesNotMatch(overview, /label="Event type"/);
assert.doesNotMatch(overview, /fieldOps\.fieldUpdate/);

console.log("Command Center simplicity and intelligence contract passed.");
