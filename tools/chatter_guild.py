"""Guild chat event handlers.

Python owns guild chat history writes. C++ only queues events
and delivery rows are sent through PlayerbotAI::SayToGuild.
"""

import logging
import random
import re

from chatter_shared import (
    call_llm,
    cleanup_message,
    strip_speaker_prefix,
    get_chatter_mode,
    get_class_name,
    get_race_name,
    get_zone_flavor,
    get_zone_name,
    parse_extra_data,
    calculate_dynamic_delay,
    parse_single_response,
)
from chatter_db import (
    get_bot_active_quests,
    get_guild_chat_history,
    get_guild_info,
    insert_chat_message,
    mark_event,
    query_online_guild_bots,
    query_online_guild_players,
    store_guild_chat,
)
from chatter_group_state import (
    check_or_create_bot_identity,
)
from chatter_memory import (
    get_bot_memories,
    sanitize_memory_for_prompt,
)
from chatter_guild_prompts import (
    build_guild_message_prompt,
)
from chatter_guild_topics import (
    category_for_event,
    choose_guild_topic,
)

logger = logging.getLogger(__name__)

_history_limit = 20
_welcome_reply_min = 1
_welcome_reply_max = 3
_conversation_chance = 20
_max_conversation_messages = 3
_conversation_min_gap_seconds = 12
_conversation_max_gap_seconds = 22
_motd_context_chance = 2
_short_line_chance = 60
_player_login_greeting_min = 1
_player_login_greeting_max = 3


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def init_guild_config(config):
    """Initialize module-level guild config."""
    global _history_limit, _welcome_reply_min
    global _welcome_reply_max, _conversation_chance
    global _max_conversation_messages
    global _conversation_min_gap_seconds
    global _conversation_max_gap_seconds
    global _motd_context_chance
    global _short_line_chance
    global _player_login_greeting_min
    global _player_login_greeting_max

    _history_limit = max(1, min(_safe_int(
        config.get('LLMChatter.GuildChat.HistoryLimit', 20),
        20,
    ), 50))
    _welcome_reply_min = max(0, min(_safe_int(
        config.get('LLMChatter.GuildChat.WelcomeReplyMin', 1),
        1,
    ), 10))
    _welcome_reply_max = max(0, min(_safe_int(
        config.get('LLMChatter.GuildChat.WelcomeReplyMax', 3),
        3,
    ), 10))
    if _welcome_reply_min > _welcome_reply_max:
        _welcome_reply_min = _welcome_reply_max
    _conversation_chance = max(0, min(_safe_int(
        config.get('LLMChatter.GuildChat.ConversationChance', 20),
        20,
    ), 100))
    _max_conversation_messages = max(2, min(_safe_int(
        config.get('LLMChatter.GuildChat.MaxConversationMessages', 3),
        3,
    ), 6))
    _conversation_min_gap_seconds = max(3, min(_safe_int(
        config.get(
            'LLMChatter.GuildChat.ConversationMinGapSeconds', 12
        ),
        12,
    ), 60))
    _conversation_max_gap_seconds = max(3, min(_safe_int(
        config.get(
            'LLMChatter.GuildChat.ConversationMaxGapSeconds', 22
        ),
        22,
    ), 90))
    if _conversation_max_gap_seconds < _conversation_min_gap_seconds:
        _conversation_max_gap_seconds = _conversation_min_gap_seconds
    _motd_context_chance = max(0, min(_safe_int(
        config.get('LLMChatter.GuildChat.MotdContextChance', 2),
        2,
    ), 100))
    _short_line_chance = max(0, min(_safe_int(
        config.get('LLMChatter.GuildChat.ShortLineChance', 60),
        60,
    ), 100))
    _player_login_greeting_min = max(1, min(_safe_int(
        config.get(
            'LLMChatter.GuildChat.PlayerLoginGreetingMin', 1
        ),
        1,
    ), 3))
    _player_login_greeting_max = max(1, min(_safe_int(
        config.get(
            'LLMChatter.GuildChat.PlayerLoginGreetingMax', 3
        ),
        3,
    ), 3))
    if _player_login_greeting_min > _player_login_greeting_max:
        _player_login_greeting_min = _player_login_greeting_max


