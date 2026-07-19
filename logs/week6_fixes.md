# Week 6 — fixes

Branch `week6-fixes` off `week6`. Corpus stays **FROZEN at 2,319** throughout.
`processing/cleaner.py` deliberately untouched (fixing it needs re-scraping + re-embedding,
which would invalidate every measured number).

---

## PHASE 1 — ENVIRONMENT (no code changed)

### Diagnosis: 8 dangling symlinks, not 1

Docker Desktop is installed and healthy. The problem is purely that `/usr/local/bin` is full
of symlinks into `/Volumes/Docker/...` — the **install DMG**, which is no longer mounted.
This happens when Docker Desktop is run once from the mounted disk image before being copied
to `/Applications`; the installer writes symlinks pointing at the DMG path.

| symlink in `/usr/local/bin` | state | in app bundle? |
|---|---|---|
| `docker` | BROKEN | ✅ present |
| `docker-compose` | BROKEN | ❌ not present (see note) |
| `docker-credential-desktop` | BROKEN | ✅ present |
| `docker-credential-osxkeychain` | BROKEN | ✅ present |
| `cagent` | BROKEN | ✅ present |
| `hub-tool` | BROKEN | ✅ present |
| `kubectl` | BROKEN | ✅ present |
| `kubectl.docker` | BROKEN | ✅ present |

**The real binary lives at `/Applications/Docker.app/Contents/Resources/bin/docker`** and is
executable. Verified directly:

```
$ /Applications/Docker.app/Contents/Resources/bin/docker --version
Docker version 29.2.1, build a5c7197

$ /Applications/Docker.app/Contents/Resources/bin/docker compose version
Docker Compose version v5.0.2
```

**Note on `docker-compose`:** the standalone v1 shim is genuinely absent from the bundle,
and it does not matter. Compose v2 ships as a CLI *plugin* invoked as the `docker compose`
subcommand, which already resolves correctly through the bundled `docker` binary (verified
above). Nothing in this project calls `docker-compose` with a hyphen — `README.md` and
`docker-compose.yml` both use `docker compose`.

### Recommended fix — PATH, no sudo (preferred)

This fixes **all eight** at once, survives Docker Desktop upgrades, and needs no admin
rights:

```bash
echo 'export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

The bundle bin directory is currently referenced in **no** shell profile
(`~/.zshrc`, `~/.zprofile`, `~/.bash_profile` all checked), so this is a clean addition.

### Alternative — repoint the symlink (needs sudo, fixes only `docker`)

```bash
sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker
```

`/usr/local/bin/docker` is owned by `root:wheel`, hence the `sudo`. This leaves the other
seven symlinks broken — fine for this project, but the PATH approach is strictly better.

*Both commands are for you to run; I have not modified anything outside the repo.*

### Verification — all three checks pass

| check | result |
|---|---|
| `docker ps` | `wanderrag-qdrant` · `qdrant/qdrant:latest` · **Up 2 hours** · `0.0.0.0:6333-6334->6333-6334/tcp` |
| `docker compose version` | **v5.0.2** |
| `docker compose ps` (in repo) | service `qdrant`, created 4 weeks ago, **Up 2 hours** |
| `curl .../collections/wanderrag_chunks` | **`points_count = 2319`**, `status = green`, `dim = 3072` |

**The frozen corpus is intact and the container is healthy.** Nothing was reinstalled,
restarted, or re-ingested.

### Risk note

The container has been up 2 hours against a 4-week-old creation date, so it *has* been
restarted at some point — meaning the volume (`qdrant_storage`) is persisting correctly and
a restart is survivable. That materially lowers the risk I flagged earlier: the corpus is on
a named Docker volume, not only in a running container's memory. Once the PATH fix is
applied, `docker compose up -d` can bring it back if it ever stops.
