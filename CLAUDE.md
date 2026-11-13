# Meeting Transcriber: notes for Claude Code

## Deploying to the home server

Meeting Transcriber runs on Bogdan's home server in Docker, behind Caddy and the Authentik login. The setup
lives in the `Boby0230/homelab` repo; its `CLAUDE.md` has the full context (what runs where, the
rules, decisions already made).

- **Branches:** work on `homelab-docker`. When a change is finished and tested, fast-forward `main` to it: `git push origin homelab-docker:main` (never force). The server builds `main` (`scripts/apps.conf` in homelab). Merging a pull request into `main` also works, but then fast-forward `homelab-docker` to `main` afterwards so the two don't drift apart.
- **Deploy** (ask Bogdan first: it restarts every app whose code changed, and a long job that is
  running in this app is interrupted):
  ```bash
  ssh bogdan@homeserver 'cd ~/homelab && git pull --ff-only && scripts/deploy.sh'
  ```
  The server user is `bogdan`, the host `homeserver` (over Tailscale; `192.168.0.130` on the home
  Wi-Fi). It fetches every app's branch, rebuilds what changed and restarts it. Don't build or
  start containers by hand.
- **Check it:** `ssh bogdan@homeserver 'cd ~/homelab && docker compose ps meeting-transcriber'` should show
  `(healthy)` after about a minute; logs with
  `ssh bogdan@homeserver 'cd ~/homelab && docker compose logs --tail 100 meeting-transcriber'`.
  This app's services: `meeting-transcriber`.
- **Data:** `jobs.db` (SQLite) and the Whisper models in the `meeting_transcriber_data` and `meeting_transcriber_models` volumes; a deploy keeps them.
- **Never** copy `.env` files, secrets or the app's data into the repo or the chat. Secrets live in
  `~/homelab` on the server (`.env` files) and stay there.