def _conversation_gap_seconds():
    if _conversation_max_gap_seconds <= _conversation_min_gap_seconds:
        return _conversation_min_gap_seconds
    return random.randint(
        _conversation_min_gap_seconds,
        _conversation_max_gap_seconds,
    )


def _parse_event_extra(event):
    return parse_extra_data(
        event.get('extra_data') or '',
        event_id=event.get('id'),
        event_type=event.get('event_type'),
    )


def _guild_enabled(config):
    return str(config.get(
        'LLMChatter.GuildChat.Enable', '0'
    )) == '1'


def _resolve_guild(db, extra):
    guild_id = _safe_int(extra.get('guild_id'), 0)
    if not guild_id:
        return None

    row = get_guild_info(db, guild_id) or {}
    return {
        'id': guild_id,
        'name': (
            row.get('name')
            or extra.get('guild_name')
            or 'the guild'
        ),
        'motd': (
            row.get('motd')
            or extra.get('guild_motd')
            or ''
        ),
        'info': (
            row.get('info')
            or extra.get('guild_info')
            or ''
        ),
    }


def _bot_from_extra(extra, prefix='bot'):
    guid = _safe_int(extra.get(f'{prefix}_guid'), 0)
    if not guid:
        return None

    class_id = _safe_int(extra.get(f'{prefix}_class'), 0)
    race_id = _safe_int(extra.get(f'{prefix}_race'), 0)
    zone_id = _safe_int(extra.get(f'{prefix}_zone_id'), 0)
    return {
        'guid': guid,
        'name': (
            extra.get(f'{prefix}_name')
            or 'Unknown bot'
        ),
        'class_id': class_id,
        'race_id': race_id,
        'class': (
            extra.get(f'{prefix}_class_name')
            or get_class_name(class_id)
        ),
        'race': (
            extra.get(f'{prefix}_race_name')
            or get_race_name(race_id)
        ),
        'level': _safe_int(
            extra.get(f'{prefix}_level'), 0
        ),
        'gender': _safe_int(
            extra.get(f'{prefix}_gender'), 0
        ),
        'zone_id': zone_id,
        'map_id': _safe_int(
            extra.get(f'{prefix}_map_id'), 0
        ),
        'zone_name': (
            extra.get(f'{prefix}_zone_name')
            or get_zone_name(zone_id)
            or 'Unknown Zone'
        ),
        'rank_id': _safe_int(
            extra.get(f'{prefix}_rank_id'), 0
        ),
        'rank_name': (
            extra.get(f'{prefix}_rank_name') or ''
        ),
    }


def _merge_bot_row(row, fallback=None):
    fallback = fallback or {}
    zone_id = _safe_int(
        row.get('zone_id'), fallback.get('zone_id', 0)
    )
    return {
        'guid': _safe_int(row.get('guid'), fallback.get('guid', 0)),
        'name': row.get('name') or fallback.get('name') or 'Unknown bot',
        'class_id': _safe_int(
            row.get('class_id'), fallback.get('class_id', 0)
        ),
        'race_id': _safe_int(
            row.get('race_id'), fallback.get('race_id', 0)
        ),
        'class': row.get('class') or fallback.get('class') or 'Adventurer',
        'race': row.get('race') or fallback.get('race') or 'Unknown',
        'level': _safe_int(row.get('level'), fallback.get('level', 0)),
        'gender': _safe_int(row.get('gender'), fallback.get('gender', 0)),
        'zone_id': zone_id,
        'map_id': _safe_int(row.get('map_id'), fallback.get('map_id', 0)),
        'zone_name': get_zone_name(zone_id) or fallback.get(
            'zone_name', 'Unknown Zone'
        ),
        'rank_id': _safe_int(
            row.get('rank_id'), fallback.get('rank_id', 0)
        ),
        'rank_name': row.get('rank_name') or fallback.get(
            'rank_name', ''
        ),
    }


