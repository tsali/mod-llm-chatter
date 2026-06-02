"""Prompt builders for guild chat."""

import random

from chatter_shared import (
    append_json_instruction,
    build_race_class_context,
    build_bot_identity_with_level,
)
from chatter_constants import RACE_SPEECH_PROFILES
from chatter_prompts import (
    build_environmental_context_lines,
    maybe_get_creative_twist,
    pick_random_mood,
    pick_random_tone,
)


def _join_lines(lines):
    return '\n'.join([line for line in lines if line])


LOCATION_TOPIC_CATEGORIES = {
    'zone_update',
    'travel',
    'local_color',
    'weather_report',
    'road_report',
    'npc_observation',
    'creature_observation',
    'flight_path',
    'map_confusion',
    'exploration',
    'capital_city',
    'inn_life',
    'hearthstone',
    'rare_spawn_story',
    'death_recovery',
}

NON_LOCATION_LINE_FOCUS = [
    'Answer through class, race, or personality; do not name your zone.',
    'Make it a guildmate-to-guildmate remark, not a travel report.',
    'Use rank, guild identity, or practical advice; avoid zone names.',
    'Use the player message as the anchor; keep location out of it.',
    'Make a short personal statement with no city or zone name.',
    'Lean on mood, tone, or backstory without mentioning where you are.',
]

LOCATION_LINE_FOCUS = [
    'Location may matter here, but only mention it if it improves the line.',
    'Use a grounded local detail, not a full travel report.',
    'Mention your surroundings briefly, then move on.',
    'Use your current place as flavor, not as the whole message.',
]

LINE_SHAPES = {
    'quick': (
        'Very short: 25-70 characters. One casual guild-chat thought, '
        'plain wording, no metaphor, not a polished speech.'
    ),
    'medium': (
        'Medium: 70-115 characters. One grounded sentence, relaxed and '
        'easy to read.'
    ),
    'full': (
        'Full: 105-150 characters. Use only when the topic benefits '
        'from a little color.'
    ),
}


def _choose_line_shape(short_line_chance: int) -> str:
    short_line_chance = max(0, min(int(short_line_chance or 0), 100))
    roll = random.randint(1, 100)
    if roll <= short_line_chance:
        return LINE_SHAPES['quick']
    remaining = max(0, 100 - short_line_chance)
    medium_chance = int(remaining * 0.7)
    if roll <= short_line_chance + medium_chance:
        return LINE_SHAPES['medium']
    return LINE_SHAPES['full']


