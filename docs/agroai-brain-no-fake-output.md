# No fake output policy

The customer chat must not render deterministic safe-mode text as if it were a live AI answer.

If live inference returns `model_status=fallback` or `status=unavailable`, the frontend should show a connection error. It should not create an assistant bubble that looks like AGRO-AI completed real reasoning.

This prevents the exact failure seen in the June 30 screen recording: repeated, robotic, fallback-shaped output.
