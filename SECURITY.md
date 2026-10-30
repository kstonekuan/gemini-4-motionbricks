# Security

This project is an independent research demo. It has no authentication, durable
queue or per-user spending controls. Keep it on loopback or behind private access
until your deployment supplies those controls.

Do not include keys or private prompts in public issues. For a vulnerability in
this director, use the repository's **Security → Report a vulnerability** feature
if enabled. If private reporting is unavailable, open an issue asking for a
private contact without disclosing exploit details. Reports about upstream
MotionBricks should follow its own security policy.

The Gemini API key is used on the backend. Browser-only key isolation is not
implemented. Treat both instructions and generated plans as untrusted input;
keep geometry checks, queue limits and request limits enabled.
