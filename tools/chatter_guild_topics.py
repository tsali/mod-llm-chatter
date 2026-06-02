"""Guild chat topic helpers.

Guild topics are global to the guild, not anchored to one
guildmate's current zone. A speaker may talk about their own
location, current tasks, practical guild needs, or social guild
events.
"""

import random


GUILD_TOPIC_POOL = [
    {
        'category': 'ask_help',
        'prompt': (
            'Ask for advice, directions, class tips, crafting info, '
            'or how others handled a quest, without asking anyone to '
            'group, summon, queue, or come help.'
        ),
    },
    {
        'category': 'offer_help',
        'prompt': (
            'Offer useful guild-chat knowledge such as crafting info, '
            'class tips, spare materials, or route advice without '
            'promising to join, invite, summon, or travel.'
        ),
    },
    {
        'category': 'quest_progress',
        'prompt': (
            'Mention a task, errand, hunt, or problem you are pursuing, '
            'without pretending others are nearby.'
        ),
    },
    {
        'category': 'zone_update',
        'prompt': (
            'Make a short update about your own zone, route, mobs, '
            'weather, inn, flight path, or nearby danger.'
        ),
    },
    {
        'category': 'travel',
        'prompt': (
            'Talk about moving between hubs, hearthstone plans, boats, '
            'zeppelins, flight masters, or repair stops.'
        ),
    },
    {
        'category': 'guild_bank',
        'prompt': (
            'Bring up guild bank supplies, repairs, reagents, potions, '
            'or useful drops in a practical way.'
        ),
    },
    {
        'category': 'profession',
        'prompt': (
            'Talk about crafting, enchants, gems, bags, food, flasks, '
            'gathering materials, or useful recipes.'
        ),
    },
    {
        'category': 'dungeon',
        'prompt': (
            'Mention a dungeon, heroic, attunement, badge run, or boss '
            'as a past experience, goal, warning, or story, not as a '
            'plan to form a group.'
        ),
    },
    {
        'category': 'pvp',
        'prompt': (
            'Mention battlegrounds, world PvP, Wintergrasp, or PvP '
            'lessons as observations, stories, or class thoughts, not '
            'as a request to queue or team up.'
        ),
    },
    {
        'category': 'congrats',
        'prompt': (
            'React to a guildmate achievement, level, loot, promotion, '
            'or progress with a grounded guild-chat line.'
        ),
    },
    {
        'category': 'motd',
        'prompt': (
            'React to the guild MOTD, guild info, raid plans, or guild '
            'rules without sounding formal.'
        ),
    },
    {
        'category': 'roleplay',
        'prompt': (
            'Add a small in-character flavor line based on your race, '
            'class, rank, or current location.'
        ),
    },
    {
        'category': 'memory',
        'prompt': (
            'Reminisce about a previous grouped moment with the player '
            'if a relevant memory is supplied.'
        ),
    },
    {
        'category': 'idle_banter',
        'prompt': (
            'Make casual guild banter: short, useful, or lightly funny, '
            'as a guildmate would.'
        ),
    },
    {
        'category': 'strategy',
        'prompt': (
            'Mention a class tactic, pull plan, training choice, threat, '
            'mana, crowd control, or survival tip.'
        ),
    },
    {
        'category': 'economy',
        'prompt': (
            'Mention auction prices, saving gold, repairs, mount money, '
            'or a useful farm.'
        ),
    },
    {
        'category': 'recruit',
        'prompt': (
            'Welcome recruits, ask about their class or path ahead, '
            'or mention guild rank and belonging naturally.'
        ),
    },
    {
        'category': 'player_login',
        'event_only': True,
        'prompt': (
            'Greet a returning guildmate warmly and casually in guild '
            'chat, without mentioning login, online status, client, '
            'server, or interface.'
        ),
    },
    {
        'category': 'schedule',
        'prompt': (
            'Mention personal timing: logging soon, doing one more '
            'quest, taking a repair break, or checking the mailbox, '
            'without organizing future group activity.'
        ),
    },
    {
        'category': 'loot',
        'prompt': (
            'Talk about loot, upgrades, drops, reagents, or who could use '
            'an item without using fake item links.'
        ),
    },
    {
        'category': 'local_color',
        'prompt': (
            'Describe one grounded detail from your own surroundings, '
            'like a road, inn, camp, flight master, mobs, or guards.'
        ),
    },
    {
        'category': 'trainer_visit',
        'prompt': (
            'Mention checking a class trainer, learning a new spell, '
            'or realizing a trainer visit is overdue.'
        ),
    },
    {
        'category': 'talent_thought',
        'prompt': (
            'Make a short comment about training choices, combat habits, '
            'threat, mana, rage, energy, or class priorities.'
        ),
    },
    {
        'category': 'gear_maintenance',
        'prompt': (
            'Mention repairs, durability, sharpening stones, weightstones, '
            'ammo, reagents, poisons, or keeping gear ready.'
        ),
    },
    {
        'category': 'bag_space',
        'prompt': (
            'Talk about bag space, vendor trash, bank sorting, mailing '
            'materials, or deciding what to keep.'
        ),
    },
    {
        'category': 'auction_watch',
        'prompt': (
            'Mention watching auction prices, undercuts, buying supplies, '
            'or saving gold without making a trade offer.'
        ),
    },
    {
        'category': 'mount_progress',
        'prompt': (
            'Mention saving for riding skill, mount money, repair costs, '
            'or the relief of finally moving faster.'
        ),
    },
    {
        'category': 'hearthstone',
        'prompt': (
            'Talk about hearthstone cooldown, setting an inn, returning '
            'to town, or choosing a convenient home point.'
        ),
    },
    {
        'category': 'flight_path',
        'prompt': (
            'Mention finding a flight master, taking a long flight, '
            'missing a route, or liking a scenic flight path.'
        ),
    },
    {
        'category': 'vendor_stop',
        'prompt': (
            'Mention selling junk, buying reagents, restocking food, '
            'or making a practical town stop.'
        ),
    },
    {
        'category': 'reputation',
        'prompt': (
            'Talk about reputation gains, tabards, factions, quartermasters, '
            'or slowly working toward a reward.'
        ),
    },
    {
        'category': 'rested_xp',
        'prompt': (
            'Mention feeling well-rested from an inn, taking a sensible '
            'rest, or trying to make good use of daylight.'
        ),
    },
    {
        'category': 'quest_clue',
        'prompt': (
            'Ask for or share a vague quest hint, mob location clue, '
            'drop-rate complaint, or objective observation.'
        ),
    },
    {
        'category': 'map_confusion',
        'prompt': (
            'Admit being turned around, misreading the map, following '
            'the wrong road, or finding a landmark again.'
        ),
    },
    {
        'category': 'hard_mob_story',
        'prompt': (
            'Mention a dangerous pull, annoying caster, patrol, elite, '
            'or named mob as a cautionary story.'
        ),
    },
    {
        'category': 'death_recovery',
        'prompt': (
            'Make a brief comment about a corpse run, a close call, '
            'repair bills, or surviving with almost no health.'
        ),
    },
    {
        'category': 'rare_spawn_story',
        'prompt': (
            'Mention seeing, missing, or hearing about a rare spawn, '
            'without telling anyone to come to it.'
        ),
    },
    {
        'category': 'exploration',
        'prompt': (
            'Talk about discovering a new area, finding a tucked-away path, '
            'or enjoying a zone view.'
        ),
    },
    {
        'category': 'capital_city',
        'prompt': (
            'Mention city errands, trade district noise, auction house '
            'crowds, trainers, banks, or guards.'
        ),
    },
    {
        'category': 'inn_life',
        'prompt': (
            'Make a small comment about inns, hearths, food, drink, '
            'resting, or the atmosphere of a town.'
        ),
    },
    {
        'category': 'cooking',
        'prompt': (
            'Mention cooking, food buffs, recipes, spices, fishing catches, '
            'or running low on meals.'
        ),
    },
    {
        'category': 'fishing',
        'prompt': (
            'Talk about fishing spots, junk catches, pools, lures, '
            'or the patience needed for fishing.'
        ),
    },
    {
        'category': 'first_aid',
        'prompt': (
            'Mention bandages, cloth supply, first aid skill, or being '
            'glad to have a bandage after a rough fight.'
        ),
    },
    {
        'category': 'pet_minion',
        'prompt': (
            'Mention a hunter pet, warlock minion, pet food, loyalty, '
            'or a class companion behaving memorably.'
        ),
    },
    {
        'category': 'class_flavor',
        'prompt': (
            'Make a class-flavored remark grounded in abilities, resources, '
            'armor type, or combat role.'
        ),
    },
    {
        'category': 'race_flavor',
        'prompt': (
            'Make a small race-flavored remark about heritage, hometown, '
            'customs, or worldview without sounding formal.'
        ),
    },
    {
        'category': 'faction_flavor',
        'prompt': (
            'Mention faction tension, guards, banners, contested roads, '
            'or seeing the other faction nearby.'
        ),
    },
    {
        'category': 'holiday',
        'prompt': (
            'Mention a seasonal event, decorations, holiday food, costumes, '
            'or festival errands in a casual way.'
        ),
    },
    {
        'category': 'achievement_goal',
        'prompt': (
            'Mention slowly working toward a title, mount, exploration '
            'goal, collection milestone, or personal mark of pride.'
        ),
    },
    {
        'category': 'loot_luck',
        'prompt': (
            'Talk about lucky drops, dry streaks, vendor greens, upgrades, '
            'or wondering if a drop even exists.'
        ),
    },
    {
        'category': 'profession_progress',
        'prompt': (
            'Mention skilling a profession, needing more practice crafts, '
            'or planning what recipe to learn next.'
        ),
    },
    {
        'category': 'guild_identity',
        'prompt': (
            'Say something that makes the guild feel lived-in: ranks, '
            'tabard pride, familiar names, or shared guild habits.'
        ),
    },
    {
        'category': 'bank_tidy',
        'prompt': (
            'Mention keeping the guild bank tidy, useful stacks, empty '
            'slots, or avoiding clutter.'
        ),
    },
    {
        'category': 'consumables',
        'prompt': (
            'Mention potions, elixirs, scrolls, food buffs, weapon buffs, '
            'or remembering consumables before trouble.'
        ),
    },
    {
        'category': 'weather_report',
        'prompt': (
            'Mention the weather where you are, mud, snow, rain, heat, '
            'fog, or how the zone feels today.'
        ),
    },
    {
        'category': 'road_report',
        'prompt': (
            'Mention a road, bridge, tunnel, pass, crossroads, patrol, '
            'or travel route from your own perspective.'
        ),
    },
    {
        'category': 'npc_observation',
        'prompt': (
            'Comment on a memorable NPC, vendor, guard, quest giver, '
            'trainer, or flight master near you.'
        ),
    },
    {
        'category': 'creature_observation',
        'prompt': (
            'Mention local beasts, undead, elementals, demons, murlocs, '
            'or other creatures in your current area.'
        ),
    },
    {
        'category': 'resource_management',
        'prompt': (
            'Talk about mana, rage, energy, ammo, shards, combo points, '
            'timing abilities, or pacing between fights.'
        ),
    },
    {
        'category': 'ui_habit',
        'prompt': (
            'Mention checking packs, the map, notes, gear condition, '
            'mail, or spellbook like an adventurer would.'
        ),
    },
    {
        'category': 'mistake',
        'prompt': (
            'Admit a small mistake: wrong turn, missed trainer, forgot '
            'reagents, sold the wrong item, or pulled too soon.'
        ),
    },
    {
        'category': 'small_victory',
        'prompt': (
            'Mention a small win: finishing an objective, finding a path, '
            'getting a drop, surviving a pull, or saving gold.'
        ),
    },
    {
        'category': 'server_life',
        'prompt': (
            'Make a casual observation about life in Azeroth, busy hubs, '
            'quiet roads, familiar names, or guild chatter passing by.'
        ),
    },
    {
        'category': 'leveling_reflection',
        'prompt': (
            'Reflect briefly on growing stronger, learning a better '
            'spell, outgrowing a zone, or feeling more capable.'
        ),
    },
    {
        'category': 'role_memory',
        'prompt': (
            'Mention a previous role moment: holding threat, saving mana, '
            'missing a stun, landing a crit, or clutch healing.'
        ),
    },
    {
        'category': 'raid_story',
        'prompt': (
            'Mention raids, bosses, wipes, loot rules, or raid prep as '
            'a memory, goal, or observation, not a plan.'
        ),
    },
]


