# AzerothCore AI Bots — System Handoff

## What this is
A WoW 3.3.5a (WotLK) AzerothCore server running **mod-playerbots** (500 bots) where bots have
AI-powered dialogue via **mod-llm-chatter** (C++ module) + a **Python bridge** that calls a local
**Ollama** LLM. Features added on top of stock mod-llm-chatter: faction-aware dialogue, lore
accuracy, whisper→AI replies (with an "open"/mature mode), and a bot lifecycle rotation system.

## Architecture (database-queue pattern)
```
mod-llm-chatter C++ hooks (in acore-world)   -> write rows to MySQL (llm_chatter_events / _queue)
Python bridge (ac-llm-bridge container)      -> polls those tables, calls Ollama, writes llm_chatter_messages
mod-llm-chatter C++ delivery (in acore-world)-> reads messages, makes bots Say/Yell/Whisper in-world
```

## Infra / access
- **VPS:** `ssh -p 11040 appbox@79.140.195.19` — passwordless `sudo`; **docker needs sudo** (appbox not
  in docker group). VPS Tailscale IP `100.78.203.99`.
- **Server dir:** `/home/appbox/azerothcore-server/` (docker-compose project).
- **Containers:** `acore-world` (worldserver), `acore-auth`, `acore-db` (mysql:8.0, network-aliased as
  BOTH `acore-db` and `ac-database`), `ac-llm-bridge` (Python), `portainer`.
  Network: `azerothcore-server_acore-network`.
- **MySQL:** internal `ac-database:3306`, external `100.78.203.99:3311`. User `acore` / pass `acore_pw`.
  DBs: `acore_auth`, `acore_characters`, `acore_world`, `acore_playerbots`.
- **Ollama:** runs on a **Windows PC** (Tailscale `100.126.205.101:11434`). MUST bind all interfaces
  (`OLLAMA_HOST=0.0.0.0`) or the VPS can't reach it. Active model:
  `huihui_ai/qwen2.5-abliterate:14b` (abliterated/uncensored — needed for the open whisper mode).
  Also present: `qwen2.5:14b-instruct`, `qwen2.5:7b-instruct`.

## Forks (IMPORTANT for rebuilds)
The `Dockerfile` clones modules fresh from GitHub at build time, so local edits don't persist.
Both modules are forked under GitHub user **tsali** and the Dockerfile points at them:
- `tsali/mod-llm-chatter` (default branch `master`)
- `tsali/mod-playerbots` (`master`)
- Core stays upstream: `mod-playerbots/azerothcore-wotlk` branch `Playerbot`.

Push auth uses a PAT in the URL: `git push https://tsali:<PAT>@github.com/tsali/<repo>.git HEAD:master`.

## Config files
- `conf/modules/mod_llm_chatter.conf` (`LLMChatter.*`) — read by BOTH the C++ module and the Python
  bridge. Key keys: `Model=huihui_ai/qwen2.5-abliterate:14b`,
  `Ollama.BaseUrl=http://100.126.205.101:11434`, `Whisper.AllowMature=1`,
  `BotSpeakerCooldownSeconds=180`, `ConversationChance=50`, `TriggerChance=20`.
- `conf/modules/playerbots.conf` (`AiPlayerbot.*`) — `LLMChatterMode=1`, `CommandPrefix=bot`,
  `DowngradeMaxLevelBot=1`, `Min/MaxRandomBotTeleportInterval=600/1800`,
  `MinRandomBots=MaxRandomBots=500`.
- Backups of edited confs: `*.bak.*` alongside each.

## Features & where they live

### Faction loyalty + lore accuracy  (Python only -> bridge restart to apply)
- `tools/chatter_constants.py`: `RACE_FACTION`, `ENEMY_FACTION`, `FACTION_CAPITALS`, `NEUTRAL_CITIES`,
  `LORE_ACCURACY_RULE`, `RACE_CANON_LORE`.
- `tools/chatter_shared.py`: `build_faction_directive()`, `build_lore_directive()` — injected into
  `build_race_class_context()` and `build_race_class_context_parts()` (the chokepoint ALL roleplay
  prompts funnel through: general / group / proximity / event).

### Whisper -> AI reply  (C++ + Python -> needs a worldserver recompile for the C++ parts)
- `src/LLMChatterPlayer.cpp`: `OnPlayerCanUseChat(...Player* receiver)` hook (registered via
  `PLAYERHOOK_CAN_PLAYER_USE_PRIVATE_CHAT`) -> builds JSON, `QueueChatterEvent("whisper",...)`.
- `src/LLMChatterDelivery.cpp`: `channel=="whisper"` -> `bot->Whisper(msg, LANG_UNIVERSAL, anchorPlayer)`.
- `tools/chatter_proximity.py`: `handle_whisper()` (self-contained prompt; honors `Whisper.AllowMature`).
- `tools/chatter_event_registry.py`: `'whisper'` EventSpec.
- `tools/llm_chatter_bridge.py`: `fetch_pending_events` WHERE clause includes `OR e.event_type = 'whisper'`.
- `data/sql/characters/updates/20260625_whisper_event.sql`: idempotent migration adding `whisper` to the
  `event_type` enum.
