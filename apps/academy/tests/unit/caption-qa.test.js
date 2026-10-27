// Mechanical caption checks for reviewers (scripts/caption-qa.mjs).
import { test } from "node:test";
import assert from "node:assert/strict";
import { captionQa, parseVtt } from "../../scripts/caption-qa.mjs";

const vtt = (...cues) => `WEBVTT\n\n${cues.map(([a, b, t]) => `${a} --> ${b}\n${t}`).join("\n\n")}\n`;

test("a well-formed caption covering the video has no issues", () => {
  const r = captionQa(vtt(["00:00.000", "00:03.000", "Welcome to AGRO-AI Academy."], ["00:03.500", "00:06.000", "NDVI measures crop vigor."]), 6.2);
  assert.deepEqual(r.issues, []);
  assert.equal(r.cues, 2);
  assert.equal(r.words, 8);
});

test("layout, reading speed, timing and coverage problems are reported", () => {
  const r = captionQa(
    vtt(
      ["00:00.000", "00:00.500", "This line is much too long to read comfortably in one go."],
      ["00:00.400", "00:09.000", "one\ntwo\nthree"],
    ),
    60,
  );
  const all = r.issues.join("\n");
  assert.match(all, /1 cue\(s\) with a line over 42 characters/);
  assert.match(all, /1 cue\(s\) over 2 lines/);
  assert.match(all, /faster than 20 characters per second/);
  assert.match(all, /shorter than 1 s/);
  assert.match(all, /longer than 7 s/);
  assert.match(all, /1 overlapping cue/);
  assert.match(all, /captions end at 9 s of a 60 s video/);
});

test("likely misrecognitions of course terms are flagged by cue number; correct spellings are not", () => {
  const r = captionQa(vtt(["00:00.000", "00:02.000", "Agro AI uses and DVI maps."], ["00:02.000", "00:04.000", "Evapo transpiration is ET zero times kay see."], ["00:04.000", "00:06.000", "AGRO-AI, NDVI and evapotranspiration."]), 6);
  assert.deepEqual(r.terms["AGRO-AI"], [1]);
  assert.deepEqual(r.terms.NDVI, [1]);
  assert.deepEqual(r.terms.evapotranspiration, [2]);
  assert.deepEqual(r.terms["ET₀ / ETc"], [2]);
  assert.deepEqual(r.terms["Kc (crop coefficient)"], [2]);
});

test("hour timestamps, cue settings and markup are parsed", () => {
  const [c] = parseVtt("WEBVTT\n\n1\n01:00:01.000 --> 01:00:03.500 align:start\n<v Joshua>Hello</v>\n");
  assert.equal(c.start, 3601);
  assert.equal(c.end, 3603.5);
  assert.deepEqual(c.lines, ["Hello"]);
  assert.equal(captionQa("not vtt").valid, false);
});