def build_guild_message_prompt(
    *,
    bot: dict,
    guild: dict,
    event_type: str,
    event_kind: str,
    mode: str,
    topic: dict,
    history_text: str = '',
    memory_text: str = '',
    quest_text: str = '',
    roster_text: str = '',
    audience_text: str = '',
    zone_flavor_text: str = '',
    player_text: str = '',
    extra_text: str = '',
    previous_line: str = '',
    motd_context_chance: int = 2,
    short_line_chance: int = 60,
):
    """Build a single guild chat response prompt."""
    bot_name = bot.get('name', 'Unknown')
    bot_race = bot.get('race', 'Unknown')
    bot_class = bot.get('class', 'Adventurer')
    bot_level = int(bot.get('level') or 0)
    bot_gender = int(bot.get('gender') or 0)
    rank_name = bot.get('rank_name') or 'Member'
    zone_name = bot.get('zone_name') or 'Unknown Zone'
    effective_mode = 'roleplay'
    traits = bot.get('traits') or []
    trait_text = ', '.join(traits) if traits else 'grounded'
    identity_tone = (bot.get('tone') or '').strip()
    moment_tone = pick_random_tone(effective_mode)
    mood = pick_random_mood(effective_mode)
    twist = maybe_get_creative_twist(
        chance=0.5, mode=effective_mode
    )
    backstory = (bot.get('backstory') or '').strip()
    guild_name = guild.get('name') or guild.get('guild_name') or 'the guild'
    motd = (guild.get('motd') or guild.get('guild_motd') or '').strip()
    info = (guild.get('info') or guild.get('guild_info') or '').strip()
    topic_category = topic.get('category') or ''
    player_lower = (player_text or '').lower()
    zone_lower = zone_name.lower()
    player_mentions_place = any(
        word in player_lower
        for word in (
            'where', 'zone', 'city', 'town', 'road',
            'weather', 'place', 'area',
        )
    ) or (
        zone_lower
        and zone_lower != 'unknown zone'
        and zone_lower in player_lower
    )
    location_focus = (
        topic_category in LOCATION_TOPIC_CATEGORIES
        or player_mentions_place
    )
    include_location_context = (
        location_focus or random.random() < 0.05
    )
    motd_focus = topic_category == 'motd' or event_kind in (
        'motd_changed',
        'info_changed',
    )
    include_motd_context = (
        bool(motd)
        and (
            motd_focus
            or random.randint(1, 100) <= max(
                0,
                min(int(motd_context_chance or 0), 100),
            )
        )
    )
    line_focus = random.choice(
        LOCATION_LINE_FOCUS
        if include_location_context else NON_LOCATION_LINE_FOCUS
    )
    line_shape = _choose_line_shape(short_line_chance)
    include_zone_flavor = (
        bool(zone_flavor_text)
        and include_location_context
    )

    identity = build_bot_identity_with_level(
        bot_name, bot_race, bot_class, bot_level,
        gender=bot_gender,
    )
    race_context = build_race_class_context(
        bot_race, bot_class
    )
    profile = RACE_SPEECH_PROFILES.get(bot_race)
    race_flavor = ''
    if profile:
        words = profile.get('flavor_words') or []
        if words:
            race_flavor = ', '.join(
                random.sample(words, min(3, len(words)))
            )
    style = 'Speak fully in-character as a World of Warcraft guildmate.'

    env_lines = build_environmental_context_lines()
    context_lines = [
        identity,
        f"Guild: {guild_name}",
        f"Guild rank: {rank_name}",
        f"Your personality: {trait_text}",
        f"Your established tone: {identity_tone}"
        if identity_tone else '',
        f"Current tone: {moment_tone}",
        f"Current mood: {mood}",
        f"Scene angle: {twist}" if twist else '',
        f"Your backstory: {backstory[:220]}" if backstory else '',
        race_context,
        f"Race flavor words you might use: {race_flavor}"
        if race_flavor else '',
        f"Event type: {event_type}",
        f"Guild event/topic: {event_kind}",
        f"Topic direction: {topic.get('prompt', '')}",
        f"Line focus: {line_focus}",
        f"Line shape: {line_shape}",
    ]
    context_lines.extend(env_lines)
    if include_location_context:
        context_lines.append(
            f"Your current location: {zone_name}"
        )
    if include_zone_flavor:
        context_lines.append(
            f"Optional zone context if relevant: {zone_flavor_text}"
        )
    if include_motd_context:
        context_lines.append(f"Guild MOTD: {motd[:180]}")
    if info:
        context_lines.append(f"Guild info: {info[:180]}")
    if quest_text:
        context_lines.append(quest_text)
    if memory_text:
        context_lines.append(memory_text)
    if roster_text:
        context_lines.append(roster_text)
    if audience_text:
        context_lines.append(audience_text)
    if history_text:
        context_lines.append(history_text)
    if player_text:
        context_lines.append(player_text)
    if previous_line:
        context_lines.append(
            f"Previous guild line: {previous_line}"
        )
    if extra_text:
        context_lines.append(extra_text)

    prompt = (
        _join_lines(context_lines)
        + "\n\n"
        + f"{style}\n"
        + "Write exactly one message for /guild chat.\n"
        + "Rules:\n"
        + "- This is guild chat, not party, say, yell, or General.\n"
        + "- Stay in character. Do not mention AI, bots, prompts, "
          "LLMs, code, addons, the game client, UI, server, or "
          "roleplay mode.\n"
        + "- Call others guildmates or by name, never \"players\".\n"
        + "- Use singular wording when the supplied online audience "
          "is small. Do not say \"guys\", \"everyone\", \"all\", or "
          "\"we all\" unless multiple guildmates are actually online.\n"
        + "- Do not claim to see a guildmate unless your location "
          "matches theirs.\n"
        + "- If location context is present, it describes YOUR current "
          "location, not the other guildmate's location.\n"
        + "- Do not mention your current location unless the player "
          "asked about a place or the topic is clearly local, travel, "
          "weather, road, or surroundings. If no location context is "
          "present, do not invent or name a zone or city.\n"
        + "- Use one anchor: player message, quest, rank, class, race, "
          "memory, mood, or location. Use guild MOTD only when the "
          "context above includes Guild MOTD. Do not list several.\n"
        + "- Do not mention the guild MOTD or message of the day unless "
          "the context above includes Guild MOTD.\n"
        + "- Never offer, request, or imply an invite, group, queue, "
          "summon, portal, run, carry, meet-up, or coordinated activity. "
          "You cannot control bot actions from guild chat.\n"
        + "- You may ask for advice, directions, crafting info, or "
          "class tips, but not active assistance.\n"
        + "- Keep it natural, useful, and varied.\n"
        + "- Follow Line shape. Guild chat often has brief, casual "
          "remarks; do not make every line the same length.\n"
        + "- Do not aim for the hard limit. Short, imperfect guild "
          "chat is often more believable than a complete thought.\n"
        + "- Do not always use a metaphor or formal comparison. Some "
          "lines should sound plain and offhand.\n"
        + "- No emojis, no markdown, no quotes around the line.\n"
        + "- Do not use fake item, quest, or spell links.\n"
        + "- HARD LIMIT: 150 characters.\n"
    )
    return append_json_instruction(
        prompt,
        allow_action=False,
        skip_emote=True,
    )