def _attach_identity(db, config, bot):
    identity = check_or_create_bot_identity(
        db, config, bot['guid'], bot['name']
    )
    if identity:
        traits = [
            identity.get('trait1'),
            identity.get('trait2'),
            identity.get('trait3'),
        ]
        bot['traits'] = [t for t in traits if t]
        bot['role'] = identity.get('role')
        bot['tone'] = identity.get('tone')
        bot['backstory'] = identity.get('backstory')
    else:
        bot['traits'] = []
    return bot


def _format_history(history):
    if not history:
        return ''
    lines = []
    for row in history:
        speaker = row.get('speaker_name') or 'Unknown'
        lines.append(f"  {speaker}: {row.get('message') or ''}")
    return "Recent guild chat:\n" + '\n'.join(lines)


def _recent_categories(history):
    return [
        row.get('topic_category')
        for row in history
        if row.get('topic_category')
    ]


def _format_roster(bots, players):
    def _member_line(member, is_bot):
        class_name = (
            member.get('class')
            or get_class_name(_safe_int(member.get('class_id'), 0))
        )
        race_name = (
            member.get('race')
            or get_race_name(_safe_int(member.get('race_id'), 0))
        )
        zone_name = (
            member.get('zone_name')
            or get_zone_name(_safe_int(member.get('zone_id'), 0))
            or 'Unknown Zone'
        )
        rank = member.get('rank_name') or 'Member'
        return (
            f"{member.get('name', 'Unknown')} "
            f"(level {member.get('level', 0)} {race_name} "
            f"{class_name}, rank {rank}, in {zone_name})"
        )

    parts = []
    if players:
        lines = '; '.join(
            _member_line(p, False) for p in players[:6]
        )
        parts.append(
            f"Selected online guildmates "
            f"({len(players)}): {lines}"
        )
    if bots:
        lines = '; '.join(
            _member_line(b, True) for b in bots[:8]
        )
        parts.append(
            f"Selected online guildmate speakers "
            f"({len(bots)}): {lines}"
        )
    return '\n'.join(parts)


def _format_audience_context(bots, players, speaker=None):
    bot_count = len(bots or [])
    player_count = len(players or [])
    speaker_name = (speaker or {}).get('name')
    other_bot_count = bot_count
    if speaker_name:
        other_bot_count = len([
            b for b in (bots or [])
            if b.get('name') != speaker_name
        ])

    player_names = [
        p.get('name', 'Unknown') for p in (players or [])[:4]
    ]
    bot_names = [
        b.get('name', 'Unknown') for b in (bots or [])[:6]
    ]
    if player_count == 1 and other_bot_count == 0:
        return (
            "Online guild audience: exactly one other guildmate "
            f"({player_names[0]}) and you. Avoid plural crowd "
            "phrases; make a direct line or a simple statement."
        )

    return (
        f"Online guild audience: {player_count} other "
        f"guildmate(s) [{', '.join(player_names) or 'none'}] "
        f"and {bot_count} guildmate speaker(s) "
        f"[{', '.join(bot_names) or 'none'}]."
    )


def _format_quests(quests):
    if not quests:
        return ''
    lines = []
    for quest in quests[:3]:
        status = 'ready to turn in' if _safe_int(
            quest.get('status'), 0
        ) == 1 else 'in progress'
        name = quest.get('quest_name') or 'a quest'
        desc = (
            quest.get('description')
            or quest.get('details')
            or ''
        )
        suffix = f" - {desc[:100]}" if desc else ''
        lines.append(f"  {name} ({status}){suffix}")
    return "Current tasks you are pursuing:\n" + '\n'.join(lines)


def _format_memories(memories):
    clean = [
        sanitize_memory_for_prompt(memory)
        for memory in memories
    ]
    clean = [m for m in clean if m]
    if not clean:
        return ''
    return "Relevant past memories:\n" + '\n'.join(
        f"  - {memory}" for memory in clean[:3]
    )