- **mod-playerbots** `src/Script/Playerbots.cpp`: whisper hook returns early when `llmChatterMode`
  (suppresses the "Invite me to your group first" denial); party-chat hook only treats messages
  prefixed with `bot ` as commands (strips the prefix). Config field `llmChatterMode` in
  `PlayerbotAIConfig.h/.cpp` (reuses the module's existing `commandPrefix`).

### Open / mature whisper mode
- `LLMChatter.Whisper.AllowMature=1` + the abliterated model. Applies ONLY to whispers (the clause is
  in `handle_whisper`); public /say, group and general chat stay tame. Set to `0` + restart bridge to
  disable.

### Bot lifecycle rotation  (standalone, DB-only, no recompile)
- `/home/appbox/azerothcore-server/tools/bot-lifecycle/bot_lifecycle.py` + `lifecycle_config.json`.
- Protects a top-geared raid core (2/class + manual allowlist) by pushing their `randomize` timer
  far-future; retires aged non-core bots by force-expiring their `randomize`+`update` timers in
  `acore_playerbots.playerbots_random_bots`. The native `RandomPlayerbotMgr` then re-randomizes/
  teleports them on its next cycle.
- **Only the 500 `rndbot`-prefixed accounts are ever touched; never deletes characters; renames only
  offline bots.** `dry_run=true` by default; `--live` to apply, `--report` for population only.

## CRITICAL gotchas
1. **Docker caches git-clone layers** -> after pushing fork changes, rebuild with `--no-cache` (or
   change the clone URL) or it builds stale code.
2. **mod-playerbots caches events in memory** (`RandomPlayerbotMgr::GetEventValue`) -> direct writes to
   `playerbots_random_bots` only take effect after a **worldserver restart**. (The lifecycle service
   must be paired with a restart.)
3. **`llm_chatter_events.event_type` is an ENUM** -> any new event type needs BOTH the enum altered (a
   migration) AND the bridge's `fetch_pending_events` filter updated, or rows are silently dropped.
4. **`CharacterDatabase.Execute` swallows SQL errors** -> failed inserts fail silently; check the DB,
   not just logs.
5. **Bridge runs from the mounted HOST tools dir**, not the image. Python changes deploy by scp-to-host
   + bridge restart (no rebuild). Only C++ changes need a rebuild.
6. **`OLLAMA_HOST=0.0.0.0`** on the Windows Ollama box, or the VPS can't reach the model.

## Procedures

### Deploy a Python/bridge change (fast, no downtime)
```
# edit in the tsali/mod-llm-chatter clone, then:
scp -P 11040 tools/<file>.py appbox@79.140.195.19:/home/appbox/azerothcore-server/modules/mod-llm-chatter/tools/
ssh -p 11040 appbox@79.140.195.19 'sudo docker restart ac-llm-bridge'
# also commit/push to the fork so a future rebuild keeps it
```

### Rebuild worldserver (C++ change, ~15-20 min, restarts the world)
```
# push fork changes first, then:
cd /home/appbox/azerothcore-server
sudo docker compose build --no-cache ac-worldserver
sudo docker compose up -d ac-worldserver     # 'up -d', NOT 'restart', to use the new image
```

### Bridge container run command (if it needs recreating)
```
sudo docker run -d --name ac-llm-bridge --restart unless-stopped \
  --network azerothcore-server_acore-network \
  -v /home/appbox/azerothcore-server/modules/mod-llm-chatter/tools:/app:ro \
  -v /home/appbox/azerothcore-server/conf/modules/mod_llm_chatter.conf:/conf/mod_llm_chatter.conf:ro \
  -v /home/appbox/llm-bridge-logs:/logs -w /app python:3.12-slim \
  bash -c "pip install --quiet --no-cache-dir -r requirements.txt && exec python -u llm_chatter_bridge.py --config /conf/mod_llm_chatter.conf"
```
`requirements.txt` = `anthropic`, `openai`, `mysql-connector-python`. Bridge talks to Ollama via the
OpenAI-compatible `/v1` endpoint.

### Run the lifecycle service
```
sudo docker run --rm --network azerothcore-server_acore-network \
  -v /home/appbox/azerothcore-server/tools/bot-lifecycle:/app -w /app python:3.12-slim \
  bash -c "pip install -q mysql-connector-python && python bot_lifecycle.py --report"   # --live to apply
```

## Health checks
- Bridge: `sudo docker logs --tail 30 ac-llm-bridge` (expect 6 `[PASS]` checks + `Registry: N live events`).
- Flow: `SELECT status,COUNT(*) FROM acore_characters.llm_chatter_events GROUP BY status;`
  and check `llm_chatter_messages` for recent `delivered=1` rows.

## Outstanding TODOs
1. **Lifecycle cron** not scheduled — needs a nightly "run `bot_lifecycle.py --live` then
   `docker compose up -d ac-worldserver`" job (restart is required for staged DB changes to take effect).
2. **Core-shielding is additive** in `bot_lifecycle.py` (the protected set can creep over cycles); make
   it idempotent (un-shield bots no longer in the core).

---
_Last updated 2026-06-25._