EVENT_TOPIC_MAP = {
    'bot_level_up': 'congrats',
    'bot_achievement': 'congrats',
    'motd_changed': 'motd',
    'info_changed': 'motd',
    'member_invited': 'recruit',
    'member_promoted': 'congrats',
    'member_demoted': 'idle_banter',
    'member_removed': 'idle_banter',
    'member_left': 'idle_banter',
    'member_online': 'player_login',
    'player_login': 'player_login',
    'bank_repair_money': 'guild_bank',
    'bank_withdraw_money': 'guild_bank',
    'bank_deposit_money': 'guild_bank',
    'bank_deposit_item': 'guild_bank',
    'bank_withdraw_item': 'guild_bank',
    'bank_move_item': 'guild_bank',
    'bank_tab_purchased': 'guild_bank',
}


def choose_guild_topic(
    recent_categories=None, preferred_category=None
):
    """Choose a topic while avoiding recent repetition."""
    recent_categories = set(recent_categories or [])
    pool = GUILD_TOPIC_POOL
    if preferred_category:
        preferred = [
            t for t in GUILD_TOPIC_POOL
            if t['category'] == preferred_category
        ]
        if preferred:
            pool = preferred
    else:
        fresh = [
            t for t in GUILD_TOPIC_POOL
            if (
                t['category'] not in recent_categories
                and not t.get('event_only')
            )
        ]
        if fresh:
            pool = fresh
    return random.choice(pool)


def category_for_event(event_kind: str) -> str:
    """Map a guild event kind to a topic category."""
    return EVENT_TOPIC_MAP.get(
        event_kind or '', event_kind or 'idle_banter'
    )