def _format_player_context(extra, bot):
    player_name = extra.get('player_name') or 'the player'
    player_message = extra.get('player_message') or ''
    return (
        f"{player_name} wrote in guild chat: "
        f"\"{player_message}\"\n"
        "Guild chat is remote. Do not claim to see the guildmate "
        "or name locations unless the prompt gives location context."
    )


def _format_event_details(extra, event_kind):
    details = []
    if event_kind == 'bot_level_up':
        details.append(
            f"Level-up: {extra.get('bot_name')} reached "
            f"level {extra.get('new_level')}."
        )
    elif event_kind == 'bot_achievement':
        details.append(
            f"Achievement earned: "
            f"{extra.get('achievement_name', 'unknown')}."
        )
    elif event_kind == 'motd_changed':
        details.append(
            f"New MOTD: {extra.get('new_motd', '')[:180]}"
        )
    elif event_kind == 'info_changed':
        details.append(
            f"Updated guild info: "
            f"{extra.get('new_info', '')[:180]}"
        )
    elif event_kind in ('member_online', 'player_login'):
        name = extra.get('player_name') or 'a guildmate'
        details.append(
            f"Guildmate returned: {name}. Greet them warmly "
            "in character. Do not mention logging in, online "
            "status, the client, or the server."
        )
    elif event_kind.startswith('bank_'):
        item = extra.get('item_name')
        amount = extra.get('amount')
        if item:
            details.append(f"Guild bank item: {item}.")
        if amount:
            details.append(
                f"Guild bank money amount in copper: {amount}."
            )
    elif event_kind.startswith('member_'):
        actor = extra.get('actor_name') or 'Someone'
        target = extra.get('target_name') or 'a guildmate'
        rank = extra.get('new_rank_name') or ''
        text = f"Guild roster event: {actor} -> {target}."
        if rank:
            text += f" Rank: {rank}."
        details.append(text)
    if extra.get('motd_focus'):
        details.append('This login line may reference the guild MOTD.')
    return '\n'.join(details)


def _choose_bot_from_roster(db, guild_id, extra, preferred=None):
    cursor = db.cursor(dictionary=True)
    exclude = []
    if preferred:
        exclude.append(preferred.get('guid'))
    bots = query_online_guild_bots(
        cursor, guild_id, exclude_guids=[], limit=20
    )
    if preferred:
        for row in bots:
            if _safe_int(row.get('guid'), 0) == preferred.get('guid'):
                return _merge_bot_row(row, preferred), bots
        return preferred, bots

    player_message = (extra.get('player_message') or '').lower()
    for row in bots:
        name = (row.get('name') or '').lower()
        if name and re.search(
            r'\b' + re.escape(name) + r'\b',
            player_message,
        ):
            return _merge_bot_row(row), bots

    if not bots:
        return None, []
    return _merge_bot_row(random.choice(bots)), bots


def _should_use_conversation(bot_count):
    return (
        bot_count >= 2
        and _conversation_chance > 0
        and random.randint(1, 100) <= _conversation_chance
    )


def _select_followup_bot(db, guild_id, exclude_guids):
    cursor = db.cursor(dictionary=True)
    rows = query_online_guild_bots(
        cursor, guild_id,
        exclude_guids=exclude_guids,
        limit=12,
    )
    if not rows:
        return None
    return _merge_bot_row(random.choice(rows))


def _conversation_instruction(selected_bots, players):
    names = ', '.join(
        bot.get('name', 'Unknown') for bot in selected_bots
    )
    player_names = ', '.join(
        p.get('name', 'Unknown') for p in players[:4]
    )
    return (
        f"Selected guildmate speakers for this exchange: {names}. "
        "Only those guildmates may write generated lines. "
        f"Other online guildmates listening: {player_names or 'none'}."
    )


