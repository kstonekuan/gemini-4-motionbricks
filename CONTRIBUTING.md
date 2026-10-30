# Contributing

Bug reports and focused pull requests are welcome. Include an instruction that
reproduces a behavior, expected and actual outcomes, and relevant versions.
Remove API keys and private prompts from logs before sharing them.

Use pnpm and Biome for TypeScript, and uv, Ruff and ty for Python. Run the checks
in [development](docs/development.md). Tests should protect observable behavior,
such as target validation or queue ordering, rather than framework internals.

Changes to the MotionBricks integration must update the patch and be verified
against the pinned upstream checkout. Do not add upstream assets, model weights,
sample motion clips, local configuration or credentials to this repository.

Contributions are provided under the repository's Apache-2.0 license. Do not
submit content you do not have the right to distribute.
