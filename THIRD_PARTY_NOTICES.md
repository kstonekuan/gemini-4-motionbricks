# Third-party components

The integration patch is derived from NVIDIA MotionBricks source (Apache-2.0).
See NOTICE. Upstream assets and models are obtained separately and retain their
own licenses; none are included in this repository.

The browser uses these open-source projects, installed through pnpm:

| Component | License |
| --- | --- |
| React, TanStack Query, ts-pattern, Zod | MIT |
| Three.js | MIT |
| XState | MIT |
| shadcn/ui and Radix UI | MIT |
| Lucide | ISC (with some inherited Feather icons under MIT) |
| Manrope, self-hosted through Fontsource | SIL Open Font License 1.1 |
| Tailwind CSS, clsx, class-variance-authority, tailwind-merge | MIT |

Python dependencies include the Google Gen AI SDK (Apache-2.0), FastAPI,
Starlette, Uvicorn, HTTPX, Pydantic and pydantic-settings (BSD or MIT), and Pillow
(MIT-CMU). Their distributions contain the authoritative license notices.
Build dependencies carry their own licenses as recorded in their distributions.
Manrope's license is included in `licenses/Manrope-OFL.txt`.

The vendored shadcn/ui component source retains the upstream MIT license in
`licenses/shadcn-ui-MIT.txt`.

AI Elements Plan/Shimmer component sources are Copyright 2023 Vercel, Inc.,
licensed under Apache-2.0. Their notice is included in
`licenses/vercel-ai-elements-LICENSE.txt`. Motion is installed under MIT.