def _generate_line(
    db, client, config, event, guild, bot,
    event_kind, topic, sequence=0,
    delay_seconds=None, player_text='',
    memory_text='', previous_line='',
    audience_text='',
    extra_text='',
    delivery_policy=None,
):
    event_id = event['id']
    event_type = event.get('event_type', 'guild_chat')
    guild_id = guild['id']

    history = get_guild_chat_history(
        db, guild_id, _history_limit
    )
    cursor = db.cursor(dictionary=True)
    roster_bots = query_online_guild_bots(
        cursor, guild_id, limit=12
    )
    roster_players = query_online_guild_players(
        cursor, guild_id, limit=8
    )
    quests = get_bot_active_quests(db, bot['guid'])
    mode = get_chatter_mode(config)

    prompt = build_guild_message_prompt(
        bot=bot,
        guild=guild,
        event_type=event_type,
        event_kind=event_kind,
        mode=mode,
        topic=topic,
        history_text=_format_history(history),
        memory_text=memory_text,
        quest_text=_format_quests(quests),
        roster_text=_format_roster(
            roster_bots, roster_players
        ),
        audience_text=(
            audience_text
            or _format_audience_context(
                roster_bots, roster_players, bot
            )
        ),
        zone_flavor_text=get_zone_flavor(
            _safe_int(bot.get('zone_id'), 0)
        ) or '',
        player_text=player_text,
        extra_text=extra_text,
        previous_line=previous_line,
        motd_context_chance=_motd_context_chance,
        short_line_chance=_short_line_chance,
    )

    response = call_llm(
        client, prompt, config,
        max_tokens_override=min(
            _safe_int(config.get('LLMChatter.MaxTokens'), 200),
            180,
        ),
        context=(
            f"guild:{event_id}:{event_kind}:"
            f"{bot['name']}"
        ),
        label='guild_chat',
        metadata={
            'guild_id': guild_id,
            'guild_name': guild.get('name'),
            'event_kind': event_kind,
            'topic_category': topic.get('category'),
        },
    )
    if not response:
        return None

    parsed = parse_single_response(response)
    msg = strip_speaker_prefix(
        parsed.get('message', ''), bot['name']
    )
    msg = cleanup_message(msg, action=None)
    if not msg:
        return None
    if len(msg) > 255:
        msg = msg[:252] + '...'

    if delay_seconds is None:
        delay_seconds = calculate_dynamic_delay(
            len(msg), config,
            responsive=(
                event_type in (
                    'guild_player_msg',
                    'guild_member_joined',
                )
            ),
        )

    insert_chat_message(
        db,
        bot['guid'],
        bot['name'],
        msg,
        channel='guild',
        delay_seconds=delay_seconds,
        event_id=event_id,
        sequence=sequence,
        emote=None,
        player_guid=event.get('subject_guid'),
        config=config,
        guild_id=guild_id,
        delivery_policy=delivery_policy,
        delivery_reason=event_type,
    )
    store_guild_chat(
        db,
        guild_id,
        bot['name'],
        True,
        msg,
        speaker_guid=bot['guid'],
        event_type=event_type,
        topic_category=topic.get('category'),
        history_limit=_history_limit,
    )
    return msg


