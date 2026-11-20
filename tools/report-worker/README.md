# LOTRO-TTS Report Worker (Cloudflare Worker)

Serverless relay that lets LOTRO-TTS users submit voice quality, NPC metadata, pronunciation, and general bug reports with one click directly from the GUI — **without requiring each user to have a GitHub account** and without embedding any API token in the client executable.

## Features
- Keeps your GitHub token strictly on Cloudflare's servers (`GITHUB_TOKEN` secret).
- Rate-limits per client IP (5 reports per 10 minutes via Cloudflare Cache API, zero raw IP logging).
- Escapes `@` mentions and Markdown fences in user inputs.
- Automatically deduplicates open `[Voice Report]` and `[NPC Report]` issues by appending a `+1` comment instead of flooding your repository.
- Tags issues automatically with `voice-report`, `npc-metadata`, `pronunciation`, `bug`, and `user-report`.

## 5-Minute Setup

1. **Create a fine-grained GitHub Token**
   - GitHub → *Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*
   - **Repository access:** Only select repositories → `ElianMoirtide/LOTRO-TTS`
   - **Repository permissions:** `Issues: Read and write` (no other permissions needed)

2. **Deploy to Cloudflare Workers (Free Tier: 100,000 requests/day)**
   ```bash
   cd tools/report-worker
   npx wrangler login
   npx wrangler secret put GITHUB_TOKEN
   npx wrangler deploy
   ```

3. **Connect LOTRO-TTS GUI**
   - Copy the deployed worker URL (e.g. `https://lotro-tts-report-worker.<your-subdomain>.workers.dev/report`).
   - Paste it into `DefaultReportEndpoint` in `src/LotroTtsGui/ReportDialog.cs` and rebuild the binaries.
   - Until configured, users can still test locally via `"report_endpoint"` in `config.json` (or `LOTRO_TTS_REPORT_URL`) or use the built-in **"Open on GitHub"** / **"Copy Markdown"** fallbacks.
