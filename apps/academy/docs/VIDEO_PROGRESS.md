# Video watch-to-complete: how it is measured and what it can prove

Video lessons with an approved, playable video (URL **and** recorded duration) complete
only by watching. "Mark as complete", `complete: true` in a progress report, and any
single reported position are refused for them.

## How watching is measured

The lesson player sends a heartbeat every ~5 seconds while playing and on every play,
pause, seek and end (`public/static/js/academy.js`). The server keeps one record per
learner and lesson (`video_watch`, migration 0006) and uses **only its own clock**:

- A heartbeat credits the span from the previous heartbeat's position to this one only
  if the previous heartbeat said playback was running, it arrived 2–120 seconds earlier
  by server time, and the advance is possible at up to **2× speed**, with a margin of
  10% + 1 s for network latency between heartbeats. A closing heartbeat (pause, seek,
  end) sooner than 2 s gets no margin and ends the run. Worst case, a client can earn
  2.7× the real time it spends (2.4× at the player's 5 s heartbeat), so covering 90%
  needs at least a third of the video's length in real time.
- Jumps, seeks forward, rewinds, faster-than-2× advances, heartbeats closer than 2 s,
  gaps over 2 minutes, offline queues replayed at once and interleaved sessions are not
  credited. Credited spans are merged, so rewatching a part never counts twice.
- The lesson completes when the merged spans cover **90% of the server-recorded
  duration**. The duration a browser reports is ignored. Approval of a video requires
  its duration, and publication readiness checks it.

The rule is implemented in `creditFor` and `recordWatchBeat` in
`src/services/progress.js`. It is tested in `tests/integration/video-watch.test.js`
with deliberate spoofing:
- a forged 95% report
- an explicit completion
- start-then-wait (the previous rule accepted this)
- a fake short duration
- 3× speed
- heartbeat floods
- replayed offline queues
- rewatch loops
- two interleaved tabs

Legitimate viewing at 1× and 2× with pauses, resumes and seeks is tested too.

## Trust boundary (what this does not prove)

The server cannot see the screen. It proves that **someone kept a session sending a
plausible playback sequence for at least a third of the video's length in real time,
covering 90% of its timeline**. It cannot prove attention: a muted tab in the
background, or a script that sends correct heartbeats in real time, will pass.

This is the accepted residual risk for a free course. Video completion is one
requirement among several. The certificate also requires:
- the graded module quizzes
- a proctor-free but randomized, timed certification exam drawn from a 30-question bank
- an 80% passing score

Assessments, not video completion, carry the credential's evidentiary weight. Stronger
assurance would need DRM-protected playback with signed license-server telemetry or
in-video knowledge checks, and is out of scope.