def process_guild_player_msg_event(db, client, config, event):
    """React to a real player's guild chat line."""
    event_id = event['id']
    if not _guild_enabled(config):
        mark_event(db, event_id, 'skipped')
        return False

    extra = _parse_event_extra(event)
    guild = _resolve_guild(db, extra)
    if not guild:
        mark_event(db, event_id, 'skipped')
        return False

    player_guid = _safe_int(
        extra.get('player_guid') or event.get('subject_guid'),
        0,
    )
    player_name = (
        extra.get('player_name')
        or event.get('subject_name')
        or 'Player'
    )
    player_message = extra.get('player_message') or ''
    if player_message:
        store_guild_chat(
            db, guild['id'], player_name, False,
            player_message,
            speaker_guid=player_guid or None,
            event_type='guild_player_msg',
            topic_category='player_reply',
            history_limit=_history_limit,
        )

    bot, roster_bots = _choose_bot_from_roster(
        db, guild['id'], extra
    )
    if not bot:
        mark_event(db, event_id, 'skipped')
        return False
    bot = _attach_identity(db, config, bot)

    followup_bot = None
    selected_instruction = ''
    if _should_use_conversation(len(roster_bots)):
        followup_bot = _select_followup_bot(
            db, guild['id'], [bot['guid']]
        )
        if followup_bot:
            followup_bot = _attach_identity(
                db, config, followup_bot
            )
            cursor = db.cursor(dictionary=True)
            players = query_online_guild_players(
                cursor, guild['id'], limit=8
            )
            selected_instruction = _conversation_instruction(
                [bot, followup_bot], players
            )

    memories = []
    if player_guid:
        memories = get_bot_memories(
            db, bot['guid'], player_guid,
            count=2,
            exclude_first_meeting=True,
            mark_used=False,
        )
    history = get_guild_chat_history(
        db, guild['id'], _history_limit
    )
    preferred = 'memory' if memories else None
    topic = choose_guild_topic(
        _recent_categories(history),
        preferred_category=preferred,
    )
    delay1 = min(
        calculate_dynamic_delay(
            len(player_message), config,
            responsive=True,
        ),
        5,
    )
    msg = _generate_line(
        db, client, config, event, guild, bot,
        'player_reply', topic, sequence=0,
        delay_seconds=delay1,
        player_text=_format_player_context(extra, bot),
        memory_text=_format_memories(memories),
        extra_text=selected_instruction,
    )
    if not msg:
        mark_event(db, event_id, 'skipped')
        return False

    if followup_bot:
        followup_topic = choose_guild_topic(
            _recent_categories(
                get_guild_chat_history(
                    db, guild['id'], _history_limit
                )
            )
        )
        _generate_line(
            db, client, config, event, guild,
            followup_bot, 'player_reply_followup',
            followup_topic, sequence=1,
            delay_seconds=delay1 + _conversation_gap_seconds(),
            player_text=_format_player_context(
                extra, followup_bot
            ),
            previous_line=msg,
            extra_text=(
                selected_instruction + " Continue the guild "
                "exchange naturally; do not force a direct "
                "answer if a simple follow-up fits better."
            ),
        )
    mark_event(db, event_id, 'completed')
    return True


def process_guild_member_joined_event(db, client, config, event):
    """Have a newly added guild bot greet the guild."""
    event_id = event['id']
    if not _guild_enabled(config):
        mark_event(db, event_id, 'skipped')
        return False

    extra = _parse_event_extra(event)
    guild = _resolve_guild(db, extra)
    new_bot = _bot_from_extra(extra, 'bot')
    if not guild or not new_bot:
        mark_event(db, event_id, 'skipped')
        return False

    preferred, roster_bots = _choose_bot_from_roster(
        db, guild['id'], extra, preferred=new_bot
    )
    new_bot = _attach_identity(
        db, config, preferred or new_bot
    )
    topic = choose_guild_topic(
        preferred_category='recruit'
    )
    first_line = _generate_line(
        db, client, config, event, guild, new_bot,
        'new_member_greeting', topic,
        sequence=0, delay_seconds=2,
        extra_text='You have just joined this guild.',
        delivery_policy='join_burst',
    )
    if not first_line:
        mark_event(db, event_id, 'skipped')
        return False

    min_replies = _safe_int(
        extra.get('welcome_reply_min'), _welcome_reply_min
    )
    max_replies = _safe_int(
        extra.get('welcome_reply_max'), _welcome_reply_max
    )
    if min_replies > max_replies:
        min_replies = max_replies
    other_bots = [
        _merge_bot_row(row) for row in roster_bots
        if _safe_int(row.get('guid'), 0) != new_bot['guid']
    ]
    random.shuffle(other_bots)
    reply_count = min(
        len(other_bots),
        random.randint(min_replies, max_replies)
        if max_replies > 0 else 0,
    )

    delay = 5
    previous = first_line
    for index, bot in enumerate(other_bots[:reply_count], start=1):
        bot = _attach_identity(db, config, bot)
        reply_topic = choose_guild_topic(
            preferred_category='recruit'
        )
        line = _generate_line(
            db, client, config, event, guild, bot,
            'welcome_reply', reply_topic,
            sequence=index, delay_seconds=delay,
            previous_line=previous,
            extra_text=(
                f"Welcome {new_bot['name']} to the guild."
            ),
            delivery_policy='join_burst',
        )
        if line:
            previous = line
            delay += random.randint(3, 6)

    mark_event(db, event_id, 'completed')
    return True


