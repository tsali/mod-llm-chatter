"""Guild-chat pacing helpers.

This module owns visible guild-chat pacing for join bursts. Charter or
guild creation can add several bots in the same second; without a
per-guild reservation row, parallel bridge workers schedule all welcome
lines at nearly identical delays.
"""

import logging
import math
import random
from typing import Optional


logger = logging.getLogger(__name__)

POLICY_JOIN_BURST = 'join_burst'


def _int_config(
    config: dict,
    key: str,
    default: int,
    minimum: int = 0,
    maximum: int = 300,
) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _debug_enabled(config: dict) -> bool:
    return str(config.get(
        'LLMChatter.GuildChat.PacingDebugLog', '0'
    )).strip() == '1'


def _sanitize_reason(reason: Optional[str]) -> str:
    text = str(reason or '')[:64]
    return text or 'unknown'


def reserve_guild_slot(
    db,
    config: dict,
    guild_id: int,
    requested_delay: float,
    policy: Optional[str] = None,
    reason: Optional[str] = None,
) -> int:
    """Reserve the next visible guild-chat slot for a guild.

    Only join-burst messages are paced for now. Player-message replies
    and ambient/social guild events keep their original scheduling so a
    guild-creation backlog does not make direct player replies feel late.
    """
    requested_delay = max(0, float(requested_delay or 0))
    original_delay = max(0, int(math.ceil(requested_delay)))
    if policy != POLICY_JOIN_BURST:
        return original_delay

    try:
        guild_id = int(guild_id or 0)
    except (TypeError, ValueError):
        guild_id = 0
    if not guild_id:
        return original_delay

    min_gap = _int_config(
        config,
        'LLMChatter.GuildChat.JoinBurstMinGapSeconds',
        10,
        maximum=120,
    )
    max_gap = _int_config(
        config,
        'LLMChatter.GuildChat.JoinBurstMaxGapSeconds',
        18,
        minimum=min_gap,
        maximum=180,
    )
    if max_gap <= 0:
        return original_delay
    gap = random.randint(min_gap, max_gap)
    reason = _sanitize_reason(reason)

    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("START TRANSACTION")
        cursor.execute("""
            INSERT IGNORE INTO llm_guild_chat_pacing
                (guild_id, next_available_at, last_activity_at)
            VALUES (%s, NOW(), NOW())
        """, (guild_id,))
        cursor.execute("""
            SELECT
                UNIX_TIMESTAMP(NOW()) AS now_ts,
                UNIX_TIMESTAMP(next_available_at) AS next_ts
            FROM llm_guild_chat_pacing
            WHERE guild_id = %s
            FOR UPDATE
        """, (guild_id,))
        row = cursor.fetchone() or {}
        now_ts = float(row.get('now_ts') or 0)
        next_ts = float(row.get('next_ts') or now_ts)
        requested_at = now_ts + requested_delay
        scheduled_at = max(requested_at, next_ts)
        next_available = scheduled_at + gap

        cursor.execute("""
            UPDATE llm_guild_chat_pacing
            SET next_available_at = FROM_UNIXTIME(%s),
                last_activity_at = FROM_UNIXTIME(%s),
                last_policy = %s,
                last_reason = %s
            WHERE guild_id = %s
        """, (
            int(math.ceil(next_available)),
            int(math.ceil(scheduled_at)),
            policy,
            reason,
            guild_id,
        ))
        db.commit()

        adjusted = max(0, int(math.ceil(scheduled_at - now_ts)))
        if _debug_enabled(config):
            logger.info(
                "[GUILD-PACING] reserve guild=%s policy=%s "
                "reason=%s requested=%ss adjusted=%ss gap=%ss",
                guild_id,
                policy,
                reason,
                original_delay,
                adjusted,
                gap,
            )
        return adjusted
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "[GUILD-PACING] reservation failed guild=%s "
            "policy=%s reason=%s",
            guild_id,
            policy,
            reason,
            exc_info=True,
        )
        return original_delay
    finally:
        cursor.close()