def process_guild_bot_login_event(db, client, config, event):
    """Optional flavor line when a guild bot logs in."""
    event_id = event['id']
    if not _guild_enabled(config):
        mark_event(db, event_id, 'skipped')
        return False

    extra = _parse_event_extra(event)
    guild = _resolve_guild(db, extra)
    bot = _bot_from_extra(extra, 'bot')
    if not guild or not bot:
        mark_event(db, event_id, 'skipped')
        return False

    preferred, _ = _choose_bot_from_roster(
        db, guild['id'], extra, preferred=bot
    )
    bot = _attach_identity(db, config, preferred or bot)
    topic = choose_guild_topic(
        preferred_category=(
            'motd' if extra.get('motd_focus')
            else 'schedule'
        )
    )
    msg = _generate_line(
        db, client, config, event, guild, bot,
        'bot_login', topic,
        sequence=0,
        delay_seconds=random.randint(3, 8),
        extra_text=_format_event_details(extra, 'bot_login'),
    )
    if not msg:
        mark_event(db, event_id, 'skipped')
        return False
    mark_event(db, event_id, 'completed')
    return True


def _process_guild_player_login_event(
    db, client, config, event, guild, extra
):
    """Have online guild bots greet a real player after login."""
    event_id = event['id']
    cursor = db.cursor(dictionary=True)
    roster_bots = query_online_guild_bots(
        cursor, guild['id'], limit=20
    )
    if not roster_bots:
        mark_event(db, event_id, 'skipped')
        return False

    random.shuffle(roster_bots)
    max_count = min(
        _player_login_greeting_max,
        len(roster_bots),
    )
    min_count = min(_player_login_greeting_min, max_count)
    greeting_count = random.randint(min_count, max_count)
    selected_bots = [
        _attach_identity(db, config, _merge_bot_row(row))
        for row in roster_bots[:greeting_count]
    ]

    players = query_online_guild_players(
        cursor, guild['id'], limit=8
    )
    selected_instruction = _conversation_instruction(
        selected_bots, players
    ) if len(selected_bots) > 1 else ''

    history = get_guild_chat_history(
        db, guild['id'], _history_limit
    )
    topic = choose_guild_topic(
        _recent_categories(history),
        preferred_category=category_for_event(
            extra.get('event_kind')
        ),
    )
    event_kind = extra.get('event_kind') or 'member_online'
    extra_text = _format_event_details(extra, event_kind)
    if selected_instruction:
        extra_text = (
            extra_text + "\n" + selected_instruction
            + " These are separate quick greetings, not a formal "
              "conversation."
        )

    previous = ''
    delay = random.randint(3, 8)
    generated = 0
    for index, bot in enumerate(selected_bots):
        line = _generate_line(
            db, client, config, event, guild, bot,
            'member_online', topic,
            sequence=index,
            delay_seconds=delay,
            previous_line=previous,
            extra_text=extra_text,
        )
        if line:
            previous = line
            generated += 1
            delay += _conversation_gap_seconds()

    mark_event(
        db, event_id,
        'completed' if generated else 'skipped'
    )
    return bool(generated)


def process_guild_social_event(db, client, config, event):
    """React to lower-frequency guild events."""
    event_id = event['id']
    if not _guild_enabled(config):
        mark_event(db, event_id, 'skipped')
        return False

    extra = _parse_event_extra(event)
    guild = _resolve_guild(db, extra)
    if not guild:
        mark_event(db, event_id, 'skipped')
        return False

    event_kind = extra.get('event_kind') or 'guild_event'
    if event_kind in ('member_online', 'player_login'):
        return _process_guild_player_login_event(
            db, client, config, event, guild, extra
        )

    bot = None
    if event_kind in ('bot_level_up', 'bot_achievement'):
        bot = _bot_from_extra(extra, 'bot')
    bot, _ = _choose_bot_from_roster(
        db, guild['id'], extra, preferred=bot
    )
    if not bot:
        mark_event(db, event_id, 'skipped')
        return False
    bot = _attach_identity(db, config, bot)

    history = get_guild_chat_history(
        db, guild['id'], _history_limit
    )
    category = category_for_event(event_kind)
    topic = choose_guild_topic(
        _recent_categories(history),
        preferred_category=category,
    )
    msg = _generate_line(
        db, client, config, event, guild, bot,
        event_kind, topic,
        sequence=0,
        delay_seconds=random.randint(2, 8),
        extra_text=_format_event_details(
            extra, event_kind
        ),
    )
    if not msg:
        mark_event(db, event_id, 'skipped')
        return False
    mark_event(db, event_id, 'completed')
    return True


def process_guild_ambient_event(db, client, config, event):
    """Process optional ambient guild chatter events."""
    event_id = event['id']
    if not _guild_enabled(config):
        mark_event(db, event_id, 'skipped')
        return False

    extra = _parse_event_extra(event)
    guild = _resolve_guild(db, extra)
    if not guild:
        mark_event(db, event_id, 'skipped')
        return False

    bot, roster_bots = _choose_bot_from_roster(
        db, guild['id'], extra
    )
    if not bot:
        mark_event(db, event_id, 'skipped')
        return False
    bot = _attach_identity(db, config, bot)

    cursor = db.cursor(dictionary=True)
    players = query_online_guild_players(
        cursor, guild['id'], limit=8
    )
    selected_bots = [bot]
    if _should_use_conversation(len(roster_bots)):
        candidates = [
            _merge_bot_row(row) for row in roster_bots
            if _safe_int(row.get('guid'), 0) != bot['guid']
        ]
        random.shuffle(candidates)
        message_count = random.randint(
            2,
            min(
                _max_conversation_messages,
                len(candidates) + 1,
            ),
        )
        for candidate in candidates[:message_count - 1]:
            selected_bots.append(
                _attach_identity(db, config, candidate)
            )

    selected_instruction = ''
    if len(selected_bots) > 1:
        selected_instruction = _conversation_instruction(
            selected_bots, players
        )

    history = get_guild_chat_history(
        db, guild['id'], _history_limit
    )
    topic = choose_guild_topic(
        _recent_categories(history)
    )
    first_delay = random.randint(3, 10)
    msg = _generate_line(
        db, client, config, event, guild, bot,
        'ambient', topic,
        sequence=0, delay_seconds=first_delay,
        extra_text=(
            selected_instruction
            + (
                " Start a short guild-chat exchange."
                if selected_instruction else ""
            )
        ),
    )
    if not msg:
        mark_event(db, event_id, 'skipped')
        return False

    previous = msg
    delay = first_delay + _conversation_gap_seconds()
    for index, speaker in enumerate(selected_bots[1:], start=1):
        followup_topic = choose_guild_topic(
            _recent_categories(
                get_guild_chat_history(
                    db, guild['id'], _history_limit
                )
            )
        )
        line = _generate_line(
            db, client, config, event, guild, speaker,
            'ambient_followup', followup_topic,
            sequence=index, delay_seconds=delay,
            previous_line=previous,
            extra_text=(
                selected_instruction + " Continue the "
                "guild-chat exchange with one natural line."
            ),
        )
        if line:
            previous = line
            delay += _conversation_gap_seconds()

    mark_event(db, event_id, 'completed')
    return True
